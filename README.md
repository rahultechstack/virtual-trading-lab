# Virtual Trading Platform — NSE:RELIANCE

Single-user, single-instrument **paper trading** platform. No real money, no
broker connectivity, no login — there is exactly one virtual wallet.

> **Current stage: 4 — Virtual trading engine.**
> Stages 1-3 delivered the project structure, the persistent wallet and a
> provider-agnostic market-data layer. Stage 4 adds the trading engine: buy,
> sell, short sell and cover, with positions, trades and P&L persisted
> atomically. Charts, WebSocket streaming, strategies, ML and backtesting are
> **not** implemented.

## Stack

| Layer      | Technology                                  |
| ---------- | ------------------------------------------- |
| Frontend   | React 18 + TypeScript + Vite                |
| Backend    | FastAPI + Python 3.11                       |
| Database   | PostgreSQL 16 (Docker), SQLAlchemy 2 async  |
| Migrations | Alembic (wired, no domain tables yet)       |

## Prerequisites

**Docker route (recommended):** Docker Desktop only. Nothing else is required —
Python and Node run inside containers.

**Local route:** Python 3.11+, Node.js 18+, and Docker for PostgreSQL.

## Layout

```
my-project/
├── docker-compose.yml     postgres + backend + frontend
├── .env                   infra env (from .env.example)
├── backend/
│   ├── Dockerfile         base / dev / prod targets
│   ├── alembic/versions/  migrations
│   ├── tests/             pytest suite (real PostgreSQL)
│   └── app/
│       ├── core/          config, logging, domain exceptions
│       ├── db/            engine, session, declarative base
│       ├── models/        ORM models (Wallet)
│       ├── schemas/       Pydantic contracts
│       ├── repositories/  data access — all SQL lives here
│       ├── market_data/   provider abstraction + integrations
│       ├── trading/       the trading engine (no web, no provider deps)
│       ├── services/      business logic + transaction boundaries
│       └── api/v1/        HTTP endpoints
└── frontend/
    ├── Dockerfile         deps / dev / build / prod targets
    ├── nginx.conf         production static hosting
    └── src/
        ├── api/           HTTP client + endpoint functions
        ├── types/         TS contracts mirroring backend schemas
        ├── hooks/         data fetching
        ├── components/    UI
        └── styles/
```

## Run with Docker

```bash
cp .env.example .env
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env

docker compose up -d --build
```

That starts three containers:

| Service    | Container          | URL                       |
| ---------- | ------------------ | ------------------------- |
| `postgres` | `vtrader-postgres` | `localhost:5432`          |
| `backend`  | `vtrader-backend`  | <http://localhost:8000>   |
| `frontend` | `vtrader-frontend` | <http://localhost:5173>   |

Source is bind-mounted, so editing `backend/app/**` or `frontend/src/**`
hot-reloads without a rebuild. Rebuild only when dependencies change:

```bash
docker compose build && docker compose up -d
```

Useful commands:

```bash
docker compose logs -f backend      # follow backend logs
docker compose logs -f frontend
docker compose restart backend
docker compose down                 # stop, keep data
docker compose down -v              # stop and DELETE the database volume
```

### Verify (Docker)

```bash
# 1. All three containers up, postgres and backend healthy
docker compose ps

# 2. Liveness — no database involved
curl http://localhost:8000/api/v1/health/ping
# -> {"message":"pong","timestamp":"..."}

# 3. Readiness — runs a live SELECT 1 against PostgreSQL
curl http://localhost:8000/api/v1/health
# -> "status":"ok" ... "database":{"status":"ok","latency_ms":23.03}

# 4. Frontend dev server responds
curl -I http://localhost:5173

# 5. TypeScript is clean
docker compose exec frontend npm run typecheck

# 6. Database reachable directly
docker compose exec postgres psql -U vtrader -d virtual_trading -c "select version();"

# 7. Migration environment connects
docker compose exec backend alembic current
```

Then open <http://localhost:5173>. The **Backend connection** card must show
`API OK`, `PostgreSQL OK` and a latency figure — that is the browser →
FastAPI → PostgreSQL round trip working end to end.

## Run locally (without containerising the app)

Start only the database, then run backend and frontend on the host:

```bash
docker compose up -d postgres
```

Backend:

