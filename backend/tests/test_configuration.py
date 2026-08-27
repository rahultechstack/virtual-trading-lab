"""Configuration tests.

These exist to prove the centralisation is real rather than cosmetic: that
changing **one** setting actually changes behaviour everywhere the value is
used, and that no module has quietly kept its own copy of a literal.

They are also the guard against regression. It is easy to add a new endpoint
with ``le=500`` typed inline; a test that reads the setting and asserts the
endpoint agrees will catch that the next time the setting moves.
"""

from decimal import Decimal
from pathlib import Path

import pytest
from httpx import AsyncClient

from app.core.config import Settings, settings

D = Decimal

#: Source root, for the "no stray literals" checks.
APP = Path(__file__).resolve().parent.parent / "app"


# ==========================================================================
# One setting governs every path that enforces it
# ==========================================================================


async def test_lowering_the_order_limit_is_respected_by_the_trading_engine(
    session, monkeypatch
):
    """The engine reads settings, not a module-level constant."""
    from app.core.exceptions import InvalidOrderError
    from app.models.enums import OrderSide
    from app.models.wallet import Wallet
    from app.trading.engine import TradingEngine
    from app.trading.execution import ExecutionEngine

    session.add(
        Wallet(
            initial_balance=D("1000000.00"),
            cash_balance=D("1000000.00"),
            currency="INR",
        )
    )
    await session.commit()

    monkeypatch.setattr(settings, "MAX_ORDER_QUANTITY", 5)
    engine = TradingEngine(session, execution=ExecutionEngine.frictionless(session))

    with pytest.raises(InvalidOrderError, match="maximum of 5"):
        await engine.place_order(
            side=OrderSide.BUY,
            quantity=10,
            reference_price=D("100.00"),
            symbol="RELIANCE",
        )


async def test_lowering_the_order_limit_is_respected_by_automatic_orders(
    session, monkeypatch
):
    """The automation service reads the same setting the engine does."""
    from app.automation.service import AutomaticOrderService
    from app.core.exceptions import InvalidAutomaticOrderError
    from app.models.automatic_order import AutomaticOrderType, TriggerCondition
    from app.models.enums import OrderSide

    monkeypatch.setattr(settings, "MAX_ORDER_QUANTITY", 5)

    with pytest.raises(InvalidAutomaticOrderError, match="maximum of 5"):
        await AutomaticOrderService(session).create(
            order_type=AutomaticOrderType.PRICE_TRIGGER,
            trigger_price=D("100.00"),
            trigger_condition=TriggerCondition.GTE,
            action=OrderSide.BUY,
            quantity=10,
            symbol="RELIANCE",
        )


async def test_lowering_the_indicator_cap_is_respected(monkeypatch):
    from app.core.exceptions import DomainError
    from app.indicators.definitions import parse_specs

    monkeypatch.setattr(settings, "MAX_INDICATORS_PER_REQUEST", 1)

    with pytest.raises(DomainError, match="At most 1 indicators"):
        parse_specs("sma:20,ema:21")


async def test_lowering_the_candle_cap_is_respected(monkeypatch):
    """The service clamps to the setting, not to a module constant."""
    from app.schemas.market_data import Interval
    from app.services.market_data_service import MarketDataService

    asked: dict = {}

    class _Recording:
        capabilities = type(
            "C",
            (),
            {"supported_intervals": list(Interval), "name": "recording"},
        )()

        async def get_historical_candles(self, **kwargs):
            asked.update(kwargs)
            return []

    monkeypatch.setattr(settings, "MAX_CANDLES_PER_REQUEST", 7)

    await MarketDataService(_Recording()).get_historical_candles(
        interval=Interval.ONE_DAY, limit=1000, symbol="RELIANCE"
    )
    assert asked["limit"] == 7


