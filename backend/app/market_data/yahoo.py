"""Yahoo Finance chart API.

Uses the public ``/v8/finance/chart`` endpoint, which serves both the latest
quote (in ``meta``) and OHLCV history (in ``indicators``) without credentials.

Two providers are built on it, because a feed that serves NSE equities is not
automatically a feed that serves crypto -- the symbol format, the trading
schedule and the limitations all differ:

    YahooChartProvider          shared HTTP + parsing (this module)
        |-- YahooFinanceProvider    NSE/BSE equities, "<SYMBOL>.NS"
        +-- YahooCryptoProvider     crypto pairs, "<SYMBOL>-INR"  (crypto.py)

Only the vendor symbol mapping and the declared capabilities differ, so the
parsing lives here once rather than being duplicated per asset class.

Measured limitations of the equity provider -- see ``capabilities`` for the
machine-readable form:

* **No bid/ask.** Depth lives on ``/v7/finance/quote``, which now returns
  HTTP 401 without a session crumb. ``Quote.bid`` and ``Quote.ask`` are
  therefore always ``None`` here.
* **No streaming.** There is no public push feed, so ``subscribe_live_data``
  raises rather than faking one by polling.
* **Unofficial.** This is not a documented or supported API. It can rate-limit
  or change shape without notice, which is exactly why it sits behind
  ``MarketDataProvider``.
* **Intraday retention.** 1m bars are retained for roughly 30 days only, and
  at most about 7 days can be fetched per request.
"""

from datetime import UTC, datetime
from decimal import Decimal

import httpx

from app.core.config import settings
from app.core.exceptions import (
    MarketDataUnavailableError,
    UnsupportedIntervalError,
)
from app.core.logging import get_logger
from app.market_data.base import MarketDataProvider
from app.schemas.market_data import Candle, Interval, ProviderCapabilities, Quote

logger = get_logger(__name__)

#: Vendor protocol details. These describe how to *speak to Yahoo*, not how
#: this platform is configured, so they live beside the client rather than in
#: settings -- changing one means changing the integration, not a deployment.
#: The endpoint itself IS configurable (``MARKET_DATA_BASE_URL``), so a mirror
#: or a recording proxy needs no code change.

#: Platform exchange code -> Yahoo symbol suffix.
_EXCHANGE_SUFFIX = {"NSE": ".NS", "BSE": ".BO"}

#: Platform interval -> Yahoo interval.
_INTERVAL = {
    Interval.ONE_MINUTE: "1m",
    Interval.FIVE_MINUTES: "5m",
    Interval.FIFTEEN_MINUTES: "15m",
    Interval.THIRTY_MINUTES: "30m",
    Interval.ONE_HOUR: "1h",
    Interval.ONE_DAY: "1d",
    Interval.ONE_WEEK: "1wk",
    Interval.ONE_MONTH: "1mo",
}

#: Default lookback per interval when the caller gives no explicit window.
_DEFAULT_RANGE = {
    Interval.ONE_MINUTE: "1d",
    Interval.FIVE_MINUTES: "5d",
    Interval.FIFTEEN_MINUTES: "5d",
    Interval.THIRTY_MINUTES: "1mo",
    Interval.ONE_HOUR: "1mo",
    Interval.ONE_DAY: "1y",
    Interval.ONE_WEEK: "5y",
    Interval.ONE_MONTH: "10y",
}

_CENT = Decimal("0.01")


def _to_money(value: float | int | None) -> Decimal | None:
    """Convert a JSON float to an exact 2dp Decimal.

    Goes via ``str`` so the shortest round-trippable representation is used:
    ``Decimal(1304.5999755859375)`` would otherwise carry the full binary
    expansion into the quantise.
    """
    if value is None:
        return None
    return Decimal(str(value)).quantize(_CENT)


