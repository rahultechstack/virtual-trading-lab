# Configuration Guide

Everything you are likely to want to change, where it lives, and what it does.

**The rule this project follows:** if a value might reasonably differ between
deployments, it is a setting. If it cannot be changed without a migration or a
code change, it stays next to the code — with a comment saying so.

---

## Where things live

| File | Holds | Applies after |
| ---- | ----- | ------------- |
| `backend/.env` | Every backend setting | `docker compose up -d --force-recreate backend` |
| `backend/app/core/config.py` | The defaults and documentation for those settings | `docker compose restart backend` |
| `backend/app/market_data/catalogue.py` | **Which stocks and coins are tradable** | `docker compose restart backend` |
| `frontend/.env` | Backend URL, API prefix, WebSocket URL | frontend **rebuild** |
| `frontend/src/config/` | UI behaviour, chart colours, timings | frontend rebuild |
| `.env` (repo root) | Docker Compose: ports, database credentials | `docker compose up -d` |

> ⚠️ **`docker compose restart` does NOT pick up a changed `.env`.** Compose
> reads `env_file` when it *creates* a container, so a restart reuses the old
> environment and your change silently does nothing. Use:
>
> ```bash
> docker compose up -d --force-recreate backend
> ```
>
> Editing a **Python** file is different — the bind-mounted source reloads, so a
> plain `restart` is enough there.

> **Frontend changes need a rebuild, not a restart.** Vite inlines
> `import.meta.env.*` at build time. In dev the hot-reload server picks changes
> up; a production image must be rebuilt.

Copy the templates before first run:

```bash
cp .env.example .env
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env
```

`backend/.env.example` is a **complete map** of every backend setting — a test
(`tests/test_configuration.py`) fails if a setting is added without being
documented there, or if the file mentions one that no longer exists.

---

## 1. API URLs and API keys

### Upstream market-data endpoint

`backend/.env`

| Setting | Default | What it does |
| ------- | ------- | ------------ |
| `MARKET_DATA_BASE_URL` | `https://query1.finance.yahoo.com/v8/finance/chart` | Endpoint the bundled providers call. Point it at a mirror or a recording proxy with no code change. |
| `MARKET_DATA_USER_AGENT` | `Mozilla/5.0 (compatible; VirtualTradingPlatform/0.1)` | Yahoo rejects requests without a browser-like agent. |
| `MARKET_DATA_TIMEOUT_SECONDS` | `15.0` | HTTP timeout for a single upstream call. |

### Credentials

| Setting | Default | What it does |
| ------- | ------- | ------------ |
| `MARKET_DATA_API_KEY` | *unset* | Held as a `SecretStr`, so it never appears in a log or traceback. |
| `MARKET_DATA_API_SECRET` | *unset* | Same. |

⚠️ **Nothing reads these today** — Yahoo's chart endpoint is keyless. They
exist as the ready-made seam for a provider that *does* need credentials. Read
them in your provider's factory in `backend/app/market_data/registry.py`.

Never put a key in `.env.example` or in code. `backend/.env` is gitignored.

### Frontend → backend

`frontend/.env`, read by `frontend/src/config/api.ts`

| Variable | Default | What it does |
| -------- | ------- | ------------ |
| `VITE_API_BASE_URL` | `http://localhost:8000` | Origin the backend is served from. No trailing slash. |
| `VITE_API_V1_PREFIX` | `/api/v1` | Must match the backend's `API_V1_PREFIX`. |

---

## 2. Market-data provider

`backend/.env`. Providers are chosen **per asset class** — a feed that serves
NSE equities is not automatically one that serves crypto.

| Setting | Default | What it does |
| ------- | ------- | ------------ |
| `MARKET_DATA_PROVIDER` | `yahoo` | Feed for stocks. |
| `CRYPTO_MARKET_DATA_PROVIDER` | `yahoo_crypto` | Feed for crypto. |
| `CRYPTO_QUOTE_CURRENCY` | `INR` | Crypto pairs are requested as `<SYMBOL>-<currency>`. Keeping this INR means one currency across the portfolio and no FX rate anywhere. |

Built-in values: `yahoo`, `yahoo_crypto`, `mock`.

**`mock`** generates a random walk for development. It logs a loud warning and
every tick carries `is_mock: true`. Never point production at it.

