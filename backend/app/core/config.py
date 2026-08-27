"""Application configuration.

**Single source of truth for every runtime setting.** Nothing else in the
codebase reads ``os.environ``, and nothing hard-codes a value a deployment
might reasonably want to change.

Every field below is overridable from ``backend/.env`` (or a real environment
variable) using the same name. See ``CONFIGURATION.md`` at the repository root
for a plain-English guide to what each one does.

Sections, in order:

===========================  ==================================================
 Section                      What lives here
===========================  ==================================================
 Application                  name, version, environment, API prefix
 Server                       bind host and port
 Database                     connection and pooling
 CORS                         which origins the browser may call from
 Feature flags                on/off switches, all in one place
 Default instrument           what the platform opens on
 Market hours                 NSE session times and the holiday list
 Market data                  provider selection, API URLs, credentials
 Mock provider                simulated-feed parameters
 Portfolio snapshots          equity-curve capture cadence
 Real-time streaming          poll interval, connection cap
 Execution realism            spread and slippage models
 Charges: equities            Indian statutory + broker charges
 Charges: crypto              simulated exchange fee, GST, TDS
 Wallet                       opening balance and currency
 Limits                       order size, page sizes, request caps
 Indicators                   VWAP session anchor, per-request cap
===========================  ==================================================

**What is NOT here, deliberately.** Structural facts that cannot be changed by
configuration alone are kept next to the code that defines them, each with a
comment saying so:

* column precision (``MONEY``, ``QUANTITY``) in ``app/models/`` -- changing it
  needs a migration;
* the supported instrument catalogue in ``app/market_data/catalogue.py`` --
  it is data, not a scalar, so it lives in its own file;
* vendor protocol details (symbol suffixes, interval names) in each provider;
* the asset-class dispatch tables (calendars, providers, fee schedules), which
  are the documented extension points for adding an asset class.
"""

