"""Backtest portfolio.

An in-memory account that behaves exactly like the live one, minus the
database. It deliberately reuses the live engine's building blocks rather than
reimplementing them:

* ``apply_fill``      -- the same position accounting, including reversals
* ``PortfolioManager`` -- the same cash rule, buys debit and sells credit,
                          charges always subtract
* ``PnLCalculator``   -- the same P&L arithmetic

Only persistence differs. A backtest writing order, trade, position and
snapshot rows for every bar would be pointlessly slow and would pollute the
real account, so state lives in fields instead -- but the numbers come out of
the same code, which is what makes a backtest comparable to live trading
rather than merely similar to it.
"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from app.models.enums import OrderSide
from app.trading.execution import Fill
from app.trading.pnl import PnLCalculator, to_money
from app.trading.position_manager import apply_fill

ZERO = Decimal("0.00")


@dataclass(frozen=True)
class BacktestTrade:
    """A fill, recorded with the same figures the live ``Trade`` row carries."""

    index: int
    timestamp: datetime
    side: OrderSide
    quantity: Decimal
    reference_price: Decimal
    execution_price: Decimal

    spread_cost: Decimal
    slippage_cost: Decimal
    total_charges: Decimal

    gross_pnl: Decimal
    net_pnl: Decimal
    closed_quantity: Decimal

    position_after: Decimal
    cash_after: Decimal
    reason: str = ""

    @property
    def is_closing(self) -> bool:
        """Only a fill that closed exposure can win or lose."""
        return self.closed_quantity > 0


@dataclass(frozen=True)
class EquityPoint:
    """One point on the backtest equity curve."""

    index: int
    timestamp: datetime
    mark_price: Decimal
    cash: Decimal
    position: Decimal
    position_value: Decimal
    total_value: Decimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    net_pnl: Decimal


class InsufficientCash(Exception):
    """The account cannot fund the order. Mirrors InsufficientFundsError."""


@dataclass
class BacktestPortfolio:
    """Cash, position and history for one backtest run."""

    initial_cash: Decimal
    cash: Decimal = field(init=False)
    quantity: Decimal = Decimal("0")
    average_price: Decimal = Decimal("0.0000")
    realized_pnl: Decimal = ZERO
    total_charges: Decimal = ZERO

    trades: list[BacktestTrade] = field(default_factory=list)
    equity_curve: list[EquityPoint] = field(default_factory=list)
    rejected_orders: int = 0

    def __post_init__(self) -> None:
        self.cash = self.initial_cash

    # -- valuation -------------------------------------------------------

    @property
    def net_realized_pnl(self) -> Decimal:
        return to_money(self.realized_pnl - self.total_charges)

    def unrealized_pnl(self, mark_price: Decimal) -> Decimal:
        if self.quantity == 0:
            return ZERO
        return PnLCalculator.unrealized_pnl(
            quantity=self.quantity,
            average_price=self.average_price,
            mark_price=mark_price,
        )

    def position_value(self, mark_price: Decimal) -> Decimal:
        if self.quantity == 0:
            return ZERO
        return PnLCalculator.position_value(
            quantity=self.quantity, mark_price=mark_price
        )

    def equity(self, mark_price: Decimal) -> Decimal:
        """Cash plus the marked value of the open position."""
        return to_money(self.cash + self.position_value(mark_price))

    # -- mutation --------------------------------------------------------

    @staticmethod
    def cash_delta(fill: Fill) -> Decimal:
        """The live cash rule: buys debit, sells credit, charges subtract."""
        traded = fill.notional * Decimal(-fill.side.direction)
        return to_money(traded - fill.total_charges)

    def can_afford(self, fill: Fill) -> bool:
        delta = self.cash_delta(fill)
        return delta >= 0 or self.cash >= -delta

    def apply(
        self,
        fill: Fill,
        *,
        index: int,
        timestamp: datetime,
        reason: str = "",
    ) -> BacktestTrade:
        """Settle a fill against the account.

        Raises:
            InsufficientCash: the debit exceeds available cash. Checked before
                anything is mutated, so a refused order leaves no trace --
                the same guarantee the live engine's transaction provides.
        """
        if not self.can_afford(fill):
            self.rejected_orders += 1
            raise InsufficientCash(
                f"Order needs {-self.cash_delta(fill)} but the account holds "
                f"{self.cash}."
            )

        outcome = apply_fill(
            quantity=self.quantity,
            average_price=self.average_price,
            fill_quantity=fill.signed_quantity,
            fill_price=fill.price,
        )

        self.quantity = outcome.new_quantity
        self.average_price = outcome.new_average_price
        self.realized_pnl = to_money(self.realized_pnl + outcome.realized_pnl)
        self.total_charges = to_money(self.total_charges + fill.total_charges)
        self.cash = to_money(self.cash + self.cash_delta(fill))

        trade = BacktestTrade(
            index=index,
            timestamp=timestamp,
            side=fill.side,
            quantity=fill.quantity,
            reference_price=fill.reference_price,
            execution_price=fill.price,
            spread_cost=fill.spread_cost,
            slippage_cost=fill.slippage_cost,
            total_charges=fill.total_charges,
            gross_pnl=outcome.realized_pnl,
            net_pnl=to_money(outcome.realized_pnl - fill.total_charges),
            closed_quantity=outcome.closed_quantity,
            position_after=self.quantity,
            cash_after=self.cash,
            reason=reason,
        )
        self.trades.append(trade)
        return trade

    def record_equity(
        self, *, index: int, timestamp: datetime, mark_price: Decimal
    ) -> EquityPoint:
        """Mark the account to market and append a curve point."""
        unrealized = self.unrealized_pnl(mark_price)
        position_value = self.position_value(mark_price)

        point = EquityPoint(
            index=index,
            timestamp=timestamp,
            mark_price=mark_price,
            cash=self.cash,
            position=self.quantity,
            position_value=position_value,
            total_value=to_money(self.cash + position_value),
            realized_pnl=self.realized_pnl,
            unrealized_pnl=unrealized,
            net_pnl=to_money(self.net_realized_pnl + unrealized),
        )
        self.equity_curve.append(point)
        return point