```bash
cd backend
cp .env.example .env

python -m venv .venv
.\.venv\Scripts\Activate.ps1     # Windows PowerShell
source .venv/bin/activate         # macOS / Linux / Git Bash

pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Frontend:

```bash
cd frontend
cp .env.example .env
npm install
npm run dev
```

> `backend/.env` sets `POSTGRES_HOST=localhost` for this route. Compose
> overrides it to `postgres` for the containerised route, so both work from the
> same file.

## Troubleshooting

If `database.status` is `error`, PostgreSQL is not reachable. Check
`docker compose ps` and that `POSTGRES_*` in `backend/.env` matches the root
`.env`. The API deliberately stays up and returns HTTP 200 with
`status: "degraded"`, so the frontend can report the failure instead of showing
nothing.

If port 5432, 8000 or 5173 is already taken, change `POSTGRES_HOST_PORT`,
`BACKEND_HOST_PORT` or `FRONTEND_HOST_PORT` in the root `.env`.

## Endpoints

| Method | Path                          | Purpose                                  |
| ------ | ----------------------------- | ---------------------------------------- |
| GET    | `/`                           | Service banner                           |
| GET    | `/api/v1/health/ping`         | Liveness, touches no dependency          |
| GET    | `/api/v1/health`              | Readiness incl. PostgreSQL probe         |
| GET    | `/api/v1/wallet`              | Get the wallet (404 if not initialised)  |
| POST   | `/api/v1/wallet/initialize`   | Create the wallet if absent (idempotent) |
| POST   | `/api/v1/wallet/reset`        | Restore cash to the opening capital      |
| GET    | `/api/v1/market-data/quote`   | Current RELIANCE quote                   |
| GET    | `/api/v1/market-data/candles` | Historical OHLCV candles                 |
| GET    | `/api/v1/market-data/provider`| Feed capabilities and limitations        |
| POST   | `/api/v1/trading/orders`      | Place an order                           |
| GET    | `/api/v1/trading/orders`      | Order history (includes rejections)      |
| GET    | `/api/v1/trading/trades`      | Trade history                            |
| GET    | `/api/v1/trading/position`    | Current position                         |
| GET    | `/api/v1/trading/portfolio`   | Cash, position and P&L                   |
| GET    | `/docs`                       | Swagger UI                               |

### Wallet

The platform has exactly one account. `wallet.id` is pinned to `1` by a CHECK
constraint, so a second wallet cannot be inserted even by direct SQL.

```bash
# Create with the configured opening capital (INR 10,00,000) -> 201
curl -X POST http://localhost:8000/api/v1/wallet/initialize

# Calling it again returns the existing wallet untouched -> 200
curl -X POST http://localhost:8000/api/v1/wallet/initialize

# Or open with a specific amount
curl -X POST http://localhost:8000/api/v1/wallet/initialize   -H "Content-Type: application/json" -d '{"initial_balance":"250000.00"}'

# Read it
curl http://localhost:8000/api/v1/wallet

# Restore cash_balance to initial_balance
curl -X POST http://localhost:8000/api/v1/wallet/reset

# Re-open at a different amount
curl -X POST http://localhost:8000/api/v1/wallet/reset   -H "Content-Type: application/json" -d '{"initial_balance":"500000.00"}'
```

Response:

```json
{
  "id": 1,
  "currency": "INR",
  "initial_balance": "1000000.00",
  "cash_balance": "1000000.00",
  "created_at": "2026-08-25T09:16:45.886410Z",
  "updated_at": "2026-08-25T09:16:45.886410Z"
}
```

> Monetary values are JSON **strings**, not numbers. The columns are
> `NUMERIC(18, 2)` and the Python type is `Decimal`; serialising through a
> JavaScript `number` would reintroduce the binary rounding error the schema
> exists to avoid. Parse them with a decimal library on the frontend.

Errors use a consistent envelope:

```json
{ "error": { "code": "wallet_not_found", "message": "Wallet has not been initialised. POST /wallet/initialize first." } }
```

Configure the opening capital in `backend/.env`:

```bash
WALLET_INITIAL_BALANCE=1000000.00
WALLET_CURRENCY=INR
```

## Market data

### Architecture

```
        RelianceMarketDataService     platform rules: one instrument, interval checks
                    |
                    v
          MarketDataProvider          the contract (abstract)
                    |
                    v
        YahooFinanceProvider          the integration
                    |
                    v
        Yahoo /v8/finance/chart       external API
