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
        |  FeeCalculator   brokerage, STT, exchange, SEBI, stamp duty, GST
        v
    Fill(price, spread_cost, slippage_cost, charges)

Each of the three models is injected, so any of them can be swapped or
switched off without touching this class -- and each is independently testable.
No partial filling and no order-book matching yet; this class remains the seam
where those would arrive.
"""

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import OrderSide
from app.models.trading import Order, Trade
from app.trading.fees import ChargeBreakdown, FeeCalculator
from app.trading.pnl import to_money
from app.trading.slippage import SlippageModel
from app.trading.spread import BidAsk, SpreadModel


@dataclass(frozen=True)
class Fill:
    """The outcome of executing an order, priced end to end."""

    quantity: int
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

    @property
    def signed_quantity(self) -> int:
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
        fees: FeeCalculator | None = None,
    ) -> None:
        self._session = session
        self.spread = spread or SpreadModel.from_settings()
        self.slippage = slippage or SlippageModel.from_settings()
        self.fees = fees or FeeCalculator.from_settings()

    @classmethod
    def frictionless(cls, session: AsyncSession) -> "ExecutionEngine":
        """An engine with no spread, no slippage and no charges.

        Fills exactly at the reference price. Used to test position accounting
        in isolation from execution costs.
        """
        return cls(
            session,
            spread=SpreadModel.disabled(),
            slippage=SlippageModel.disabled(),
            fees=FeeCalculator.disabled(),
        )

    def execute(self, order: Order, reference_price: Decimal) -> Fill:
        """Price the fill: spread, then slippage, then charges.

        Pure -- it decides the fill but writes nothing, which keeps it
        directly testable. Persisting is ``record_trade``'s job.
        """
        direction = order.side.direction

        spread = self.spread.apply(
            mid_price=reference_price, direction=direction, quantity=order.quantity
        )
        slippage = self.slippage.apply(
            base_price=spread.fill_price, direction=direction, quantity=order.quantity
        )
        execution_price = slippage.slipped_price

        charges = self.fees.calculate(
            side=order.side, quantity=order.quantity, price=execution_price
        )

        return Fill(
            quantity=order.quantity,
            price=execution_price,
            side=order.side,
            reference_price=reference_price,
            quote=spread.quote,
            spread_cost=spread.cost,
            slippage_cost=slippage.cost,
            charges=charges,
        )

    async def record_trade(
        self,
        *,
        order: Order,
        fill: Fill,
        gross_pnl: Decimal,
        closed_quantity: int,
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
