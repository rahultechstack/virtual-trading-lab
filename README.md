# Virtual Trading Platform — NSE:RELIANCE

Single-user, single-instrument **paper trading** platform. No real money, no
broker connectivity, no login — there is exactly one virtual wallet.

> **Current stage: 2 — Database and virtual wallet.**
> Stage 1 delivered the project structure, health API and frontend
> connectivity. Stage 2 adds the persistent wallet: schema, migration, service
> layer, REST API and tests. Trading logic, market data, charts, indicators,
> strategies and backtesting are **not** implemented.

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

## Migrations

Alembic runs inside the backend container. Drop `docker compose exec backend`
to run these on the host instead.

```bash
# Apply all pending migrations
docker compose exec backend alembic upgrade head

# Current revision / history
docker compose exec backend alembic current
docker compose exec backend alembic history --verbose

# Roll back one revision
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

Coverage: wallet creation (defaults, custom amount, idempotency, validation),
retrieval (found and not-found), reset (restore and re-open), persistence
across a simulated restart via a fresh engine, exact decimal precision, and the
database-level singleton and non-negative-balance constraints.

## Not in this stage

Buy / sell / short selling, the trading engine, positions and trades tables,
market data, WebSocket streaming, TradingView charts, technical indicators,
strategies, backtesting, Redis and APScheduler jobs. Authentication is out of
scope permanently — this is a single-user local system by design.