def test_the_market_data_endpoint_is_configurable(monkeypatch):
    """The provider takes its URL from settings, not a module literal."""
    from app.market_data.yahoo import YahooFinanceProvider

    monkeypatch.setattr(settings, "MARKET_DATA_BASE_URL", "https://example.test/chart")
    provider = YahooFinanceProvider()
    # httpx normalises a base URL with a trailing slash.
    assert str(provider._client.base_url).rstrip("/") == "https://example.test/chart"


def test_the_market_data_user_agent_is_configurable(monkeypatch):
    from app.market_data.yahoo import YahooFinanceProvider

    monkeypatch.setattr(settings, "MARKET_DATA_USER_AGENT", "probe/1.0")
    provider = YahooFinanceProvider()
    assert provider._client.headers["User-Agent"] == "probe/1.0"


def test_the_crypto_quote_currency_is_configurable(monkeypatch):
    from app.market_data.crypto import YahooCryptoProvider

    monkeypatch.setattr(settings, "CRYPTO_QUOTE_CURRENCY", "USD")
    assert YahooCryptoProvider.from_settings()._vendor_symbol("BTC", "CRYPTO") == (
        "BTC-USD"
    )


# ==========================================================================
# The API surface reflects the configured limits
# ==========================================================================


async def test_history_page_limits_come_from_settings(client: AsyncClient):
    """Requesting more than the configured cap is refused, not silently cut."""
    over = settings.MAX_HISTORY_PAGE_SIZE + 1
    response = await client.get("/api/v1/trading/orders", params={"limit": over})
    assert response.status_code == 422

    at_cap = await client.get(
        "/api/v1/trading/orders", params={"limit": settings.MAX_HISTORY_PAGE_SIZE}
    )
    assert at_cap.status_code == 200


async def test_the_order_schema_advertises_the_configured_limit(client: AsyncClient):
    """OpenAPI shows the configured value, so clients see the real bound.

    ``quantity`` accepts a number or a Decimal string, so the bound sits on the
    numeric branch of the ``anyOf``.
    """
    schema = (await client.get("/openapi.json")).json()
    quantity = schema["components"]["schemas"]["PlaceOrderRequest"]["properties"][
        "quantity"
    ]
    numeric = next(
        branch for branch in quantity["anyOf"] if branch.get("type") == "number"
    )
    assert numeric["maximum"] == settings.MAX_ORDER_QUANTITY


async def test_the_candle_endpoint_advertises_the_configured_cap(client: AsyncClient):
    over = settings.MAX_CANDLES_PER_REQUEST + 1
    response = await client.get(
        "/api/v1/market-data/candles", params={"limit": over, "interval": "1d"}
    )
    assert response.status_code == 422


# ==========================================================================
# Nothing has kept a private copy of a centralised value
# ==========================================================================


def _sources() -> list[Path]:
    return [
        path
        for path in APP.rglob("*.py")
        if "__pycache__" not in str(path)
    ]


@pytest.mark.parametrize(
    ("literal", "allowed_in"),
    [
        # The order limit lives in settings; models keep the DDL ceiling only.
        ("10_000_000", {"config.py", "trading.py"}),
        # The candle cap lives in settings.
        ("le=5000", set()),
        # Page sizes live in settings.
        ("le=500)", set()),
    ],
)
def test_no_module_keeps_its_own_copy_of_a_centralised_limit(literal, allowed_in):
    offenders = [
        path.name
        for path in _sources()
        if literal in path.read_text(encoding="utf-8") and path.name not in allowed_in
    ]
    assert not offenders, (
        f"{literal!r} is centralised in app/core/config.py but still appears "
        f"literally in: {sorted(set(offenders))}"
    )


def test_the_upstream_endpoint_is_not_hard_coded_outside_config():
    offenders = [
        path.name
        for path in _sources()
        if "query1.finance.yahoo.com" in path.read_text(encoding="utf-8")
        and path.name != "config.py"
    ]
    assert not offenders, f"upstream URL hard-coded in: {sorted(set(offenders))}"