import json
from decimal import Decimal
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, SecretStr, computed_field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Application ---------------------------------------------------
    APP_NAME: str = "Virtual Trading Platform"
    APP_VERSION: str = "0.1.0"
    ENVIRONMENT: Literal["development", "staging", "production"] = "development"
    DEBUG: bool = True
    API_V1_PREFIX: str = "/api/v1"

    # --- Server ---------------------------------------------------------
    BACKEND_HOST: str = "0.0.0.0"
    BACKEND_PORT: int = 8000

    # --- Database -------------------------------------------------------
    POSTGRES_USER: str = "vtrader"
    POSTGRES_PASSWORD: str = "vtrader_dev_password"
    POSTGRES_DB: str = "virtual_trading"
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432

    DB_ECHO: bool = False
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_PRE_PING: bool = True
    # Disable connection pooling entirely. Required under pytest, where each
    # test may run in its own event loop and a pooled asyncpg connection
    # created in a previous loop cannot be reused.
    DB_USE_NULL_POOL: bool = False

    # --- CORS -----------------------------------------------------------
    # NoDecode: pydantic-settings would otherwise JSON-decode this field before
    # the validator below gets a chance to split the comma-separated form.
    CORS_ORIGINS: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173"]
    )

    # =====================================================================
    # FEATURE FLAGS
    # =====================================================================
    # Every on/off switch in the platform, in one place. Each is also
    # documented in its own section below, next to the values it governs.

    #: Apply brokerage and statutory charges. Off = frictionless simulation.
    CHARGES_ENABLED: bool = True
    #: Refuse orders while the instrument's market is closed. Off by default:
    #: this is a paper-trading lab. Crypto is unaffected -- it never closes.
    ENFORCE_MARKET_HOURS: bool = False
    #: Capture portfolio snapshots on a timer, for the equity curve.
    SNAPSHOT_ENABLED: bool = True
    #: Also snapshot inside each order's transaction.
    SNAPSHOT_ON_TRADE: bool = True
    #: Suppress a periodic snapshot identical to the previous one.
    SNAPSHOT_SKIP_UNCHANGED: bool = True
    #: Derive bid/ask from the spread model when the feed has no depth.
    #: Ticks label these "modelled" so they are never mistaken for real.
    STREAM_MODEL_BID_ASK: bool = True
    #: Keep polling an instrument that has an ACTIVE automatic order even when
    #: no browser is connected, so a stop-loss can fire overnight.
    STREAM_POLL_FOR_AUTOMATION: bool = True

    # --- Default instrument ------------------------------------------------
    # The platform trades any instrument in the supported universe -- the
    # catalogue is in app/market_data/catalogue.py -- against ONE virtual
    # wallet.
    #
    # TRADING_SYMBOL is the DEFAULT instrument: what a request that omits a
    # symbol resolves to, and what the UI opens on. It is NOT a restriction.
    TRADING_SYMBOL: str = "RELIANCE"
    TRADING_EXCHANGE: str = "NSE"

    # --- Market hours ------------------------------------------------------
    # Whether a closed market actually BLOCKS an order is ENFORCE_MARKET_HOURS,
    # in the feature-flags block above. The schedule below is always resolved
    # and reported regardless.
    #
    # Crypto never consults any of this: its calendar is open 24/7, so the
    # check passes at any hour, on any day, including NSE holidays.

    # NSE cash-market session, in NSE_TIMEZONE. Pre-open (09:00-09:15) is a
    # call auction and is NOT continuous trading, so it is reported as
    # PRE_OPEN rather than OPEN.
    NSE_TIMEZONE: str = "Asia/Kolkata"
    NSE_PRE_OPEN_TIME: str = "09:00"
    NSE_OPEN_TIME: str = "09:15"
    NSE_CLOSE_TIME: str = "15:30"

    # Full-day NSE trading holidays as ISO dates, comma separated.
    #
    # ONLY fixed-date national holidays are shipped as defaults. India's
    # exchange holiday list is published annually by NSE and most of it moves
    # year to year (Diwali, Holi, Eid, Muhurat trading and others follow lunar
    # calendars). Those CANNOT be derived and are deliberately not guessed at
    # here -- set this from the official NSE circular each year. See
    # ARCHITECTURE.md 20.4.
    NSE_HOLIDAYS: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: [
            "2026-01-26",  # Republic Day
            "2026-05-01",  # Maharashtra Day
            "2026-08-15",  # Independence Day
            "2026-10-02",  # Gandhi Jayanti
            "2026-12-25",  # Christmas
        ]
    )

    # --- Market data -----------------------------------------------------
    # Providers are chosen PER ASSET CLASS, because a feed that serves NSE
    # equities is not automatically a feed that serves crypto. See
    # app/market_data/router.py.
    #
    # MARKET_DATA_PROVIDER is the equity feed and remains the name every
    # existing deployment sets.
    MARKET_DATA_PROVIDER: str = "yahoo"
    # The crypto feed. Verified to serve BTC-INR/ETH-INR with 1m-1mo OHLCV.
    CRYPTO_MARKET_DATA_PROVIDER: str = "yahoo_crypto"
    MARKET_DATA_TIMEOUT_SECONDS: float = 15.0

    # Upstream endpoint for the bundled Yahoo-backed providers (both the
    # equity and the crypto one -- they share a transport). Point this at a
    # mirror or a recording proxy without touching any code.
    MARKET_DATA_BASE_URL: str = "https://query1.finance.yahoo.com/v8/finance/chart"
    # Yahoo rejects requests without a browser-like agent.
    MARKET_DATA_USER_AGENT: str = (
        "Mozilla/5.0 (compatible; VirtualTradingPlatform/0.1)"
    )

    # Quote currency for crypto pairs. The provider is asked for
    # <SYMBOL>-<CRYPTO_QUOTE_CURRENCY>, so INR keeps one currency across the
    # whole portfolio and no FX conversion is ever needed.
    CRYPTO_QUOTE_CURRENCY: str = "INR"

    # Credentials for providers that need them. SecretStr keeps the value out
    # of logs, tracebacks and repr output. NEVER hard-code a key here - set it
    # in .env, which is gitignored.
    #
    # NOTE: none of the bundled providers read these -- Yahoo's chart endpoint
    # is keyless. They exist as the ready-made seam for a provider that does
    # need credentials, so adding one is a config change rather than a schema
    # change. Read them in your provider's factory in
    # app/market_data/registry.py.
    MARKET_DATA_API_KEY: SecretStr | None = None
    MARKET_DATA_API_SECRET: SecretStr | None = None

    # --- Portfolio snapshots ----------------------------------------------
    # SNAPSHOT_ENABLED / _ON_TRADE / _SKIP_UNCHANGED are in the feature-flags
    # block above.
    SNAPSHOT_INTERVAL_SECONDS: float = 300.0

    # --- Real-time streaming ----------------------------------------------
    # STREAM_MODEL_BID_ASK and STREAM_POLL_FOR_AUTOMATION are in the
    # feature-flags block above.
    #
    # How often the backend asks the provider for a price. This is the real
    # meaning of "live" for a polled feed -- see ARCHITECTURE.md.
    STREAM_POLL_INTERVAL_SECONDS: float = 5.0
    STREAM_MAX_CONNECTIONS: int = 50
    # How often the automatic-order monitor re-reads which symbols are armed,
    # measured in evaluations. Guards against a trigger inserted outside this
    # process (psql, a second worker) never being noticed. Creating or
    # cancelling an order through the API invalidates the cache immediately.
    AUTOMATION_REVALIDATE_EVERY_EVALUATIONS: int = 20

    # --- Mock provider (MARKET_DATA_PROVIDER=mock) -------------------------
    # Simulated data for development. Never enable this in production.
    MOCK_BASE_PRICE: Decimal = Decimal("1400")
    MOCK_VOLATILITY_BPS: Decimal = Decimal("15")
    MOCK_SPREAD_BPS: Decimal = Decimal("4")
    MOCK_TICK_INTERVAL_SECONDS: float = 2.0
    MOCK_SEED: int | None = None

    # --- Execution realism -----------------------------------------------
    # Which charge schedule applies: INTRADAY or DELIVERY. Intraday is the
    # default because Indian cash-market shorts must be squared off same day.
    EXECUTION_SEGMENT: str = "INTRADAY"

    # Bid/ask spread, in basis points. This is the FULL spread; half is
    # applied either side of the reference (mid) price.
    SPREAD_BPS: Decimal = Decimal("2")

    # Slippage: NONE, FIXED_BPS or PERCENT. Always applied adversely.
    SLIPPAGE_MODEL: str = "FIXED_BPS"
    SLIPPAGE_BPS: Decimal = Decimal("2")
    SLIPPAGE_PERCENT: Decimal = Decimal("0")

    # --- Charges: equities (AssetClass.STOCK) -------------------------------
    # Governed by CHARGES_ENABLED in the feature-flags block above.
    # Applied by FeeCalculator in app/trading/fees.py.
    #
    # Rates are PERCENTAGES of turnover (0.03 means 0.03%).
    # These defaults reflect a typical NSE discount broker. Statutory rates
    # are revised periodically - verify against a current schedule.
    BROKERAGE_PERCENT: Decimal = Decimal("0.03")
    BROKERAGE_MAX_PER_ORDER: Decimal | None = Decimal("20")

    STT_INTRADAY_SELL_PERCENT: Decimal = Decimal("0.025")
    STT_DELIVERY_PERCENT: Decimal = Decimal("0.1")

    EXCHANGE_TXN_PERCENT: Decimal = Decimal("0.00297")
    SEBI_CHARGES_PERCENT: Decimal = Decimal("0.0001")

    STAMP_DUTY_INTRADAY_BUY_PERCENT: Decimal = Decimal("0.003")
    STAMP_DUTY_DELIVERY_BUY_PERCENT: Decimal = Decimal("0.015")

    GST_PERCENT: Decimal = Decimal("18")
    DP_CHARGES_PER_SELL: Decimal = Decimal("0")

    # --- Charges: crypto (AssetClass.CRYPTO) --------------------------------
    # SIMULATED. No crypto exchange has been integrated, so these are
    # deliberately CONFIGURABLE ASSUMPTIONS rather than any real venue's
    # published schedule. Change them to match whichever exchange you want to
    # model. Documented in ARCHITECTURE.md 20.7.
    #
    # NSE charges (STT, stamp duty, SEBI turnover fee, DP charges) are
    # statutory to the securities market and are NEVER applied to crypto.
    #
    # A flat taker fee on turnover, both sides. 0.10% is a common order of
    # magnitude for a retail spot taker; it is an assumption, not a quote.
    CRYPTO_FEE_PERCENT: Decimal = Decimal("0.10")
    CRYPTO_FEE_MAX_PER_ORDER: Decimal | None = None
    # GST on the exchange's service fee, mirroring the equity treatment.
    CRYPTO_GST_PERCENT: Decimal = Decimal("18")
    # TDS on the transfer of a Virtual Digital Asset, withheld on the SELL
    # side. Unlike the fee above this one is statutory (India, s.194S), which
    # is why it is modelled rather than folded into the fee. Set to 0 to
    # disable it entirely.
    CRYPTO_TDS_PERCENT: Decimal = Decimal("1")

    # --- Wallet ----------------------------------------------------------
    # Opening capital granted when the wallet is first initialised.
    # Decimal (never float) because this is money.
    WALLET_INITIAL_BALANCE: Decimal = Decimal("1000000.00")
    WALLET_CURRENCY: str = "INR"

    # =====================================================================
    # LIMITS
    # =====================================================================
    # Bounds the platform enforces on requests. Every validation path reads
    # these -- there are no duplicate literals in the schemas or endpoints.

    #: Largest quantity a single order may be for, in the instrument's own
    #: units. Applies to manual orders and automatic ones alike.
    #:
    #: NOTE: the database CHECK constraint carries its own ceiling
    #: (``DB_MAX_ORDER_QUANTITY`` in app/models/trading.py). Lowering this
    #: setting works immediately; RAISING it above that ceiling needs a
    #: migration, because the constraint is baked into the schema.
    MAX_ORDER_QUANTITY: int = 10_000_000

    #: Most candles any one market-data or backtest request may return.
    MAX_CANDLES_PER_REQUEST: int = 5_000
    #: Most rows a history listing (orders, trades, triggers) may return.
    MAX_HISTORY_PAGE_SIZE: int = 500
    #: Default page size when a listing request omits one.
    DEFAULT_HISTORY_PAGE_SIZE: int = 100
    #: Most portfolio snapshots one history request may return. Higher than a
    #: normal page because the equity curve is plotted from it.
    MAX_SNAPSHOT_PAGE_SIZE: int = 5_000

    # --- Indicators --------------------------------------------------------
    #: Most indicators one request may ask for. Each is a full pass over the
    #: series, so this bounds the work a single call can cause.
    MAX_INDICATORS_PER_REQUEST: int = 10
    #: Timezone that anchors intraday VWAP to a trading session. Separate from
    #: NSE_TIMEZONE on purpose: this is about where a *bar series* resets,
    #: which need not be the exchange whose calendar governs trading.
    VWAP_SESSION_TIMEZONE: str = "Asia/Kolkata"

    #: How far ahead a market calendar searches for the next open or close
    #: before giving up. Comfortably longer than any real exchange closure.
    CALENDAR_SEARCH_HORIZON_DAYS: int = 30

    @field_validator("NSE_HOLIDAYS", mode="before")
    @classmethod
    def _parse_holidays(cls, value: object) -> object:
        """Accept ``2026-01-26,2026-08-15`` from .env, a JSON array, or a list."""
        if not isinstance(value, str):
            return value
        text = value.strip()
        if not text:
            return []
        if text.startswith("["):
            return json.loads(text)
        return [entry.strip() for entry in text.split(",") if entry.strip()]

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def _parse_origins(cls, value: object) -> object:
        """Accept ``a,b,c`` from .env as well as a JSON array or a real list."""
        if not isinstance(value, str):
            return value
        text = value.strip()
        if text.startswith("["):
            return json.loads(text)
        return [origin.strip() for origin in text.split(",") if origin.strip()]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def DATABASE_URL(self) -> str:
        """Async URL used by the application (asyncpg driver)."""
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )


@lru_cache
def get_settings() -> Settings:
    """Cached accessor so settings are parsed exactly once per process."""
    return Settings()


settings = get_settings()
