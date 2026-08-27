"""Application configuration.

Single source of truth for every runtime setting. Nothing else in the codebase
reads ``os.environ`` directly.
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

    # --- Domain constants ------------------------------------------------
    # The platform trades any instrument in the supported universe (see
    # app/market_data/instruments.py) against ONE virtual wallet.
    #
    # TRADING_SYMBOL is the DEFAULT instrument -- what a request that omits a
    # symbol resolves to, and what the UI opens on. It is not a restriction.
    TRADING_SYMBOL: str = "RELIANCE"
    TRADING_EXCHANGE: str = "NSE"

    # --- Market hours ------------------------------------------------------
    # Whether the trading engine REFUSES an order while the instrument's
    # market is closed. Off by default: this is a paper-trading lab and being
    # able to place a practice order at 9pm is the point. Turn it on to
    # simulate a real broker.
    #
    # Crypto is unaffected either way -- its calendar is open 24/7, so the
    # check passes at any hour, on any day, including NSE holidays.
    ENFORCE_MARKET_HOURS: bool = False

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

    # Quote currency for crypto pairs. The provider is asked for
    # <SYMBOL>-<CRYPTO_QUOTE_CURRENCY>, so INR keeps one currency across the
    # whole portfolio and no FX conversion is ever needed.
    CRYPTO_QUOTE_CURRENCY: str = "INR"

    # Credentials for providers that need them. SecretStr keeps the value out
    # of logs, tracebacks and repr output. NEVER hard-code a key here - set it
    # in .env, which is gitignored.
    MARKET_DATA_API_KEY: SecretStr | None = None
    MARKET_DATA_API_SECRET: SecretStr | None = None

    # --- Portfolio snapshots ----------------------------------------------
    SNAPSHOT_ENABLED: bool = True
    SNAPSHOT_INTERVAL_SECONDS: float = 300.0
    # Also snapshot inside each order's transaction, so the equity curve has
    # an exact point at every moment the account actually changed.
    SNAPSHOT_ON_TRADE: bool = True
    # Suppress a periodic row identical to the previous one, so an idle
    # account does not fill the table overnight.
    SNAPSHOT_SKIP_UNCHANGED: bool = True

    # --- Real-time streaming ----------------------------------------------
    STREAM_POLL_INTERVAL_SECONDS: float = 5.0
    STREAM_MAX_CONNECTIONS: int = 50
    # Keep polling an instrument that has an ACTIVE automatic order even when
    # no browser is connected. Without this a stop-loss only fires while a tab
    # is open, which defeats the purpose of a 24/7 market: a crypto stop set on
    # Friday would sit inert all weekend. With nothing armed and nobody
    # watching, nothing is polled either way.
    STREAM_POLL_FOR_AUTOMATION: bool = True
    # Derive bid/ask from the spread model when the provider has no depth.
    # Ticks label these as "modelled" so they are never mistaken for real.
    STREAM_MODEL_BID_ASK: bool = True

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

    # --- Charges ----------------------------------------------------------
    # Master switch; turn off for frictionless simulation.
    CHARGES_ENABLED: bool = True

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

    # --- Crypto charges ----------------------------------------------------
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
