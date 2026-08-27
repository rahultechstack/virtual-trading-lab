"""The trading engine.

Orchestrates the five collaborators and owns the transaction boundary:

    TradingEngine
      |-- OrderManager      order rows and their state
      |-- ExecutionEngine   fills and trade records
      |-- PositionManager   position accounting
      |-- PortfolioManager  cash and valuation
      +-- PnLCalculator     the arithmetic (used via the two managers)

Independent by construction: it imports no market-data provider and no web
framework. Execution prices are supplied by the caller, so the engine can be
driven equally by an HTTP endpoint, a backtest harness or a test.

**Atomicity.** A filled order writes to four tables -- orders, trades,
positions and wallet. All of it happens inside one transaction, and the wallet
and position rows are locked with ``SELECT ... FOR UPDATE`` before anything is
computed. An order therefore either lands completely or not at all; it can
never debit cash without moving the position, or vice versa.
"""

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import (
    InvalidOrderError,
    InvalidPositionOperationError,
    TradingError,
    UnsupportedSymbolError,
    WalletNotFoundError,
)
from app.core.logging import get_logger
from app.models.enums import OrderSide, OrderStatus, OrderType
from app.models.trading import MAX_ORDER_QUANTITY, Order, Position, Trade
from app.repositories.wallet_repository import WalletRepository
from app.trading.execution import ExecutionEngine
from app.trading.order_manager import OrderManager
from app.trading.portfolio import PortfolioManager, PortfolioSnapshot
from app.trading.position_manager import PositionManager, apply_fill

logger = get_logger(__name__)


@dataclass(frozen=True)
class OrderResult:
    """Everything one accepted order produced."""

    order: Order
    trade: Trade
    position: Position
    #: P&L from price movement on this fill, before charges.
    gross_pnl: Decimal
    #: Charges on this fill.
    total_charges: Decimal
    #: gross_pnl minus total_charges.
    net_pnl: Decimal
    #: Signed cash movement, charges included.
    cash_delta: Decimal


