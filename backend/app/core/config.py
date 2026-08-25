"""Application configuration.

Single source of truth for every runtime setting. Nothing else in the codebase
reads ``os.environ`` directly.
"""

import json
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, computed_field, field_validator
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

    # --- CORS -----------------------------------------------------------
    # NoDecode: pydantic-settings would otherwise JSON-decode this field before
    # the validator below gets a chance to split the comma-separated form.
    CORS_ORIGINS: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173"]
    )

    # --- Domain constants ------------------------------------------------
    # The platform is deliberately single-instrument and single-wallet.
    TRADING_SYMBOL: str = "RELIANCE"
    TRADING_EXCHANGE: str = "NSE"

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