### Adding a provider

1. Write a class satisfying `MarketDataProvider`
   (`backend/app/market_data/base.py`).
2. Add one entry to `_PROVIDERS` in `backend/app/market_data/registry.py`.
3. Set `MARKET_DATA_PROVIDER` or `CRYPTO_MARKET_DATA_PROVIDER` to its name.

Nothing else changes. If your provider has a real push socket, override
`subscribe_live_data` and the stream switches from polling to streaming on its
own.

---

## 3. WebSocket URL

`frontend/.env`, read by `frontend/src/config/api.ts`

| Variable | Default | What it does |
| -------- | ------- | ------------ |
| `VITE_WS_BASE_URL` | *blank* | **Leave blank in almost every setup.** Blank derives the socket URL from `VITE_API_BASE_URL` by swapping the scheme (`http`→`ws`, `https`→`wss`), so there is one thing to configure. Set it only when the socket is served from a different origin. |

The path itself is `STREAM_PATH` in `config/api.ts` — it is the only WebSocket
the app opens and matches the backend route.

Backend side (`backend/.env`):

| Setting | Default | What it does |
| ------- | ------- | ------------ |
| `STREAM_POLL_INTERVAL_SECONDS` | `5.0` | How often the backend asks the provider for a price. For a polled feed this **is** what "live" means. |
| `STREAM_MAX_CONNECTIONS` | `50` | Concurrent WebSocket clients allowed. |

Client-side behaviour lives in `frontend/src/config/realtime.ts`:
`INITIAL_BACKOFF_MS`, `MAX_BACKOFF_MS`, `PING_INTERVAL_MS`, `STALE_AFTER_MS`.

> Keep `PING_INTERVAL_MS` (25s) comfortably below any proxy's idle timeout, and
> `STALE_AFTER_MS` a few multiples of the backend's poll interval — otherwise a
> normal gap between polls reads as a fault.

---

## 4. Supported stocks and crypto

### `backend/app/market_data/catalogue.py` — **the one file to edit**

```python
NSE_INSTRUMENTS = (
    _nse("RELIANCE", "Reliance Industries"),
    _nse("WIPRO", "Wipro"),          # <- add a stock like this
)

CRYPTO_INSTRUMENTS = (
    _crypto("BTC", "Bitcoin"),
    _crypto("SOL", "Solana"),        # <- add a coin like this
)
```

Restart the backend. The API, the instrument picker, the calendars, the fee
rules and the provider routing all read from here — nothing else needs changing,
and a test fails if an instrument is ever declared anywhere else.

⚠️ **Only list what the provider actually serves.** An instrument is tradable
only when it is both in this catalogue *and* served by its feed. Check first:

```bash
curl "http://localhost:8000/api/v1/instruments/WIPRO"   # data_available: true
```

⚠️ **Assets below ₹0.01 cannot be listed.** Prices are stored as
`NUMERIC(18,2)`, so an asset like SHIB (~₹0.0005) would round to zero. The
provider raises rather than returning `0.00`.

### Default instrument

| Where | Setting | What it does |
| ----- | ------- | ------------ |
| `backend/.env` | `TRADING_SYMBOL`, `TRADING_EXCHANGE` | What a request that omits a symbol resolves to. **Not a restriction** — every catalogued instrument is tradable. |
| `frontend/.env` | `VITE_TRADING_SYMBOL`, `VITE_TRADING_EXCHANGE` | Only the placeholder shown before the first tick, and the tab title. A mismatch is cosmetic. |

---

## 5. Default wallet balance

`backend/.env`

| Setting | Default | What it does |
| ------- | ------- | ------------ |
| `WALLET_INITIAL_BALANCE` | `1000000.00` | Opening capital granted when the wallet is first created. |
| `WALLET_CURRENCY` | `INR` | Currency label on the wallet. |

Applies **only at creation**. An existing wallet keeps its balance; to start
over, `POST /api/v1/wallet/reset` (optionally with a new balance), or delete the
database (see §12).

---

## 6. Brokerage and fees

Charges are **asset-aware**: NSE's statutory charges are never applied to
crypto. `CHARGES_ENABLED=false` turns everything off for frictionless
simulation.

### Equities — `backend/.env`

Applied by `FeeCalculator` in `backend/app/trading/fees.py`. Rates are
**percentages of turnover** (`0.03` means 0.03%).

