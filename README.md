# Virtual Trading Platform — NSE:RELIANCE

Single-user, single-instrument **paper trading** platform. No real money, no
broker connectivity, no login — there is exactly one virtual wallet.

> **Current stage: 1 — Foundation.**
> Project structure, database configuration, FastAPI health API and a React +
> TypeScript page that proves end-to-end connectivity. Trading logic, market
> data, charts, indicators, strategies and backtesting are **not** implemented.

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
│   ├── alembic/           migration environment
│   └── app/
│       ├── core/          config + logging
│       ├── db/            engine, session, declarative base
│       ├── models/        ORM models (empty in Stage 1)
│       ├── schemas/       Pydantic contracts
│       ├── services/      business logic
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

| Method | Path                  | Purpose                              |
| ------ | --------------------- | ------------------------------------ |
| GET    | `/`                   | Service banner                       |
| GET    | `/api/v1/health/ping` | Liveness, touches no dependency      |
| GET    | `/api/v1/health`      | Readiness incl. PostgreSQL probe     |
| GET    | `/docs`               | Swagger UI                           |

## Not in this stage

Trading logic (buy / sell / short), wallet and order tables, market data,
WebSocket streaming, TradingView charts, technical indicators, strategies,
backtesting, Redis, APScheduler jobs. Authentication is out of scope
permanently — this is a single-user local system by design.
