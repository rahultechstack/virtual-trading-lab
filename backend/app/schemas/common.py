"""Shared field types for the API schemas."""

from decimal import Decimal
from typing import Annotated

from pydantic import PlainSerializer


def _plain(value: Decimal) -> str:
    """Render a Decimal without scientific notation.

    Pydantic serialises ``Decimal("0E-8")`` as ``"0E-8"`` and
    ``Decimal("0.00000001")`` as ``"1E-8"``. Both are correct and both are
    useless to a client: one reads as an error, the other cannot be dropped
    into an HTML number input. ``f`` formatting gives ``0.00000000`` and
    ``0.00000001``.
    """
    return f"{value:f}"


#: A quantity on the wire: an exact Decimal, always in plain notation.
#:
#: Quantities are strings rather than JSON numbers for the same reason money
#: is -- crypto sizes carry eight decimal places, which a double would not
#: represent exactly.
Quantity = Annotated[
    Decimal,
    PlainSerializer(_plain, return_type=str, when_used="json"),
]
