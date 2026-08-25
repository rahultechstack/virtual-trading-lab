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

- Python 3.11+
- Node.js 18+ and npm
- Docker Desktop (for PostgreSQL)

## Layout

```
my-project/
├── docker-compose.yml     PostgreSQL service
├── .env                   infra env (from .env.example)
├── backend/
│   ├── alembic/           migration environment
│   └── app/
│       ├── core/          config + logging
│       ├── db/            engine, session, declarative base
│       ├── models/        ORM models (empty in Stage 1)
│       ├── schemas/       Pydantic contracts
│       ├── services/      business logic
│       └── api/v1/        HTTP endpoints
└── frontend/src/
    ├── api/               HTTP client + endpoint functions
    ├── types/             TS contracts mirroring backend schemas
    ├── hooks/             data fetching
    ├── components/        UI
    └── styles/
```

## Install & run

### 1. Database

```bash
cp .env.example .env
docker compose up -d
docker compose ps
```

### 2. Backend

```bash
cd backend
cp .env.example .env

python -m venv .venv
# Windows PowerShell:
.\.venv\Scripts\Activate.ps1
# macOS / Linux / Git Bash:
source .venv/bin/activate

pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Serves on <http://localhost:8000> — interactive docs at `/docs`.

### 3. Frontend

```bash
cd frontend
cp .env.example .env
npm install
npm run dev
```

Serves on <http://localhost:5173>.

## Verify

```bash
# Database container is healthy
docker compose ps
# STATUS column must read: Up (healthy)

# Backend liveness (no database required)
curl http://localhost:8000/api/v1/health/ping
# -> {"message":"pong","timestamp":"..."}

# Backend readiness (includes a live SELECT 1 against PostgreSQL)
curl http://localhost:8000/api/v1/health
# -> "status":"ok" and "database":{"status":"ok", ... }

# Frontend type safety
cd frontend && npm run typecheck
```

Then open <http://localhost:5173>. The **Backend connection** card must show
`API OK`, `PostgreSQL OK` and a latency figure — that is the browser →
FastAPI → PostgreSQL round trip working.

If `database.status` is `error`, PostgreSQL is not reachable: check
`docker compose ps` and that `POSTGRES_*` in `backend/.env` matches the root
`.env`. The API stays up and returns HTTP 200 with `status: "degraded"` by
design, so the frontend can report the failure instead of showing nothing.

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