```

Nothing above `MarketDataProvider` imports a vendor. Swapping feeds is a
config change:

```bash
MARKET_DATA_PROVIDER=yahoo      # backend/.env
```

Adding a provider means writing one module and adding one line to
`app/market_data/registry.py`.

### What the default provider can and cannot do

Yahoo Finance is the default because it needs no credentials and serves NSE.
Its limits were measured, not assumed:

| Capability          | Status | Detail                                                     |
| ------------------- | ------ | ---------------------------------------------------------- |
| Last price          | Yes    | Measured ~5 s behind the exchange during market hours       |
| Volume, OHLC, timestamp | Yes | Session values in `meta`                                    |
| Historical candles  | Yes    | 1m, 5m, 15m, 30m, 1h, 1d, 1wk, 1mo                          |
| **Bid / ask**       | **No** | Depth needs `/v7/finance/quote`, which returns **HTTP 401** |
| **Live streaming**  | **No** | No public WebSocket feed exists                             |

`bid` and `ask` are therefore always `null`, and `subscribe_live_data()` raises
`LiveDataNotSupportedError` rather than quietly polling. Query the limitations
at runtime:

```bash
curl http://localhost:8000/api/v1/market-data/provider
```

To get real bid/ask and a push feed you need a licensed broker API — Zerodha
Kite Connect or Upstox — which requires a funded account, a paid subscription
and a daily login flow. That is a provider swap, not a rewrite.

### Endpoints

```bash
# Current quote
curl http://localhost:8000/api/v1/market-data/quote

# Daily candles, most recent 3
curl "http://localhost:8000/api/v1/market-data/candles?interval=1d&limit=3"

# Intraday
curl "http://localhost:8000/api/v1/market-data/candles?interval=1m&limit=2"

# Explicit window
curl "http://localhost:8000/api/v1/market-data/candles?interval=1d&start=2026-08-01T00:00:00Z&end=2026-08-10T00:00:00Z"

# What the feed supports
curl http://localhost:8000/api/v1/market-data/provider
```

Quote response:

```json
{
  "symbol": "RELIANCE", "exchange": "NSE",
  "last_price": "1312.70", "bid": null, "ask": null,
  "volume": 6819709, "timestamp": "2026-08-25T09:44:59Z",
  "previous_close": "1309.80", "day_open": "1304.30",
  "day_high": "1317.10", "day_low": "1300.00",
  "currency": "INR", "provider": "yahoo", "is_delayed": false
}
```

Prices are JSON **strings** carrying `Decimal` values, as with the wallet.
Timestamps are UTC; NSE trades 09:15–15:30 IST (03:45–10:00 UTC).

### Credentials

The default provider needs none. Providers that do read them from environment
variables — never from source:

```bash
MARKET_DATA_API_KEY=            # backend/.env, gitignored
MARKET_DATA_API_SECRET=
```

They are typed `SecretStr`, so they cannot leak into logs or tracebacks.

## Trading engine

### Components

```
TradingEngine                 orchestration + the transaction boundary
  |-- OrderManager            order rows and their state
  |-- ExecutionEngine         fills and trade records
  |-- PositionManager         position accounting
  |-- PortfolioManager        cash movement and valuation
  +-- PnLCalculator           the arithmetic
```

The engine imports no web framework and no market-data provider. Execution
prices are passed in, so the same engine can be driven by an HTTP request, a
backtest harness or a test.

### Position model

`quantity` carries the direction: **> 0 long**, **= 0 flat**, **< 0 short**.
`average_price` is the weighted average entry price of the open quantity and
resets to zero when flat. `realized_pnl` accumulates across the whole history
and survives going flat.

The four sides map to two directions - `BUY` and `BUY_TO_COVER` increase
quantity, `SELL` and `SHORT_SELL` decrease it. They differ in **intent**, which
the engine enforces:

| Side           | Rule                                                    |
| -------------- | ------------------------------------------------------- |
| `BUY`          | May cross zero: covers a short, then opens a long        |
| `SELL`         | Closing only - may not exceed the long position          |
| `SHORT_SELL`   | May cross zero: closes a long, then opens a short        |
| `BUY_TO_COVER` | Closing only - may not exceed the short position         |

Selling more than you hold is a short, so it must be stated explicitly with
`SHORT_SELL` rather than happening silently. Same for `BUY` past a short.

### Cash model

Cash moves with the fill and nothing else: a buy debits `quantity x price`, a
sell credits it. One rule covers all four sides and yields correct P&L in both
directions:

```
Long   BUY   100 @ 1400  (-140,000),  SELL  100 @ 1450  (+145,000)  ->  +5,000
Short  SHORT 100 @ 1450  (+145,000),  COVER 100 @ 1400  (-140,000)  ->  +5,000
```

Debits are checked before they are applied, so an unaffordable order raises
`insufficient_funds` rather than tripping the wallet non-negative constraint
at COMMIT.

> **Known gap.** Short proceeds are credited as spendable cash and no margin is
> reserved against an open short, so short size is not bounded by account
> equity the way a real broker would bound it. Margin, brokerage, taxes and
> slippage are all out of scope for this stage.

### Atomicity

A filled order writes to four tables - `orders`, `trades`, `positions`,
`wallet`. It happens inside **one transaction**, with the wallet and position
rows locked via `SELECT ... FOR UPDATE` before anything is computed. An order
lands completely or not at all; it can never debit cash without moving the
position. Two tests inject a failure mid-order and assert nothing reached the
database.

Rejected orders are still persisted, with a `rejection_reason`, so the audit
trail shows what was attempted rather than only what succeeded.

### Worked example

```bash
API=http://localhost:8000/api/v1