| Setting | Default | What it does |
| ------- | ------- | ------------ |
| `EXECUTION_SEGMENT` | `INTRADAY` | `INTRADAY` or `DELIVERY`. Changes which STT and stamp-duty rates apply. |
| `BROKERAGE_PERCENT` | `0.03` | Broker commission. |
| `BROKERAGE_MAX_PER_ORDER` | `20` | Cap per order. Blank for no cap. |
| `STT_INTRADAY_SELL_PERCENT` | `0.025` | Securities Transaction Tax, intraday sell leg only. |
| `STT_DELIVERY_PERCENT` | `0.1` | STT for delivery, both legs. |
| `EXCHANGE_TXN_PERCENT` | `0.00297` | Exchange transaction charge. |
| `SEBI_CHARGES_PERCENT` | `0.0001` | SEBI turnover fee. |
| `STAMP_DUTY_INTRADAY_BUY_PERCENT` | `0.003` | Stamp duty, buy side only. |
| `STAMP_DUTY_DELIVERY_BUY_PERCENT` | `0.015` | Same, delivery rate. |
| `GST_PERCENT` | `18` | GST on brokerage + exchange + SEBI fees. |
| `DP_CHARGES_PER_SELL` | `0` | Flat depository charge on a delivery sell. |

⚠️ Statutory rates are revised periodically. Verify against a current broker
schedule before treating these numbers as authoritative.

### Crypto — `backend/.env`

⚠️ **Simulated.** No crypto exchange is integrated, so these are configurable
**assumptions**, not any venue's published schedule. Point them at whichever
exchange you want to model.

| Setting | Default | What it does |
| ------- | ------- | ------------ |
| `CRYPTO_FEE_PERCENT` | `0.10` | Exchange trading fee, both sides. |
| `CRYPTO_FEE_MAX_PER_ORDER` | *blank* | Cap per order. Blank means none. |
| `CRYPTO_GST_PERCENT` | `18` | GST on the fee (not on turnover). |
| `CRYPTO_TDS_PERCENT` | `1` | TDS on a Virtual Digital Asset transfer, **sell side only**. Statutory (India, s.194S) rather than assumed. Set `0` to disable. |

**Never applied to crypto:** STT, stamp duty, SEBI turnover fee, exchange
transaction charges, DP charges.

### Adding a fee schedule for a new asset class

Add one entry to `_FEE_BUILDERS` in `backend/app/trading/fees.py`. That table is
the only place fees are dispatched.

---

## 7. Slippage and spread

`backend/.env`. Both are applied **adversely** — a fill is never better than the
reference price.

| Setting | Default | What it does |
| ------- | ------- | ------------ |
| `SPREAD_BPS` | `2` | Full bid/ask spread in basis points; half is applied either side of the mid. |
| `SLIPPAGE_MODEL` | `FIXED_BPS` | `NONE`, `FIXED_BPS` or `PERCENT`. |
| `SLIPPAGE_BPS` | `2` | Used by `FIXED_BPS`. |
| `SLIPPAGE_PERCENT` | `0` | Used by `PERCENT`. |

Both are in basis points of the price, so they scale correctly for an asset
worth ₹8 or ₹76,00,000 — there is deliberately no per-asset-class setting.

`STREAM_MODEL_BID_ASK` (default on) derives a bid/ask from the spread model when
the feed carries no order book. Such ticks are labelled `modelled` so they are
never mistaken for real depth.

---

## 8. Market hours

`backend/.env`

| Setting | Default | What it does |
| ------- | ------- | ------------ |
| `ENFORCE_MARKET_HOURS` | `false` | Whether a closed market **blocks** an order. Off by default: this is a paper-trading lab, and practising an order at 9pm is the point. The status is always resolved and reported either way. |
| `NSE_TIMEZONE` | `Asia/Kolkata` | Zone the session times are expressed in. |
| `NSE_PRE_OPEN_TIME` | `09:00` | Start of the call auction. Reported as `PRE_OPEN`; **not** tradable. |
| `NSE_OPEN_TIME` | `09:15` | Continuous trading begins. |
| `NSE_CLOSE_TIME` | `15:30` | Continuous trading ends. |
| `NSE_HOLIDAYS` | 5 fixed-date holidays | Full-day closures, ISO dates, comma separated. |

