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

**Asset-class awareness.** The engine never inspects a symbol. It resolves the
instrument once, then that instrument answers every question that used to have
a single hard-coded answer:

    instrument.exchange        which venue the row records
    instrument.asset_class     which fee schedule and calendar apply
    instrument.quantity_step   whether 0.001 is a legal size
    calendar_for(instrument)   whether the market is open right now

Adding an asset class therefore adds rows to those tables, not branches here.

**Atomicity.** A filled order writes to four tables -- orders, trades,
positions and wallet. All of it happens inside one transaction, and the wallet
and position rows are locked with ``SELECT ... FOR UPDATE`` before anything is
computed. An order therefore either lands completely or not at all; it can
never debit cash without moving the position, or vice versa.
"""

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import (
    InvalidOrderError,
    InvalidPositionOperationError,
    MarketClosedError,
    TradingError,
    UnsupportedSymbolError,
    WalletNotFoundError,
)
from app.core.logging import get_logger
from app.market_data.instruments import (
    Instrument,
    normalise_quantity,
    resolve_instrument,
    resolve_symbol,
)
from app.markets.registry import calendar_for
from app.models.enums import OrderSide, OrderStatus, OrderType
from app.models.trading import Order, Position, Trade
from app.repositories.wallet_repository import WalletRepository
from app.trading.execution import ExecutionEngine
from app.trading.order_manager import OrderManager
from app.trading.portfolio import (
    PortfolioManager,
    PortfolioSnapshot,
    PortfolioValuation,
    value_portfolio,
)
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
        quantity,
        reference_price: Decimal,
        symbol: str | None = None,
        requested_price: Decimal | None = None,
    ) -> OrderResult:
        """Validate, execute and settle an order atomically.

        Args:
            side: BUY, SELL, SHORT_SELL or BUY_TO_COVER.
            quantity: Positive size. Whole units for a stock; fractional for
                crypto, down to the instrument's ``quantity_step``. Accepts an
                int, a ``Decimal`` or a numeric string -- a float is converted
                via ``str`` so binary-float noise never reaches the ledger.
            reference_price: Mid price to trade around. The execution price is
                derived from it by the spread and slippage models, both
                adverse, so the fill is never better than this.
            symbol: Any instrument in the supported universe. Defaults to the
                configured default instrument.
            requested_price: Recorded for audit; does not affect the fill.

        Raises:
            UnsupportedSymbolError: symbol outside the supported universe.
            InvalidQuantityError: size not positive, or off the instrument's
                tradable increment (0.5 shares, or sub-satoshi crypto).
            MarketClosedError: the instrument's market is shut and
                ENFORCE_MARKET_HOURS is on. Crypto never raises this.
            InvalidOrderError: malformed price, or size beyond the bound.
            InvalidPositionOperationError: a closing-only side that would do
                more than close.
            InsufficientFundsError: the wallet cannot fund the order.
            WalletNotFoundError: the wallet has not been initialised.
        """
        instrument = resolve_instrument(symbol)
        resolved_symbol = instrument.symbol
        # The instrument decides what a legal size is -- not this method.
        quantity = normalise_quantity(instrument, quantity)
        self._validate_request(quantity, reference_price)
        self._require_open_market(instrument)

        # Lock both mutable rows before reading anything from them, so a
        # concurrent order cannot interleave between read and write.
        wallet = await self._wallets.get_for_update()
        if wallet is None:
            raise WalletNotFoundError()
        position = await self.positions.get_or_create_for_update(resolved_symbol)

        order = await self.orders.create(
            symbol=resolved_symbol,
            exchange=instrument.exchange,
            asset_class=instrument.asset_class,
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
                mark_prices={resolved_symbol: fill.price},
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
        """Current position, materialised flat if never traded.

        The materialised row is deliberately NOT persisted -- looking at an
        instrument is not trading it.
        """
        instrument = resolve_instrument(symbol)
        position = await self.positions.get(instrument.symbol)
        if position is None:
            position = Position(
                symbol=instrument.symbol,
                exchange=instrument.exchange,
                asset_class=instrument.asset_class,
                quantity=Decimal("0"),
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

    async def list_positions(self) -> list[Position]:
        """Every instrument that has ever traded, alphabetically."""
        result = await self._session.execute(
            select(Position).order_by(Position.symbol.asc())
        )
        return list(result.scalars().all())

    async def get_portfolio_summary(
        self, *, mark_prices: dict[str, Decimal] | None = None
    ) -> PortfolioValuation:
        """Value the whole account across every instrument held.

        One wallet, many positions. ``mark_prices`` maps symbol -> price; any
        open position without one is reported unvalued rather than guessed at,
        and its symbol is listed in ``unpriced_symbols``. As everywhere else,
        prices are passed in rather than fetched.
        """
        wallet = await self._wallets.get()
        if wallet is None:
            raise WalletNotFoundError()
        positions = await self.list_positions()
        return value_portfolio(
            wallet=wallet, positions=positions, mark_prices=mark_prices
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
        """Any instrument in the supported universe; None means the default."""
        return resolve_symbol(symbol)

    @staticmethod
    def _resolve_exchange(symbol: str) -> str:
        """The exchange the instrument is listed on, not a global constant."""
        return resolve_instrument(symbol).exchange

    @staticmethod
    def _require_open_market(instrument: Instrument) -> None:
        """Refuse an order while the instrument's market is shut.

        Off by default (``ENFORCE_MARKET_HOURS``), because this is a paper
        trading lab and practising an order at 9pm is the point rather than a
        mistake. The calendar is consulted and reported regardless -- the
        setting only decides whether being closed is fatal.

        The engine asks the instrument's own calendar, so crypto passes at
        every hour of every day without a single crypto-specific branch here.
        """
        if not settings.ENFORCE_MARKET_HOURS:
            return

        session = calendar_for(instrument).trading_status()
        if session.is_open:
            return

        reopens = (
            f" It reopens at {session.next_open.isoformat()}."
            if session.next_open is not None
            else ""
        )
        raise MarketClosedError(
            f"{instrument.symbol} cannot be traded right now: {session.reason}"
            f"{reopens}"
        )

    @staticmethod
    def _validate_request(quantity: Decimal, reference_price: Decimal) -> None:
        """Bounds that hold for every asset class.

        Positivity and step size are already settled by ``normalise_quantity``,
        which knows the instrument; only the absolute bound and the price
        remain.
        """
        if quantity > settings.MAX_ORDER_QUANTITY:
            raise InvalidOrderError(
                f"Quantity {quantity} exceeds the maximum of "
                f"{settings.MAX_ORDER_QUANTITY}."
            )
        if reference_price <= 0:
            raise InvalidOrderError(
                f"Reference price must be positive, got {reference_price}."
            )

    @staticmethod
    def _validate_against_position(
        side: OrderSide, quantity: Decimal, position: Position
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