curl -X POST $API/wallet/initialize

curl -X POST $API/trading/orders -H "Content-Type: application/json" \
  -d '{"side":"BUY","quantity":100,"execution_price":"1400"}'
# position +100 @ 1400, cash -140,000

curl -X POST $API/trading/orders -H "Content-Type: application/json" \
  -d '{"side":"SELL","quantity":100,"execution_price":"1450"}'
# position 0, realized +5,000

curl -X POST $API/trading/orders -H "Content-Type: application/json" \
  -d '{"side":"SHORT_SELL","quantity":100,"execution_price":"1450"}'
# position -100 @ 1450

curl -X POST $API/trading/orders -H "Content-Type: application/json" \
  -d '{"side":"BUY","quantity":100,"execution_price":"1400"}'
# position 0, realized +5,000 (cumulative 10,000)

curl "$API/trading/portfolio?mark_price=1400"
curl $API/trading/orders
curl $API/trading/trades
```

Reversal in one order - hold +100, then `SHORT_SELL 150 @ 1450`: closes the
100 long for +5,000 and opens a 50 short at 1450, the new basis being the fill
price.

Portfolio valuation takes `mark_price` as a **query parameter** rather than
fetching it, which is what keeps the engine independent of the market-data
layer. Without it, unrealized P&L and position value report zero.

## Migrations

Alembic runs inside the backend container. Drop `docker compose exec backend`
to run these on the host instead.

```bash
# Apply all pending migrations
docker compose exec backend alembic upgrade head

# Current revision / history
docker compose exec backend alembic current
docker compose exec backend alembic history --verbose

# Roll back one revision (enum types drop too, so re-upgrading works)
docker compose exec backend alembic downgrade -1

# After changing a model, generate a new migration and review it before applying
docker compose exec backend alembic revision --autogenerate -m "describe change"
```

## Tests

Tests run against a **real PostgreSQL database** — never SQLite — because the
wallet depends on `NUMERIC` precision, CHECK constraints and
`SELECT ... FOR UPDATE`. A dedicated `virtual_trading_test` database is
created, migrated with Alembic and dropped around each run, so development
data is never touched.

```bash
# Run the suite
docker compose exec backend pytest

# Verbose, or a single file
docker compose exec backend pytest -v
docker compose exec backend pytest tests/test_wallet_persistence.py

# On the host instead (needs postgres reachable on localhost:5432)
cd backend && pip install -r requirements-dev.txt && pytest
```

121 tests.

* **Wallet** - creation, retrieval, reset, persistence across a simulated
  restart, decimal precision, singleton and non-negative constraints.
* **Market data** - payload mapping, null-bar handling, interval and window
  parameters, failure mapping, capability honesty. Never touches the network:
  provider tests use an httpx `MockTransport`, endpoint tests inject a fake
  provider through FastAPI dependency override.
* **Position accounting** (`test_position_accounting.py`) - pure arithmetic,
  no database: long entry/exit, partial exit, short entry/cover, both
  reversals, weighted averaging, P&L signs, rounding.
* **Trading engine** (`test_trading_engine.py`) - the same cases against real
  PostgreSQL, plus cash movement, invalid orders, insufficient funds, the
  audit trail, and two atomicity tests that inject a mid-order failure and
  assert nothing was written.

## Not in this stage

Margin and leverage rules, brokerage, taxes, slippage, partial fills, limit
and stop orders, WebSocket streaming, the React trading UI, TradingView
charts, technical indicators, strategies, ML, backtesting, market-data
persistence, Redis and APScheduler jobs. Authentication is out of scope
permanently - this is a single-user local system by design.
