"""Market calendar tests.

The whole point of the calendar layer is that crypto's schedule does not
consult NSE's. These tests pin that down at the times the brief names --
Saturday 02:00, Sunday 18:30, Monday 03:00 -- and on an Indian holiday.

Every case passes an explicit ``datetime``. Nothing here depends on when the
suite happens to run, which is what makes "is it open on a Sunday?" a question
with a stable answer.
"""

from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo

import pytest

from app.markets.calendar import (
    CryptoMarketCalendar,
    NSEMarketCalendar,
    TradingStatus,
)
from app.markets.registry import (
    calendar_for_symbol,
    is_tradable_now,
    reset_calendars,
    trading_status_for,
)

IST = ZoneInfo("Asia/Kolkata")

#: A fixed week in 2026 used throughout, so every weekday is unambiguous.
#: 2026-08-24 is a Monday, so 29th is Saturday and 30th is Sunday.
MONDAY = datetime(2026, 8, 24, 12, 0, tzinfo=IST)
WEDNESDAY = datetime(2026, 8, 26, 12, 0, tzinfo=IST)
FRIDAY = datetime(2026, 8, 28, 12, 0, tzinfo=IST)
SATURDAY = datetime(2026, 8, 29, 2, 0, tzinfo=IST)
SUNDAY = datetime(2026, 8, 30, 18, 30, tzinfo=IST)

#: A configured full-day NSE holiday.
HOLIDAY = datetime(2026, 1, 26, 12, 0, tzinfo=IST)


@pytest.fixture(autouse=True)
def _fresh_calendars():
    """Calendars are cached process-wide; rebuild them around each test."""
    reset_calendars()
    yield
    reset_calendars()


def nse() -> NSEMarketCalendar:
    return NSEMarketCalendar(
        holidays=frozenset({HOLIDAY.date()}),
    )


# ==========================================================================
# NSE: open
# ==========================================================================


def test_nse_is_open_during_the_session_on_a_weekday():
    assert nse().is_market_open(WEDNESDAY) is True
    assert nse().trading_status(WEDNESDAY).status is TradingStatus.OPEN


def test_nse_opens_exactly_at_the_bell_and_closes_exactly_at_the_close():
    calendar = nse()
    day = WEDNESDAY.date()

    just_before = datetime.combine(day, time(9, 14, 59), tzinfo=IST)
    at_open = datetime.combine(day, time(9, 15), tzinfo=IST)
    just_before_close = datetime.combine(day, time(15, 29, 59), tzinfo=IST)
    at_close = datetime.combine(day, time(15, 30), tzinfo=IST)

    assert calendar.is_market_open(just_before) is False
    assert calendar.is_market_open(at_open) is True
    assert calendar.is_market_open(just_before_close) is True
    # The close is the boundary, not still trading.
    assert calendar.is_market_open(at_close) is False


# ==========================================================================
# NSE: closed
# ==========================================================================


def test_nse_is_closed_before_the_open_and_after_the_close():
    calendar = nse()
    day = WEDNESDAY.date()

    early = datetime.combine(day, time(7, 0), tzinfo=IST)
    late = datetime.combine(day, time(16, 30), tzinfo=IST)

    assert calendar.is_market_open(early) is False
    assert calendar.trading_status(early).status is TradingStatus.CLOSED
    assert calendar.is_market_open(late) is False
    assert calendar.trading_status(late).status is TradingStatus.CLOSED


def test_the_pre_open_auction_is_reported_but_is_not_open_for_trading():
    """09:00-09:15 is a call auction, not continuous trading."""
    calendar = nse()
    pre_open = datetime.combine(WEDNESDAY.date(), time(9, 5), tzinfo=IST)

    assert calendar.trading_status(pre_open).status is TradingStatus.PRE_OPEN
    assert calendar.is_market_open(pre_open) is False


# ==========================================================================
# NSE: weekend and holiday
# ==========================================================================


