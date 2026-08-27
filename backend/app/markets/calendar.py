"""Market calendars: when an instrument may be traded.

    Instrument -> AssetClass -> MarketCalendar -> is_market_open()

This is the *only* place trading-schedule knowledge lives. No API route and no
React component decides whether a market is open; they ask a calendar, or they
read what the backend already resolved.

Two implementations today:

* :class:`NSEMarketCalendar` -- Mon-Fri, 09:15-15:30 IST, minus the configured
  holiday list. Pre-open (09:00-09:15) is a call auction rather than
  continuous trading, so it reports ``PRE_OPEN``, and ``is_market_open()`` is
  False during it.
* :class:`CryptoMarketCalendar` -- always open. Every hour, every day,
  including weekends and Indian exchange holidays. ``next_open`` and
  ``next_close`` are ``None`` because a continuous market has neither.

Adding an ETF or INDEX class means registering a calendar in
``app/markets/registry.py``; nothing in the trading engine changes.

**All arithmetic is timezone-aware.** A naive datetime is interpreted as UTC
rather than as local time, so the answer does not depend on where the server
happens to be running.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

#: How far ahead ``next_open``/``next_close`` will search before giving up.
#: Comfortably longer than any realistic exchange closure.
_SEARCH_HORIZON_DAYS = settings.CALENDAR_SEARCH_HORIZON_DAYS


class TradingStatus(StrEnum):
    """What a market is doing right now."""

    OPEN = "OPEN"
    #: Call-auction window before the continuous session. Not tradable here.
    PRE_OPEN = "PRE_OPEN"
    #: A normal trading day, but outside session hours.
    CLOSED = "CLOSED"
    WEEKEND = "WEEKEND"
    HOLIDAY = "HOLIDAY"


@dataclass(frozen=True)
class MarketSession:
    """A calendar's full answer about one moment.

    ``next_open`` and ``next_close`` are ``None`` for a market that never
    closes, which is a meaningful answer rather than a missing one.
    """

    status: TradingStatus
    is_open: bool
    #: The moment this describes, in the market's own timezone.
    at: datetime
    timezone: str
    next_open: datetime | None
    next_close: datetime | None
    #: Human explanation, e.g. "NSE is closed for a holiday."
    reason: str

    @property
    def is_24x7(self) -> bool:
        return self.next_open is None and self.next_close is None and self.is_open


class MarketCalendar(ABC):
    """When may this market be traded?"""

    #: Stable identifier, surfaced by the API.
    name: str = "market"

    @property
    @abstractmethod
    def timezone(self) -> str:
        """IANA timezone the schedule is expressed in."""

    @property
    def is_continuous(self) -> bool:
        """True for a market with no session boundaries at all."""
        return False

    @abstractmethod
    def is_market_open(self, at: datetime | None = None) -> bool:
        """Whether continuous trading is available at ``at`` (default: now)."""

    @abstractmethod
    def next_open(self, after: datetime | None = None) -> datetime | None:
        """When trading next becomes available. ``None`` if always open."""

    @abstractmethod
    def next_close(self, after: datetime | None = None) -> datetime | None:
        """When trading next stops. ``None`` if it never does."""

    @abstractmethod
    def trading_status(self, at: datetime | None = None) -> MarketSession:
        """The full picture: status, open flag, next boundaries and a reason."""

    # -- shared helpers ---------------------------------------------------

    def _localise(self, at: datetime | None) -> datetime:
        """Coerce any input to an aware datetime in this market's timezone.

        A naive datetime is read as UTC. Guessing the server's local zone
        instead would make the same call answer differently on two machines.
        """
        moment = at or datetime.now(tz=UTC)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC)
        return moment.astimezone(ZoneInfo(self.timezone))


class CryptoMarketCalendar(MarketCalendar):
    """Crypto: open 24 hours a day, 7 days a week, permanently.

    Saturday 02:00, Sunday 18:30, Monday 03:00, Diwali, Christmas -- all open.
    Nothing about this schedule consults the NSE calendar, by construction:
    there is no code path from here to a weekday check or a holiday list.
    """

    name = "crypto"

    def __init__(self, timezone: str = "UTC") -> None:
        # Only affects how times are *displayed*; the market is open at every
        # instant regardless of which zone the question is asked in.
        self._timezone = timezone

    @property
    def timezone(self) -> str:
        return self._timezone

    @property
    def is_continuous(self) -> bool:
        return True

    def is_market_open(self, at: datetime | None = None) -> bool:
        return True

    def next_open(self, after: datetime | None = None) -> datetime | None:
        # Never closed, so there is no next open. None says that precisely;
        # returning "now" would imply a boundary that does not exist.
        return None

    def next_close(self, after: datetime | None = None) -> datetime | None:
        return None

    def trading_status(self, at: datetime | None = None) -> MarketSession:
        return MarketSession(
            status=TradingStatus.OPEN,
            is_open=True,
            at=self._localise(at),
            timezone=self._timezone,
            next_open=None,
            next_close=None,
            reason="Crypto trades continuously, 24 hours a day, every day.",
        )


class NSEMarketCalendar(MarketCalendar):
    """The NSE cash-market schedule.

    Mon-Fri, ``open_time``-``close_time`` in ``timezone``, excluding the
    configured full-day holidays.

    **The holiday list is configuration, not code.** NSE publishes it annually
    and most of it moves year to year, so ``NSE_HOLIDAYS`` ships only
    fixed-date national holidays and must be topped up from the official
    circular. An out-of-date list means the calendar reports OPEN on a day the
    exchange was shut -- see ARCHITECTURE.md 20.4.
    """

    name = "nse"

    def __init__(
        self,
        *,
        timezone: str = "Asia/Kolkata",
        pre_open_time: time = time(9, 0),
        open_time: time = time(9, 15),
        close_time: time = time(15, 30),
        holidays: frozenset[date] = frozenset(),
    ) -> None:
        self._timezone = timezone
        self._pre_open = pre_open_time
        self._open = open_time
        self._close = close_time
        self._holidays = holidays

    @classmethod
    def from_settings(cls) -> "NSEMarketCalendar":
        from app.core.config import settings

        return cls(
            timezone=settings.NSE_TIMEZONE,
            pre_open_time=_parse_time(settings.NSE_PRE_OPEN_TIME, time(9, 0)),
            open_time=_parse_time(settings.NSE_OPEN_TIME, time(9, 15)),
            close_time=_parse_time(settings.NSE_CLOSE_TIME, time(15, 30)),
            holidays=_parse_holidays(settings.NSE_HOLIDAYS),
        )

    @property
    def timezone(self) -> str:
        return self._timezone

    @property
    def holidays(self) -> frozenset[date]:
        return self._holidays

    # -- queries ----------------------------------------------------------

    def is_trading_day(self, day: date) -> bool:
        """A weekday that is not a listed holiday."""
        return day.weekday() < 5 and day not in self._holidays

    def is_market_open(self, at: datetime | None = None) -> bool:
        moment = self._localise(at)
        if not self.is_trading_day(moment.date()):
            return False
        # Half-open interval: 15:30:00 exactly is the close, not still open.
        return self._open <= moment.timetz().replace(tzinfo=None) < self._close

    def next_open(self, after: datetime | None = None) -> datetime | None:
        moment = self._localise(after)

        # Later today, if today trades and the bell has not rung yet.
        if self.is_trading_day(moment.date()):
            todays_open = self._at(moment.date(), self._open)
            if moment < todays_open:
                return todays_open

        for offset in range(1, _SEARCH_HORIZON_DAYS + 1):
            day = moment.date() + timedelta(days=offset)
            if self.is_trading_day(day):
                return self._at(day, self._open)

        # Only reachable if the holiday list closes the exchange for a month.
        logger.warning(
            "No NSE trading day found within %s days of %s.",
            _SEARCH_HORIZON_DAYS,
            moment.date(),
        )
        return None

    def next_close(self, after: datetime | None = None) -> datetime | None:
        moment = self._localise(after)

        if self.is_trading_day(moment.date()):
            todays_close = self._at(moment.date(), self._close)
            if moment < todays_close:
                return todays_close

        for offset in range(1, _SEARCH_HORIZON_DAYS + 1):
            day = moment.date() + timedelta(days=offset)
            if self.is_trading_day(day):
                return self._at(day, self._close)

        return None

    def trading_status(self, at: datetime | None = None) -> MarketSession:
        moment = self._localise(at)
        day = moment.date()
        clock = moment.timetz().replace(tzinfo=None)

        if day in self._holidays:
            status = TradingStatus.HOLIDAY
            reason = f"NSE is closed: {day.isoformat()} is a trading holiday."
        elif day.weekday() >= 5:
            status = TradingStatus.WEEKEND
            reason = "NSE is closed for the weekend."
        elif self._pre_open <= clock < self._open:
            status = TradingStatus.PRE_OPEN
            reason = (
                "NSE is in the pre-open call auction; continuous trading has "
                "not started."
            )
        elif clock < self._open:
            status = TradingStatus.CLOSED
            reason = "NSE has not opened yet today."
        elif clock < self._close:
            status = TradingStatus.OPEN
            reason = "NSE is open for continuous trading."
        else:
            status = TradingStatus.CLOSED
            reason = "NSE has closed for the day."

        return MarketSession(
            status=status,
            is_open=status is TradingStatus.OPEN,
            at=moment,
            timezone=self._timezone,
            next_open=self.next_open(moment),
            next_close=self.next_close(moment),
            reason=reason,
        )

    # -- internals --------------------------------------------------------

    def _at(self, day: date, clock: time) -> datetime:
        return datetime.combine(day, clock, tzinfo=ZoneInfo(self._timezone))


def _parse_time(raw: str, fallback: time) -> time:
    """Parse ``HH:MM`` from configuration, falling back rather than crashing."""
    try:
        hour, _, minute = raw.strip().partition(":")
        return time(int(hour), int(minute))
    except (ValueError, AttributeError):
        logger.warning("Could not parse market time '%s'; using %s.", raw, fallback)
        return fallback


def _parse_holidays(raw: list[str]) -> frozenset[date]:
    """Parse ISO dates from configuration, skipping anything malformed."""
    days: set[date] = set()
    for entry in raw or ():
        try:
            days.add(date.fromisoformat(str(entry).strip()))
        except ValueError:
            logger.warning("Ignoring unparseable NSE holiday '%s'.", entry)
    return frozenset(days)