class TradingEngine:
    """Executes orders against the single virtual account."""

    def __init__(
        self, session: AsyncSession, *, execution: ExecutionEngine | None = None
    ) -> None:
        self._session = session
        self.orders = OrderManager(session)
        # Injected so spread, slippage and fee models can be swapped or
        # switched off without touching the engine.
        self.execution = execution or ExecutionEngine(session)
        self.positions = PositionManager(session)
        self.portfolio = PortfolioManager(WalletRepository(session))
        self._wallets = WalletRepository(session)

    # -- public API ------------------------------------------------------

    async def place_order(
        self,
        *,
        side: OrderSide,
        quantity: int,
        reference_price: Decimal,
        symbol: str | None = None,
        requested_price: Decimal | None = None,
    ) -> OrderResult:
        """Validate, execute and settle an order atomically.

        Args:
            side: BUY, SELL, SHORT_SELL or BUY_TO_COVER.
            quantity: Positive number of shares.
            reference_price: Mid price to trade around. The execution price is
                derived from it by the spread and slippage models, both
                adverse, so the fill is never better than this.
            symbol: Must be the configured instrument if given.
            requested_price: Recorded for audit; does not affect the fill.

        Raises:
            InvalidOrderError: malformed quantity, price or symbol.
            InvalidPositionOperationError: a closing-only side that would do
                more than close.
            InsufficientFundsError: the wallet cannot fund the order.
            WalletNotFoundError: the wallet has not been initialised.
        """
        resolved_symbol = self._resolve_symbol(symbol)
        self._validate_request(quantity, reference_price)

        # Lock both mutable rows before reading anything from them, so a
        # concurrent order cannot interleave between read and write.
        wallet = await self._wallets.get_for_update()
        if wallet is None:
            raise WalletNotFoundError()
        position = await self.positions.get_or_create_for_update(resolved_symbol)

        order = await self.orders.create(
            symbol=resolved_symbol,
            exchange=settings.TRADING_EXCHANGE,
            side=side,
            quantity=quantity,
            requested_price=requested_price,
            order_type=OrderType.MARKET,
        )

        fill = self.execution.execute(order, reference_price)

        try:
            self._validate_against_position(side, quantity, position)
            self.portfolio.assert_affordable(wallet, fill)
        except TradingError as exc:
            # Keep the rejected order as an audit record, then surface the
            # failure. Committing here is safe: nothing else has been written.
            await self.orders.mark_rejected(order, exc.message)
            await self._session.commit()
            logger.info("Order %s rejected: %s", order.id, exc.message)
            raise

        outcome = apply_fill(
            quantity=position.quantity,
            average_price=position.average_price,
            fill_quantity=fill.signed_quantity,
            fill_price=fill.price,
        )

        self.positions.apply(position, outcome, fill.total_charges)
        self.portfolio.apply_cash(wallet, fill)
        cash_delta = self.portfolio.cash_delta(fill)

        trade = await self.execution.record_trade(
            order=order,
            fill=fill,
            gross_pnl=outcome.realized_pnl,
            closed_quantity=outcome.closed_quantity,
        )
        await self.orders.mark_filled(order, fill.price)

        # Realign any stop-loss against the position this fill just moved,
        # inside the SAME transaction: a stop can never briefly outlive the
        # position it protects, and a partial exit clamps it rather than
        # leaving it able to sell shares that are no longer held.
        # Imported locally -- the automation package imports this engine back.
        from app.automation.service import AutomaticOrderService

        await AutomaticOrderService(self._session).reconcile_for_position(
            symbol=resolved_symbol, position_quantity=outcome.new_quantity
        )

        # Snapshot inside the same transaction, marked at the fill price: at
        # the instant of a trade that price *is* the market. Enrolling it here
        # means the equity curve can never record a state that never existed.
        if settings.SNAPSHOT_ON_TRADE:
            from app.analytics.snapshots import SnapshotService
            from app.models.portfolio_snapshot import SnapshotSource

            await SnapshotService(self._session).capture(
                mark_price=fill.price,
                source=SnapshotSource.TRADE,
                commit=False,
            )

        await self._session.commit()
        await self._session.refresh(order)
        await self._session.refresh(position)
        await self._session.refresh(trade)

        logger.info(
            "Filled order %s: %s %s ref %s -> exec %s, position %s, "
            "gross %s, charges %s, net %s",
            order.id,
            side,
            quantity,
            reference_price,
            fill.price,
            outcome.new_quantity,
            outcome.realized_pnl,
            fill.total_charges,
            trade.net_pnl,
        )

        return OrderResult(
            order=order,
            trade=trade,
            position=position,
            gross_pnl=outcome.realized_pnl,
            total_charges=fill.total_charges,
            net_pnl=trade.net_pnl,
            cash_delta=cash_delta,
        )

    async def get_position(self, symbol: str | None = None) -> Position:
        """Current position, materialised flat if never traded."""
        resolved = self._resolve_symbol(symbol)
        position = await self.positions.get(resolved)
        if position is None:
            position = Position(
                symbol=resolved,
                exchange=settings.TRADING_EXCHANGE,
                quantity=0,
                average_price=Decimal("0.0000"),
                realized_pnl=Decimal("0.00"),
                total_charges=Decimal("0.00"),
                net_realized_pnl=Decimal("0.00"),
            )
        return position

    async def get_portfolio(
        self, *, mark_price: Decimal | None = None, symbol: str | None = None
    ) -> PortfolioSnapshot:
        """Value the account.

        ``mark_price`` is passed in rather than fetched, keeping the engine
        independent of the market-data layer.
        """
        wallet = await self._wallets.get()
        if wallet is None:
            raise WalletNotFoundError()
        position = await self.get_position(symbol)
        return self.portfolio.snapshot(
            wallet=wallet,
            quantity=position.quantity,
            average_price=position.average_price,
            realized_pnl=position.realized_pnl,
            total_charges=position.total_charges,
            net_realized_pnl=position.net_realized_pnl,
            mark_price=mark_price,
        )

    async def list_orders(
        self, *, limit: int = 100, offset: int = 0, status: OrderStatus | None = None
    ) -> list[Order]:
        return await self.orders.list_recent(limit=limit, offset=offset, status=status)

    async def list_trades(self, *, limit: int = 100, offset: int = 0) -> list[Trade]:
        return await self.execution.list_recent(limit=limit, offset=offset)

    # -- validation ------------------------------------------------------

    @staticmethod
    def _resolve_symbol(symbol: str | None) -> str:
        if symbol is None:
            return settings.TRADING_SYMBOL
        if symbol.strip().upper() != settings.TRADING_SYMBOL.upper():
            raise UnsupportedSymbolError(
                f"This platform trades {settings.TRADING_EXCHANGE}:"
                f"{settings.TRADING_SYMBOL} only. Received '{symbol}'."
            )
        return settings.TRADING_SYMBOL

    @staticmethod
    def _validate_request(quantity: int, reference_price: Decimal) -> None:
        if quantity <= 0:
            raise InvalidOrderError(f"Quantity must be positive, got {quantity}.")
        if quantity > MAX_ORDER_QUANTITY:
            raise InvalidOrderError(
                f"Quantity {quantity} exceeds the maximum of {MAX_ORDER_QUANTITY}."
            )
        if reference_price <= 0:
            raise InvalidOrderError(
                f"Reference price must be positive, got {reference_price}."
            )

    @staticmethod
    def _validate_against_position(
        side: OrderSide, quantity: int, position: Position
    ) -> None:
        """Enforce the intent of closing-only sides.

        SELL and BUY_TO_COVER may only reduce an existing position. Going
        beyond it would silently open the opposite direction, so the engine
        refuses and asks for that to be stated explicitly with SHORT_SELL or
        BUY. BUY and SHORT_SELL are free to cross zero and reverse.
        """
        if side is OrderSide.SELL:
            if position.quantity <= 0:
                raise InvalidPositionOperationError(
                    "SELL closes a long position, but the position is "
                    f"{position.quantity}. Use SHORT_SELL to open a short."
                )
            if quantity > position.quantity:
                raise InvalidPositionOperationError(
                    f"Cannot SELL {quantity}; the long position is only "
                    f"{position.quantity}. Use SHORT_SELL to sell beyond it."
                )

        elif side is OrderSide.BUY_TO_COVER:
            if position.quantity >= 0:
                raise InvalidPositionOperationError(
                    "BUY_TO_COVER closes a short position, but the position is "
                    f"{position.quantity}. Use BUY to open a long."
                )
            if quantity > abs(position.quantity):
                raise InvalidPositionOperationError(
                    f"Cannot BUY_TO_COVER {quantity}; the short position is only "
                    f"{abs(position.quantity)}. Use BUY to buy beyond it."
                )