def test_nse_is_closed_on_saturday():
    calendar = nse()
    midday = datetime.combine(SATURDAY.date(), time(12, 0), tzinfo=IST)
    assert calendar.is_market_open(midday) is False
    assert calendar.trading_status(midday).status is TradingStatus.WEEKEND


def test_nse_is_closed_on_sunday():
    calendar = nse()
    assert calendar.is_market_open(SUNDAY) is False
    assert calendar.trading_status(SUNDAY).status is TradingStatus.WEEKEND


def test_nse_is_closed_on_a_configured_holiday_even_though_it_is_a_weekday():
    calendar = nse()
    assert HOLIDAY.weekday() < 5, "the fixture date must be a weekday to prove this"
    assert calendar.is_market_open(HOLIDAY) is False
    assert calendar.trading_status(HOLIDAY).status is TradingStatus.HOLIDAY


def test_the_holiday_reason_names_the_date():
    assert HOLIDAY.date().isoformat() in nse().trading_status(HOLIDAY).reason


# ==========================================================================
# NSE: next open / next close
# ==========================================================================


def test_next_open_from_a_saturday_is_the_following_monday_morning():
    when = nse().next_open(SATURDAY)
    assert when is not None
    assert when.date() == datetime(2026, 8, 31).date()
    assert when.timetz().replace(tzinfo=None) == time(9, 15)


def test_next_open_skips_a_holiday():
    """26 Jan 2026 is a configured holiday; the 23rd is the Friday before."""
    friday_evening = datetime(2026, 1, 23, 18, 0, tzinfo=IST)
    when = nse().next_open(friday_evening)
    assert when is not None
    # Saturday, Sunday and the Monday holiday are all skipped.
    assert when.date() == datetime(2026, 1, 27).date()


def test_next_close_during_a_session_is_todays_close():
    when = nse().next_close(WEDNESDAY)
    assert when is not None
    assert when.date() == WEDNESDAY.date()
    assert when.timetz().replace(tzinfo=None) == time(15, 30)


def test_next_close_after_the_bell_is_the_next_trading_day():
    friday_evening = datetime.combine(FRIDAY.date(), time(18, 0), tzinfo=IST)
    when = nse().next_close(friday_evening)
    assert when is not None
    assert when.date() == datetime(2026, 8, 31).date()


# ==========================================================================
# Crypto: always open
# ==========================================================================


def test_crypto_is_open_on_a_weekday_afternoon():
    assert CryptoMarketCalendar().is_market_open(WEDNESDAY) is True


def test_crypto_is_open_at_two_in_the_morning_on_a_saturday():
    """The brief's example: BTC, Saturday 02:00 -> trading allowed."""
    assert CryptoMarketCalendar().is_market_open(SATURDAY) is True


def test_crypto_is_open_on_a_sunday_evening():
    """The brief's example: BTC, Sunday 18:30 -> trading allowed."""
    assert CryptoMarketCalendar().is_market_open(SUNDAY) is True


def test_crypto_is_open_at_three_in_the_morning_on_a_monday():
    """The brief's example: BTC, Monday 03:00 -> trading allowed."""
    monday_night = datetime.combine(MONDAY.date(), time(3, 0), tzinfo=IST)
    assert CryptoMarketCalendar().is_market_open(monday_night) is True


def test_crypto_is_open_on_an_indian_exchange_holiday():
    assert CryptoMarketCalendar().is_market_open(HOLIDAY) is True


def test_crypto_is_open_at_every_hour_of_every_day_of_a_whole_week():
    """Exhaustive rather than illustrative: 7 days x 24 hours, all open."""
    calendar = CryptoMarketCalendar()
    for day in range(24, 31):
        for hour in range(24):
            moment = datetime(2026, 8, day, hour, 30, tzinfo=IST)
            assert calendar.is_market_open(moment) is True, moment


def test_crypto_reports_no_next_open_or_close_because_it_never_closes():
    calendar = CryptoMarketCalendar()
    # None is the honest answer -- a continuous market has no boundary, and
    # returning "now" would invent one.
    assert calendar.next_open(SATURDAY) is None
    assert calendar.next_close(SATURDAY) is None
    assert calendar.is_continuous is True


