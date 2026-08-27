"""Execution.

Turns an accepted order into a realistic fill and records the resulting trade.

The caller supplies a **reference price** -- a mid price. The engine derives the
actual execution price from it in two adverse steps, then prices the charges:

    reference (mid)
        |  SpreadModel     buys lift the ask, sells hit the bid
        v
    quoted price
        |  SlippageModel   the book moves against you in flight
        v
    execution price
        |  FeeSchedule     chosen by ASSET CLASS -- equity charges for a stock,
        v                  exchange fee + TDS for crypto
    Fill(price, spread_cost, slippage_cost, charges)

Each of the three models is injected, so any of them can be swapped or
switched off without touching this class -- and each is independently testable.

**Fees are per asset class.** The engine holds one calculator per class and
picks by ``Fill.asset_class``, so NSE's statutory charges never land on a
crypto trade. Passing a single ``fees=`` calculator overrides every class,
which is what the backtester and the cost-preview endpoint do when they want
one explicit schedule.

Spread and slippage are deliberately *not* per-class: both are expressed in
basis points of the price, so they scale correctly for an asset worth Rs 8 or
Rs 76,00,000 without any per-class configuration.

No partial filling and no order-book matching yet; this class remains the seam
where those would arrive.
"""

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.market_data.instruments import AssetClass
from app.models.enums import OrderSide
from app.models.trading import Order, Trade
from app.trading.fees import ChargeBreakdown, fee_calculators
from app.trading.pnl import to_money
from app.trading.slippage import SlippageModel
from app.trading.spread import BidAsk, SpreadModel


@dataclass(frozen=True)
class Fill:
    """The outcome of executing an order, priced end to end."""

    quantity: Decimal
    price: Decimal
    side: OrderSide

    #: The mid price the caller asked to trade around.
    reference_price: Decimal
    #: The two-sided quote derived from it.
    quote: BidAsk
    #: Money lost to crossing the spread.
    spread_cost: Decimal
    #: Money lost to adverse price movement.
    slippage_cost: Decimal
    #: Itemised statutory and broker charges.
    charges: ChargeBreakdown

    #: Which charge schedule and market rules produced this fill. Last, with a
    #: default, so every existing positional construction keeps working.
    asset_class: AssetClass = AssetClass.STOCK

    @property
    def signed_quantity(self) -> Decimal:
        """Positive when the fill increases the position, negative when it reduces it."""
        return self.quantity * self.side.direction

    @property
    def notional(self) -> Decimal:
        """Absolute cash value of the fill at its execution price."""
        return self.price * Decimal(self.quantity)

    @property
    def total_charges(self) -> Decimal:
        return self.charges.total

    @property
    def execution_cost(self) -> Decimal:
        """Everything the fill cost beyond the reference price.

        Spread and slippage are already embedded in ``price`` -- they are
        reported separately so the damage is visible, not double-counted.
        """
        return to_money(self.spread_cost + self.slippage_cost + self.total_charges)


class ExecutionEngine:
    """Executes orders and writes trade records."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        spread: SpreadModel | None = None,
        slippage: SlippageModel | None = None,
        fees=None,
    ) -> None:
        self._session = session
        self.spread = spread or SpreadModel.from_settings()
        self.slippage = slippage or SlippageModel.from_settings()
        #: An explicitly injected calculator applies to EVERY asset class --
        #: callers that pass one are asking for that exact schedule. Otherwise
        #: each class gets its own, built from settings.
        self._fees_override = fees
        self._fees_by_class = None if fees is not None else fee_calculators()

    def fees_for(self, asset_class: AssetClass):
        """The charge schedule this engine applies to an asset class."""
        if self._fees_override is not None:
            return self._fees_override
        return self._fees_by_class[asset_class]

    @property
    def fees(self):
        """The equity schedule.

        Kept because fees were a single object before crypto existed, and
        callers that only ever deal in equities still read it.
        """
        return self.fees_for(AssetClass.STOCK)

    @classmethod
    def frictionless(cls, session: AsyncSession) -> "ExecutionEngine":
        """An engine with no spread, no slippage and no charges.

        Fills exactly at the reference price. Used to test position accounting
        in isolation from execution costs.
        """
        engine = cls(
            session,
            spread=SpreadModel.disabled(),
            slippage=SlippageModel.disabled(),
        )
        # Every class charges nothing, rather than only equities.
        engine._fees_override = None
        engine._fees_by_class = fee_calculators(enabled=False)
        return engine

    def price_fill(
        self,
        *,
        side: OrderSide,
        quantity: Decimal,
        reference_price: Decimal,
        asset_class: AssetClass = AssetClass.STOCK,
    ) -> Fill:
        """Price a fill: spread, then slippage, then the asset's charges.

        Pure -- it decides the fill but writes nothing and touches no ORM
        object. That is what lets the backtester price its fills through
        exactly this code path rather than a parallel implementation.
        """
        quantity = Decimal(quantity)
        direction = side.direction

        spread = self.spread.apply(
            mid_price=reference_price, direction=direction, quantity=quantity
        )
        slippage = self.slippage.apply(
            base_price=spread.fill_price, direction=direction, quantity=quantity
        )
        execution_price = slippage.slipped_price

        charges = self.fees_for(asset_class).calculate(
            side=side, quantity=quantity, price=execution_price
        )

        return Fill(
            quantity=quantity,
            price=execution_price,
            side=side,
            asset_class=asset_class,
            reference_price=reference_price,
            quote=spread.quote,
            spread_cost=spread.cost,
            slippage_cost=slippage.cost,
            charges=charges,
        )

    def execute(self, order: Order, reference_price: Decimal) -> Fill:
        """Price the fill for a persisted order.

        The asset class comes off the order row, so the charge schedule is
        decided by what was traded rather than by any ambient default.
        """
        return self.price_fill(
            side=order.side,
            quantity=order.quantity,
            reference_price=reference_price,
            asset_class=order.asset_class,
        )

    async def record_trade(
        self,
        *,
        order: Order,
        fill: Fill,
        gross_pnl: Decimal,
        closed_quantity: Decimal,
    ) -> Trade:
        """Persist the fill with its full cost breakdown.

        ``net_pnl`` is gross P&L less this fill's charges. An opening fill
        realises no gross P&L, so its net is simply the cost of entering.
        """
        charges = fill.charges
        trade = Trade(
            order_id=order.id,
            symbol=order.symbol,
            exchange=order.exchange,
            asset_class=order.asset_class,
            side=fill.side,
            quantity=fill.quantity,
            execution_price=fill.price,
            reference_price=fill.reference_price,
            bid_price=fill.quote.bid,
            ask_price=fill.quote.ask,
            spread_cost=fill.spread_cost,
            slippage_cost=fill.slippage_cost,
            brokerage=charges.brokerage,
            stt=charges.stt,
            exchange_charges=charges.exchange_charges,
            sebi_charges=charges.sebi_charges,
            stamp_duty=charges.stamp_duty,
            gst=charges.gst,
            dp_charges=charges.dp_charges,
            tds=charges.tds,
            total_charges=charges.total,
            gross_pnl=gross_pnl,
            net_pnl=to_money(gross_pnl - charges.total),
            closed_quantity=closed_quantity,
        )
        self._session.add(trade)
        await self._session.flush()
        return trade

    async def list_recent(self, *, limit: int = 100, offset: int = 0) -> list[Trade]:
        """Newest first."""
        result = await self._session.execute(
            select(Trade).order_by(Trade.id.desc()).limit(limit).offset(offset)
        )
        return list(result.scalars().all())
