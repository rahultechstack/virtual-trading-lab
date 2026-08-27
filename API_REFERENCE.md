# API & Developer Reference — RELIANCE Virtual Trading Platform

Generated from the actual repository at commit `1f0a749`, branch `main`.
No code was modified. Anything absent is marked **Not implemented**.

Companion document: `ARCHITECTURE.md` (system design, data flow, risks).

**Base URL:** `http://localhost:8000` · **API prefix:** `/api/v1`
(`settings.API_V1_PREFIX`) · **Auth:** none — see §1.0.

| § | Section |
|---|---------|
| 1 | [API Reference](#1-api-reference) |
| 2 | [WebSocket API](#2-websocket-api) |
| 3 | [Data Models (Pydantic)](#3-data-models-pydantic) |
| 4 | [Database Models (SQLAlchemy)](#4-database-models-sqlalchemy) |
| 5 | [Trading Engine API](#5-trading-engine-api) |
| 6 | [Frontend API Client](#6-frontend-api-client) |
| 7 | [Frontend WebSocket Client](#7-frontend-websocket-client) |
| 8 | [Environment Variables](#8-environment-variables) |
| 9 | [Common Development Tasks](#9-common-development-tasks) |
| 10 | [Modification Cookbook](#10-modification-cookbook) |
| 11 | [AI Coding Instructions](#11-ai-coding-instructions) |
| 12 | [Source of Truth](#12-source-of-truth) |

---

## 1. API Reference

### 1.0 Authentication — none

**There is no login, no user model, no session, no token, no API key and no
`Authorization` handling anywhere in this repository.** Verified by grep over
`backend/app` and `frontend/src`. Every endpoint below is public to anyone who
can reach the port. The only protection is `CORSMiddleware` (browser origins
only — `curl` and Postman are unaffected). There is **no rate limiting**.

Read **"Auth: none required"** on every endpoint in this section.

### 1.1 Endpoint index

| # | Method | Path | File |
|---|--------|------|------|
| 1 | GET | `/` | `app/main.py` |
| 2 | GET | `/docs`, `/redoc`, `/openapi.json` | FastAPI built-in |
| 3 | GET | `/api/v1/health/ping` | `app/api/v1/endpoints/health.py` |
| 4 | GET | `/api/v1/health` | `app/api/v1/endpoints/health.py` |
| 5 | GET | `/api/v1/wallet` | `app/api/v1/endpoints/wallet.py` |
| 6 | POST | `/api/v1/wallet/initialize` | `app/api/v1/endpoints/wallet.py` |
| 7 | POST | `/api/v1/wallet/reset` | `app/api/v1/endpoints/wallet.py` |
| 8 | GET | `/api/v1/market-data/provider` | `app/api/v1/endpoints/market_data.py` |
| 9 | GET | `/api/v1/market-data/quote` | `app/api/v1/endpoints/market_data.py` |
| 10 | GET | `/api/v1/market-data/candles` | `app/api/v1/endpoints/market_data.py` |
| 11 | GET | `/api/v1/indicators/catalogue` | `app/api/v1/endpoints/indicators.py` |
| 12 | GET | `/api/v1/indicators` | `app/api/v1/endpoints/indicators.py` |
| 13 | POST | `/api/v1/trading/orders` | `app/api/v1/endpoints/trading.py` |
| 14 | GET | `/api/v1/trading/orders` | `app/api/v1/endpoints/trading.py` |
| 15 | GET | `/api/v1/trading/trades` | `app/api/v1/endpoints/trading.py` |
| 16 | GET | `/api/v1/trading/position` | `app/api/v1/endpoints/trading.py` |
| 17 | GET | `/api/v1/trading/portfolio` | `app/api/v1/endpoints/trading.py` |
| 18 | GET | `/api/v1/trading/execution-cost` | `app/api/v1/endpoints/trading.py` |
| 19 | GET | `/api/v1/stream/status` | `app/api/v1/endpoints/stream.py` |
| 20 | **WS** | `/api/v1/stream/prices` | `app/api/v1/endpoints/stream.py` |
| 21 | GET | `/api/v1/portfolio/snapshots` | `app/api/v1/endpoints/portfolio.py` |
| 22 | POST | `/api/v1/portfolio/snapshots` | `app/api/v1/endpoints/portfolio.py` |
| 23 | GET | `/api/v1/portfolio/performance` | `app/api/v1/endpoints/portfolio.py` |
| 24 | GET | `/api/v1/strategies` | `app/api/v1/endpoints/backtest.py` |
| 25 | POST | `/api/v1/strategies/backtest` | `app/api/v1/endpoints/backtest.py` |

> The backtest module is mounted at prefix **`/strategies`**, not `/backtest`.

**Error envelope.** Every `DomainError` becomes
`{"error": {"code": "...", "message": "..."}}` via the handler in
`app/main.py:domain_error_handler`. Pydantic/Query validation failures are
**not** overridden and use FastAPI's default `{"detail": [...]}` with **422**.

---

### 1.2 `GET /`

* **File:** `app/main.py` (inside `create_app`), function `root`
* **Purpose:** service banner listing the main sub-paths
* **Params / body:** none · **Response:** `dict[str, str]` (no schema class)
* **Status:** 200 · **Errors:** none · **Services:** none · **Tables:** none

```bash
curl http://localhost:8000/
```
```json
{"service":"Virtual Trading Platform","version":"0.1.0","docs":"/docs",
 "health":"/api/v1/health","wallet":"/api/v1/wallet",
 "market_data":"/api/v1/market-data","indicators":"/api/v1/indicators",
 "strategies":"/api/v1/strategies","trading":"/api/v1/trading",
 "stream":"/api/v1/stream/prices","portfolio_history":"/api/v1/portfolio/snapshots"}
```

---

### 1.3 `GET /api/v1/health/ping`

* **File:** `app/api/v1/endpoints/health.py`, function `ping`
* **Purpose:** liveness probe; touches no dependency
* **Params / body:** none · **Response schema:** `PingResponse`
* **Status:** 200 · **Errors:** none
* **Services:** `health_service.ping()` · **Tables:** none

```bash
curl http://localhost:8000/api/v1/health/ping
```
```json
{"message":"pong","timestamp":"2026-08-25T09:14:03.117441+00:00"}
```

---

### 1.4 `GET /api/v1/health`

* **File:** `app/api/v1/endpoints/health.py`, function `health`
* **Purpose:** readiness probe including a live `SELECT 1`
* **Params / body:** none · **Response schema:** `HealthResponse`
* **Status:** **always 200** — inspect `status` / `database.status` in the body
* **Errors:** none. `HealthService.check_database` catches every exception and
  returns `status:"error"` with `detail:"<Type>: <msg>"`.
* **Services:** `health_service.full_health(session)` · **Tables:** none (raw `SELECT 1`)
* **DI:** `DbSession`

```bash
curl http://localhost:8000/api/v1/health
```
```json
{"status":"ok","app_name":"Virtual Trading Platform","version":"0.1.0",
 "environment":"development","timestamp":"2026-08-25T09:14:03.117441+00:00",
 "database":{"status":"ok","detail":"PostgreSQL connection established.","latency_ms":1.83}}
```

---

### 1.5 `GET /api/v1/wallet`

* **File:** `app/api/v1/endpoints/wallet.py`, function `get_wallet`
* **Purpose:** return the single virtual account
* **Params / body:** none · **Response schema:** `WalletResponse`
* **Status:** 200 · **Errors:** `404 wallet_not_found`
* **Services:** `WalletService.get_wallet()` → `WalletRepository.get()`
* **Tables:** `wallet` (SELECT)

```bash
curl http://localhost:8000/api/v1/wallet
```
```json
{"id":1,"currency":"INR","initial_balance":"1000000.00","cash_balance":"859958.00",
 "created_at":"2026-08-25T09:00:00+00:00","updated_at":"2026-08-25T09:12:41+00:00"}
```
404 body:
```json
{"error":{"code":"wallet_not_found",
 "message":"Wallet has not been initialised. POST /wallet/initialize first."}}
```

---

### 1.6 `POST /api/v1/wallet/initialize`

* **File:** `app/api/v1/endpoints/wallet.py`, function `initialize_wallet`
* **Purpose:** create the wallet if absent. **Idempotent** — a repeat call never
  overwrites a balance.
* **Request body:** `WalletInitializeRequest | None` (the whole body is optional)

| Field | Type | Req | Validation |
|-------|------|-----|-----------|
| `initial_balance` | `Decimal \| None` | no | `gt=0`, `max_digits=18`, `decimal_places=2`. Omitted → `settings.WALLET_INITIAL_BALANCE` |

* **Response schema:** `WalletResponse`
* **Status:** **201** when created, **200** when it already existed (the handler
  mutates `response.status_code`)
* **Errors:** `422` on a non-positive or over-precise amount
* **Services:** `WalletService.initialize_wallet()` → `WalletRepository.get()` /
  `.create()`. Catches `IntegrityError` on a concurrent double-init and adopts
  the winner's row (`created=False`).
* **Tables:** `wallet` (SELECT, INSERT) — commits

```bash
curl -X POST http://localhost:8000/api/v1/wallet/initialize \
     -H 'Content-Type: application/json' -d '{"initial_balance":"500000.00"}'
```

---

### 1.7 `POST /api/v1/wallet/reset`

* **File:** `app/api/v1/endpoints/wallet.py`, function `reset_wallet`
* **Purpose:** restore `cash_balance` to `initial_balance`
* **Request body:** `WalletResetRequest | None` — same single optional
  `initial_balance` field. Supplied → re-opens the account at the new amount.
* **Response schema:** `WalletResponse` · **Status:** 200
* **Errors:** `404 wallet_not_found`, `422`
* **Services:** `WalletService.reset_wallet()` → `WalletRepository.get_for_update()`
  (`SELECT ... FOR UPDATE`) — commits
* **Tables:** `wallet` (SELECT FOR UPDATE, UPDATE)

> **This resets cash only.** `positions`, `orders`, `trades` and
> `portfolio_snapshots` are untouched. There is no "full reset" endpoint;
> `SnapshotService.purge()` exists but is **not wired to any route**.

---

### 1.8 `GET /api/v1/market-data/provider`

* **File:** `app/api/v1/endpoints/market_data.py`, function `get_provider_capabilities`
* **Purpose:** report what the configured feed actually supports
* **Params / body:** none · **Response schema:** `ProviderCapabilities`
* **Status:** 200 · **Errors:** none
* **Services:** `RelianceMarketDataService.capabilities` → `provider.capabilities`
* **Tables:** none · **DI:** `ServiceDep` → `Depends(get_provider)`

```json
{"name":"yahoo","supports_quotes":true,"supports_historical":true,
 "supports_bid_ask":false,"supports_live_stream":false,"is_delayed":false,
 "quote_delay_minutes":0,"requires_credentials":false,"is_mock":false,
 "supported_intervals":["1m","5m","15m","30m","1h","1d","1wk","1mo"],
 "limitations":["No bid/ask: ...","No streaming: ...","Unofficial API: ...",
                "1-minute history is retained for roughly 30 days only.",
                "Not licensed for commercial redistribution."]}
```

---

### 1.9 `GET /api/v1/market-data/quote`

* **File:** `app/api/v1/endpoints/market_data.py`, function `get_quote`
* **Purpose:** latest traded price for NSE:RELIANCE

| Query | Type | Req | Validation |
|-------|------|-----|-----------|
| `symbol` | `str \| None` | no | must equal `RELIANCE` (case-insensitive) if supplied |

* **Response schema:** `Quote` · **Status:** 200
* **Errors:** `400 unsupported_symbol`, `503 market_data_unavailable`
* **Services:** `RelianceMarketDataService.get_current_quote()` →
  `YahooFinanceProvider.get_current_quote()`
* **Tables:** none

```json
{"symbol":"RELIANCE","exchange":"NSE","last_price":"1402.35","bid":null,"ask":null,
 "volume":4821330,"timestamp":"2026-08-25T09:14:00+00:00","previous_close":"1395.10",
 "day_open":"1396.00","day_high":"1408.75","day_low":"1391.20","currency":"INR",
 "provider":"yahoo","is_delayed":false,"is_mock":false}
```

> `bid`/`ask` are **always `null`** on the Yahoo provider — check
> `GET /market-data/provider` → `supports_bid_ask`.

---

### 1.10 `GET /api/v1/market-data/candles`

* **File:** `app/api/v1/endpoints/market_data.py`, function `get_candles`
* **Purpose:** OHLCV history, **oldest candle first**

| Query | Type | Default | Validation |
|-------|------|---------|-----------|
| `interval` | `Interval` | `1d` | enum: `1m,5m,15m,30m,1h,1d,1wk,1mo` |
| `start` | `datetime \| None` | `None` | ISO 8601 |
| `end` | `datetime \| None` | `None` | ISO 8601; defaults to now when `start` given |
| `limit` | `int \| None` | `None` | `ge=1, le=5000`; keeps the **most recent** N |
| `symbol` | `str \| None` | `None` | must be `RELIANCE` |

* **Response schema:** `CandleSeries` · **Status:** 200
* **Errors:** `400 unsupported_symbol`, `400 unsupported_interval`, `422`, `503`
* **Validation chain:** `_require_supported_symbol` → `_require_supported_interval`
  → `effective_limit = min(limit or MAX_CANDLES, MAX_CANDLES)` where `MAX_CANDLES=5000`
* **Services:** `RelianceMarketDataService.get_historical_candles()` →
  `YahooFinanceProvider.get_historical_candles()` / `_parse_candles()`
* **Tables:** none

```bash
curl "http://localhost:8000/api/v1/market-data/candles?interval=5m&limit=2"
```
```json
{"symbol":"RELIANCE","exchange":"NSE","interval":"5m","provider":"yahoo","count":2,
 "candles":[{"timestamp":"2026-08-25T09:00:00+00:00","open":"1398.00","high":"1401.20",
             "low":"1397.55","close":"1400.10","volume":51230},
            {"timestamp":"2026-08-25T09:05:00+00:00","open":"1400.10","high":"1403.40",
             "low":"1399.80","close":"1402.35","volume":47110}]}
```

> Bars the exchange never printed (nulls in the Yahoo arrays) are **dropped, not
> forward-filled**.

---

### 1.11 `GET /api/v1/indicators/catalogue`

* **File:** `app/api/v1/endpoints/indicators.py`, function `catalogue`
* **Purpose:** available indicators with defaults and bounds
* **Params / body:** none · **Response schema:** `list[IndicatorCatalogueEntry]`
* **Status:** 200 · **Errors:** none
* **Services:** `indicator_service.catalogue()` reading `CATALOGUE`
* **Tables:** none

---

### 1.12 `GET /api/v1/indicators`

* **File:** `app/api/v1/endpoints/indicators.py`, function `compute_indicators`
* **Purpose:** compute studies over the same candles the chart draws

| Query | Type | Default | Validation |
|-------|------|---------|-----------|
| `indicators` | `str` | **required** | comma-separated specs |
| `interval` | `Interval` | `1d` | enum |
| `limit` | `int` | `250` | `ge=2, le=5000` |
| `start` / `end` | `datetime \| None` | `None` | ISO 8601 |

**Spec grammar** (`app/indicators/definitions.py:parse_spec`):
`sma:20`, `ema:21`, `rsi:14`, `macd:12:26:9`, `bbands:20:2`, `vwap[:period]`.
Omitted parameters use the catalogue defaults.

**Validation rules:**

| Rule | Raised by | Error |
|------|-----------|-------|
| unknown indicator name | `parse_spec` | `400 invalid_indicator` |
| more parameters than the definition declares | `parse_spec` | `400 invalid_indicator` |
| non-numeric parameter | `_coerce` | `400 invalid_indicator` |
| parameter outside `[minimum, maximum]` | `_coerce` | `400 invalid_indicator` |
| MACD `fast >= slow` | `_validate_relationships` | `400 invalid_indicator` |
| more than `MAX_INDICATORS = 10` specs | `parse_specs` | `400 invalid_indicator` |
| duplicate spec | `parse_specs` | silently de-duplicated by `IndicatorSpec.key` |

* **Response schema:** `IndicatorSetResponse`
* **Status:** 200 · **Errors:** `400 invalid_indicator`, `422`, `503`
* **Services:** `parse_specs` → `RelianceMarketDataService.get_historical_candles`
  → `indicator_service.calculate` → `candles_to_frame` → `CALCULATORS[type]` (TA-Lib)
* **Tables:** none

```bash
curl "http://localhost:8000/api/v1/indicators?indicators=sma:20,rsi:14&interval=5m&limit=240"
```
```json
{"symbol":"RELIANCE","exchange":"NSE","interval":"5m","provider":"yahoo",
 "candle_count":240,
 "indicators":[
   {"key":"sma_20","type":"sma","label":"SMA(20)","pane":"price","params":{"period":20},
    "warmup":19,"insufficient_data":false,"scale_min":null,"scale_max":null,
    "series":[{"key":"sma_20","label":"SMA(20)","style":"line",
               "points":[{"timestamp":"2026-08-25T08:35:00+00:00","value":"1397.8420"}]}]},
   {"key":"rsi_14","type":"rsi","label":"RSI(14)","pane":"separate","params":{"period":14},
    "warmup":14,"insufficient_data":false,"scale_min":"0","scale_max":"100",
    "series":[{"key":"rsi_14","label":"RSI(14)","style":"line","points":[...]}]}]}
```

> Warm-up bars are **omitted entirely**, not sent as nulls. An indicator whose
> warm-up exceeds the window is still returned with `insufficient_data: true`
> and an empty `series`.

---

### 1.13 `POST /api/v1/trading/orders` — place an order

* **File:** `app/api/v1/endpoints/trading.py`, function `place_order`
* **Purpose:** execute an order atomically against the virtual account
* **Request schema:** `PlaceOrderRequest`

| Field | Type | Req | Validation |
|-------|------|-----|-----------|
| `side` | `OrderSide` | yes | `BUY` \| `SELL` \| `SHORT_SELL` \| `BUY_TO_COVER` |
| `quantity` | `int` | yes | `gt=0`, `le=10_000_000` |
| `reference_price` | `Decimal` | yes | `gt=0`, `max_digits=18`, `decimal_places=2` — a **mid** price |
| `requested_price` | `Decimal \| None` | no | `gt=0`; audit only, does not affect the fill |
| `symbol` | `str \| None` | no | must be `RELIANCE` |

* **Response schema:** `OrderResultResponse`
* **Status:** **201** on fill

| Status | Code | Cause |
|--------|------|-------|
| 400 | `invalid_order` | `quantity <= 0`, `quantity > MAX_ORDER_QUANTITY`, `reference_price <= 0` |
| 400 | `invalid_position_operation` | `SELL` with no long / exceeding it; `BUY_TO_COVER` with no short / exceeding it |
| 400 | `insufficient_funds` | wallet cannot cover notional **plus charges** |
| 400 | `unsupported_symbol` | `symbol` other than `RELIANCE` |
| 404 | `wallet_not_found` | wallet not initialised |
| 422 | — | Pydantic: bad enum, non-positive quantity/price, too many decimals |

* **Services:** `TradingEngine.place_order` → `WalletRepository.get_for_update`,
  `PositionManager.get_or_create_for_update`, `OrderManager.create`,
  `ExecutionEngine.execute` (→ `SpreadModel`, `SlippageModel`, `FeeCalculator`),
  `PortfolioManager.assert_affordable`, `apply_fill`, `PositionManager.apply`,
  `PortfolioManager.apply_cash`, `ExecutionEngine.record_trade`,
  `OrderManager.mark_filled`, `SnapshotService.capture(commit=False)`
* **Tables affected (one transaction):** `orders` INSERT+UPDATE ·
  `trades` INSERT · `positions` SELECT FOR UPDATE + INSERT/UPDATE ·
  `wallet` SELECT FOR UPDATE + UPDATE · `portfolio_snapshots` INSERT
  (when `SNAPSHOT_ON_TRADE=true`)
* **Rejection path:** the order row **is persisted** as `REJECTED` with
  `rejection_reason` and committed before the error is raised. Errors raised
  *before* `OrderManager.create` (`invalid_order`, `unsupported_symbol`,
  `wallet_not_found`) leave **no row**.

```bash
curl -X POST http://localhost:8000/api/v1/trading/orders \
  -H 'Content-Type: application/json' \
  -d '{"side":"BUY","quantity":100,"reference_price":"1400.00"}'
```
```json
{"order":{"id":1,"symbol":"RELIANCE","exchange":"NSE","side":"BUY","order_type":"MARKET",
          "quantity":100,"requested_price":null,"execution_price":"1400.42",
          "status":"FILLED","rejection_reason":null,
          "created_at":"2026-08-25T09:12:41+00:00","filled_at":"2026-08-25T09:12:41+00:00"},
 "trade":{"id":1,"order_id":1,"symbol":"RELIANCE","exchange":"NSE","side":"BUY",
          "quantity":100,"reference_price":"1400.00","bid_price":"1399.86",
          "ask_price":"1400.14","execution_price":"1400.42","spread_cost":"14.00",
          "slippage_cost":"28.00","brokerage":"20.00","stt":"0.00",
          "exchange_charges":"4.16","sebi_charges":"0.14","stamp_duty":"4.00",
          "gst":"4.37","dp_charges":"0.00","total_charges":"32.67",
          "gross_pnl":"0.00","net_pnl":"-32.67","closed_quantity":0,
          "created_at":"2026-08-25T09:12:41+00:00"},
 "position":{"symbol":"RELIANCE","exchange":"NSE","quantity":100,
             "average_price":"1400.4200","realized_pnl":"0.00",
             "total_charges":"32.67","net_realized_pnl":"-32.67",
             "updated_at":"2026-08-25T09:12:41+00:00"},
 "gross_pnl":"0.00","total_charges":"32.67","net_pnl":"-32.67","cash_delta":"-140074.67"}
```
Rejection example:
```json
{"error":{"code":"invalid_position_operation",
 "message":"Cannot SELL 150; the long position is only 100. Use SHORT_SELL to sell beyond it."}}
```

---

### 1.14 `GET /api/v1/trading/orders`

* **File:** `app/api/v1/endpoints/trading.py`, function `list_orders`
* **Purpose:** order history, **newest first, rejected orders included**

| Query | Type | Default | Validation |
|-------|------|---------|-----------|
| `limit` | `int` | `100` | `ge=1, le=500` |
| `offset` | `int` | `0` | `ge=0` |
| `status` | `OrderStatus \| None` | `None` | **query alias** for the Python parameter `order_status`; enum `PENDING/FILLED/REJECTED/CANCELLED` |

* **Response schema:** `list[OrderResponse]` · **Status:** 200 · **Errors:** `422`
* **Services:** `TradingEngine.list_orders` → `OrderManager.list_recent`
  (`ORDER BY orders.id DESC`)
* **Tables:** `orders` SELECT (plus a `selectin` load of `trades` via the
  `Order.trades` relationship, even though `OrderResponse` does not expose it)

---

### 1.15 `GET /api/v1/trading/trades`

* **File:** `app/api/v1/endpoints/trading.py`, function `list_trades`
* **Query:** `limit` (`ge=1, le=500`, default 100), `offset` (`ge=0`)
* **Response schema:** `list[TradeResponse]` · **Status:** 200 · **Errors:** `422`
* **Services:** `TradingEngine.list_trades` → `ExecutionEngine.list_recent`
  (`ORDER BY trades.id DESC`) · **Tables:** `trades` SELECT

---

### 1.16 `GET /api/v1/trading/position`

* **File:** `app/api/v1/endpoints/trading.py`, function `get_position`
* **Purpose:** current position; `quantity` carries direction (>0 long, 0 flat, <0 short)
* **Params / body:** none · **Response schema:** `PositionResponse`
* **Status:** 200 · **Errors:** none — when nothing has ever traded a **flat
  position is materialised in memory** (not persisted), so this never 404s
* **Services:** `TradingEngine.get_position` → `PositionManager.get`
* **Tables:** `positions` SELECT

---

### 1.17 `GET /api/v1/trading/portfolio`

* **File:** `app/api/v1/endpoints/trading.py`, function `get_portfolio`

| Query | Type | Default | Validation |
|-------|------|---------|-----------|
| `mark_price` | `Decimal \| None` | `None` | `gt=0` |

* **Response schema:** `PortfolioResponse` · **Status:** 200
* **Errors:** `404 wallet_not_found`, `422`
* **Services:** `TradingEngine.get_portfolio` → `WalletRepository.get`,
  `PositionManager.get`, `PortfolioManager.snapshot`
* **Tables:** `wallet` SELECT, `positions` SELECT

> **Without `mark_price`, `unrealized_pnl` and `position_value` are `0.00` by
> design** — the engine never fetches prices itself. The frontend supplies the
> live tick price so the arithmetic stays in `Decimal` server-side.

---

### 1.18 `GET /api/v1/trading/execution-cost`

* **File:** `app/api/v1/endpoints/trading.py`, function `preview_execution_cost`
* **Purpose:** price a hypothetical order through the real models; **writes nothing**

| Query | Type | Req | Validation |
|-------|------|-----|-----------|
| `side` | `OrderSide` | **yes** | enum |
| `quantity` | `int` | **yes** | `ge=1, le=10_000_000` |
| `reference_price` | `Decimal` | **yes** | `gt=0` (mid price) |

* **Response schema:** `ExecutionCostPreview` · **Status:** 200 · **Errors:** `422`
* **Services:** `ExecutionEngine(session).price_fill()` — pure
* **Tables:** none (a session is injected but never used on this path)

```bash
curl "http://localhost:8000/api/v1/trading/execution-cost?side=BUY&quantity=100&reference_price=1400.00"
```

---

### 1.19 `GET /api/v1/stream/status`

* **File:** `app/api/v1/endpoints/stream.py`, function `stream_status`
* **Purpose:** what the live stream is doing and which provider is behind it
* **Params / body:** none · **Response:** plain `dict` — **no Pydantic schema**;
  the shape is `PriceStreamService.status()` (mirrored by `StreamStatus` in
  `frontend/src/types/stream.ts`)
* **Status:** 200 · **Errors:** none · **Tables:** none

```json
{"running":true,"mode":"poll","provider":"yahoo","is_mock":false,"is_delayed":false,
 "symbol":"RELIANCE","exchange":"NSE","poll_interval_seconds":5.0,"connections":1,
 "ticks_broadcast":128,"errors":0,"last_error":null}
```

---

### 1.20 `GET /api/v1/portfolio/snapshots`

* **File:** `app/api/v1/endpoints/portfolio.py`, function `list_snapshots`
* **Purpose:** the equity curve, **oldest first** (ready to plot)

| Query | Type | Default | Validation |
|-------|------|---------|-----------|
| `start` / `end` | `datetime \| None` | `None` | ISO 8601 |
| `limit` | `int` | `500` | `ge=1, le=5000` |
| `source` | `SnapshotSource \| None` | `None` | `PERIODIC` \| `TRADE` \| `MANUAL` |

* **Response schema:** `SnapshotSeriesResponse` · **Status:** 200 · **Errors:** `422`
* **Services:** `SnapshotService.history()` — window applied first, then the
  limit keeps the **most recent** rows, then the list is reversed
* **Tables:** `portfolio_snapshots` SELECT

---

### 1.21 `POST /api/v1/portfolio/snapshots`

* **File:** `app/api/v1/endpoints/portfolio.py`, function `capture_snapshot`
* **Purpose:** record the account's value now, `source=MANUAL`
* **Query:** `mark_price` (`Decimal | None`, `gt=0`). **Body: none.**
* **Response schema:** `SnapshotResponse` · **Status:** **201**
* **Errors:** `404 wallet_not_found`, `422`
* **Services:** `SnapshotService.capture(mark_price=..., source=MANUAL)` — commits
* **Tables:** `wallet` SELECT, `positions` SELECT, `portfolio_snapshots` INSERT

> Without `mark_price` an open position cannot be valued, so only the cash side
> is recorded (`mark_price` is stored NULL when the position is flat regardless).

---

### 1.22 `GET /api/v1/portfolio/performance`

* **File:** `app/api/v1/endpoints/portfolio.py`, function `performance_summary`
* **Params / body:** none · **Response schema:** `PerformanceResponse`
* **Status:** 200 · **Errors:** none — an empty database returns zeros and nulls
* **Services:** `PerformanceAnalyzer.summary()` → `_totals`, `_outcomes`,
  `_extreme(descending=True/False)`, `_order_counts` (five queries; all
  arithmetic runs in PostgreSQL over `NUMERIC`)
* **Tables:** `trades` SELECT, `orders` SELECT

**Definitions used (must match `app/backtest/results.py`):** only fills with
`closed_quantity > 0` can win or lose; a win is `net_pnl > 0` (**net**, after
charges). `largest_winning_trade` returns `null` if the best closing trade is
not actually positive.

---

### 1.23 `GET /api/v1/strategies`

* **File:** `app/api/v1/endpoints/backtest.py`, function `list_strategies`
* **Params / body:** none · **Response schema:** `list[StrategySchema]`
* **Status:** 200 · **Errors:** none
* **Services:** `describe_all()` → `Strategy.describe()` · **Tables:** none

```json
[{"name":"ma_crossover","display_name":"Moving Average Crossover",
  "description":"Buys when the fast SMA crosses above the slow SMA ...",
  "params":[{"name":"fast","default":10,"minimum":2,"maximum":200,"description":"Fast SMA period."},
            {"name":"slow","default":30,"minimum":3,"maximum":500,"description":"Slow SMA period."},
            {"name":"allow_short","default":1,"minimum":0,"maximum":1,
             "description":"1 to short on a death cross, 0 to only go flat."}]}]
```

---

### 1.24 `POST /api/v1/strategies/backtest`

* **File:** `app/api/v1/endpoints/backtest.py`, function `run_backtest`
* **Request schema:** `BacktestRequest`

| Field | Type | Default | Validation |
|-------|------|---------|-----------|
| `strategy` | `str` | **required** | must be in `_STRATEGIES` |
| `params` | `dict[str, Any]` | `{}` | validated by the strategy's `__init__` |
| `interval` | `Interval` | `1d` | enum |
| `limit` | `int` | `500` | `ge=10, le=5000` |
| `start` / `end` | `datetime \| None` | `None` | |
| `initial_capital` | `Decimal` | `1000000.00` | `gt=0`, 18/2 |
| `fill_timing` | `FillTiming` | `next_open` | `next_open` \| `current_close` |
| `sizing_mode` | `SizingMode` | `percent_of_equity` | + `fixed_quantity`, `fixed_value` |
| `equity_percent` | `Decimal` | `95` | `gt=0, le=100` |
| `fixed_quantity` | `int` | `100` | `ge=1, le=10_000_000` |
| `fixed_value` | `Decimal` | `100000.00` | `gt=0`, 18/2 |
| `close_at_end` | `bool` | `true` | |

* **Response schema:** `BacktestResultSchema` (includes the full `trades` and
  `equity_curve` arrays)
* **Status:** 200
* **Errors:** `400 unknown_strategy`, `400 invalid_strategy_params`, `422`, `503`
* **Services:** `create_strategy` → `RelianceMarketDataService.get_historical_candles`
  → `BacktestEngine.run` (which calls `ExecutionEngine.price_fill` and `apply_fill`)
* **Tables:** **none — a backtest writes nothing.**

```bash
curl -X POST http://localhost:8000/api/v1/strategies/backtest \
  -H 'Content-Type: application/json' \
  -d '{"strategy":"ma_crossover","params":{"fast":10,"slow":30,"allow_short":1},
       "interval":"1d","limit":500}'
```

---

## 2. WebSocket API

There is exactly **one** WebSocket endpoint.

### 2.1 `WS /api/v1/stream/prices`

* **File:** `app/api/v1/endpoints/stream.py`, function `price_stream`
  (`@router.websocket("/prices")`)
* **URL:** `ws://localhost:8000/api/v1/stream/prices` (`wss://` in TLS
  deployments). Built client-side by `wsUrl('/stream/prices')` in
  `frontend/src/api/client.ts`.
* **Auth:** none. `CORSMiddleware` does **not** apply to WebSocket handshakes.

### 2.2 Connection behaviour

```
1. manager = get_connection_manager()          ConnectionManager singleton
   service = get_price_stream()                PriceStreamService singleton
2. await manager.connect(websocket)
      if len(connections) >= STREAM_MAX_CONNECTIONS (default 50):
          stats.total_rejected += 1; raise ConnectionLimitReached
      await websocket.accept(); connections.add(ws); total_accepted += 1
3. if not service.is_running: await service.start()   <-- LAZY: the upstream feed
                                                          starts on the FIRST client
4. send {"type":"status", data: service.status() + server_time}
5. if service.last_tick is not None: send it immediately  (no wait for a poll)
6. loop: message = await websocket.receive_json()
         if message.get("type") == "ping": send {"type":"pong", ...}
         anything else is ignored
7. WebSocketDisconnect -> manager.disconnect(ws)
   any other Exception -> manager.close(ws)   (code 1000)
```

**Rejection path (pool full):** the server calls `accept()` **then** sends a
fatal error frame and closes with code **1008** (`_POLICY_VIOLATION`), so the
client sees a reason rather than a bare handshake failure.

**Shutdown:** `shutdown_price_stream()` (from `app/main.py:lifespan`) stops the
service and calls `ConnectionManager.disconnect_all(code=1001)`.

### 2.3 Client → server messages

Only one message is understood. The socket is read-only for market data.

| `type` | Payload | Purpose |
|--------|---------|---------|
| `ping` | `{"type":"ping"}` | heartbeat; sent by `useLivePrice` every 25 s |

Anything else — including malformed JSON — is ignored (malformed JSON raises
inside `receive_json()` and drops the connection via the bare `except`).

### 2.4 Server → client messages

Built by `PriceStreamService.build_tick()` / `status()` / `_handle_failure()` in
`app/realtime/price_stream.py`. Mirrored by `StreamMessage` in
`frontend/src/types/stream.ts`. **All monetary values are JSON strings.**

#### `tick`

| Field | Type | Req | Notes |
|-------|------|-----|-------|
| `symbol`, `exchange` | string | yes | |
| `last_price` | string | yes | Decimal |
| `bid`, `ask` | string \| null | yes (nullable) | null only when `bid_ask_source="unavailable"` |
| `bid_ask_source` | `"provider"`\|`"modelled"`\|`"unavailable"` | yes | `modelled` = derived from `SpreadModel`, never a real book |
| `volume` | number | yes | |
| `timestamp` | string | yes | exchange time, ISO 8601 UTC |
| `previous_close`, `day_open`, `day_high`, `day_low` | string \| null | yes (nullable) | |
| `change`, `change_percent` | string \| null | yes (nullable) | null when `previous_close` is absent |
| `currency`, `provider` | string | yes | |
| `is_mock`, `is_delayed` | boolean | yes | |
| `mode` | `"push"`\|`"poll"` | yes | |
| `server_time` | string | yes | ISO 8601 UTC |

```json
{"type":"tick","data":{"symbol":"RELIANCE","exchange":"NSE","last_price":"1402.35",
 "bid":"1402.21","ask":"1402.49","bid_ask_source":"modelled","volume":4821330,
 "timestamp":"2026-08-25T09:14:00+00:00","previous_close":"1395.10",
 "day_open":"1396.00","day_high":"1408.75","day_low":"1391.20",
 "change":"7.25","change_percent":"0.52","currency":"INR","provider":"yahoo",
 "is_mock":false,"is_delayed":false,"mode":"poll",
 "server_time":"2026-08-25T09:14:03.117441+00:00"}}
```

#### `status`

Sent once on connect. Same body as `GET /api/v1/stream/status` plus `server_time`.
Fields: `running`, `mode`, `provider`, `is_mock`, `is_delayed`, `symbol`,
`exchange`, `poll_interval_seconds`, `connections`, `ticks_broadcast`, `errors`,
`last_error` (all required except `last_error`, which is nullable) and
`server_time`.

#### `error`

| Field | Type | Req |
|-------|------|-----|
| `message` | string | yes |
| `detail` | string | optional (upstream failures only) |
| `fatal` | boolean | optional (connection-limit refusal only) |
| `timestamp` | string | optional (upstream failures only) |

```json
{"type":"error","data":{"message":"Upstream market data is unavailable.",
 "detail":"MarketDataUnavailableError: Yahoo Finance returned HTTP 429 for RELIANCE.NS.",
 "timestamp":"2026-08-25T09:14:08+00:00"}}
```
```json
{"type":"error","data":{"message":"Refusing connection: 50 clients already connected.",
 "fatal":true}}
```

#### `pong`

```json
{"type":"pong","data":{"server_time":"2026-08-25T09:14:28.004112+00:00"}}
```

### 2.5 Broadcasting

`ConnectionManager.broadcast()` (`app/realtime/connection_manager.py`):
snapshots the connection set under an `asyncio.Lock`, sends concurrently via
`asyncio.gather(..., return_exceptions=True)` so one slow client cannot stall
the rest, and **drops any client whose send raises**.

### 2.6 Reconnection behaviour

**Server: none.** The server never re-dials a client; it reaps dead sockets.

**Client** (`frontend/src/hooks/useLivePrice.ts`):

| Constant | Value | Meaning |
|----------|-------|---------|
| `INITIAL_BACKOFF_MS` | 1 000 | first retry delay |
| `MAX_BACKOFF_MS` | 15 000 | cap |
| `PING_INTERVAL_MS` | 25 000 | heartbeat |
| `STALE_AFTER_MS` | 30 000 | mark the price stale |

On `onclose`: clear timers, `setConnection('reconnecting')`, compute
`delay = backoff * jitter` where `jitter = Math.random()*0.3 + 0.85`, double the
backoff up to the cap, increment `attempt`, `setTimeout(connect, delay)`.
`reconnect()` (the header badge is a button) resets the backoff to 1 s.

**Server → provider** reconnection exists only in PUSH mode:
`PriceStreamService._run_push_loop` broadcasts an error frame, sleeps a backoff
of 1 s doubling to 30 s, then re-attaches to `subscribe_live_data`. In POLL mode
the next scheduled tick simply tries again.
---

## 3. Data Models (Pydantic)

All schemas live in `backend/app/schemas/`. ORM-backed models set
`model_config = ConfigDict(from_attributes=True)` and are populated with
`Model.model_validate(orm_row)`. `_MONEY = {"max_digits": 18, "decimal_places": 2}`
mirrors `NUMERIC(18,2)`. Every `Decimal` serialises as a **JSON string**.

### 3.1 `app/schemas/health.py`

| Class | Fields (type · req) | Validation | Usage |
|-------|--------------------|-----------|-------|
| `ServiceStatus` | `Literal["ok","degraded","error"]` (type alias) | — | `HealthResponse`, `DatabaseHealth` |
| `DatabaseHealth` | `status: ServiceStatus` ·req; `detail: str` ·req; `latency_ms: float\|None` ·opt(None) | — | nested in `HealthResponse` |
| `HealthResponse` | `status`, `app_name: str`, `version: str`, `environment: str`, `timestamp: datetime`, `database: DatabaseHealth` — all required | — | `GET /health` |
| `PingResponse` | `message: Literal["pong"]` (default `"pong"`); `timestamp: datetime` ·req | — | `GET /health/ping` |

### 3.2 `app/schemas/wallet.py`

| Class | Fields | Validation | Usage |
|-------|--------|-----------|-------|
| `WalletResponse` | `id: int`, `currency: str`, `initial_balance: Decimal`, `cash_balance: Decimal`, `created_at: datetime`, `updated_at: datetime` — all required | `from_attributes=True` | all three wallet endpoints |
| `WalletInitializeRequest` | `initial_balance: Decimal\|None` ·opt(None) | `gt=0`, 18/2 | body of `POST /wallet/initialize` |
| `WalletResetRequest` | `initial_balance: Decimal\|None` ·opt(None) | `gt=0`, 18/2 | body of `POST /wallet/reset` |

### 3.3 `app/schemas/market_data.py`

| Class | Fields | Validation | Usage |
|-------|--------|-----------|-------|
| `Interval` | StrEnum: `ONE_MINUTE="1m"`, `FIVE_MINUTES="5m"`, `FIFTEEN_MINUTES="15m"`, `THIRTY_MINUTES="30m"`, `ONE_HOUR="1h"`, `ONE_DAY="1d"`, `ONE_WEEK="1wk"`, `ONE_MONTH="1mo"` | enum membership | query params, provider mapping, backtest |
| `Quote` | `symbol`·req, `exchange`·req, `last_price: Decimal`·req, `bid: Decimal\|None`·opt, `ask: Decimal\|None`·opt, `volume: int`·req, `timestamp: datetime`·req, `previous_close/day_open/day_high/day_low: Decimal\|None`·opt, `currency: str`(default `"INR"`), `provider: str`·req, `is_delayed: bool`·req, `is_mock: bool`(default `False`) | — | `GET /market-data/quote`, provider return type, `build_tick` input |
| `Candle` | `timestamp: datetime`, `open/high/low/close: Decimal`, `volume: int` — all required | — | `CandleSeries`, indicators, backtest, strategies |
| `CandleSeries` | `symbol`, `exchange`, `interval: Interval`, `provider`, `count: int`, `candles: list[Candle]` — all required | — | `GET /market-data/candles` |
| `ProviderCapabilities` | `name`, `supports_quotes`, `supports_historical`, `supports_bid_ask`, `supports_live_stream`, `is_delayed`, `quote_delay_minutes: int`, `requires_credentials`, `supported_intervals: list[Interval]` — required; `is_mock: bool`(False), `limitations: list[str]`(`[]`) | — | `GET /market-data/provider`; **drives PUSH/POLL mode and modelled bid/ask** |

### 3.4 `app/schemas/indicators.py`

| Class | Fields | Usage |
|-------|--------|-------|
| `IndicatorPointResponse` | `timestamp: datetime`, `value: Decimal` — req | one plotted point |
| `IndicatorSeriesResponse` | `key: str`, `label: str`, `style: SeriesStyle`, `points: list[IndicatorPointResponse]` — req | one plottable line |
| `IndicatorResponse` | `key`, `type: IndicatorType`, `label`, `pane: Pane`, `params: dict[str, float\|int]`, `warmup: int`, `insufficient_data: bool`, `series: list[...]` — req; `scale_min/scale_max: Decimal\|None`(None) | one computed indicator |
| `IndicatorSetResponse` | `symbol`, `exchange`, `interval: Interval`, `provider`, `candle_count: int`, `indicators: list[IndicatorResponse]` — req | `GET /indicators` |
| `IndicatorParamCatalogue` | `name: str`, `default/minimum/maximum: float\|int` — req | catalogue |
| `IndicatorCatalogueEntry` | `type: str`, `display_name: str`, `pane: str`, `description: str`, `params: list[IndicatorParamCatalogue]` — req | `GET /indicators/catalogue` |

`IndicatorType`, `Pane` and `SeriesStyle` are **imported from**
`app/indicators/definitions.py`, not redefined here.

### 3.5 `app/schemas/trading.py`

| Class | Fields | Validation | Usage |
|-------|--------|-----------|-------|
| `PlaceOrderRequest` | `side: OrderSide`·req; `quantity: int`·req; `reference_price: Decimal`·req; `requested_price: Decimal\|None`·opt; `symbol: str\|None`·opt | `quantity gt=0 le=10_000_000`; `reference_price gt=0` 18/2; `requested_price gt=0` 18/2 | body of `POST /trading/orders` |
| `OrderResponse` | `id`, `symbol`, `exchange`, `side`, `order_type`, `quantity`, `requested_price: Decimal\|None`, `execution_price: Decimal\|None`, `status: OrderStatus`, `rejection_reason: str\|None`, `created_at`, `filled_at: datetime\|None` | `from_attributes` | order endpoints |
| `ChargesResponse` | `brokerage`, `stt`, `exchange_charges`, `sebi_charges`, `stamp_duty`, `gst`, `dp_charges`, `total_charges` — all `Decimal`, req | `from_attributes` | nested in `ExecutionCostPreview` |
| `TradeResponse` | `id`, `order_id`, `symbol`, `exchange`, `side`, `quantity`, `execution_price`·req; `reference_price/bid_price/ask_price: Decimal\|None`·opt; `spread_cost`, `slippage_cost`, all seven charge fields, `total_charges`, `gross_pnl`, `net_pnl`, `closed_quantity: int`, `created_at` | `from_attributes` | `GET /trading/trades`, nested in `OrderResultResponse` |
| `PositionResponse` | `symbol`, `exchange`, `quantity: int`, `average_price`, `realized_pnl`, `total_charges`, `net_realized_pnl`; `updated_at: datetime\|None`(None) | `from_attributes` | `GET /trading/position` |
| `OrderResultResponse` | `order: OrderResponse`, `trade: TradeResponse`, `position: PositionResponse`, `gross_pnl`, `total_charges`, `net_pnl`, `cash_delta` — req | — | `POST /trading/orders` |
| `PortfolioResponse` | `cash_balance`, `initial_balance`, `quantity: int`, `average_price`, `realized_pnl`, `total_charges`, `net_realized_pnl`, `unrealized_pnl`, `position_value`, `total_equity`, `total_pnl`, `net_total_pnl`, `mark_price: Decimal\|None`, `currency` — req | — | `GET /trading/portfolio` (built with `PortfolioResponse(**vars(snapshot))`) |
| `ExecutionCostPreview` | `side`, `quantity`, `reference_price`, `bid_price`, `ask_price`, `spread`, `execution_price`, `spread_cost`, `slippage_cost`, `charges: ChargesResponse`, `total_execution_cost` — req | — | `GET /trading/execution-cost` |

### 3.6 `app/schemas/portfolio.py`

| Class | Fields | Usage |
|-------|--------|-------|
| `SnapshotResponse` | `id`, `captured_at`, `source: SnapshotSource`, `symbol`, `quantity: int`, `average_price`, `mark_price: Decimal\|None`(None), `cash`, `position_value`, `total_value`, `realized_pnl`, `total_charges`, `unrealized_pnl`, `net_pnl` (`from_attributes`) | snapshot endpoints |
| `SnapshotSeriesResponse` | `count: int`, `first_captured_at: datetime\|None`, `last_captured_at: datetime\|None`, `snapshots: list[SnapshotResponse]` | `GET /portfolio/snapshots` |
| `TradeExtremeResponse` | `trade_id: int`, `side: str`, `quantity: int`, `execution_price`, `gross_pnl`, `total_charges`, `net_pnl`, `created_at` (`from_attributes`) | nested in `PerformanceResponse` |
| `PerformanceResponse` | `total_trades`, `closing_trades`, `winning_trades`, `losing_trades`, `breakeven_trades` (ints); `win_rate: Decimal\|None`(None); `total_gross_pnl`, `total_charges`, `total_net_pnl`; `average_win/average_loss/profit_factor: Decimal\|None`(None); `largest_winning_trade/largest_losing_trade: TradeExtremeResponse\|None`(None); `total_orders`, `filled_orders`, `rejected_orders` (ints) | `GET /portfolio/performance` |

### 3.7 `app/schemas/backtest.py`

| Class | Fields | Validation | Usage |
|-------|--------|-----------|-------|
| `StrategyParamSchema` | `name: str`, `default/minimum/maximum: float\|int`, `description: str`(`""`) | — | nested |
| `StrategySchema` | `name`, `display_name`, `description`, `params: list[StrategyParamSchema]` | — | `GET /strategies` |
| `BacktestRequest` | see the table in §1.24 | field-level `ge/le/gt` | body of `POST /strategies/backtest` |
| `BacktestTradeSchema` | `index: int`, `timestamp`, `side: OrderSide`, `quantity`, `reference_price`, `execution_price`, `spread_cost`, `slippage_cost`, `total_charges`, `gross_pnl`, `net_pnl`, `closed_quantity`, `position_after: int`, `cash_after`, `reason: str` (`from_attributes`) | — | nested |
| `EquityPointSchema` | `timestamp`, `mark_price`, `cash`, `position: int`, `position_value`, `total_value`, `realized_pnl`, `unrealized_pnl`, `net_pnl` (`from_attributes`) | — | nested (note: `EquityPoint.index` is **not** exposed) |
| `BacktestResultSchema` | `strategy`, `symbol`, `exchange`, `interval`, `start_at/end_at: datetime\|None`, `bars: int`, `initial_capital`, `final_equity`, `total_return`, `total_return_pct`, `total_trades`, `closing_trades`, `winning_trades`, `losing_trades`, `breakeven_trades`, `win_rate: Decimal\|None`, `gross_pnl`, `total_charges`, `net_pnl`, `max_drawdown`, `max_drawdown_pct`, `profit_factor/average_win/average_loss/largest_win/largest_loss: Decimal\|None`, `exposure_pct`, `rejected_orders: int`, `final_position: int`, `trades: list[BacktestTradeSchema]`, `equity_curve: list[EquityPointSchema]` | `from_attributes` | `POST /strategies/backtest` |

`FillTiming` and `SizingMode` are imported from `app/backtest/engine.py`.

### 3.8 Non-Pydantic dataclasses used as API payload sources

These are **frozen dataclasses**, not Pydantic, but are serialised through
`from_attributes` schemas or `vars()`:

| Dataclass | File | Serialised by |
|-----------|------|---------------|
| `OrderResult` | `app/trading/engine.py` | unpacked field-by-field in `place_order` |
| `PortfolioSnapshot` | `app/trading/portfolio.py` | `PortfolioResponse(**vars(snapshot))` |
| `Fill`, `BidAsk`, `SpreadResult`, `SlippageResult`, `ChargeBreakdown` | `app/trading/{execution,spread,slippage,fees}.py` | read field-by-field in `preview_execution_cost` |
| `IndicatorResult`, `IndicatorSeriesResult`, `IndicatorPoint` | `app/indicators/service.py` | `IndicatorResponse.model_validate(...)` |
| `BacktestResult`, `BacktestTrade`, `EquityPoint` | `app/backtest/{results,portfolio}.py` | `BacktestResultSchema.model_validate(...)` |
| `PerformanceSummary`, `TradeExtreme` | `app/analytics/performance.py` | `PerformanceResponse.model_validate(...)` |
| `FillOutcome` | `app/trading/position_manager.py` | internal only |
| `ConnectionStats` | `app/realtime/connection_manager.py` | internal only |
| `IndicatorSpec`, `IndicatorDef`, `ParamDef` | `app/indicators/definitions.py` | via `catalogue()` dicts |
| `Decision`, `StrategyContext`, `StrategyParam` | `app/strategies/base.py` | via `describe()` dicts |

---

## 4. Database Models (SQLAlchemy)

All under `backend/app/models/`. Base and mixin in `app/db/base.py`.
Naming convention (`NAMING_CONVENTION`): `ix_%(column_0_label)s`,
`uq_%(table_name)s_%(column_0_name)s`, `ck_%(table_name)s_%(constraint_name)s`,
`fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s`, `pk_%(table_name)s`.

`TimestampMixin` adds `created_at` and `updated_at` (`TIMESTAMPTZ NOT NULL
server_default now()`, `updated_at` also `onupdate=now()`).

> `app/models/__init__.py` must re-export every model — Alembic autogenerate
> reads `Base.metadata`.

### 4.1 `Wallet` — table `wallet`

**File:** `app/models/wallet.py` · **Constant:** `WALLET_ID = 1`

| Column | Type | Null | Default |
|--------|------|------|---------|
| `id` | `Integer` | no | `1` (app-side, `autoincrement=False`) — **PK** |
| `currency` | `String(3)` | no | `'INR'` |
| `initial_balance` | `Numeric(18,2)` | no | — |
| `cash_balance` | `Numeric(18,2)` | no | — |
| `created_at` / `updated_at` | `DateTime(timezone=True)` | no | `now()` |

**Constraints:** `pk_wallet`; `ck_wallet_singleton` (`id = 1`);
`ck_wallet_initial_balance_positive`; `ck_wallet_cash_balance_non_negative`.
**Indexes:** PK only. **Relationships:** none.

### 4.2 `Order` — table `orders`

**File:** `app/models/trading.py` · **Constant:** `MAX_ORDER_QUANTITY = 10_000_000`

| Column | Type | Null | Notes |
|--------|------|------|-------|
| `id` | `BigInteger` autoincrement | no | **PK** |
| `symbol` | `String(32)` | no | `index=True` |
| `exchange` | `String(16)` | no | default `'NSE'` |
| `side` | `Enum(OrderSide, name="order_side", native_enum=True, validate_strings=True)` | no | |
| `order_type` | `Enum(OrderType, name="order_type")` | no | default `MARKET` |
| `quantity` | `Integer` | no | |
| `requested_price` | `Numeric(18,2)` | yes | audit only |
| `execution_price` | `Numeric(18,2)` | yes | NULL until filled |
| `status` | `Enum(OrderStatus, name="order_status")` | no | default `PENDING`, `index=True` |
| `rejection_reason` | `String(500)` | yes | truncated by `mark_rejected` |
| `filled_at` | `DateTime(timezone=True)` | yes | |
| `created_at` / `updated_at` | `DateTime(timezone=True)` | no | |

**Constraints:** `pk_orders`; `ck_orders_quantity_positive`;
`ck_orders_quantity_within_bounds` (`quantity <= 10000000`);
`ck_orders_requested_price_positive`; `ck_orders_execution_price_positive`;
`ck_orders_filled_orders_have_a_price`
(`status <> 'FILLED' OR execution_price IS NOT NULL`).
**Indexes:** `ix_orders_symbol`, `ix_orders_status`, `ix_orders_created_at`.
**Relationships:** `trades: list[Trade]` — `back_populates="order"`,
`cascade="all, delete-orphan"`, `lazy="selectin"`.
**Property:** `signed_quantity = quantity * side.direction`.

### 4.3 `Trade` — table `trades`

**File:** `app/models/trading.py`

Identity: `id` (BigInteger PK), `order_id` (**FK** → `orders.id`,
`ON DELETE CASCADE`, `index=True`), `symbol` (`String(32)`, indexed),
`exchange` (`String(16)`, default `'NSE'`), `side` (`order_side`),
`quantity` (`Integer`).

Pricing: `execution_price` `Numeric(18,2)` **NOT NULL**; `reference_price`,
`bid_price`, `ask_price` `Numeric(18,2)` nullable.

Costs and P&L — all `Numeric(18,2)` NOT NULL with `server_default=text("0")`:
`spread_cost`, `slippage_cost`, `brokerage`, `stt`, `exchange_charges`,
`sebi_charges`, `stamp_duty`, `gst`, `dp_charges`, `total_charges`,
`gross_pnl`, `net_pnl`. Plus `closed_quantity` `Integer NOT NULL DEFAULT 0`.
Plus `created_at` / `updated_at`.

**Constraints:** `pk_trades`; `fk_trades_order_id_orders`;
`ck_trades_quantity_positive`; `ck_trades_execution_price_positive`.
**Indexes:** `ix_trades_order_id`, `ix_trades_symbol`, `ix_trades_created_at`.
**Relationship:** `order: Order` — `back_populates="trades"`.

Semantics: `gross_pnl` is **zero on an opening fill**; `net_pnl = gross_pnl -
total_charges`; `closed_quantity > 0` is the definition of a closing trade used
by both `PerformanceAnalyzer` and `backtest/results.summarise`.

### 4.4 `Position` — table `positions`

**File:** `app/models/trading.py`

| Column | Type | Null | Notes |
|--------|------|------|-------|
| `symbol` | `String(32)` | no | **PK** — natural key |
| `exchange` | `String(16)` | no | default `'NSE'` |
| `quantity` | `Integer` | no | **signed**: >0 long, 0 flat, <0 short |
| `average_price` | `Numeric(18,4)` | no | always positive; 0 when flat |
| `realized_pnl` | `Numeric(18,2)` | no | cumulative gross; survives going flat |
| `total_charges` | `Numeric(18,2)` | no | cumulative, opening fills included |
| `net_realized_pnl` | `Numeric(18,2)` | no | `realized_pnl - total_charges` |
| `created_at` / `updated_at` | `DateTime(timezone=True)` | no | |

**Constraints:** `pk_positions`; `ck_positions_average_price_non_negative`;
`ck_positions_average_price_matches_quantity` —
`(quantity = 0 AND average_price = 0) OR (quantity <> 0 AND average_price > 0)`.
**Indexes:** PK only. **Relationships:** none (**no FK to orders/trades**).
**Properties:** `is_long`, `is_short`, `is_flat`.

### 4.5 `PortfolioSnapshot` — table `portfolio_snapshots`

**File:** `app/models/portfolio_snapshot.py` · **Append-only** — nothing UPDATEs a row.

| Column | Type | Null | Notes |
|--------|------|------|-------|
| `id` | `BigInteger` autoincrement | no | **PK** |
| `captured_at` | `DateTime(timezone=True)` | no | `server_default now()`, indexed |
| `source` | `Enum(SnapshotSource, name="snapshot_source")` | no | default `PERIODIC`, `index=True` |
| `symbol` | `String(32)` | no | |
| `quantity` | `Integer` | no | default 0 |
| `average_price` | `Numeric(18,4)` | no | default `0.0000` |
| `mark_price` | `Numeric(18,2)` | **yes** | **NULL when flat** |
| `cash` | `Numeric(18,2)` | no | |
| `position_value` | `Numeric(18,2)` | no | signed |
| `total_value` | `Numeric(18,2)` | no | `cash + position_value` |
| `realized_pnl`, `total_charges`, `unrealized_pnl`, `net_pnl` | `Numeric(18,2)` | no | default 0 |

**Constraints:** `pk_portfolio_snapshots`;
`ck_portfolio_snapshots_cash_non_negative`;
`ck_portfolio_snapshots_mark_price_positive`.
**Indexes:** `ix_portfolio_snapshots_captured_at`, `ix_portfolio_snapshots_source`.
**Relationships:** none.
**Method:** `is_equivalent_to(other)` — compares `quantity`, `cash`,
`position_value`, `total_value`, `realized_pnl`, `unrealized_pnl`,
`total_charges`; powers `SNAPSHOT_SKIP_UNCHANGED`.

### 4.6 Enums — `app/models/enums.py` + `portfolio_snapshot.py`

| Python enum | PG type | Members | Extras |
|-------------|---------|---------|--------|
| `OrderSide` | `order_side` | `BUY`, `SELL`, `SHORT_SELL`, `BUY_TO_COVER` | `.direction` → `+1` for BUY/BUY_TO_COVER else `-1`; `.is_closing_only` → True for SELL/BUY_TO_COVER |
| `OrderStatus` | `order_status` | `PENDING`, `FILLED`, `REJECTED`, `CANCELLED` | `CANCELLED` is **never set by any code** |
| `OrderType` | `order_type` | `MARKET` | only member |
| `SnapshotSource` | `snapshot_source` | `PERIODIC`, `TRADE`, `MANUAL` | |

### 4.7 Migrations — `backend/alembic/versions/`

| Revision | Down-rev | File | Content |
|----------|----------|------|---------|
| `ea97efd67efb` | — | `20260825_0912_create_wallet_table.py` | `wallet` + 3 CHECKs |
| `44b98124fbd4` | `ea97efd67efb` | `20260825_0956_create_orders_trades_and_positions.py` | 3 enums created explicitly (`checkfirst`), then `orders`, `trades`, `positions`; enums dropped on downgrade |
| `b41705c11d09` | `44b98124fbd4` | `20260825_1010_add_execution_costs_and_net_pnl.py` | all cost columns; **renames** `trades.realized_pnl` → `gross_pnl`; `server_default` on new NOT NULL columns; backfills `positions.net_realized_pnl` |
| `51917e5fa5f1` | `b41705c11d09` | `20260825_1119_add_portfolio_snapshots.py` | `snapshot_source` enum + `portfolio_snapshots`; aligns 3 server defaults |

**Head:** `51917e5fa5f1`. No branches.

**The only foreign key in the whole schema is `trades.order_id → orders.id`.**

---

## 5. Trading Engine API

Package `backend/app/trading/`. Imports **no** web framework and **no**
market-data provider. Prices are always supplied by the caller.

### 5.1 `TradingEngine` — `app/trading/engine.py`

```python
TradingEngine(session: AsyncSession, *, execution: ExecutionEngine | None = None)
```
Attributes: `.orders` (`OrderManager`), `.execution` (`ExecutionEngine`),
`.positions` (`PositionManager`), `.portfolio` (`PortfolioManager`),
`._wallets` (`WalletRepository`).

| Method | Purpose | Parameters | Returns | Raises | Side effects / DB |
|--------|---------|-----------|---------|--------|-------------------|
| `place_order` | validate, execute and settle atomically | kw-only: `side: OrderSide`, `quantity: int`, `reference_price: Decimal`, `symbol: str\|None=None`, `requested_price: Decimal\|None=None` | `OrderResult` | `InvalidOrderError`, `UnsupportedSymbolError`, `WalletNotFoundError`, `InvalidPositionOperationError`, `InsufficientFundsError` | **one transaction**: locks `wallet` + `positions` `FOR UPDATE`; INSERT `orders`; INSERT `trades`; UPDATE `positions`, `wallet`, `orders`; INSERT `portfolio_snapshots` if `SNAPSHOT_ON_TRADE`; `commit()`; refreshes order/position/trade. On a domain rejection: marks the order `REJECTED` and **commits** before raising. |
| `get_position` | current position | `symbol: str\|None=None` | `Position` (materialised flat if absent, **not persisted**) | `UnsupportedSymbolError` | SELECT `positions` |
| `get_portfolio` | value the account | kw-only `mark_price: Decimal\|None=None`, `symbol: str\|None=None` | `PortfolioSnapshot` (dataclass) | `WalletNotFoundError`, `UnsupportedSymbolError` | SELECT `wallet`, `positions` |
| `list_orders` | order history | kw-only `limit=100`, `offset=0`, `status: OrderStatus\|None=None` | `list[Order]` | — | SELECT `orders` |
| `list_trades` | trade history | kw-only `limit=100`, `offset=0` | `list[Trade]` | — | SELECT `trades` |
| `_resolve_symbol` (static) | enforce the single instrument | `symbol: str\|None` | `str` | `UnsupportedSymbolError` | none |
| `_validate_request` (static) | quantity/price sanity | `quantity: int`, `reference_price: Decimal` | `None` | `InvalidOrderError` | none |
| `_validate_against_position` (static) | closing-only intent | `side`, `quantity`, `position` | `None` | `InvalidPositionOperationError` | none |

`OrderResult` (frozen dataclass): `order`, `trade`, `position`, `gross_pnl`,
`total_charges`, `net_pnl`, `cash_delta`.

### 5.2 Order management — `OrderManager` (`app/trading/order_manager.py`)

```python
OrderManager(session: AsyncSession)
```

| Method | Purpose | Parameters | Returns | Raises | DB |
|--------|---------|-----------|---------|--------|----|
| `create` | record a new order in `PENDING` | kw-only `symbol`, `exchange`, `side`, `quantity`, `requested_price`, `order_type=OrderType.MARKET` | `Order` | — | INSERT `orders` + `flush()` (no commit) |
| `mark_filled` | `FILLED` + price + `filled_at=now(UTC)` | `order: Order`, `execution_price: Decimal` | `Order` | — | UPDATE `orders` + `flush()` |
| `mark_rejected` | `REJECTED` + reason (truncated to 500) | `order: Order`, `reason: str` | `Order` | — | UPDATE `orders` + `flush()` |
| `get` | fetch by id | `order_id: int` | `Order \| None` | — | SELECT |
| `list_recent` | newest first | kw-only `limit=100`, `offset=0`, `status=None` | `list[Order]` | — | SELECT |

### 5.3 Execution — `ExecutionEngine` (`app/trading/execution.py`)

```python
ExecutionEngine(session, *, spread=None, slippage=None, fees=None)
ExecutionEngine.frictionless(session)   # classmethod: no spread, no slippage, no charges
```
Defaults come from `SpreadModel.from_settings()`, `SlippageModel.from_settings()`,
`FeeCalculator.from_settings()`.

| Method | Purpose | Parameters | Returns | Raises | Side effects |
|--------|---------|-----------|---------|--------|--------------|
| `price_fill` | **pure** — spread → slippage → charges | kw-only `side: OrderSide`, `quantity: int`, `reference_price: Decimal` | `Fill` | — | **none** (no session, no ORM). This is what the backtester calls. |
| `execute` | price the fill for a persisted order | `order: Order`, `reference_price: Decimal` | `Fill` | — | none |
| `record_trade` | persist the fill with its full breakdown | kw-only `order`, `fill`, `gross_pnl`, `closed_quantity` | `Trade` | — | INSERT `trades` + `flush()` (no commit). Sets `net_pnl = to_money(gross_pnl - charges.total)` |
| `list_recent` | newest first | kw-only `limit=100`, `offset=0` | `list[Trade]` | — | SELECT `trades` |

`Fill` (frozen dataclass): `quantity`, `price`, `side`, `reference_price`,
`quote: BidAsk`, `spread_cost`, `slippage_cost`, `charges: ChargeBreakdown`.
Properties: `signed_quantity`, `notional`, `total_charges`, `execution_cost`.

### 5.4 Positions — `app/trading/position_manager.py`

```python
apply_fill(*, quantity: int, average_price: Decimal,
           fill_quantity: int, fill_price: Decimal) -> FillOutcome
```
**Pure function. The single source of truth for position accounting.** Three
cases: opening from flat; adding in the same direction (re-average, realize
nothing); trading against the position (close `min(|qty|,|fill|)` at the
existing average, realize P&L, and if larger, cross zero — the remainder opens
the opposite direction at the fill price and the average resets). Returns
`FillOutcome(new_quantity, new_average_price, realized_pnl, closed_quantity,
opened_quantity)` with property `is_reversal`.

```python
PositionManager(session: AsyncSession)
```

| Method | Purpose | Parameters | Returns | Raises | DB |
|--------|---------|-----------|---------|--------|----|
| `get` | fetch the row | `symbol: str` | `Position \| None` | — | SELECT |
| `get_or_create_for_update` | row-locked; created flat if absent | `symbol: str` | `Position` | `IntegrityError` (re-raised only if the retry also finds nothing) | `SELECT ... FOR UPDATE`; INSERT + `flush()`; **on `IntegrityError` calls `session.rollback()`** and re-locks |
| `_locked` | internal locked read | `symbol: str` | `Position \| None` | — | `SELECT ... FOR UPDATE` |
| `apply` (static) | write an outcome onto the row | `position`, `outcome`, `charges=Decimal("0.00")` | `Position` | — | mutates the ORM object (flushed later). Accumulates `total_charges` on **every** fill and recomputes `net_realized_pnl` |

### 5.5 Portfolio / wallet — `PortfolioManager` (`app/trading/portfolio.py`)

```python
PortfolioManager(wallet_repository: WalletRepository)
```

| Method | Purpose | Parameters | Returns | Raises | Side effects |
|--------|---------|-----------|---------|--------|--------------|
| `cash_delta` (static) | signed cash movement | `fill: Fill` | `Decimal` | — | none. `to_money(fill.notional * -fill.side.direction - fill.total_charges)` |
| `assert_affordable` (static) | reject an uncoverable debit **before** mutating | `wallet: Wallet`, `fill: Fill` | `None` | `InsufficientFundsError` | none |
| `apply_cash` (static) | move cash for a checked fill | `wallet: Wallet`, `fill: Fill` | `Wallet` | — | mutates `wallet.cash_balance` |
| `snapshot` (static) | value the account | kw-only `wallet`, `quantity`, `average_price`, `realized_pnl`, `total_charges=0`, `net_realized_pnl=None`, `mark_price=None` | `PortfolioSnapshot` (dataclass) | — | none. Without `mark_price` (or when flat) `unrealized_pnl` and `position_value` are `0.00` |

`WalletRepository` (`app/repositories/wallet_repository.py`) —
`get() -> Wallet|None` (SELECT), `get_for_update() -> Wallet|None`
(`SELECT ... FOR UPDATE`), `create(initial_balance, currency) -> Wallet`
(INSERT + `flush()`).

`WalletService` (`app/services/wallet_service.py`) —
`get_wallet()` raises `WalletNotFoundError`; `initialize_wallet(initial_balance=None)`
returns `(Wallet, created: bool)` and **commits**, catching `IntegrityError`;
`reset_wallet(initial_balance=None)` locks, sets `cash_balance = initial_balance`,
**commits**.

### 5.6 P&L — `PnLCalculator` (`app/trading/pnl.py`)

All `@staticmethod`, fully pure. Module functions: `to_money(value)` → 2 dp
`ROUND_HALF_UP`; `to_average(value)` → 4 dp. Constants `CENT = Decimal("0.01")`,
`AVERAGE_PRECISION = Decimal("0.0001")`.

| Method | Parameters (kw-only) | Returns | Formula |
|--------|---------------------|---------|---------|
| `realized_pnl` | `entry_price`, `exit_price`, `quantity: int`, `direction: int` | `Decimal` | `(exit - entry) * qty * direction`; returns `0.00` if `quantity <= 0` |
| `unrealized_pnl` | `quantity: int` (signed), `average_price`, `mark_price` | `Decimal` | `(mark - average) * quantity`; `0.00` when flat |
| `position_value` | `quantity: int` (signed), `mark_price` | `Decimal` | `quantity * mark_price` (negative for a short) |
| `weighted_average_price` | `existing_quantity`, `existing_average`, `added_quantity`, `added_price` | `Decimal` (4 dp) | weighted blend; `0.0000` if the total is `<= 0` |

No exceptions, no side effects, no database.

### 5.7 Fees — `FeeCalculator` (`app/trading/fees.py`)

```python
FeeCalculator(*, segment=Segment.INTRADAY, enabled=True, brokerage_percent=Decimal("0.03"),
              brokerage_max_per_order=Decimal("20"), stt_intraday_sell_percent=...,
              stt_delivery_percent=..., exchange_txn_percent=..., sebi_charges_percent=...,
              stamp_duty_intraday_buy_percent=..., stamp_duty_delivery_buy_percent=...,
              gst_percent=Decimal("18"), dp_charges_per_sell=Decimal("0"))
FeeCalculator.from_settings()   # classmethod
FeeCalculator.disabled()        # classmethod — charges nothing
```

| Method | Purpose | Parameters | Returns |
|--------|---------|-----------|---------|
| `calculate` | itemise the charges on one fill | kw-only `side: OrderSide`, `quantity: int`, `price: Decimal` | `ChargeBreakdown` (`.zero()` when disabled, `quantity <= 0` or `price <= 0`) |
| `_percent_of` (static) | helper | `base`, `percent` | `Decimal` |
| `_brokerage` | % of turnover, capped | `turnover` | `Decimal` |
| `_stt` | intraday sell-only / delivery both | `turnover`, kw `is_buy` | `Decimal`, **rounded to whole rupee** |
| `_stamp_duty` | buy leg only | `turnover`, kw `is_buy` | `Decimal`, **whole rupee** |
| `_dp_charges` | delivery sells only | kw `is_buy` | `Decimal` |

Module function `to_rupee(value)` → nearest whole rupee. GST is charged on
`brokerage + exchange + sebi` only — **not** on STT or stamp duty.
`ChargeBreakdown` (frozen): the seven charge fields plus the `total` property.
`Segment` StrEnum: `INTRADAY`, `DELIVERY`.

No exceptions, no side effects, no database.

### 5.8 Slippage — `SlippageModel` (`app/trading/slippage.py`)

```python
SlippageModel(*, slippage_type=SlippageType.FIXED_BPS,
              basis_points=Decimal("2"), percent=Decimal("0"))
SlippageModel.from_settings() / SlippageModel.disabled()
```

| Member | Purpose | Parameters | Returns |
|--------|---------|-----------|---------|
| `is_enabled` (property) | | — | `bool` |
| `rate()` | adverse movement as a fraction of price | — | `Decimal` (`bps/10000`, `percent/100`, or `0`) |
| `apply()` | move the price **against** the trader | kw-only `base_price`, `direction: int`, `quantity: int` | `SlippageResult(base_price, slipped_price, price_impact, cost)` |

`SlippageType`: `NONE`, `FIXED_BPS`, `PERCENT`. Always adverse — `apply()`
multiplies by `direction`. No exceptions, no DB.

### 5.9 Spread — `SpreadModel` (`app/trading/spread.py`)

```python
SpreadModel(*, basis_points=Decimal("2"))   # FULL spread; half applied each side
SpreadModel.from_settings() / SpreadModel.disabled()
```

| Member | Purpose | Parameters | Returns |
|--------|---------|-----------|---------|
| `is_enabled` (property) | | — | `bool` |
| `quote()` | build bid/ask around a mid | `mid_price: Decimal` | `BidAsk(mid, bid, ask)` |
| `apply()` | cross the spread and report the cost | kw-only `mid_price`, `direction: int`, `quantity: int` | `SpreadResult(quote, fill_price, price_impact, cost)` |

`BidAsk` property `spread` (= `ask - bid`) and method `price_for(direction)` —
buys lift the ask, sells hit the bid. Also used by `PriceStreamService.build_tick`
to model bid/ask when the provider has no depth.

### 5.10 Risk — **Not implemented**

There is **no `RiskManager` class, module or function** in this repository.
What exists instead:

| Control | Location |
|---------|----------|
| Quantity bounds | `TradingEngine._validate_request` + `MAX_ORDER_QUANTITY` + `ck_orders_quantity_within_bounds` |
| Cash sufficiency | `PortfolioManager.assert_affordable` |
| Direction sanity | `TradingEngine._validate_against_position` |
| Non-negative cash | `ck_wallet_cash_balance_non_negative` |
| Connection cap | `ConnectionManager.max_connections` |

**Not implemented:** margin, leverage, exposure caps, position limits,
stop-loss, daily-loss limits, circuit breakers. `app/trading/portfolio.py`
documents the gap: short proceeds are credited as spendable cash and nothing is
reserved against an open short.

### 5.11 Backtesting — `app/backtest/`

`BacktestEngine` (`engine.py`):
```python
BacktestEngine(*, config=None, spread=None, slippage=None, fees=None, indicator_service=None)
```
Constructs `ExecutionEngine(session=None, ...)` — safe because only
`price_fill()` is ever called on it.

| Method | Purpose | Parameters | Returns | Raises | Side effects |
|--------|---------|-----------|---------|--------|--------------|
| `run` | run a strategy over candles | kw-only `strategy: Strategy`, `candles: list[Candle]`, `symbol="RELIANCE"`, `exchange="NSE"`, `interval="1d"` | `BacktestResult` | — | **none — writes nothing to the database** |
| `_precompute` | indicators once over the whole series, aligned by timestamp | `strategy`, `candles`, `interval` | `dict[str, list[Decimal\|None]]` | — | none |
| `_context` | build the per-bar `StrategyContext` | `index`, `candles`, `indicators`, `portfolio` | `StrategyContext` | — | none |
| `_reference_price` | next open, or current close under `CURRENT_CLOSE` | `index`, `candles` | `Decimal` | — | none |
| `_order_quantity` | shares needed to reach the target | `signal`, `portfolio`, `price` | `int` | — | none |
| `_execute` | size and settle a decision | kw-only `decision`, `index`, `candles`, `portfolio` | `None` | — | mutates the portfolio |
| `_close_out` | flatten on the last bar; re-record the final equity point | `candles`, `portfolio` | `None` | — | mutates the portfolio |
| `_settle` | price and apply a fill; swallow `InsufficientCash` | kw-only `side`, `quantity`, `reference_price`, `index`, `candle`, `portfolio`, `reason` | `None` | — | mutates the portfolio; `rejected_orders += 1` on refusal |

`PositionSizer.target_size(*, equity, price) -> int` —
`FIXED_QUANTITY` → `config.fixed_quantity`; `FIXED_VALUE` →
`int(fixed_value / price)`; `PERCENT_OF_EQUITY` →
`int(equity * equity_percent / 100 / price)`; `0` if `price <= 0`.

`BacktestPortfolio` (`portfolio.py`):

| Member | Purpose | Parameters | Returns | Raises |
|--------|---------|-----------|---------|--------|
| `net_realized_pnl` (property) | | — | `Decimal` | — |
| `unrealized_pnl` / `position_value` / `equity` | valuation | `mark_price` | `Decimal` | — |
| `cash_delta` (static) | **the live cash rule** | `fill: Fill` | `Decimal` | — |
| `can_afford` | | `fill: Fill` | `bool` | — |
| `apply` | settle a fill via `apply_fill()` | `fill`, kw-only `index`, `timestamp`, `reason=""` | `BacktestTrade` | `InsufficientCash` — checked **before** any mutation |
| `record_equity` | mark to market, append a curve point | kw-only `index`, `timestamp`, `mark_price` | `EquityPoint` | — |

`results.py`: `max_drawdown(curve) -> DrawdownResult`;
`summarise(*, strategy, symbol, exchange, interval, initial_capital, trades,
curve, rejected_orders, final_position) -> BacktestResult`. Win/loss rules are
identical to `PerformanceAnalyzer`.

### 5.12 Strategies — `app/strategies/`

`Strategy` (ABC, `base.py`) — class attributes `name`, `display_name`,
`description`, `params: tuple[StrategyParam, ...]`.

| Method | Purpose | Parameters | Returns | Notes |
|--------|---------|-----------|---------|-------|
| `required_indicators()` | **abstract** — indicators to precompute | — | `list[IndicatorSpec]` | |
| `on_bar(context)` | **abstract** — decide | `StrategyContext` | `Decision` | |
| `warmup_bars()` | bars to skip | — | `int` (default `0`) | |
| `reset()` | clear per-run state | — | `None` | called once before each run |
| `describe()` | metadata for the API | — | `dict` | |

`StrategyContext` (frozen) — `index`, `candle`, `candles` (history **up to and
including** this bar), `position`, `average_price`, `cash`, `equity`,
`_indicators`. Properties `close`, `is_long`, `is_short`, `is_flat`.
`indicator(key, offset=0) -> Decimal|None` — **raises `ValueError` on a negative
offset** ("would read future bars, which is lookahead bias").
`has_indicator(key, offset=0) -> bool`.

`Signal` StrEnum: `BUY`, `SELL`, `SHORT`, `COVER`, `HOLD`; `.order_side` maps to
`OrderSide` (`None` for HOLD); `.is_actionable`.
`Decision(signal, quantity=None, reason="")` + `Decision.hold(reason="")`.

`MovingAverageCrossover` (`ma_crossover.py`, `name="ma_crossover"`) —
`__init__(*, fast=10, slow=30, allow_short=True)`, **raises `ValueError` if
`fast >= slow`**; `warmup_bars()` returns `slow`.

Registry (`registry.py`): `available_strategies() -> list[str]`,
`describe_all() -> list[dict]`,
`create_strategy(name, params=None) -> Strategy` — raises
`UnknownStrategyError` / `InvalidStrategyParamsError`. `_coerce()` converts
whole JSON numbers to `int` and treats parameters named `allow_*`/`use_*` as
booleans.

> **Strategies are backtest-only.** Nothing calls `on_bar` outside
> `BacktestEngine.run`, and no code path turns a `Signal` into
> `TradingEngine.place_order`. A live strategy runner is **Not implemented**.

### 5.13 Analytics — `app/analytics/`

| Class / function | File | Method | Returns | DB |
|------------------|------|--------|---------|----|
| `SnapshotService` | `snapshots.py` | `capture(*, mark_price=None, source=MANUAL, skip_if_unchanged=False, commit=True)` → `PortfolioSnapshot \| None`; raises `WalletNotFoundError` | INSERT `portfolio_snapshots`; SELECT `wallet`, `positions`; commits unless `commit=False` |
| | | `latest()` → `PortfolioSnapshot \| None` | SELECT |
| | | `history(*, start=None, end=None, limit=500, source=None)` → `list[...]` oldest-first | SELECT |
| | | `count()` → `int` | SELECT |
| | | `purge()` → `int` — **not wired to any endpoint** | DELETE + commit |
| `PerformanceAnalyzer` | `performance.py` | `summary()` → `PerformanceSummary` | 5 SELECTs over `trades` and `orders` |
| `capture_periodic_snapshot` | `scheduler.py` | async, never raises | own `SessionLocal()`; SELECT `positions`; may fetch a quote |
| `start_snapshot_scheduler` / `stop_snapshot_scheduler` | `scheduler.py` | APScheduler job `portfolio-snapshot` | — |

### 5.14 Real-time — `app/realtime/`

`PriceStreamService` (`price_stream.py`): `mode` (property → `StreamMode`),
`is_running`, `status() -> dict`, `async start()`, `async stop()`,
`build_tick(quote) -> dict`, plus internals `_run_push_loop`, `_poll_once`,
`_broadcast_quote`, `_handle_failure`. Module singletons
`get_connection_manager()`, `get_price_stream()`, `async shutdown_price_stream()`.

`ConnectionManager` (`connection_manager.py`): `connection_count`,
`has_listeners`, `async connect(ws)` (raises `ConnectionLimitReached`),
`async disconnect(ws)`, `async close(ws, code=1000)`,
`async disconnect_all(code=1001)`, `async send_to(ws, message) -> bool`,
`async broadcast(message) -> int`.

### 5.15 Market data — `app/market_data/`

`MarketDataProvider` (ABC, `base.py`): `capabilities` (abstract property),
`async get_current_quote(symbol, exchange)` (abstract),
`async get_historical_candles(symbol, exchange, interval, start=None, end=None, limit=None)`
(abstract), `subscribe_live_data(symbol, exchange)` — **default raises
`LiveDataNotSupportedError`**, `async aclose()` (default no-op).

`YahooFinanceProvider` — overrides everything except `subscribe_live_data`
(deliberately). Internals: `_vendor_symbol`, `_fetch_chart`, `_session_open`,
`_parse_candles`, `_to_money`.

`MockMarketDataProvider` — **also overrides `subscribe_live_data`** (async
generator). `from_settings()` classmethod; internals `_advance`, `_quote_from`.

Registry (`registry.py`): `available_providers() -> list[str]`,
`create_provider(name=None)` (raises `ValueError` on an unknown name),
`get_provider()` (process-wide singleton), `async close_provider()`.

`RelianceMarketDataService` (`app/services/market_data_service.py`):
`symbol`, `exchange`, `capabilities` (properties);
`async get_current_quote(symbol=None)`;
`async get_historical_candles(interval=ONE_DAY, start=None, end=None, limit=None, symbol=None)`;
`subscribe_live_data(symbol=None)`. Constant `MAX_CANDLES = 5000`.

### 5.16 Indicators — `app/indicators/`

`IndicatorService.calculate(*, candles, specs, interval) -> list[IndicatorResult]`
— never raises for a single bad indicator; it logs and returns an empty result.
`IndicatorService.catalogue() -> list[dict]` (static).
Module singleton `indicator_service`.
`candles_to_frame(candles, interval) -> pd.DataFrame` — Decimal → `float64`
(the only sanctioned float conversion in the backend).
`definitions.parse_spec(raw) -> IndicatorSpec` and
`parse_specs(raw) -> list[IndicatorSpec]` — raise `InvalidIndicatorError`.
`library.CALCULATORS` dispatch table; `library.warmup_for(spec) -> int`;
`library.to_decimal(value) -> Decimal | None`.
---

## 6. Frontend API Client

Every HTTP call goes through `frontend/src/api/client.ts`. **No component calls
`fetch` directly.**

```ts
BASE_URL  = import.meta.env.VITE_API_BASE_URL  ?? 'http://localhost:8000'
V1_PREFIX = import.meta.env.VITE_API_V1_PREFIX ?? '/api/v1'

apiUrl(path)                       -> `${BASE_URL}${V1_PREFIX}${path}`
wsUrl(path)                        -> VITE_WS_BASE_URL, else BASE_URL http->ws
apiGet<T>(path, signal?)           -> Promise<T>
apiPost<T>(path, body?, signal?)   -> Promise<T>
class ApiError extends Error { status?, code?, get isNotFound() }
```

`toApiError()` reads `body.error.message` → string `body.detail` → generic
`HTTP <status>`. A network failure becomes
`"Cannot reach the API at {BASE_URL}. Is the backend running?"`.
`AbortError` is re-thrown untouched.

### 6.1 Complete call map

| # | React component | Hook | API client function (`src/api/`) | HTTP endpoint | Backend service | Response type | State update |
|---|-----------------|------|----------------------------------|---------------|-----------------|---------------|--------------|
| 1 | `TradingPanel` | — (direct) | `trading.placeOrder(payload)` | `POST /trading/orders` | `TradingEngine.place_order` | `OrderResult` | `setLastFill(result)` → fill receipt; `onFilled(result)` → `Terminal.handleFilled` → `useAccount.refresh()` |
| 2 | `Terminal` | `useAccount` | `wallet.fetchWallet()` | `GET /wallet` | `WalletService.get_wallet` | `Wallet` | `setWallet` + `setNeedsWallet(result === null)` — a 404 is caught and mapped to `null` |
| 3 | `Terminal` | `useAccount` | `trading.fetchPosition()` | `GET /trading/position` | `TradingEngine.get_position` | `Position` | `setPosition` |
| 4 | `Terminal` | `useAccount` | `trading.fetchPortfolio(mark)` | `GET /trading/portfolio?mark_price=…` | `TradingEngine.get_portfolio` | `Portfolio` | `setPortfolio`; 404 → `null` |
| 5 | `Terminal` | `useAccount` | `trading.fetchOrders(25)` | `GET /trading/orders?limit=25` | `TradingEngine.list_orders` | `Order[]` | `setOrders` |
| 6 | `Terminal` | `useAccount` | `trading.fetchTrades(25)` | `GET /trading/trades?limit=25` | `TradingEngine.list_trades` | `Trade[]` | `setTrades` |
| 7 | `WalletPanel` (via `Terminal`) | `useAccount.createWallet` | `wallet.initializeWallet()` | `POST /wallet/initialize` | `WalletService.initialize_wallet` | `Wallet` | then `refresh()` (all of 2–6) |
| 8 | `PriceChart` | — (direct effect) | `marketData.fetchCandles(interval, limit, signal)` | `GET /market-data/candles?interval=…&limit=…` | `RelianceMarketDataService.get_historical_candles` | `CandleSeries` | `candleSeries.setData()`, `volumeSeries.setData()`, `lastBarRef.current`, `setBarCount`, `fitContent()` |
| 9 | `PriceChart` | `useIndicators` | `indicators.fetchIndicators(interval, limit, specs, signal)` | `GET /indicators?indicators=…&interval=…&limit=…` | `indicator_service.calculate` | `IndicatorSet` | `setIndicators(result.indicators)` → split into `overlays` / `oscillators` |
| 10 | `TradeHistoryPage` | — | `trading.fetchTrades(200)` | `GET /trading/trades?limit=200` | `TradingEngine.list_trades` | `Trade[]` | `setTrades` (once on mount + manual Refresh) |
| 11 | `OrderHistoryPage` | — | `trading.fetchOrders(200)` | `GET /trading/orders?limit=200` | `TradingEngine.list_orders` | `Order[]` | `setOrders`; filtering is **client-side** (`ALL/FILLED/REJECTED`) |
| 12 | `PortfolioHistoryPage` | — | `portfolio.fetchSnapshots(1000)` | `GET /portfolio/snapshots?limit=1000` | `SnapshotService.history` | `SnapshotSeries` | `setSnapshots(series.snapshots)` → `EquityCurve` + table |
| 13 | `PortfolioHistoryPage` | — | `portfolio.captureSnapshot(markPrice)` | `POST /portfolio/snapshots?mark_price=…` | `SnapshotService.capture` | `PortfolioSnapshot` | then `load()` (call 12 again) |
| 14 | `PerformancePage` | — | `portfolio.fetchPerformance()` | `GET /portfolio/performance` | `PerformanceAnalyzer.summary` | `Performance` | `setSummary` |
| 15 | `HealthCard` **(dead code)** | `useHealth` | `health.fetchHealth(signal)` | `GET /health` | `HealthService.full_health` | `HealthResponse` | `setData` / `setState` |

**Endpoints with no frontend caller:** `GET /health/ping`,
`GET /market-data/provider`, `GET /market-data/quote`,
`GET /indicators/catalogue`, `GET /trading/execution-cost`,
`GET /stream/status`, `POST /wallet/reset`, `GET /strategies`,
`POST /strategies/backtest`, `GET /` — and `GET /health` is only reachable from
the dead `HealthCard`. **There is no backtesting UI.**

### 6.2 Trace: order submission end to end

```
TradingPanel.submit('BUY')
  guard: blocked = disabled || noPrice || invalidQuantity || pending !== null
  setPending('BUY'); setError(null)
        |
        v
api/trading.ts  placeOrder({side:'BUY', quantity, reference_price: markPrice})
        |
        v
api/client.ts   apiPost('/trading/orders', body)
        fetch('http://localhost:8000/api/v1/trading/orders', {method:'POST', ...})
        |
        v
backend  app/api/v1/endpoints/trading.py:place_order
        PlaceOrderRequest validation -> 422 on failure
        TradingEngine(session).place_order(...)
            lock wallet + position FOR UPDATE
            OrderManager.create -> ExecutionEngine.execute
            _validate_against_position -> PortfolioManager.assert_affordable
            apply_fill -> PositionManager.apply -> PortfolioManager.apply_cash
            ExecutionEngine.record_trade -> OrderManager.mark_filled
            SnapshotService.capture(commit=False) -> COMMIT
        OrderResultResponse (201)
        |
        v
TradingPanel  setLastFill(result)   -> renders quantity @ price, charges, net P&L
              onFilled(result)
        |
        v
Terminal.handleFilled -> useAccount.refresh()
        Promise.all([fetchWallet, fetchPosition, fetchPortfolio(mark),
                     fetchOrders(25), fetchTrades(25)])
        setWallet / setNeedsWallet / setPosition / setPortfolio / setOrders / setTrades
        |
        v
Re-render: WalletPanel, PositionPanel, OrdersPanel, TradeHistory — all from ONE
consistent set of reads. There is no optimistic update and no partial patching.
```

On failure: `setError(err.message)` → "Order rejected" alert;
`setLastFill(null)`. `finally` → `setPending(null)`.

### 6.3 Frontend state layer

**No Redux, no Zustand, no Context, no React Query.** All state is local React
state inside hooks (`frontend/src/hooks/`).

| Hook | Exposes | Notes |
|------|---------|-------|
| `useAccount(markPrice)` | `wallet, position, portfolio, orders, trades, loading, error, needsWallet, refresh, createWallet` | `HISTORY_LIMIT = 25`; `REVALUE_THROTTLE_MS = 3000`; 404 on wallet/portfolio → `needsWallet`, not an error; the throttled revaluation effect **swallows failures** and returns without rescheduling if inside the window |
| `useIndicators(interval, limit)` | `enabled, toggle, clear, indicators, loading, error` | selection persisted at `localStorage['vtrader.indicators']`; unknown ids filtered on load against `INDICATOR_PRESETS`; aborts in-flight requests |
| `useLivePrice()` | see §7 | |
| `useHashRoute()` | `route, navigate` | `hashchange` listener; `NAV` array |
| `useHealth()` | `state, data, error, refresh` | **unused** |

Money arrives as **strings** and is converted to `number` only at render time by
`frontend/src/utils/format.ts` (`formatRupees`, `formatMoney`, `formatQuantity`,
`formatPercent`, `formatTime`, `formatDateTime`, `signClass`, `toNumber`).
**No arithmetic is done on money in JavaScript** — unrealized P&L is recomputed
server-side in `Decimal` on every throttled `GET /trading/portfolio`.

---

## 7. Frontend WebSocket Client

**File:** `frontend/src/hooks/useLivePrice.ts` — the only WebSocket code in the
frontend. Types in `frontend/src/types/stream.ts`.

### 7.1 Connection

```ts
new WebSocket(wsUrl('/stream/prices'))   // ws://localhost:8000/api/v1/stream/prices
```

`connect()` first drops any previous socket (`onclose = null; close()`) so a
reconnect can never leave two live sockets feeding the same state. A `WebSocket`
constructor throw sets `connection = 'offline'`.

Refs used: `socketRef`, `retryTimerRef`, `pingTimerRef`, `backoffRef`,
`lastTickAtRef`, `activeRef` (guards against a reconnect scheduled after unmount).

### 7.2 Message handlers

```ts
socket.onopen = () => {
  backoffRef.current = INITIAL_BACKOFF_MS; setAttempt(0);
  setConnection('live'); setError(null);
  pingTimerRef = setInterval(() => socket.send('{"type":"ping"}'), PING_INTERVAL_MS);
}

socket.onmessage = (event) => {
  try { message = JSON.parse(event.data) } catch { return }   // ignore non-JSON
  switch (message.type) {
    case 'tick':   setTick(data); setError(null);
                   lastTickAtRef.current = Date.now(); setIsStale(false); break;
    case 'status': setStatus(data); break;
    case 'error':  setError(data);  break;
    case 'pong':   break;                                     // no state change
  }
}

socket.onerror = () => {}   // onclose always follows and carries the useful info

socket.onclose = () => { clearTimers(); socketRef.current = null;
                         setConnection('reconnecting'); /* backoff, see 7.4 */ }
```

### 7.3 State updates

| State | Type | Set by | Consumed by |
|-------|------|--------|-------------|
| `tick` | `PriceTick \| null` | `tick` frames | `Terminal` → `markPrice`; `TerminalHeader`; `PriceChart`; `PositionPanel`; `TradingPanel`; `useAccount` revaluation |
| `status` | `StreamStatus \| null` | `status` frame | `TerminalHeader` (provider + mode chip) |
| `error` | `StreamError \| null` | `error` frames; cleared on any tick and on open | exposed but **not currently rendered** by `Terminal` |
| `connection` | `'connecting'\|'live'\|'reconnecting'\|'offline'` | lifecycle | `TerminalHeader` badge |
| `attempt` | `number` | incremented in `onclose`, reset on open | `TerminalHeader` `(n)` suffix |
| `isStale` | `boolean` | a 5 s interval comparing `lastTickAtRef` to `STALE_AFTER_MS` | `TerminalHeader` `STALE` badge |

Downstream effect in `PriceChart` — the live tick mutates the forming bar in
place, no refetch:

```ts
useEffect(() => {
  const updated = { time: bar.time, open: bar.open,
                    high: Math.max(bar.high, price),
                    low:  Math.min(bar.low,  price),
                    close: price };
  lastBarRef.current = updated;
  series.update(updated);
}, [tick]);
```

### 7.4 Reconnection

```ts
const INITIAL_BACKOFF_MS = 1_000;
const MAX_BACKOFF_MS     = 15_000;
const PING_INTERVAL_MS   = 25_000;
const STALE_AFTER_MS     = 30_000;

// in onclose:
const jitter = Math.random() * 0.3 + 0.85;          // 0.85 – 1.15
const delay  = Math.round(backoffRef.current * jitter);
backoffRef.current = Math.min(backoffRef.current * 2, MAX_BACKOFF_MS);
setAttempt(n => n + 1);
retryTimerRef.current = setTimeout(connect, delay);
```

`reconnect()` — bound to the connection badge in `TerminalHeader` — clears
timers, resets the backoff to 1 s, sets `connection = 'connecting'` and dials
immediately.

Unmount: `activeRef.current = false`, timers cleared, `onclose` nulled, socket
closed — so no reconnect is scheduled after teardown.

> **Two sockets exist when the portfolio page is open**: `PortfolioHistoryPage`
> calls `useLivePrice()` independently of `Terminal`. Also, React `StrictMode`
> (set in `main.tsx`) double-invokes effects in development, so a socket is
> opened and closed twice on mount.

---

## 8. Environment Variables

Defaults are declared in `backend/app/core/config.py` (`Settings`). Templates:
`.env.example`, `backend/.env.example`, `frontend/.env.example`.
`.env` and `*.env` are gitignored (`!.env.example` re-included).
**No real secret is committed in this repository, and none is quoted here.**

> `app/core/config.py` is the **only** module that reads the environment.
> `settings = get_settings()` runs at import time and `get_settings` is
> `@lru_cache`d — anything overriding a setting must do so **before** the first
> `app.*` import (this is exactly what `tests/conftest.py` does).

### 8.1 Application

| Variable | Purpose | Required? | Example | Used by |
|----------|---------|-----------|---------|---------|
| `APP_NAME` | Service name in the banner, docs title, health | no (`Virtual Trading Platform`) | `Virtual Trading Platform` | `main.py`, `HealthService` |
| `APP_VERSION` | Version string | no (`0.1.0`) | `0.1.0` | `main.py`, `HealthService` |
| `ENVIRONMENT` | `development`\|`staging`\|`production` | no (`development`) | `development` | `HealthService`, startup log |
| `DEBUG` | FastAPI debug + log level | no (`true`) | `true` | `main.py`, `core/logging.py` |
| `API_V1_PREFIX` | Router mount prefix | no (`/api/v1`) | `/api/v1` | `main.py`, root banner |
| `BACKEND_HOST` | Declared only | no (`0.0.0.0`) | `0.0.0.0` | **nothing reads it** — uvicorn takes it on the CLI |
| `BACKEND_PORT` | Declared only | no (`8000`) | `8000` | **nothing reads it** |

### 8.2 Database

| Variable | Purpose | Required? | Example | Used by |
|----------|---------|-----------|---------|---------|
| `POSTGRES_USER` | DB user | no (`vtrader`) | `vtrader` | `Settings.DATABASE_URL`, compose, `conftest.py` |
| `POSTGRES_PASSWORD` | DB password | no (dev placeholder) | *(set your own; never commit)* | `Settings.DATABASE_URL`, compose |
| `POSTGRES_DB` | DB name | no (`virtual_trading`) | `virtual_trading` | `DATABASE_URL`, compose |
| `POSTGRES_HOST` | DB host | no (`localhost`) | `postgres` inside Docker | `DATABASE_URL` |
| `POSTGRES_PORT` | DB port | no (`5432`) | `5432` | `DATABASE_URL` |
| `DB_ECHO` | Log SQL | no (`false`) | `false` | `db/session.py`, `core/logging.py` |
| `DB_POOL_SIZE` | Pool size | no (`5`) | `5` | `db/session.py` |
| `DB_MAX_OVERFLOW` | Pool overflow | no (`10`) | `10` | `db/session.py` |
| `DB_POOL_PRE_PING` | Validate pooled conns | no (`true`) | `true` | `db/session.py` |
| `DB_USE_NULL_POOL` | Disable pooling — **required `true` under pytest** | no (`false`) | `true` | `db/session.py`, set by `tests/conftest.py` |
| `TEST_POSTGRES_DB` | Test database name | no (`virtual_trading_test`) | `virtual_trading_test` | `tests/conftest.py` only |

### 8.3 CORS and domain

| Variable | Purpose | Required? | Example | Used by |
|----------|---------|-----------|---------|---------|
| `CORS_ORIGINS` | Allowed browser origins; comma-separated **or** JSON array | no (`["http://localhost:5173"]`) | `http://localhost:5173,http://127.0.0.1:5173` | `main.py` `CORSMiddleware` |
| `TRADING_SYMBOL` | The one tradable instrument | no (`RELIANCE`) | `RELIANCE` | `TradingEngine`, `RelianceMarketDataService`, `SnapshotService`, `PriceStreamService`, scheduler |
| `TRADING_EXCHANGE` | Exchange code | no (`NSE`) | `NSE` | same as above; `_EXCHANGE_SUFFIX` lookup |

### 8.4 Market data

| Variable | Purpose | Required? | Example | Used by |
|----------|---------|-----------|---------|---------|
| `MARKET_DATA_PROVIDER` | Which provider to load: `yahoo` \| `mock` | no (`yahoo`) | `yahoo` | `market_data/registry.py` |
| `MARKET_DATA_TIMEOUT_SECONDS` | httpx timeout | no (`15.0`) | `15` | `registry._build_yahoo` → `YahooFinanceProvider` |
| `MARKET_DATA_API_KEY` | Provider credential (`SecretStr`) | no (`None`) | *(unset)* | **declared but never read** — for a future provider |
| `MARKET_DATA_API_SECRET` | Provider credential (`SecretStr`) | no (`None`) | *(unset)* | **declared but never read** |

### 8.5 Execution realism

| Variable | Purpose | Required? | Example | Used by |
|----------|---------|-----------|---------|---------|
| `EXECUTION_SEGMENT` | Charge schedule: `INTRADAY` \| `DELIVERY` | no (`INTRADAY`) | `INTRADAY` | `FeeCalculator.from_settings` |
| `SPREAD_BPS` | **Full** spread in bps; half each side | no (`2`) | `2` | `SpreadModel.from_settings` (engine **and** `build_tick`) |
| `SLIPPAGE_MODEL` | `NONE` \| `FIXED_BPS` \| `PERCENT` | no (`FIXED_BPS`) | `FIXED_BPS` | `SlippageModel.from_settings` |
| `SLIPPAGE_BPS` | Adverse bps | no (`2`) | `2` | `SlippageModel` |
| `SLIPPAGE_PERCENT` | Adverse % | no (`0`) | `0` | `SlippageModel` |

### 8.6 Charges — all are **percentages of turnover** (`0.03` = 0.03%)

| Variable | Purpose | Required? | Example | Used by |
|----------|---------|-----------|---------|---------|
| `CHARGES_ENABLED` | Master switch | no (`true`) | `true` | `FeeCalculator` |
| `BROKERAGE_PERCENT` | Brokerage rate | no (`0.03`) | `0.03` | `FeeCalculator._brokerage` |
| `BROKERAGE_MAX_PER_ORDER` | Per-order cap (nullable) | no (`20`) | `20` | `FeeCalculator._brokerage` |
| `STT_INTRADAY_SELL_PERCENT` | STT, intraday sell leg | no (`0.025`) | `0.025` | `FeeCalculator._stt` |
| `STT_DELIVERY_PERCENT` | STT, delivery both legs | no (`0.1`) | `0.1` | `FeeCalculator._stt` |
| `EXCHANGE_TXN_PERCENT` | Exchange transaction charge | no (`0.00297`) | `0.00297` | `FeeCalculator.calculate` |
| `SEBI_CHARGES_PERCENT` | SEBI turnover fee | no (`0.0001`) | `0.0001` | `FeeCalculator.calculate` |
| `STAMP_DUTY_INTRADAY_BUY_PERCENT` | Stamp duty, intraday buy | no (`0.003`) | `0.003` | `FeeCalculator._stamp_duty` |
| `STAMP_DUTY_DELIVERY_BUY_PERCENT` | Stamp duty, delivery buy | no (`0.015`) | `0.015` | `FeeCalculator._stamp_duty` |
| `GST_PERCENT` | GST on brokerage+exchange+SEBI | no (`18`) | `18` | `FeeCalculator.calculate` |
| `DP_CHARGES_PER_SELL` | Flat DP fee, delivery sells | no (`0`) | `0` | `FeeCalculator._dp_charges` |

### 8.7 Wallet, streaming, snapshots, mock

| Variable | Purpose | Required? | Example | Used by |
|----------|---------|-----------|---------|---------|
| `WALLET_INITIAL_BALANCE` | Opening capital | no (`1000000.00`) | `1000000.00` | `WalletService.initialize_wallet` |
| `WALLET_CURRENCY` | Currency code | no (`INR`) | `INR` | `WalletRepository.create` |
| `STREAM_POLL_INTERVAL_SECONDS` | Poll cadence in POLL mode | no (`5.0`) | `5` | `PriceStreamService` job |
| `STREAM_MAX_CONNECTIONS` | WebSocket pool cap | no (`50`) | `50` | `ConnectionManager` |
| `STREAM_MODEL_BID_ASK` | Derive bid/ask when the feed has no depth | no (`true`) | `true` | `PriceStreamService.build_tick` |
| `SNAPSHOT_ENABLED` | Enable the periodic job | no (`true`) | `true` | `analytics/scheduler.py` |
| `SNAPSHOT_INTERVAL_SECONDS` | Job cadence; also the tick-freshness window | no (`300.0`) | `300` | `scheduler.py`, `_current_mark_price` |
| `SNAPSHOT_ON_TRADE` | Snapshot inside each order's transaction | no (`true`) | `true` | `TradingEngine.place_order` |
| `SNAPSHOT_SKIP_UNCHANGED` | Suppress identical periodic rows | no (`true`) | `true` | `capture_periodic_snapshot` |
| `MOCK_BASE_PRICE` | Random-walk anchor | no (`1400`) | `1400` | `MockMarketDataProvider` |
| `MOCK_VOLATILITY_BPS` | Step size | no (`15`) | `15` | `MockMarketDataProvider` |
| `MOCK_SPREAD_BPS` | Synthesised spread | no (`4`) | `4` | `MockMarketDataProvider` |
| `MOCK_TICK_INTERVAL_SECONDS` | Push cadence | no (`2.0`) | `2` | `MockMarketDataProvider.subscribe_live_data` |
| `MOCK_SEED` | Reproducible walk | no (`None`) | `42` | `MockMarketDataProvider` |

### 8.8 Frontend (build-time — baked into the bundle, never secret)

| Variable | Purpose | Required? | Example | Used by |
|----------|---------|-----------|---------|---------|
| `VITE_API_BASE_URL` | Backend origin | no (`http://localhost:8000`) | `http://localhost:8000` | `api/client.ts` |
| `VITE_API_V1_PREFIX` | API prefix | no (`/api/v1`) | `/api/v1` | `api/client.ts` |
| `VITE_WS_BASE_URL` | WebSocket origin override | no (blank → derived) | *(blank)* | `api/client.ts:wsUrl` |
| `CHOKIDAR_USEPOLLING` | Poll for file changes under Docker bind mounts | no | `true` | `vite.config.ts` |

### 8.9 docker-compose only

| Variable | Purpose | Required? | Example | Used by |
|----------|---------|-----------|---------|---------|
| `POSTGRES_HOST_PORT` | Host port for Postgres | no (`5432`) | `5432` | `docker-compose.yml` |
| `BACKEND_HOST_PORT` | Host port for the API | no (`8000`) | `8000` | `docker-compose.yml` |
| `FRONTEND_HOST_PORT` | Host port for Vite | no (`5173`) | `5173` | `docker-compose.yml` |

---

## 9. Common Development Tasks

### 9.1 Start everything (Docker — the intended path)

```bash
cp .env.example .env
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env
docker compose up -d --build
docker compose ps                       # all three healthy?
docker compose exec backend alembic upgrade head
curl -X POST http://localhost:8000/api/v1/wallet/initialize
# UI:   http://localhost:5173
# Docs: http://localhost:8000/docs
```

> `docker compose restart backend` does **not** re-read `env_file`. After
> editing `backend/.env`: `docker compose up -d --force-recreate backend`.

### 9.2 Start PostgreSQL only

```bash
docker compose up -d postgres
docker compose exec postgres psql -U vtrader -d virtual_trading -c "select version();"
```

### 9.3 Start the backend on the host

```bash
docker compose up -d postgres            # a real PostgreSQL is required
cd backend
pip install -r requirements-dev.txt
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```
Ensure `POSTGRES_HOST=localhost` in `backend/.env`.

### 9.4 Start the frontend on the host

```bash
cd frontend
npm install
npm run dev            # http://localhost:5173
```

### 9.5 Run migrations

```bash
docker compose exec backend alembic upgrade head        # apply
docker compose exec backend alembic current             # where am I
docker compose exec backend alembic history --verbose   # the chain
docker compose exec backend alembic downgrade -1        # step back
docker compose exec backend alembic revision --autogenerate -m "describe change"
```
Drop `docker compose exec backend` to run from `backend/` on the host.
**Head is `51917e5fa5f1`.**

### 9.6 Create / reset the database

```bash
# Reset the whole database (DESTROYS ALL DATA):
docker compose down -v          # deletes the vtrader_postgres_data volume
docker compose up -d postgres
docker compose exec backend alembic upgrade head
curl -X POST http://localhost:8000/api/v1/wallet/initialize

# Keep data, stop containers:
docker compose down
docker compose up -d

# Reset only the cash balance (leaves positions/orders/trades/snapshots):
curl -X POST http://localhost:8000/api/v1/wallet/reset
```

### 9.7 Run tests

```bash
# Backend (Docker)
docker compose exec backend pytest
docker compose exec backend pytest -v
docker compose exec backend pytest tests/test_trading_engine.py
docker compose exec backend pytest tests/test_backtest.py -k parity

# Backend (host)
docker compose up -d postgres
cd backend && pip install -r requirements-dev.txt && pytest

# Frontend — typecheck only; there are NO frontend tests
docker compose exec frontend npm run typecheck
cd frontend && npm run typecheck

# Manual WebSocket probe
docker compose exec backend python tests/_ws_probe.py \
  ws://localhost:8000/api/v1/stream/prices 3
```

The suite creates and drops `virtual_trading_test` itself; the configured
`POSTGRES_USER` needs `CREATE DATABASE` permission. 13 modules, ~353 tests.

### 9.8 Add a new API endpoint

1. Add a route function to the right module in `app/api/v1/endpoints/`
   (or a new module + one `include_router(...)` line in `app/api/v1/router.py`).
2. Add request/response models to `app/schemas/`.
3. Put the logic in a service or on the engine — **the route must be transport
   only**. Use `DbSession` for a session, `ServiceDep` for market data.
4. Mirror the response type into `frontend/src/types/*.ts` and add a wrapper in
   `frontend/src/api/*.ts`.
5. Add a test using the `client` fixture in `backend/tests/`.
6. Remember: **there is no auth**, so the endpoint is public.

### 9.9 Add a new database model

1. New module in `app/models/`; subclass `Base` (add `TimestampMixin` if wanted).
2. **Export it from `app/models/__init__.py`** — mandatory for autogenerate.
3. `alembic revision --autogenerate -m "..."` then **read the generated file**.
   Native enums must be created/dropped explicitly with `checkfirst`; new NOT
   NULL columns on a populated table need a `server_default`.
4. Extend the `TRUNCATE` list in `tests/conftest.py:clean_tables`.
5. `alembic upgrade head`.

### 9.10 Add a new frontend component

1. Create the file under `frontend/src/components/terminal/` or
   `components/history/` (a history page should wrap its body in `PageShell`).
2. Import types from `@/types/*`, formatters from `@/utils/format`, and never
   call `fetch` directly — go through `@/api/*`.
3. Render it from `Terminal.tsx`, or add a route: extend `Route`, `ROUTES` and
   `NAV` in `hooks/useHashRoute.ts` and add a branch in `App.tsx`.
4. Style in `styles/terminal.css` / `styles/global.css`.
5. `npm run typecheck`.

### 9.11 Add a new strategy

1. New module in `app/strategies/` subclassing `Strategy`.
2. Set `name`, `display_name`, `description`, `params`; implement
   `required_indicators()` and `on_bar()`; override `warmup_bars()` / `reset()`
   as needed. Raise `ValueError` from `__init__` for cross-parameter rules —
   `create_strategy` converts it to `InvalidStrategyParamsError` (400).
3. Add one entry to `_STRATEGIES` in `app/strategies/registry.py`.
4. Name boolean parameters `allow_*` or `use_*` — that is what `_coerce()` keys on.
5. Add tests; it appears in `GET /strategies` automatically.

### 9.12 Add a new indicator

1. `app/indicators/definitions.py` — add an `IndicatorType` member and an
   `IndicatorDef` entry in `CATALOGUE`.
2. `app/indicators/library.py` — write `def x(frame, spec) -> dict[str, np.ndarray]`,
   register it in `CALCULATORS`, extend `warmup_for()`.
3. Multi-line output: add suffix labels to `_SERIES_LABELS` (and
   `_HISTOGRAM_SUFFIXES` for a histogram) in `app/indicators/service.py`.
4. To expose it in the UI, add a preset to `INDICATOR_PRESETS` in
   `frontend/src/types/indicators.ts` with an `id`, `spec`, `label`, `pane`, `color`.
5. Add tests to `tests/test_indicators.py`.

### 9.13 Change trading rules

| Rule | File · function |
|------|-----------------|
| Which sides may reverse a position | `app/trading/engine.py` · `_validate_against_position` |
| Quantity / price sanity | `app/trading/engine.py` · `_validate_request`; `MAX_ORDER_QUANTITY` in `app/models/trading.py`; `ck_orders_quantity_within_bounds` |
| Single-instrument enforcement | `app/trading/engine.py` · `_resolve_symbol`; `RelianceMarketDataService._require_supported_symbol` |
| Funding | `app/trading/portfolio.py` · `assert_affordable` |
| Position arithmetic | `app/trading/position_manager.py` · `apply_fill` |

After any change: `pytest tests/test_trading_engine.py tests/test_position_accounting.py tests/test_backtest.py`.

### 9.14 Change brokerage

* **Rate only:** edit `BROKERAGE_PERCENT` / `BROKERAGE_MAX_PER_ORDER` in
  `backend/.env`, then `docker compose up -d --force-recreate backend`.
* **Shape (slab, per-share, flat):** `app/trading/fees.py` ·
  `FeeCalculator._brokerage` + the matching `__init__` params + `from_settings()`.
* GST follows automatically (`calculate` charges GST on brokerage+exchange+SEBI).
* Tests: `tests/test_execution_costs.py`, `tests/test_realistic_execution.py`.
* **Affects new fills only** — historical `trades` rows keep their stored charges.

### 9.15 Change slippage

* **Rate/model:** `SLIPPAGE_MODEL`, `SLIPPAGE_BPS`, `SLIPPAGE_PERCENT` in `backend/.env`.
* **New model:** `app/trading/slippage.py` — add a `SlippageType` member,
  extend `rate()` and `apply()` and `from_settings()`. `apply()` already
  receives `quantity`, so a size-dependent model needs no signature change.
* **Must stay adverse.** `apply()` multiplies by `direction`; a signed rate would
  silently make fills better.
* Tests: `tests/test_execution_costs.py`, `tests/test_realistic_execution.py`.

### 9.16 Change the market-data provider

* **Switch existing:** `MARKET_DATA_PROVIDER=mock` (or `yahoo`) in `backend/.env`
  → `docker compose up -d --force-recreate backend`.
* **Add a new one:**
  1. New module in `app/market_data/` subclassing `MarketDataProvider`.
  2. Implement `capabilities` (**declare limitations honestly**),
     `get_current_quote`, `get_historical_candles`, `aclose`. Override
     `subscribe_live_data` **only if the provider genuinely pushes**.
  3. Add a factory and one `_PROVIDERS` entry in `app/market_data/registry.py`.
  4. Credentials: `MARKET_DATA_API_KEY` / `_SECRET` already exist as
     `SecretStr` fields in `config.py`.
  5. Test with `httpx.MockTransport` (see `tests/test_market_data_provider.py`).
* `capabilities.supports_live_stream` **decides PUSH vs POLL**;
  `supports_bid_ask=False` makes the stream model bid/ask and label it
  `"modelled"`; `is_mock=True` triggers the startup warning and the `SIMULATED`
  UI badge. `get_provider()` caches one instance — a change needs a restart.

---

## 10. Modification Cookbook — "How do I modify this application?"

### 10.1 Add a new strategy

| | |
|---|---|
| **Create** | `backend/app/strategies/<name>.py` |
| **Interface** | `Strategy` (ABC) in `app/strategies/base.py` |
| **Implement** | `required_indicators() -> list[IndicatorSpec]`, `on_bar(context: StrategyContext) -> Decision` |
| **Optional** | `warmup_bars() -> int`, `reset() -> None` |
| **Declare** | class attrs `name`, `display_name`, `description`, `params: tuple[StrategyParam, ...]` |
| **Register** | one entry in `_STRATEGIES` in `app/strategies/registry.py` |
| **Return** | `Decision(signal=Signal.BUY/SELL/SHORT/COVER, quantity=None, reason="...")` or `Decision.hold(...)` |
| **Do NOT touch** | `app/backtest/engine.py`, `app/api/v1/endpoints/backtest.py`, `app/schemas/backtest.py`, `StrategyContext` |
| **Gotchas** | `_coerce()` treats `allow_*`/`use_*` params as booleans. `context.indicator(key, offset)` **raises on a negative offset**. Strategies are backtest-only — see §5.12. |
| **Tests** | `tests/test_strategies.py`, plus a run through `tests/test_backtest.py` |

### 10.2 Add a new indicator

| | |
|---|---|
| **Modify** | `app/indicators/definitions.py` — `IndicatorType` member + `CATALOGUE` entry (`IndicatorDef` with `ParamDef`s, `Pane`, optional `scale_min/max`) |
| | `app/indicators/library.py` — the calculator function + a `CALCULATORS` entry + `warmup_for()` |
| | `app/indicators/service.py` — only for a multi-line indicator: `_SERIES_LABELS`, `_HISTOGRAM_SUFFIXES` |
| | `frontend/src/types/indicators.ts` — `INDICATOR_PRESETS` to surface it in the UI |
| **Signature** | `def name(frame: pd.DataFrame, spec: IndicatorSpec) -> dict[str, np.ndarray]` |
| **Do NOT touch** | `app/api/v1/endpoints/indicators.py`, `IndicatorService.calculate`, `app/schemas/indicators.py` |
| **Gotchas** | warm-up must come back as `NaN` (dropped by `_to_points`), never back-filled. `frame.attrs["interval"]` carries the interval (VWAP uses it). Cross-parameter rules go in `_validate_relationships`. |
| **Tests** | `tests/test_indicators.py` |

### 10.3 Change order execution

| | |
|---|---|
| **Primary file** | `app/trading/execution.py` — `ExecutionEngine.price_fill` is the pipeline (spread → slippage → fees) and the seam where partial fills / order-book matching would arrive |
| **Cost models** | `app/trading/spread.py`, `app/trading/slippage.py`, `app/trading/fees.py` |
| **Persistence** | `ExecutionEngine.record_trade` + the `Trade` model in `app/models/trading.py` |
| **Orchestration** | `app/trading/engine.py` — `TradingEngine.place_order` (call order + transaction boundary) |
| **Order lifecycle** | `app/trading/order_manager.py` |
| **Do NOT touch** | `apply_fill` (position arithmetic), `PnLCalculator` — execution decides *what price*, not *what it means* |
| **Gotchas** | `price_fill()` must stay **pure** — the backtester calls it with `session=None`. Spread and slippage must remain adverse. |
| **Tests** | `tests/test_execution_costs.py`, `tests/test_realistic_execution.py`, `tests/test_trading_engine.py`, `tests/test_backtest.py` (**parity**) |

### 10.4 Change wallet rules

| | |
|---|---|
| **Cash model** | `app/trading/portfolio.py` — `PortfolioManager.cash_delta`, `assert_affordable`, `apply_cash` |
| **Wallet lifecycle** | `app/services/wallet_service.py` — `initialize_wallet`, `reset_wallet`, `get_wallet` |
| **SQL** | `app/repositories/wallet_repository.py` — `get`, `get_for_update`, `create` |
| **Schema** | `app/models/wallet.py` + a new Alembic revision if columns/constraints change |
| **API** | `app/api/v1/endpoints/wallet.py`, `app/schemas/wallet.py` |
| **Mirror in backtest** | `BacktestPortfolio.cash_delta` / `can_afford` in `app/backtest/portfolio.py` — **change both or parity breaks** |
| **Gotchas** | `POST /wallet/reset` resets cash only; `SnapshotService.purge()` exists but is unwired. Short proceeds are spendable cash — no margin. |
| **Tests** | `tests/test_wallet_api.py`, `tests/test_wallet_persistence.py`, `tests/test_trading_engine.py`, `tests/test_backtest.py` |

### 10.5 Change P&L

| | |
|---|---|
| **Calculator** | `app/trading/pnl.py` — `PnLCalculator.realized_pnl`, `unrealized_pnl`, `position_value`, `weighted_average_price`, `to_money`, `to_average` |
| **Position rules** | `app/trading/position_manager.py` — `apply_fill`, `PositionManager.apply` |
| **Valuation** | `app/trading/portfolio.py` — `PortfolioManager.snapshot` |
| **History** | `app/analytics/snapshots.py` — `SnapshotService.capture` |
| **Aggregates** | `app/analytics/performance.py` — `PerformanceAnalyzer` (SQL over stored columns) |
| **Backtest** | `app/backtest/portfolio.py`, `app/backtest/results.py` — they call the same functions; do not fork them |
| **Do NOT touch** | endpoints or schemas, unless a field's *meaning* changes |
| **Gotchas** | **Historical rows are not recomputed.** `trades.gross_pnl/net_pnl`, `positions.*`, every `portfolio_snapshots` row keeps its old value — the equity curve gets a discontinuity at deploy. |
| **Tests** | `test_position_accounting.py`, `test_trading_engine.py`, `test_realistic_execution.py`, `test_portfolio_history.py`, `test_backtest.py` (**parity**) |

### 10.6 Change an API response

| | |
|---|---|
| **Schema** | `backend/app/schemas/<area>.py` — the response class |
| **Route** | `backend/app/api/v1/endpoints/<area>.py` — `response_model=` and the return statement |
| **Service** | whatever produces the value (`app/services/`, `app/trading/`, `app/analytics/`) |
| **Frontend type** | `frontend/src/types/<area>.ts` — **hand-mirrored, no codegen** |
| **Frontend consumers** | `frontend/src/api/*.ts` and the components reading the field |
| **Gotchas** | Money must stay a `Decimal` server-side (serialises as a JSON string) and a `string` in TS. Renaming a field is a silent runtime break — `tsc` cannot see it. Do both sides in one commit. |
| **Tests** | the matching `tests/test_*_api.py`; `npm run typecheck` |

### 10.7 Change the UI

| Target | File |
|--------|------|
| Page composition, post-fill refresh | `frontend/src/components/terminal/Terminal.tsx` |
| Price banner, badges, reconnect button | `components/terminal/TerminalHeader.tsx` |
| Order entry | `components/terminal/TradingPanel.tsx` — the **only** place `placeOrder` is called |
| Wallet figures | `components/terminal/WalletPanel.tsx` |
| Open position | `components/terminal/PositionPanel.tsx` |
| Order / trade tables | `components/terminal/OrdersPanel.tsx`, `TradeHistory.tsx` |
| History pages | `components/history/*.tsx` (wrap the body in `PageShell`) |
| Navigation / routes | `hooks/useHashRoute.ts` (`Route`, `ROUTES`, `NAV`) + `App.tsx` + `components/NavBar.tsx` |
| Styles | `styles/terminal.css`, `styles/global.css` |
| Formatting | `utils/format.ts` |

**Do NOT** compute money in the browser — ask the server. **Do NOT** call
`fetch` outside `api/client.ts`. There are no frontend tests; `npm run typecheck`
is the only automated check.

### 10.8 Change the chart

| | |
|---|---|
| **Price chart** | `frontend/src/components/terminal/PriceChart.tsx` — chart creation effect (runs **once**), `toCandlestick`/`toVolume`/`toSeconds`, `colorFor`, the overlay-drawing effect, the live-tick effect mutating `lastBarRef`, the time-scale sync effect |
| **Oscillators** | `components/terminal/OscillatorPane.tsx` — one chart per `pane === 'separate'` indicator; `SERIES_COLORS`, `toLineData`, `toHistogramData` |
| **Equity curve** | `components/history/EquityCurve.tsx` — collapses same-second snapshots (Lightweight Charts needs strictly ascending times) |
| **Timeframes** | `frontend/src/types/marketData.ts` — `TIMEFRAMES` |
| **Indicator presets/colours** | `frontend/src/types/indicators.ts` — `INDICATOR_PRESETS` |
| **Library** | `lightweight-charts` ^4.2.3 — **v4 has no panes**, hence separate chart instances synced via `syncedChartsRef` / `registerChart` / `unregisterChart` |
| **Do NOT touch** | anything under `backend/` — indicators are computed server-side from the same candles the chart draws |
| **Gotchas** | The sync effect's dependency array is `[oscillators.length]`. A `TIMEFRAMES` interval the provider does not serve returns `400 unsupported_interval`. |

### 10.9 Change the market-data provider

| | |
|---|---|
| **Abstraction** | `app/market_data/base.py` — `MarketDataProvider` (ABC) |
| **Implementations** | `app/market_data/yahoo.py`, `app/market_data/mock.py` |
| **Selection** | `app/market_data/registry.py` — `_PROVIDERS`, `get_provider`, `create_provider`, `close_provider` |
| **Config** | `MARKET_DATA_PROVIDER`, `MARKET_DATA_TIMEOUT_SECONDS`, `MARKET_DATA_API_KEY/_SECRET` in `app/core/config.py` |
| **Contracts** | `app/schemas/market_data.py` — `Quote`, `Candle`, `CandleSeries`, `ProviderCapabilities`, `Interval` |
| **Do NOT touch** | `RelianceMarketDataService`, any endpoint, `PriceStreamService`, the schemas — they depend only on the ABC |
| **Gotchas** | `capabilities` drives real behaviour (PUSH/POLL, modelled bid/ask, the `SIMULATED` badge). Only override `subscribe_live_data` if the provider genuinely pushes. `get_provider()` caches one instance per process. |
| **Tests** | a new module modelled on `tests/test_market_data_provider.py` using `httpx.MockTransport` |

### 10.10 Change WebSocket messages

| | |
|---|---|
| **Payload builders** | `app/realtime/price_stream.py` — `build_tick`, `status`, `_handle_failure` |
| **Endpoint frames** | `app/api/v1/endpoints/stream.py` — the `status` frame, `ping`/`pong` |
| **Frontend types** | `frontend/src/types/stream.ts` |
| **Frontend handler** | `frontend/src/hooks/useLivePrice.ts` — the `switch (message.type)` |
| **Do NOT touch** | `ConnectionManager` — it is payload-agnostic |
| **Gotchas** | The tick is a **hand-built dict, not a Pydantic model** — nothing validates it on either end. Money stays a string. `status()` is also the body of `GET /stream/status`. |
| **Tests** | `tests/test_realtime.py`, `tests/test_stream_endpoint.py` |

### 10.11 Add a new order type

| | |
|---|---|
| **Enum** | `app/models/enums.py` — `OrderType`; then a migration (`ALTER TYPE order_type ADD VALUE ...`) |
| **Request** | `app/schemas/trading.py` — `PlaceOrderRequest` needs `limit_price` / `trigger_price` |
| **Creation** | `app/trading/order_manager.py:create`; `TradingEngine.place_order` currently hard-codes `OrderType.MARKET` |
| **Matching** | `app/trading/execution.py` — the seam. **There is no order book and no matching loop today.** |
| **Frontend** | `frontend/src/types/trading.ts` (`OrderType = 'MARKET'`), `components/terminal/TradingPanel.tsx` |
| **Gotchas** | `OrderStatus.CANCELLED` exists but nothing sets it. `ck_orders_filled_orders_have_a_price` assumes a filled order has a price. `ALTER TYPE ... ADD VALUE` cannot run in a transaction block on older PostgreSQL. |

---

## 11. AI Coding Instructions

### 11.1 Project architecture in one paragraph

A single-instrument (NSE:RELIANCE), single-wallet **paper** trading platform.
FastAPI + SQLAlchemy 2 async + PostgreSQL 16 behind a React 18 + Vite SPA.
Endpoints are transport only; rules live in services and in
`backend/app/trading/`, a self-contained engine that imports no web framework
and no market-data provider. Market data comes through a provider ABC
(`yahoo` live, `mock` simulated). One WebSocket streams prices; REST carries
commands and account state. A backtester reuses the live pricing and accounting
code so backtest and live numbers are identical by construction.

### 11.2 Invariants — breaking any of these is a bug

1. **Money is `Decimal` everywhere.** The only sanctioned float conversion is
   `candles_to_frame()` in `app/indicators/service.py` (TA-Lib needs `float64`;
   these are studies, not money). In the frontend, money is a **string** and is
   converted to `number` only at render time in `utils/format.ts`.
2. **All rounding goes through `to_money()` (2 dp), `to_average()` (4 dp) and
   `to_rupee()` (whole rupee, STT + stamp duty).** No ad-hoc `.quantize()`.
3. **One order = one transaction.** `TradingEngine.place_order` commits exactly
   once (or once on the rejection path). Locks are taken **wallet first, then
   position** — everywhere.
4. **The engine never fetches a price.** `reference_price` and `mark_price` are
   always parameters.
5. **`apply_fill()` is the single source of truth for position accounting**, and
   `ExecutionEngine.price_fill()` for fill pricing. Live and backtest both call
   them. Never fork either.
6. **Spread and slippage are always adverse.** A fill is never better than the
   reference price.
7. **A win is a *closing* fill (`closed_quantity > 0`) with `net_pnl > 0`** —
   identically in `app/analytics/performance.py` and `app/backtest/results.py`.
8. **Providers declare their capabilities honestly.** `supports_live_stream`
   decides PUSH vs POLL; `supports_bid_ask` decides modelled bid/ask;
   `is_mock` drives the warning and the `SIMULATED` badge.
9. **No lookahead in strategies.** `StrategyContext` exposes history up to and
   including the current bar; `indicator(key, offset)` refuses a negative offset.
10. **`app/core/config.py` is the only reader of the environment.**
11. **There is no authentication.** Any new endpoint is public.

### 11.3 Central files — read these first

| File | Why |
|------|-----|
| `backend/app/main.py` | app factory, lifespan, the single exception handler |
| `backend/app/core/config.py` | every setting |
| `backend/app/trading/engine.py` | the transaction boundary and order flow |
| `backend/app/trading/position_manager.py` | `apply_fill` — the accounting core |
| `backend/app/trading/execution.py` | the fill-pricing pipeline |
| `backend/app/trading/portfolio.py` | the cash rule |
| `backend/app/models/trading.py` | orders / trades / positions schema |
| `backend/app/api/v1/router.py` | the endpoint map |
| `backend/app/realtime/price_stream.py` | the tick payload contract |
| `frontend/src/hooks/useAccount.ts` | frontend account state |
| `frontend/src/hooks/useLivePrice.ts` | the WebSocket client |
| `frontend/src/api/client.ts` | the only `fetch` |

### 11.4 Where to make common changes

| Task | Files |
|------|-------|
| New endpoint | `app/api/v1/endpoints/*`, `app/schemas/*`, a service, `frontend/src/api/*`, `frontend/src/types/*` |
| New strategy | `app/strategies/<name>.py` + `_STRATEGIES` |
| New indicator | `app/indicators/definitions.py` + `library.py` (+ `INDICATOR_PRESETS`) |
| New provider | `app/market_data/<name>.py` + `_PROVIDERS` |
| Charge / spread / slippage rates | `backend/.env` (or the model class for a new shape) |
| New table | `app/models/*`, `app/models/__init__.py`, a new Alembic revision, `conftest.py` |
| UI | `frontend/src/components/**`, `styles/*.css` |

### 11.5 Files to leave alone unless that IS the task

* `backend/alembic/versions/*` — **never edit an applied migration.** Add a
  revision.
* `app/trading/pnl.py`, `app/trading/position_manager.py:apply_fill` — changing
  these changes live trading, backtests, snapshots and the performance summary
  simultaneously, and does **not** recompute historical rows.
* `app/trading/engine.py:place_order` call order and commit point.
* `app/market_data/base.py` — the ABC; changing it breaks every provider.
* `app/db/session.py`, `app/db/base.py` (`NAMING_CONVENTION` in particular —
  it determines constraint names in existing migrations).
* `app/realtime/connection_manager.py` — payload-agnostic membership/locking.
* `frontend/src/api/client.ts` — the single transport chokepoint.

### 11.6 Preserving backward compatibility

* **REST:** add fields, do not rename or remove them. A new required request
  field breaks existing callers — give it a default. Keep money as `Decimal`
  server-side and `string` in TS.
* **WebSocket:** the tick payload is unvalidated on both ends. Add fields;
  never rename. Update `frontend/src/types/stream.ts` in the same commit.
* **Database:** additive migrations. A rename must be an `alter_column` /
  `op.alter_column(..., new_column_name=...)`, never DROP+ADD — see
  `b41705c11d09`, where autogenerate would have discarded P&L on every trade.
* **Enums:** `order_side`, `order_status`, `order_type` and `snapshot_source`
  are **native PostgreSQL types**. Adding a member needs a migration.
* **Config:** new settings need a default in `Settings` **and** a line in
  `backend/.env.example`.

### 11.7 Running tests around a change

```bash
# BEFORE — establish a green baseline
docker compose exec backend pytest -q

# make the change

# AFTER — full suite, then the targeted ones
docker compose exec backend pytest -q
docker compose exec backend pytest tests/test_backtest.py -k parity   # if you touched
                                                                      # pricing/accounting
cd frontend && npm run typecheck                                      # if you touched TS
```

Targeted suites by area:

| Area touched | Run |
|--------------|-----|
| pricing / charges | `test_execution_costs.py`, `test_realistic_execution.py` |
| position / P&L | `test_position_accounting.py`, `test_trading_engine.py`, `test_backtest.py` |
| wallet | `test_wallet_api.py`, `test_wallet_persistence.py` |
| market data | `test_market_data_provider.py`, `test_market_data_api.py` |
| indicators | `test_indicators.py` |
| strategies / backtest | `test_strategies.py`, `test_backtest.py` |
| WebSocket | `test_realtime.py`, `test_stream_endpoint.py` |
| snapshots / analytics | `test_portfolio_history.py` |

### 11.8 Not breaking migrations

1. Never edit an applied revision — add a new one.
2. Always `alembic revision --autogenerate` **then read the file.** This repo
   documents three autogenerate mistakes: enums emitted per-table and stranded
   on downgrade; a rename emitted as DROP+ADD; NOT NULL columns added without a
   `server_default`.
3. Native enums: create and drop them **explicitly** with `checkfirst`
   (`create_type=False` on the `postgresql.ENUM`), as `44b98124fbd4` and
   `51917e5fa5f1` do.
4. New NOT NULL columns on a populated table need `server_default`.
5. Export every new model from `app/models/__init__.py`, or autogenerate cannot
   see it.
6. Verify a round trip: `alembic upgrade head` → `alembic downgrade -1` →
   `alembic upgrade head`.
7. Head is `51917e5fa5f1`; `down_revision` must chain to it.

### 11.9 Not breaking trading calculations

* Change `PnLCalculator` / `apply_fill` / `cash_delta` in **one place only**;
  everything else calls them.
* Run `tests/test_backtest.py -k parity` — it drives the same order sequence
  through the live DB-backed engine and the in-memory backtester and asserts the
  numbers match. **If parity fails, the change is wrong.**
* `test_realistic_execution.py` configures models **explicitly** rather than
  from settings — preserve that, so an `.env` edit cannot silently move test
  expectations.
* Remember charges accumulate on **every** fill, opening ones included
  (`PositionManager.apply`).
* Historical rows are never recomputed. A P&L change needs a data-migration plan
  or an accepted discontinuity.

### 11.10 Not breaking WebSocket contracts

* The tick is built by hand in `PriceStreamService.build_tick` and consumed by
  `frontend/src/types/stream.ts` + `useLivePrice`. **Nothing validates it.**
  Rename a field and the browser silently sees `undefined`.
* Keep every monetary field a **string**.
* `status()` feeds both the `status` frame and `GET /api/v1/stream/status`.
* The only client→server message is `{"type":"ping"}`; adding another requires
  changing the receive loop in `app/api/v1/endpoints/stream.py`.
* Close codes in use: **1008** (connection limit), **1000** (client error),
  **1001** (server shutdown).
* Tests: `tests/test_stream_endpoint.py` (Starlette `TestClient`, no network).

### 11.11 Not changing API contracts accidentally

* `response_model=` on the route is the contract. Changing the returned dataclass
  or ORM row without updating the schema silently drops or adds fields.
* `frontend/src/types/*.ts` are **hand-mirrored** from `app/schemas/*.py`.
  There is no codegen and no shared client. Change both in one commit.
* Query-parameter aliases matter: `list_orders` exposes the Python parameter
  `order_status` as `?status=`.
* Status codes are meaningful: `POST /wallet/initialize` returns **201 or 200**;
  `POST /portfolio/snapshots` returns **201**; `POST /trading/orders` returns
  **201**; `GET /health` is **always 200**.
* The error envelope is `{"error":{"code","message"}}` for `DomainError` and
  `{"detail":[...]}` for validation. `frontend/src/api/client.ts:toApiError`
  handles both — keep it that way.
* Verify against `http://localhost:8000/openapi.json` after any schema change.

---

## 12. Source of Truth

| Concern | Authoritative file(s) | Notes |
|---------|----------------------|-------|
| **Trading rules** | `backend/app/trading/engine.py` — `TradingEngine._validate_request`, `_validate_against_position`, `_resolve_symbol`, `place_order` | side semantics in `app/models/enums.py:OrderSide` (`.direction`, `.is_closing_only`) |
| **Wallet / cash** | `backend/app/trading/portfolio.py` (`PortfolioManager.cash_delta`, `assert_affordable`, `apply_cash`); `backend/app/services/wallet_service.py`; `backend/app/repositories/wallet_repository.py`; `backend/app/models/wallet.py` | mirrored for backtests in `app/backtest/portfolio.py:BacktestPortfolio.cash_delta` |
| **Positions** | `backend/app/trading/position_manager.py` — **`apply_fill()`** is the algorithm; `PositionManager` is the thin DB layer; `backend/app/models/trading.py:Position` is the schema | |
| **P&L** | `backend/app/trading/pnl.py` — `PnLCalculator` + `to_money` / `to_average` | valuation in `PortfolioManager.snapshot`; aggregates in `app/analytics/performance.py` |
| **Fees / charges** | `backend/app/trading/fees.py` — `FeeCalculator`, `ChargeBreakdown`, `Segment`, `to_rupee` | rates configured in `app/core/config.py` / `backend/.env` |
| **Spread & slippage** | `backend/app/trading/spread.py`, `backend/app/trading/slippage.py` | |
| **Market data** | `backend/app/market_data/base.py` (the ABC contract); `registry.py` (selection); `yahoo.py` / `mock.py` (implementations); `backend/app/services/market_data_service.py` (platform rules) | |
| **API contracts** | `backend/app/schemas/*.py` + the `response_model=` on each route in `backend/app/api/v1/endpoints/*.py`; the generated `/openapi.json` | `frontend/src/types/*.ts` are **hand-written mirrors**, not authoritative |
| **Database schema** | `backend/app/models/*.py` (`Base.metadata`) for the code; `backend/alembic/versions/*` for what is actually deployed — **head `51917e5fa5f1`** | naming rules in `backend/app/db/base.py:NAMING_CONVENTION` |
| **Frontend state** | `frontend/src/hooks/useAccount.ts` (account), `useLivePrice.ts` (price), `useIndicators.ts` (indicator selection, also `localStorage['vtrader.indicators']`), `useHashRoute.ts` (route) | no Redux / Zustand / Context / React Query |
| **WebSocket messages** | `backend/app/realtime/price_stream.py` — `build_tick()`, `status()`, `_handle_failure()`; plus the `status`/`pong`/limit frames in `backend/app/api/v1/endpoints/stream.py` | mirrored in `frontend/src/types/stream.ts`; **no schema validation anywhere** |
| **Strategies** | `backend/app/strategies/base.py` (the `Strategy` contract, `Signal`, `Decision`, `StrategyContext`); `registry.py` (`_STRATEGIES`) | `ma_crossover.py` is the only implementation |
| **Indicators** | `backend/app/indicators/definitions.py` (`CATALOGUE`, spec grammar); `library.py` (`CALCULATORS`, `warmup_for`) | `service.py` orchestrates; presets in `frontend/src/types/indicators.ts` |
| **Backtesting** | `backend/app/backtest/engine.py` (loop, fill timing, sizing); `portfolio.py` (in-memory account); `results.py` (metrics) | must stay consistent with `app/analytics/performance.py` |
| **Configuration** | `backend/app/core/config.py` — `Settings` | the only reader of the environment |
| **Error semantics** | `backend/app/core/exceptions.py` + the handler in `backend/app/main.py` | plus `InvalidIndicatorError` (`indicators/definitions.py`) and the two strategy errors (`strategies/registry.py`) |
| **Test fixtures / DB lifecycle** | `backend/tests/conftest.py` | |

### Not implemented (do not document these as existing)

* Authentication, authorisation, users, sessions, tokens, rate limiting
* `RiskManager`, margin, leverage, exposure limits, stop-loss, circuit breakers
* Limit / stop orders, order cancellation (`OrderStatus.CANCELLED` is never set)
* Partial fills, an order book, order matching
* A live strategy runner (strategies run only inside `BacktestEngine`)
* Multi-instrument or multi-user support
* Any ML model or inference path
* Caching of market data (no Redis — deliberately absent from `docker-compose.yml`)
* Frontend tests (only `npm run typecheck`)
* A backtesting UI (the endpoint exists; nothing in the frontend calls it)
* A "full account reset" endpoint (`SnapshotService.purge()` is unwired)

---

*Generated from a complete read of the repository at commit `1f0a749`.
No application code was modified.*

---

## 13. Automatic Orders API (stop-loss & price triggers)

Added after the original document. **Auth: none required**, like every other
endpoint. Architecture, position interaction and duplicate protection are
documented in `ARCHITECTURE.md` §18.

### 13.1 Endpoints

| # | Method | Path | Purpose |
|---|--------|------|---------|
| 26 | POST | `/api/v1/automatic-orders` | Create a stop-loss or price trigger |
| 27 | GET | `/api/v1/automatic-orders/active` | Active triggers |
| 28 | GET | `/api/v1/automatic-orders` | History (all statuses) |
| 29 | GET | `/api/v1/automatic-orders/{id}` | One trigger |
| 30 | POST | `/api/v1/automatic-orders/{id}/cancel` | Cancel an ACTIVE trigger |

File: `app/api/v1/endpoints/automatic_orders.py`.

### 13.2 `POST /api/v1/automatic-orders`

Request schema `CreateAutomaticOrderRequest`:

| Field | Type | Req | Validation |
|-------|------|-----|-----------|
| `order_type` | `AutomaticOrderType` | yes | `STOP_LOSS` \| `PRICE_TRIGGER` |
| `trigger_price` | `Decimal` | yes | `gt=0`, 18/2 |
| `trigger_condition` | `TriggerCondition` | yes | `GTE` (at/above) \| `LTE` (at/below) |
| `action` | `OrderSide` | yes | `BUY` \| `SELL` \| `SHORT_SELL` \| `BUY_TO_COVER` |
| `quantity` | `int` | yes | `gt=0`, `le=10_000_000` |
| `symbol` | `str \| None` | no | must be the configured symbol |
| `reference_price` | `Decimal \| None` | no | `gt=0`. Omitted → endpoint falls back to the live stream's last tick |

**STOP_LOSS rules**, derived from the open position (never trusted from the request):

| Position | Required `trigger_condition` | Required `action` |
|---|---|---|
| LONG | `LTE` | `SELL` |
| SHORT | `GTE` | `BUY_TO_COVER` |
| FLAT | — | rejected |

Also: `quantity <= abs(position.quantity)`, and — when a reference price is
available — a long's trigger must sit **below** it, a short's **above** it.

Response `AutomaticOrderResponse`. **201** on success.

| Status | Code | Cause |
|---|---|---|
| 400 | `invalid_automatic_order` | flat position, wrong direction/condition, quantity over the position, trigger that would fire immediately, bad quantity/price |
| 400 | `unsupported_symbol` | symbol other than the configured one |
| 422 | — | Pydantic (non-positive values, bad enum) |

```bash
curl -X POST http://localhost:8000/api/v1/automatic-orders \
  -H 'Content-Type: application/json' \
  -d '{"order_type":"STOP_LOSS","trigger_price":"1350.00",
       "trigger_condition":"LTE","action":"SELL","quantity":100}'
```
```json
{"id":1,"symbol":"RELIANCE","exchange":"NSE","order_type":"STOP_LOSS",
 "trigger_price":"1350.00","trigger_condition":"LTE","action":"SELL","quantity":100,
 "status":"ACTIVE","created_at":"2026-08-27T11:09:48.166341Z","triggered_at":null,
 "cancelled_at":null,"trigger_market_price":null,"triggered_order_id":null,"reason":null}
```

### 13.3 Reads and cancel

* **`GET /automatic-orders/active`** — query `limit` (`ge=1, le=500`, default 100).
  Oldest first: the order the monitor evaluates them in. `200`.
* **`GET /automatic-orders`** — query `limit`, `offset`, `status` (alias for
  `order_status`). Newest first, all statuses. `200`.
* **`GET /automatic-orders/{id}`** — `200`; `404 automatic_order_not_found`.
* **`POST /automatic-orders/{id}/cancel`** — `200`;
  `400 invalid_automatic_order` if already terminal; `404`. Takes
  `SELECT ... FOR UPDATE` with `populate_existing` so it cannot overwrite a
  claim the monitor just committed.

**Services:** `AutomaticOrderService`. **Tables:** `automatic_orders`
(+ `positions` read on stop-loss validation). Creating or cancelling never
touches `orders`, `trades` or `wallet`.

### 13.4 Model — table `automatic_orders`

File `app/models/automatic_order.py`. Migration `7c4e1a9b2d55`.

| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | `BigInteger` | no | PK |
| `symbol` | `String(32)` | no | indexed |
| `exchange` | `String(16)` | no | default `'NSE'` |
| `order_type` | `automatic_order_type` | no | `STOP_LOSS` \| `PRICE_TRIGGER` |
| `trigger_price` | `Numeric(18,2)` | no | |
| `trigger_condition` | `trigger_condition` | no | `GTE` \| `LTE` |
| `action` | `order_side` | no | **reuses** the existing enum |
| `quantity` | `Integer` | no | |
| `status` | `automatic_order_status` | no | `ACTIVE`/`TRIGGERED`/`CANCELLED`/`FAILED`, indexed |
| `triggered_at`, `cancelled_at` | `TIMESTAMPTZ` | yes | |
| `trigger_market_price` | `Numeric(18,2)` | yes | price that satisfied the condition |
| `triggered_order_id` | `BigInteger` | yes | **FK** → `orders.id` `ON DELETE SET NULL` |
| `reason` | `String(500)` | yes | cancel reason / failure message |
| `created_at`, `updated_at` | `TIMESTAMPTZ` | no | `TimestampMixin` |

Constraints: `quantity > 0`, `quantity <= 10000000`, `trigger_price > 0`,
`status <> 'TRIGGERED' OR triggered_at IS NOT NULL`,
`status <> 'CANCELLED' OR cancelled_at IS NOT NULL`.
Indexes: `symbol`, `status`, `triggered_order_id`, `(symbol, status)`, `created_at`.

New enums: `automatic_order_type`, `trigger_condition`, `automatic_order_status`.
`order_side` is reused and is **not** dropped on downgrade.

### 13.5 WebSocket event

Same socket, `ws://localhost:8000/api/v1/stream/prices`. New server→client frame:

```json
{"type":"automatic_order",
 "data":{"event":"triggered","automatic_order_id":1,
         "server_time":"2026-08-27T11:09:48.703530Z",
         "order_type":"PRICE_TRIGGER","trigger_condition":"GTE",
         "trigger_price":"1.00","action":"SELL","quantity":10,
         "status":"TRIGGERED","symbol":"RELIANCE","reason":null,
         "trigger_market_price":"1282.20","triggered_order_id":28,
         "execution_price":"1281.81","net_pnl":"-15.80",
         "total_charges":"8.00","position_after":0}}
```

`event` is `"triggered"` or `"failed"`. On `failed`, the execution fields are
absent and `reason` carries the engine's rejection message.

Built by `AutomaticOrderMonitor._event`; typed in
`frontend/src/types/stream.ts` as `AutomaticOrderEvent`; handled in
`useLivePrice` and consumed by `Terminal`, which refreshes every account panel
and reloads the trigger list. No page refresh is needed.

`GET /api/v1/stream/status` gains an `automation` block:

```json
"automation": {"evaluations": 13, "triggered": 1, "failed": 0}
```

### 13.6 Frontend

| File | Role |
|---|---|
| `frontend/src/types/automaticOrders.ts` | contracts + label maps |
| `frontend/src/api/automaticOrders.ts` | `createAutomaticOrder`, `fetchActiveAutomaticOrders`, `fetchAutomaticOrderHistory`, `cancelAutomaticOrder` |
| `frontend/src/components/terminal/AutomaticOrderPanel.tsx` | create form + active list + cancel |
| `frontend/src/components/terminal/Terminal.tsx` | renders the panel; refreshes on `automatic_order` events |

For a stop-loss the panel **pre-fills and locks** condition + action from the
open position. That is convenience only — the backend re-derives and
re-validates, and the frontend never evaluates a price against a trigger.