def test_the_crypto_session_reports_open_with_a_24x7_reason():
    session = CryptoMarketCalendar().trading_status(SUNDAY)
    assert session.status is TradingStatus.OPEN
    assert session.is_open is True
    assert session.is_24x7 is True


# ==========================================================================
# Independence: the crypto schedule does not consult NSE's
# ==========================================================================


def test_crypto_stays_open_at_every_moment_nse_is_shut():
    """The core requirement, stated as a direct comparison."""
    equities = nse()
    crypto = CryptoMarketCalendar()

    shut = [SATURDAY, SUNDAY, HOLIDAY]
    shut.append(datetime.combine(WEDNESDAY.date(), time(3, 0), tzinfo=IST))
    shut.append(datetime.combine(WEDNESDAY.date(), time(22, 0), tzinfo=IST))

    for moment in shut:
        assert equities.is_market_open(moment) is False, moment
        assert crypto.is_market_open(moment) is True, moment


# ==========================================================================
# Routing: an instrument gets the calendar for its asset class
# ==========================================================================


def test_a_stock_is_routed_to_the_nse_calendar():
    assert calendar_for_symbol("RELIANCE").name == "nse"


def test_a_coin_is_routed_to_the_crypto_calendar():
    assert calendar_for_symbol("BTC").name == "crypto"
    assert calendar_for_symbol("ETH").name == "crypto"


def test_every_crypto_instrument_is_tradable_right_now():
    """Whenever this suite runs -- weekday, weekend, 3am -- crypto is open."""
    from app.market_data.instruments import AssetClass, instrument_registry

    for instrument in instrument_registry.all(AssetClass.CRYPTO):
        assert is_tradable_now(instrument.symbol) is True, instrument.symbol


def test_trading_status_for_a_coin_reports_a_continuous_market():
    session = trading_status_for("BTC")
    assert session.is_open is True
    assert session.next_open is None
    assert session.next_close is None


def test_an_unsupported_symbol_has_no_calendar():
    from app.core.exceptions import UnsupportedSymbolError

    with pytest.raises(UnsupportedSymbolError):
        calendar_for_symbol("AAPL")


# ==========================================================================
# Timezone handling
# ==========================================================================


def test_a_naive_datetime_is_read_as_utc_not_as_server_local_time():
    """Otherwise the same call would answer differently on two machines."""
    # 06:00 UTC == 11:30 IST, inside the NSE session.
    naive = datetime(2026, 8, 26, 6, 0)
    aware = datetime(2026, 8, 26, 6, 0, tzinfo=UTC)
    assert nse().is_market_open(naive) == nse().is_market_open(aware) is True


def test_a_utc_datetime_outside_the_ist_session_is_closed():
    # 04:00 UTC == 09:30 IST is open; 12:00 UTC == 17:30 IST is not.
    assert nse().is_market_open(datetime(2026, 8, 26, 4, 0, tzinfo=UTC)) is True
    assert nse().is_market_open(datetime(2026, 8, 26, 12, 0, tzinfo=UTC)) is False


def test_the_session_is_reported_in_the_markets_own_timezone():
    session = nse().trading_status(datetime(2026, 8, 26, 6, 0, tzinfo=UTC))
    assert session.timezone == "Asia/Kolkata"
    assert session.at.hour == 11 and session.at.minute == 30


# ==========================================================================
# Configuration
# ==========================================================================


def test_an_unparseable_holiday_is_ignored_rather_than_crashing_the_calendar():
    """A typo in configuration must not take the whole platform down."""
    from app.markets.calendar import _parse_holidays

    parsed = _parse_holidays(["2026-01-26", "not-a-date", "2026-12-25"])
    assert len(parsed) == 2


def test_an_unparseable_session_time_falls_back_rather_than_crashing():
    from app.markets.calendar import _parse_time

    assert _parse_time("bogus", time(9, 15)) == time(9, 15)
    assert _parse_time("10:30", time(9, 15)) == time(10, 30)