⚠️ **Update `NSE_HOLIDAYS` every year.** Only fixed-date national holidays ship
as defaults. Most of India's exchange holiday list moves year to year — Diwali,
Holi, Eid, Muhurat trading follow lunar calendars and cannot be derived, so they
are deliberately **not guessed at**. Take the list from the official NSE
circular:

```bash
NSE_HOLIDAYS=2026-01-26,2026-03-04,2026-08-15,2026-10-02,2026-11-09
```

An out-of-date list means the calendar reports OPEN on a day the exchange was
shut. Harmless while `ENFORCE_MARKET_HOURS` is off; with it on, it would wrongly
permit an order.

**Crypto ignores all of this.** Its calendar is open 24/7 by construction —
there is no code path from it to a weekday check or a holiday list.

Adding a calendar for a new asset class: one entry in `_BUILDERS` in
`backend/app/markets/registry.py`.

---

## 9. Trading limits

`backend/.env`. Every validation path reads these, so changing one changes it
everywhere — schemas, endpoints, engine and automation alike.

| Setting | Default | What it does |
| ------- | ------- | ------------ |
| `MAX_ORDER_QUANTITY` | `10000000` | Largest single order, in the instrument's own units. |
| `MAX_CANDLES_PER_REQUEST` | `5000` | Cap on candles per market-data or backtest request. |
| `MAX_HISTORY_PAGE_SIZE` | `500` | Cap on rows in an orders/trades/triggers listing. |
| `DEFAULT_HISTORY_PAGE_SIZE` | `100` | Page size when a request omits one. |
| `MAX_SNAPSHOT_PAGE_SIZE` | `5000` | Cap on portfolio snapshots per request. Higher because the equity curve is plotted from it. |
| `MAX_INDICATORS_PER_REQUEST` | `10` | Each indicator is a full pass over the series. |

⚠️ **`MAX_ORDER_QUANTITY` can be lowered freely but not raised past the
database.** The `CHECK` constraint carries its own ceiling
(`DB_MAX_ORDER_QUANTITY` in `backend/app/models/trading.py`, currently
10,000,000). Raising the setting above it needs a migration — the constraint is
part of the schema.

**Minimum order size is not a setting.** It comes from the instrument's
`quantity_step` (1 for a stock, 0.00000001 for crypto), set in the catalogue.

---

## 10. Feature flags

All in one block at the top of `backend/app/core/config.py`, all settable in
`backend/.env`.

| Flag | Default | Off means |
| ---- | ------- | --------- |
| `CHARGES_ENABLED` | `true` | Frictionless simulation: no brokerage, no taxes. |
| `ENFORCE_MARKET_HOURS` | `false` | *(on means)* orders are refused while the market is closed. |
| `SNAPSHOT_ENABLED` | `true` | No periodic equity-curve snapshots. |
| `SNAPSHOT_ON_TRADE` | `true` | No snapshot inside each order's transaction. |
| `SNAPSHOT_SKIP_UNCHANGED` | `true` | An idle account writes a duplicate row every interval. |
| `STREAM_MODEL_BID_ASK` | `true` | Bid/ask report as unavailable instead of being modelled. |
| `STREAM_POLL_FOR_AUTOMATION` | `true` | Stop-losses only fire while a browser tab is open. |

> `STREAM_POLL_FOR_AUTOMATION` is what lets a crypto stop-loss set on Friday
> fire over the weekend. With nothing armed and nobody watching, no upstream
> call is made either way.

---

## 11. Frontend configuration

`frontend/src/config/` — five files, by what they govern.

| File | Holds |
| ---- | ----- |
| `api.ts` | Backend origin, API prefix, WebSocket URL, `apiUrl()` / `wsUrl()` |
| `realtime.ts` | Reconnect backoff, heartbeat, staleness thresholds |
| `ui.ts` | Page sizes, refresh cadence, quantity presets, storage keys |
| `chart.ts` | Chart palette, indicator colours, chart time zone |
| `instrument.ts` | Which instrument the UI opens on |

Frequently useful values:

