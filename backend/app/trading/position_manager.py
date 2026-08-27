"""Position accounting.

The core algorithm is a pure function -- ``apply_fill`` takes numbers and
returns numbers -- so every accounting rule can be tested without a database.
``PositionManager`` is the thin layer that loads a row, applies that function
and writes the result back.
"""

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.market_data.instruments import resolve_instrument
from app.models.trading import Position
from app.trading.pnl import PnLCalculator, to_money


@dataclass(frozen=True)
class FillOutcome:
    """What a fill did to a position.

    Quantities are ``Decimal`` throughout, not ``int``: a fill may be
    fractional. The arithmetic below is identical either way -- nothing here
    ever depended on quantities being whole.
    """

    new_quantity: Decimal
    new_average_price: Decimal
    realized_pnl: Decimal
    #: Units of the prior position that this fill closed.
    closed_quantity: Decimal
    #: Units of new exposure this fill opened.
    opened_quantity: Decimal

    @property
    def is_reversal(self) -> bool:
        """True when the fill closed one direction and opened the other."""
        return self.closed_quantity > 0 and self.opened_quantity > 0


def apply_fill(
    *,
    quantity: Decimal,
    average_price: Decimal,
    fill_quantity: Decimal,
    fill_price: Decimal,
) -> FillOutcome:
    """Apply a signed fill to a position and report the outcome.

    Args:
        quantity: Current signed position. Positive long, negative short.
        average_price: Current weighted average entry price. Zero when flat.
        fill_quantity: Signed size of the fill. Positive buys, negative sells.
        fill_price: Price the fill executed at.

    Three cases:

    1. **Opening from flat** -- the fill becomes the position at its own price.
    2. **Adding in the same direction** -- quantities add and the entry price
       is re-averaged. Nothing is realized.
    3. **Trading against the position** -- units are closed at the existing
       average and P&L is realized on them. If the fill is larger than the
       position it crosses zero: the remainder opens the opposite direction at
       the fill price, and the average resets to that price.
    """
    quantity = Decimal(quantity)
    fill_quantity = Decimal(fill_quantity)
    zero = Decimal("0")

    if fill_quantity == 0:
        return FillOutcome(quantity, average_price, Decimal("0.00"), zero, zero)

    # 1. Opening from flat.
    if quantity == 0:
        return FillOutcome(
            new_quantity=fill_quantity,
            new_average_price=fill_price,
            realized_pnl=Decimal("0.00"),
            closed_quantity=zero,
            opened_quantity=abs(fill_quantity),
        )

    same_direction = (quantity > 0) == (fill_quantity > 0)

    # 2. Adding to the existing side.
    if same_direction:
        new_average = PnLCalculator.weighted_average_price(
            existing_quantity=abs(quantity),
            existing_average=average_price,
            added_quantity=abs(fill_quantity),
            added_price=fill_price,
        )
        return FillOutcome(
            new_quantity=quantity + fill_quantity,
            new_average_price=new_average,
            realized_pnl=Decimal("0.00"),
            closed_quantity=zero,
            opened_quantity=abs(fill_quantity),
        )

    # 3. Trading against the position: close, and possibly reverse.
    closed = min(abs(quantity), abs(fill_quantity))
    direction = 1 if quantity > 0 else -1

    realized = PnLCalculator.realized_pnl(
        entry_price=average_price,
        exit_price=fill_price,
        quantity=closed,
        direction=direction,
    )

    new_quantity = quantity + fill_quantity
    opened = abs(fill_quantity) - closed

    if new_quantity == 0:
        # Flat: no exposure left, so no entry price to carry.
        new_average = Decimal("0.0000")
    elif opened > 0:
        # Crossed through zero -- the remainder is a brand-new position
        # opened at this fill's price.
        new_average = fill_price
    else:
        # Partially closed; the surviving units keep their original basis.
        new_average = average_price

    return FillOutcome(
        new_quantity=new_quantity,
        new_average_price=new_average,
        realized_pnl=realized,
        closed_quantity=closed,
        opened_quantity=opened,
    )


class PositionManager:
    """Loads, mutates and persists the position row."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, symbol: str) -> Position | None:
        result = await self._session.execute(
            select(Position).where(Position.symbol == symbol)
        )
        return result.scalar_one_or_none()

    async def get_or_create_for_update(self, symbol: str) -> Position:
        """Row-locked position, created flat if it does not exist.

        The lock serialises concurrent orders: two fills can never read the
        same starting quantity and both write back a result computed from it.
        """
        position = await self._locked(symbol)
        if position is not None:
            return position

        instrument = resolve_instrument(symbol)
        position = Position(
            symbol=symbol,
            exchange=instrument.exchange,
            asset_class=instrument.asset_class,
            quantity=Decimal("0"),
            average_price=Decimal("0.0000"),
            realized_pnl=Decimal("0.00"),
            total_charges=Decimal("0.00"),
            net_realized_pnl=Decimal("0.00"),
        )
        self._session.add(position)
        try:
            await self._session.flush()
        except IntegrityError:
            # A concurrent order created it first; take the lock on that row.
            await self._session.rollback()
            existing = await self._locked(symbol)
            if existing is None:  # pragma: no cover - defensive
                raise
            return existing
        return position

    async def _locked(self, symbol: str) -> Position | None:
        result = await self._session.execute(
            select(Position).where(Position.symbol == symbol).with_for_update()
        )
        return result.scalar_one_or_none()

    @staticmethod
    def apply(
        position: Position,
        outcome: FillOutcome,
        charges: Decimal = Decimal("0.00"),
    ) -> Position:
        """Write a fill outcome onto the position row.

        ``charges`` accumulate on *every* fill, opening ones included, so
        ``net_realized_pnl`` reflects the full cost of the round trip rather
        than only the exit leg.
        """
        position.quantity = outcome.new_quantity
        position.average_price = outcome.new_average_price
        position.realized_pnl = to_money(position.realized_pnl + outcome.realized_pnl)
        position.total_charges = to_money(position.total_charges + charges)
        position.net_realized_pnl = to_money(
            position.realized_pnl - position.total_charges
        )
        return position