class YahooChartProvider(MarketDataProvider):
    """Shared plumbing for every provider backed by Yahoo's chart endpoint.

    Subclasses supply ``name``, ``capabilities`` and ``_vendor_symbol``. They
    inherit the HTTP client, error translation, quote assembly and candle
    parsing, so an asset class is added by describing how its symbols are
    spelled -- not by reimplementing the feed.
    """

    name = "yahoo-chart"
    #: Fallback currency when the payload omits one.
    default_currency = "INR"

    def __init__(
        self,
        timeout_seconds: float | None = None,
        base_url: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        # Every argument falls back to settings, so a caller that passes
        # nothing gets exactly the configured behaviour.
        self._client = httpx.AsyncClient(
            base_url=base_url or settings.MARKET_DATA_BASE_URL,
            headers={"User-Agent": user_agent or settings.MARKET_DATA_USER_AGENT},
            timeout=(
                timeout_seconds
                if timeout_seconds is not None
                else settings.MARKET_DATA_TIMEOUT_SECONDS
            ),
        )

    # -- vendor mapping (subclass responsibility) -------------------------

    def _vendor_symbol(self, symbol: str, exchange: str) -> str:
        raise NotImplementedError

    # -- transport --------------------------------------------------------

    async def _fetch_chart(self, vendor_symbol: str, params: dict) -> dict:
        """GET the chart endpoint and unwrap the single result object."""
        try:
            response = await self._client.get(f"/{vendor_symbol}", params=params)
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPStatusError as exc:
            raise MarketDataUnavailableError(
                f"Yahoo Finance returned HTTP {exc.response.status_code} "
                f"for {vendor_symbol}."
            ) from exc
        except httpx.HTTPError as exc:
            raise MarketDataUnavailableError(
                f"Could not reach Yahoo Finance: {exc}"
            ) from exc
        except ValueError as exc:
            raise MarketDataUnavailableError(
                "Yahoo Finance returned a malformed response."
            ) from exc

        chart = payload.get("chart") or {}
        if chart.get("error"):
            raise MarketDataUnavailableError(
                f"Yahoo Finance error for {vendor_symbol}: {chart.get('error')}"
            )

        results = chart.get("result") or []
        if not results:
            raise MarketDataUnavailableError(
                f"Yahoo Finance returned no data for {vendor_symbol}."
            )
        return results[0]

    # -- quotes ----------------------------------------------------------

    async def get_current_quote(self, symbol: str, exchange: str) -> Quote:
        vendor_symbol = self._vendor_symbol(symbol, exchange)
        result = await self._fetch_chart(
            vendor_symbol, {"interval": "1d", "range": "1d"}
        )
        meta = result.get("meta") or {}

        last_price = _to_money(meta.get("regularMarketPrice"))
        if last_price is None:
            raise MarketDataUnavailableError(
                f"Yahoo Finance returned no price for {vendor_symbol}."
            )
        if last_price <= 0:
            # An asset priced below one paisa rounds to zero here. The ledger
            # is denominated in paise, so it genuinely cannot be traded rather
            # than merely being awkward -- say so instead of returning 0.00.
            raise MarketDataUnavailableError(
                f"{vendor_symbol} is priced below the smallest representable "
                f"amount (0.01 {meta.get('currency') or self.default_currency}); "
                "this platform cannot price it."
            )

        market_time = meta.get("regularMarketTime")
        timestamp = (
            datetime.fromtimestamp(market_time, tz=UTC)
            if market_time
            else datetime.now(tz=UTC)
        )

        # Yahoo reports the prior close under different keys depending on the
        # requested interval: "previousClose" for intraday, "chartPreviousClose"
        # for daily. Accept either.
        previous_close = meta.get("previousClose")
        if previous_close is None:
            previous_close = meta.get("chartPreviousClose")

        return Quote(
            symbol=symbol.upper(),
            exchange=exchange.upper(),
            last_price=last_price,
            # Always None: this feed carries no depth. See the class docstring.
            bid=None,
            ask=None,
            volume=int(meta.get("regularMarketVolume") or 0),
            timestamp=timestamp,
            previous_close=_to_money(previous_close),
            # There is no day-open field in meta; it comes from the session bar
            # returned alongside it.
            day_open=self._session_open(result),
            day_high=_to_money(meta.get("regularMarketDayHigh")),
            day_low=_to_money(meta.get("regularMarketDayLow")),
            currency=meta.get("currency") or self.default_currency,
            provider=self.name,
            is_delayed=False,
        )

    @staticmethod
    def _session_open(result: dict) -> Decimal | None:
        """First open price in the accompanying bar series, if present."""
        blocks = (result.get("indicators") or {}).get("quote") or []
        opens = (blocks[0].get("open") if blocks else None) or []
        for value in opens:
            if value is not None:
                return _to_money(value)
        return None

    # -- history ---------------------------------------------------------

    async def get_historical_candles(
        self,
        symbol: str,
        exchange: str,
        interval: Interval,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int | None = None,
    ) -> list[Candle]:
        vendor_interval = _INTERVAL.get(interval)
        if vendor_interval is None:
            raise UnsupportedIntervalError(
                f"Yahoo Finance does not serve the '{interval}' interval."
            )

        params: dict[str, str | int] = {"interval": vendor_interval}
        if start is not None:
            params["period1"] = int(start.timestamp())
            params["period2"] = int((end or datetime.now(tz=UTC)).timestamp())
        else:
            params["range"] = _DEFAULT_RANGE[interval]

        vendor_symbol = self._vendor_symbol(symbol, exchange)
        result = await self._fetch_chart(vendor_symbol, params)

        candles = self._parse_candles(result)
        if limit is not None and limit < len(candles):
            # Keep the most recent bars.
            candles = candles[-limit:]
        return candles

    @staticmethod
    def _parse_candles(result: dict) -> list[Candle]:
        """Zip Yahoo's column-oriented arrays into candles.

        Gaps (halts, holidays) come back as nulls in the OHLC arrays. Those
        rows are dropped rather than forward-filled, so a caller never sees a
        bar the exchange did not print. A continuous market simply has no such
        gaps, which is why the same parser serves both asset classes.
        """
        timestamps = result.get("timestamp") or []
        quote_blocks = (result.get("indicators") or {}).get("quote") or [{}]
        block = quote_blocks[0] if quote_blocks else {}

        opens = block.get("open") or []
        highs = block.get("high") or []
        lows = block.get("low") or []
        closes = block.get("close") or []
        volumes = block.get("volume") or []

        candles: list[Candle] = []
        for index, epoch in enumerate(timestamps):
            try:
                raw_open = opens[index]
                raw_high = highs[index]
                raw_low = lows[index]
                raw_close = closes[index]
            except IndexError:
                break

            if None in (raw_open, raw_high, raw_low, raw_close):
                continue

            raw_volume = volumes[index] if index < len(volumes) else None

            candles.append(
                Candle(
                    timestamp=datetime.fromtimestamp(epoch, tz=UTC),
                    open=_to_money(raw_open),
                    high=_to_money(raw_high),
                    low=_to_money(raw_low),
                    close=_to_money(raw_close),
                    volume=int(raw_volume or 0),
                )
            )
        return candles

    # subscribe_live_data() is deliberately NOT overridden: the base class
    # raises LiveDataNotSupportedError, which is the truthful behaviour here.

    async def aclose(self) -> None:
        await self._client.aclose()


class YahooFinanceProvider(YahooChartProvider):
    """Keyless market data for NSE and BSE equities."""

    name = "yahoo"
    default_currency = "INR"

    def _vendor_symbol(self, symbol: str, exchange: str) -> str:
        suffix = _EXCHANGE_SUFFIX.get(exchange.upper(), "")
        return f"{symbol.upper()}{suffix}"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            name=self.name,
            supports_quotes=True,
            supports_historical=True,
            supports_bid_ask=False,
            supports_live_stream=False,
            is_delayed=False,
            quote_delay_minutes=0,
            requires_credentials=False,
            supported_intervals=list(_INTERVAL.keys()),
            limitations=[
                "No bid/ask: the endpoint carrying order-book depth requires an "
                "authenticated session, so bid and ask are always null.",
                "No streaming: there is no public WebSocket feed, so "
                "subscribe_live_data() raises LiveDataNotSupportedError.",
                "Unofficial API: undocumented and unsupported by Yahoo; it may "
                "rate-limit or change shape without notice.",
                "1-minute history is retained for roughly 30 days only.",
                "Not licensed for commercial redistribution.",
            ],
        )
