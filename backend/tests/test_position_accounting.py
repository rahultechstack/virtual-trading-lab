"""Position accounting, tested as pure arithmetic.

``apply_fill`` takes numbers and returns numbers, so every rule below is
verified without a database, a session or an event loop. Each expected value
is worked by hand in the test name or a comment.
"""

from decimal import Decimal

import pytest

from app.trading.pnl import PnLCalculator
from app.trading.position_manager import apply_fill

D = Decimal


# --------------------------------------------------------------------------
# Long entry
# --------------------------------------------------------------------------


def test_long_entry_from_flat():
    """BUY 100 @ 1400 -> +100 @ 1400."""
    out = apply_fill(
        quantity=0, average_price=D("0"), fill_quantity=100, fill_price=D("1400")
    )

    assert out.new_quantity == 100
    assert out.new_average_price == D("1400")
    assert out.realized_pnl == D("0.00")
    assert out.closed_quantity == 0
    assert out.opened_quantity == 100


def test_adding_to_a_long_averages_the_entry_price():
    """+100 @ 1400, then BUY 100 @ 1500 -> +200 @ 1450."""
    out = apply_fill(
        quantity=100,
        average_price=D("1400"),
        fill_quantity=100,
        fill_price=D("1500"),
    )

    assert out.new_quantity == 200
    assert out.new_average_price == D("1450.0000")
    assert out.realized_pnl == D("0.00")


def test_adding_to_a_long_weights_by_size_not_count():
    """+100 @ 1400 then BUY 300 @ 1500 -> avg 1475, not 1450."""
    out = apply_fill(
        quantity=100,
        average_price=D("1400"),
        fill_quantity=300,
        fill_price=D("1500"),
    )

    assert out.new_quantity == 400
    assert out.new_average_price == D("1475.0000")


# --------------------------------------------------------------------------
# Long exit
# --------------------------------------------------------------------------


def test_long_exit_realizes_profit_and_goes_flat():
    """+100 @ 1400, SELL 100 @ 1450 -> flat, +5,000."""
    out = apply_fill(
        quantity=100,
        average_price=D("1400"),
        fill_quantity=-100,
        fill_price=D("1450"),
    )

    assert out.new_quantity == 0
    assert out.new_average_price == D("0.0000")
    assert out.realized_pnl == D("5000.00")
    assert out.closed_quantity == 100
    assert out.opened_quantity == 0


def test_long_exit_realizes_a_loss():
    """+100 @ 1400, SELL 100 @ 1350 -> flat, -5,000."""
    out = apply_fill(
        quantity=100,
        average_price=D("1400"),
        fill_quantity=-100,
        fill_price=D("1350"),
    )

    assert out.new_quantity == 0
    assert out.realized_pnl == D("-5000.00")


# --------------------------------------------------------------------------
# Partial long exit
# --------------------------------------------------------------------------


def test_partial_long_exit_keeps_the_original_basis():
    """+100 @ 1400, SELL 40 @ 1450 -> +60 still @ 1400, +2,000 realized."""
    out = apply_fill(
        quantity=100,
        average_price=D("1400"),
        fill_quantity=-40,
        fill_price=D("1450"),
    )

    assert out.new_quantity == 60
    assert out.new_average_price == D("1400"), "surviving units keep their basis"
    assert out.realized_pnl == D("2000.00")
    assert out.closed_quantity == 40
    assert out.opened_quantity == 0


def test_repeated_partial_exits_accumulate_correctly():
    """Three partial sells of a 300 lot realize the same as one sell of 300."""
    quantity, average = 300, D("1000")
    total = D("0.00")
    for size in (100, 100, 100):
        out = apply_fill(
            quantity=quantity,
            average_price=average,
            fill_quantity=-size,
            fill_price=D("1100"),
        )
        total += out.realized_pnl
        quantity, average = out.new_quantity, out.new_average_price

    assert quantity == 0
    assert total == D("30000.00")


# --------------------------------------------------------------------------
# Short entry
# --------------------------------------------------------------------------


def test_short_entry_from_flat():
    """SHORT 100 @ 1450 -> -100 @ 1450."""
    out = apply_fill(
        quantity=0, average_price=D("0"), fill_quantity=-100, fill_price=D("1450")
    )

    assert out.new_quantity == -100
    assert out.new_average_price == D("1450")
    assert out.realized_pnl == D("0.00")
    assert out.opened_quantity == 100


def test_adding_to_a_short_averages_the_entry_price():
    """-100 @ 1450, SHORT 100 @ 1550 -> -200 @ 1500."""
    out = apply_fill(
        quantity=-100,
        average_price=D("1450"),
        fill_quantity=-100,
        fill_price=D("1550"),
    )

    assert out.new_quantity == -200
    assert out.new_average_price == D("1500.0000")
    assert out.realized_pnl == D("0.00")


# --------------------------------------------------------------------------
# Short cover
# --------------------------------------------------------------------------


def test_short_cover_profits_when_price_falls():
    """-100 @ 1450, BUY 100 @ 1400 -> flat, +5,000."""
    out = apply_fill(
        quantity=-100,
        average_price=D("1450"),
        fill_quantity=100,
        fill_price=D("1400"),
    )

    assert out.new_quantity == 0
    assert out.new_average_price == D("0.0000")
    assert out.realized_pnl == D("5000.00")
    assert out.closed_quantity == 100


def test_short_cover_loses_when_price_rises():
    """-100 @ 1450, BUY 100 @ 1500 -> flat, -5,000."""
    out = apply_fill(
        quantity=-100,
        average_price=D("1450"),
        fill_quantity=100,
        fill_price=D("1500"),
    )

    assert out.new_quantity == 0
    assert out.realized_pnl == D("-5000.00")


