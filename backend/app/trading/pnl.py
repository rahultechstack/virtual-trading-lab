"""P&L arithmetic.

Pure functions over ``Decimal`` -- no database, no I/O, no state. Every money
result is quantised to paise so that repeated partial fills cannot accumulate
fractional dust.
"""

from decimal import ROUND_HALF_UP, Decimal

#: Money is exact to two decimal places.
CENT = Decimal("0.01")
#: Derived averages keep two extra digits to limit rounding drift.
AVERAGE_PRECISION = Decimal("0.0001")


def to_money(value: Decimal) -> Decimal:
    """Round a monetary amount to paise, half-up."""
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def to_average(value: Decimal) -> Decimal:
    """Round a weighted average price to four decimal places."""
    return value.quantize(AVERAGE_PRECISION, rounding=ROUND_HALF_UP)


class PnLCalculator:
    """Profit and loss for a single instrument.

    Sign convention throughout: a *long* profits when price rises, a *short*
    profits when it falls. Both are expressed as one formula by carrying the
    position's direction.
    """

    @staticmethod
    def realized_pnl(
        *,
        entry_price: Decimal,
        exit_price: Decimal,
        quantity: int,
        direction: int,
    ) -> Decimal:
        """P&L locked in by closing ``quantity`` units.

        Args:
            entry_price: Weighted average price the closed units were opened at.
            exit_price: Price they were closed at.
            quantity: Units closed. Always positive.
            direction: ``+1`` if the position being closed was long, ``-1`` if
                it was short.

        Long: ``(exit - entry) * qty``. Short: ``(entry - exit) * qty``.
        """
        if quantity <= 0:
            return Decimal("0.00")
        gross = (exit_price - entry_price) * Decimal(quantity) * Decimal(direction)
        return to_money(gross)

    @staticmethod
    def unrealized_pnl(
        *, quantity: int, average_price: Decimal, mark_price: Decimal
    ) -> Decimal:
        """Open-position P&L if it were closed at ``mark_price``.

        ``quantity`` is signed, so the direction is already carried by it and
        one expression covers both long and short.
        """
        if quantity == 0:
            return Decimal("0.00")
        return to_money((mark_price - average_price) * Decimal(quantity))

    @staticmethod
    def position_value(*, quantity: int, mark_price: Decimal) -> Decimal:
        """Signed market value of the open position.

        Negative for a short, which is the liability owed to buy it back.
        """
        return to_money(Decimal(quantity) * mark_price)

    @staticmethod
    def weighted_average_price(
        *,
        existing_quantity: int,
        existing_average: Decimal,
        added_quantity: int,
        added_price: Decimal,
    ) -> Decimal:
        """Blend a new fill into an existing average entry price.

        Quantities are absolute sizes; direction is irrelevant because adding
        to a short averages exactly as adding to a long does.
        """
        total = existing_quantity + added_quantity
        if total <= 0:
            return Decimal("0.0000")
        blended = (
            existing_average * Decimal(existing_quantity)
            + added_price * Decimal(added_quantity)
        ) / Decimal(total)
        return to_average(blended)
