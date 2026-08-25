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
    realized_pnl: Decimal
    cash_delta: Decimal


class TradingEngine:
    """Executes orders against the single virtual account."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self.orders = OrderManager(session)
        self.execution = ExecutionEngine(session)
        self.positions = PositionManager(session)
        self.portfolio = PortfolioManager(WalletRepository(session))
        self._wallets = WalletRepository(session)

    # -- public API ------------------------------------------------------

    async def place_order(
        self,
        *,
        side: OrderSide,
        quantity: int,
        execution_price: Decimal,
        symbol: str | None = None,
        requested_price: Decimal | None = None,
    ) -> OrderResult:
        """Validate, execute and settle an order atomically.

        Args:
            side: BUY, SELL, SHORT_SELL or BUY_TO_COVER.
            quantity: Positive number of shares.
            execution_price: Price to fill at. Supplied by the caller in this
                stage; a later stage sources it from live market data.
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
        self._validate_request(quantity, execution_price)

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

        fill = self.execution.execute(order, execution_price)

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

        self.positions.apply(position, outcome)
        self.portfolio.apply_cash(wallet, fill)
        cash_delta = self.portfolio.cash_delta(fill)

        trade = await self.execution.record_trade(
            order=order,
            fill=fill,
            realized_pnl=outcome.realized_pnl,
            closed_quantity=outcome.closed_quantity,
        )
        await self.orders.mark_filled(order, fill.price)

        await self._session.commit()
        await self._session.refresh(order)
        await self._session.refresh(position)
        await self._session.refresh(trade)

        logger.info(
            "Filled order %s: %s %s @ %s -> position %s, realized %s",
            order.id,
            side,
            quantity,
            fill.price,
            outcome.new_quantity,
            outcome.realized_pnl,
        )

        return OrderResult(
            order=order,
            trade=trade,
            position=position,
            realized_pnl=outcome.realized_pnl,
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
    def _validate_request(quantity: int, execution_price: Decimal) -> None:
        if quantity <= 0:
            raise InvalidOrderError(f"Quantity must be positive, got {quantity}.")
        if quantity > MAX_ORDER_QUANTITY:
            raise InvalidOrderError(
                f"Quantity {quantity} exceeds the maximum of {MAX_ORDER_QUANTITY}."
            )
        if execution_price <= 0:
            raise InvalidOrderError(
                f"Execution price must be positive, got {execution_price}."
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