| Constant | File | Default | What it does |
| -------- | ---- | ------- | ------------ |
| `TERMINAL_HISTORY_LIMIT` | `ui.ts` | `25` | Rows in the terminal's Orders/Trades tabs. |
| `HISTORY_PAGE_LIMIT` | `ui.ts` | `200` | Rows on the full history pages. |
| `SNAPSHOT_PAGE_LIMIT` | `ui.ts` | `1000` | Points on the equity curve. |
| `REVALUE_THROTTLE_MS` | `ui.ts` | `3000` | Minimum gap between portfolio re-valuations. |
| `WHOLE_QUANTITY_PRESETS` | `ui.ts` | `1, 10, 50, 100` | Quick-size buttons for stocks. |
| `FRACTIONAL_QUANTITY_PRESETS` | `ui.ts` | `0.001 … 1` | Quick-size buttons for crypto. |
| `UP_COLOR` / `DOWN_COLOR` | `chart.ts` | green / red | Candles and P&L series, everywhere. |
| `INDICATOR_COLORS` | `chart.ts` | 5 named colours | Palette every indicator draws from. |
| `CHART_TIME_ZONE` | `chart.ts` | `Asia/Kolkata` | Zone the chart's time axis renders in. |

> Page-size constants are what the browser *asks for*. The backend caps each
> independently — raising one above the backend's cap gets a `422`, not more
> rows.

---

## 12. Docker and the database

Repo-root `.env`, consumed by `docker-compose.yml`.

| Variable | Default | What it does |
| -------- | ------- | ------------ |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | `vtrader` / … | Database credentials. Must match `backend/.env`. |
| `BACKEND_HOST_PORT` | `8000` | Host port the API is published on. |
| `FRONTEND_HOST_PORT` | `5173` | Host port the UI is published on. |
| `POSTGRES_HOST_PORT` | `5432` | Host port Postgres is published on. |

**The database lives inside the project**, at `data/postgres`:

```bash
docker compose down && rm -rf data/postgres && docker compose up -d
docker compose exec backend alembic upgrade head
curl -X POST http://localhost:8000/api/v1/wallet/initialize
```

Stopping or rebuilding containers preserves history; deleting `data/postgres`
resets everything.

---

## What is deliberately *not* configurable

These cannot be changed by configuration alone. Each is commented in place.

| Thing | Where | Why |
| ----- | ----- | --- |
| Column precision (`MONEY`, `QUANTITY`, `AVERAGE`) | `backend/app/models/` | Part of the schema; changing it needs a migration. |
| `DB_MAX_ORDER_QUANTITY` | `backend/app/models/trading.py` | Baked into a `CHECK` constraint. |
| Vendor symbol suffixes (`.NS`, `-INR`) and interval names | each provider | Protocol details — changing one means changing the integration. |
| Asset-class dispatch tables (calendars, providers, fee schedules) | `markets/registry.py`, `market_data/router.py`, `trading/fees.py` | The documented extension points for adding an asset class. |
| Arithmetic constants (`ZERO`, `_PERCENT`) | throughout | Not configuration. |

---

## Adding a whole asset class

Six steps, all in named tables:

1. Add the member to `AssetClass` — `backend/app/market_data/instrument_types.py`
2. Add its instruments — `backend/app/market_data/catalogue.py`
3. Register a calendar — `backend/app/markets/registry.py`
4. Register a fee schedule — `backend/app/trading/fees.py`
5. Register a provider — `backend/app/market_data/registry.py` + `router.py`
6. Add the enum value in a migration (`asset_class` is a native Postgres enum)

The trading engine, execution engine, position accounting, portfolio valuation,
automation and WebSocket layers need no change.

---

## Verifying a change

```bash
docker compose up -d --force-recreate backend        # after a .env change
docker compose exec backend pytest tests/test_configuration.py   # 21 tests
docker compose exec backend pytest                               # full suite
```

A quick way to confirm a limit really took effect — the OpenAPI document is
generated from the same settings the engine enforces:

```bash
curl -s localhost:8000/openapi.json   | python -c "import sys,json; q=json.load(sys.stdin)['components']['schemas']['PlaceOrderRequest']['properties']['quantity']; print(next(b for b in q['anyOf'] if b.get('type')=='number')['maximum'])"
```

`tests/test_configuration.py` asserts that lowering a limit actually changes
behaviour, that no module keeps a private copy of a centralised value, that only
`config.py` reads the environment, and that `.env.example` stays a complete map
of the settings that exist.