def test_only_config_reads_the_environment():
    """Every setting must arrive through Settings, so .env is authoritative."""
    offenders = [
        path.name
        for path in _sources()
        if ("os.environ" in path.read_text(encoding="utf-8")
            or "os.getenv" in path.read_text(encoding="utf-8"))
        and path.name != "config.py"
    ]
    assert not offenders, f"reads the environment directly: {sorted(set(offenders))}"


# ==========================================================================
# Settings are genuinely overridable from the environment
# ==========================================================================


def test_every_setting_can_be_overridden_by_an_environment_variable(monkeypatch):
    """A field nobody can set from .env is not really configuration."""
    monkeypatch.setenv("MAX_ORDER_QUANTITY", "42")
    monkeypatch.setenv("CRYPTO_FEE_PERCENT", "0.25")
    monkeypatch.setenv("ENFORCE_MARKET_HOURS", "true")

    fresh = Settings()
    assert fresh.MAX_ORDER_QUANTITY == 42
    assert fresh.CRYPTO_FEE_PERCENT == D("0.25")
    assert fresh.ENFORCE_MARKET_HOURS is True


def test_the_holiday_list_accepts_a_comma_separated_environment_value(monkeypatch):
    monkeypatch.setenv("NSE_HOLIDAYS", "2027-01-26, 2027-08-15")
    assert Settings().NSE_HOLIDAYS == ["2027-01-26", "2027-08-15"]


def test_documented_env_examples_match_real_settings():
    """Guards against a setting being renamed and .env.example going stale."""
    path = APP.parent / ".env.example"
    if not path.exists():
        # Not copied into the runtime image; this check is for a source
        # checkout, where it is the one that matters.
        pytest.skip(".env.example is not present in this environment")
    example = path.read_text(encoding="utf-8")

    # Commented-out entries count as documented -- they are there to make the
    # file a complete map of what can be tuned. A prose comment that merely
    # contains "=" is not a setting, hence the strict NAME= shape.
    import re

    documented = set(
        re.findall(r"^\s*#?\s*([A-Z][A-Z0-9_]*)=", example, re.M)
    )
    known = set(Settings.model_fields)

    unknown = documented - known
    assert not unknown, (
        f".env.example documents settings that no longer exist: {sorted(unknown)}"
    )

    missing = known - documented
    assert not missing, (
        f"settings exist but .env.example does not mention them: {sorted(missing)}. "
        "Add them (commented out is fine) so the file stays a complete map."
    )


# ==========================================================================
# The instrument catalogue is one file
# ==========================================================================


def test_the_catalogue_is_the_only_place_instruments_are_declared():
    """Adding a stock or coin must mean editing exactly one file."""
    offenders = [
        path.name
        for path in _sources()
        if "_nse(" in path.read_text(encoding="utf-8") and path.name != "catalogue.py"
    ]
    assert not offenders, f"instruments declared outside the catalogue: {offenders}"


def test_the_catalogue_still_exports_what_the_registry_needs():
    from app.market_data.catalogue import (
        ALL_INSTRUMENTS,
        CRYPTO_INSTRUMENTS,
        NSE_INSTRUMENTS,
    )

    assert len(ALL_INSTRUMENTS) == len(NSE_INSTRUMENTS) + len(CRYPTO_INSTRUMENTS)
    assert {i.symbol for i in NSE_INSTRUMENTS} & {"RELIANCE", "TCS"}
    assert {i.symbol for i in CRYPTO_INSTRUMENTS} >= {"BTC", "ETH"}


def test_old_import_paths_still_work():
    """The split must not break any existing import."""
    from app.market_data.instruments import (  # noqa: F401
        ALL_INSTRUMENTS,
        SATOSHI,
        WHOLE_UNITS,
        AssetClass,
        Instrument,
        InstrumentType,
        instrument_registry,
        normalise_quantity,
        resolve_instrument,
        resolve_symbol,
    )

    assert resolve_symbol("btc") == "BTC"