def test_partial_short_cover_keeps_the_original_basis():
    """-100 @ 1450, BUY 30 @ 1400 -> -70 still @ 1450, +1,500."""
    out = apply_fill(
        quantity=-100,
        average_price=D("1450"),
        fill_quantity=30,
        fill_price=D("1400"),
    )

    assert out.new_quantity == -70
    assert out.new_average_price == D("1450")
    assert out.realized_pnl == D("1500.00")


# --------------------------------------------------------------------------
# Reversals
# --------------------------------------------------------------------------


def test_reversal_from_long_to_short():
    """+100 @ 1400, SELL 150 @ 1450.

    Closes 100 for +5,000 and opens a 50 short at 1450 -- the new basis is the
    fill price, not the old long's.
    """
    out = apply_fill(
        quantity=100,
        average_price=D("1400"),
        fill_quantity=-150,
        fill_price=D("1450"),
    )

    assert out.new_quantity == -50
    assert out.new_average_price == D("1450")
    assert out.realized_pnl == D("5000.00")
    assert out.closed_quantity == 100
    assert out.opened_quantity == 50
    assert out.is_reversal


def test_reversal_from_short_to_long():
    """-100 @ 1450, BUY 250 @ 1400.

    Closes 100 for +5,000 and opens a 150 long at 1400.
    """
    out = apply_fill(
        quantity=-100,
        average_price=D("1450"),
        fill_quantity=250,
        fill_price=D("1400"),
    )

    assert out.new_quantity == 150
    assert out.new_average_price == D("1400")
    assert out.realized_pnl == D("5000.00")
    assert out.closed_quantity == 100
    assert out.opened_quantity == 150
    assert out.is_reversal


def test_reversal_realizes_only_the_closed_portion():
    """A loss-making reversal must not price the new leg into the P&L."""
    out = apply_fill(
        quantity=100,
        average_price=D("1400"),
        fill_quantity=-300,
        fill_price=D("1300"),
    )

    assert out.realized_pnl == D("-10000.00"), "100 units x -100, not 300 x -100"
    assert out.new_quantity == -200
    assert out.new_average_price == D("1300")


# --------------------------------------------------------------------------
# The worked example from the specification
# --------------------------------------------------------------------------


def test_the_specified_round_trip_sequence():
    """BUY 100@1400 -> +100; SELL 100@1450 -> 0; SHORT 100@1450 -> -100;
    BUY 100@1400 -> 0. Total realized 10,000."""
    quantity, average, realized = 0, D("0"), D("0.00")

    for fill_quantity, price in (
        (100, D("1400")),
        (-100, D("1450")),
        (-100, D("1450")),
        (100, D("1400")),
    ):
        out = apply_fill(
            quantity=quantity,
            average_price=average,
            fill_quantity=fill_quantity,
            fill_price=price,
        )
        quantity, average = out.new_quantity, out.new_average_price
        realized += out.realized_pnl

    assert quantity == 0
    assert realized == D("10000.00"), "5,000 on the long plus 5,000 on the short"


# --------------------------------------------------------------------------
# Edge cases
# --------------------------------------------------------------------------


def test_zero_fill_changes_nothing():
    out = apply_fill(
        quantity=100, average_price=D("1400"), fill_quantity=0, fill_price=D("1500")
    )

    assert out.new_quantity == 100
    assert out.new_average_price == D("1400")
    assert out.realized_pnl == D("0.00")


def test_flat_position_carries_no_entry_price():
    """Required by the ck_positions_average_price_matches_quantity constraint."""
    out = apply_fill(
        quantity=50, average_price=D("1400"), fill_quantity=-50, fill_price=D("1400")
    )

    assert out.new_quantity == 0
    assert out.new_average_price == D("0.0000")


def test_average_price_keeps_four_decimals_to_limit_drift():
    """3 @ 100 + 4 @ 101 = 100.5714..., not 100.57."""
    out = apply_fill(
        quantity=3, average_price=D("100"), fill_quantity=4, fill_price=D("101")
    )

    assert out.new_average_price == D("100.5714")


# --------------------------------------------------------------------------
# PnLCalculator directly
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("entry", "exit_", "quantity", "direction", "expected"),
    [
        ("1400", "1450", 100, 1, "5000.00"),
        ("1400", "1350", 100, 1, "-5000.00"),
        ("1450", "1400", 100, -1, "5000.00"),
        ("1450", "1500", 100, -1, "-5000.00"),
    ],
)
def test_realized_pnl_signs(entry, exit_, quantity, direction, expected):
    result = PnLCalculator.realized_pnl(
        entry_price=D(entry),
        exit_price=D(exit_),
        quantity=quantity,
        direction=direction,
    )

    assert result == D(expected)


def test_unrealized_pnl_uses_the_signed_quantity():
    long_pnl = PnLCalculator.unrealized_pnl(
        quantity=100, average_price=D("1400"), mark_price=D("1450")
    )
    short_pnl = PnLCalculator.unrealized_pnl(
        quantity=-100, average_price=D("1450"), mark_price=D("1400")
    )

    assert long_pnl == D("5000.00")
    assert short_pnl == D("5000.00")


def test_unrealized_pnl_is_zero_when_flat():
    assert (
        PnLCalculator.unrealized_pnl(
            quantity=0, average_price=D("0"), mark_price=D("1450")
        )
        == D("0.00")
    )


def test_short_position_value_is_a_negative_liability():
    assert PnLCalculator.position_value(quantity=-100, mark_price=D("1450")) == D(
        "-145000.00"
    )
