"""Trading domain enumerations.

Stored as native PostgreSQL enums so the database rejects a bad value even if
it arrives outside the application.
"""

from enum import StrEnum


class OrderSide(StrEnum):
    """The four supported actions.

    ``BUY`` and ``BUY_TO_COVER`` both increase quantity; ``SELL`` and
    ``SHORT_SELL`` both decrease it. The pairs differ in *intent*, which the
    engine validates:

    * ``SELL`` closes a long and may not exceed it -- selling more than you
      hold must be stated explicitly as ``SHORT_SELL``.
    * ``BUY_TO_COVER`` closes a short and may not exceed it -- buying beyond
      the short must be stated explicitly as ``BUY``.
    * ``BUY`` and ``SHORT_SELL`` may cross through zero and reverse the
      position.
    """

    BUY = "BUY"
    SELL = "SELL"
    SHORT_SELL = "SHORT_SELL"
    BUY_TO_COVER = "BUY_TO_COVER"

    @property
    def direction(self) -> int:
        """+1 when the side increases quantity, -1 when it decreases it."""
        return 1 if self in (OrderSide.BUY, OrderSide.BUY_TO_COVER) else -1

    @property
    def is_closing_only(self) -> bool:
        """True for sides that may only reduce an existing position."""
        return self in (OrderSide.SELL, OrderSide.BUY_TO_COVER)


class OrderStatus(StrEnum):
    PENDING = "PENDING"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class OrderType(StrEnum):
    """Only MARKET exists in Stage 4.

    Orders execute at a price supplied by the caller; limit and stop handling
    arrive with the live-pricing stage.
    """

    MARKET = "MARKET"
