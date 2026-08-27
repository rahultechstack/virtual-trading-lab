# Technical Architecture — RELIANCE Virtual Trading Platform

> **Purpose of this document.** If you come back to this project in six months
> — or if an AI coding agent is asked to change it — this file should be enough
> to know *where everything is* and *how to modify it safely*.
>
> It describes the **actual implementation** at commit `1f0a749` on branch
> `main`. Nothing here is aspirational. Anything absent from the code is
> explicitly marked **NOT IMPLEMENTED**.

---

## Table of contents

| §  | Section |
| -- | ------- |
| 1  | [System Architecture](#1-system-architecture) |
| 2  | [Repository Structure](#2-repository-structure) |
| 3  | [Backend Architecture](#3-backend-architecture) |
| 4  | [Trading Engine Architecture](#4-trading-engine-architecture) |
| 5  | [Market Data Architecture](#5-market-data-architecture) |
| 6  | [Frontend Architecture](#6-frontend-architecture) |
| 7  | [Database Architecture](#7-database-architecture) |
| 8  | [API Architecture](#8-api-architecture) |
| 9  | [WebSocket Architecture](#9-websocket-architecture) |
| 10 | [Data Flow](#10-data-flow) |
| 11 | [Configuration Architecture](#11-configuration-architecture) |
| 12 | [Error Handling](#12-error-handling) |
| 13 | [Testing Architecture](#13-testing-architecture) |
| 14 | [Dependency Map](#14-dependency-map) |
| 15 | [Modification Guide](#15-modification-guide--where-do-i-modify-x) |
| 16 | [Safe Modification Rules](#16-safe-modification-rules) |
| 17 | [Architecture Risks](#17-architecture-risks) |

---

## Executive summary

| Property | Value |
| -------- | ----- |
| Domain | Single-instrument paper trading, **NSE:RELIANCE** only |
| Backend | Python 3.11, FastAPI 0.115.6, SQLAlchemy 2.0.36 async, PostgreSQL 16 |
| Frontend | React 18.3 + TypeScript 5.6, Vite 5.4, `lightweight-charts` 4.2 |
| Real-time | One WebSocket endpoint; server polls or pushes depending on provider |
| Background jobs | APScheduler — a price poller and a portfolio snapshotter |
| Authentication | **NONE.** No login, no users, no tokens, no sessions. See §8.1. |
| Money type | `Decimal` end to end; `NUMERIC(18,2)` / `NUMERIC(18,4)` in Postgres |
| Total source | ~20,470 lines across 164 tracked files |
| Backend tests | 13 pytest modules, ~353 test functions, against real PostgreSQL |
| Frontend tests | **NONE.** Only `tsc --noEmit` typechecking. See §13.5. |

---

## 1. System Architecture

### 1.1 Layer diagram (components that actually exist)

```
+===========================================================================+
|                              BROWSER                                      |
|                                                                           |
|   frontend/src/main.tsx  ->  App.tsx  ->  useHashRoute (5 hash routes)    |
|                                                                           |
|   +--------------------+  +---------------------------------------------+ |
|   |  Terminal.tsx      |  |  history/ pages                             | |
|   |  TerminalHeader    |  |  TradeHistoryPage   OrderHistoryPage        | |
|   |  PriceChart        |  |  PortfolioHistoryPage   PerformancePage     | |
|   |   + OscillatorPane |  |  EquityCurve   PageShell                    | |
|   |  PositionPanel     |  +---------------------------------------------+ |
|   |  TradingPanel      |                                                 |
|   |  WalletPanel       |   HOOKS (all state lives here - no Redux)       |
|   |  OrdersPanel       |   useLivePrice  useAccount  useIndicators       |
|   |  TradeHistory      |   useHashRoute  useHealth                       |
|   +--------------------+                                                 |
+============================|=================|===========================+
                             |                 |
         WebSocket           |                 |   HTTP (fetch)
   ws://.../api/v1/          |                 |   src/api/client.ts
        stream/prices        |                 |   -> api/{trading,wallet,
                             |                 |       marketData,indicators,
                             |                 |       portfolio,health}.ts
+============================v=================v===========================+
|                     FASTAPI  (backend/app/main.py)                        |
|                                                                           |
|   CORSMiddleware  ->  DomainError exception handler  ->  api_router       |
|                                                                           |
|   app/api/v1/router.py aggregates 8 endpoint modules:                    |
|   health | wallet | market_data | indicators | trading | stream |         |
|   portfolio | backtest                                                    |
|                                                                           |
|   DI:  app/api/deps.py         DbSession = Annotated[AsyncSession, ...]  |
|        market_data.py          get_market_data_service(Depends(          |
|                                get_provider))                             |
+========|============|=============|==============|=======================+
         |            |             |              |
         v            v             v              v
+----------------+ +-----------+ +-----------+ +--------------------------+
| SERVICES       | | ANALYTICS | | INDICATORS| | STRATEGIES / BACKTEST    |
| WalletService  | | Snapshot- | | Indicator-| | registry.create_strategy |
| HealthService  | | Service   | | Service   | | MovingAverageCrossover   |
| Reliance-      | | Perfor-   | | library.py| | BacktestEngine           |
| MarketData-    | | mance-    | | (TA-Lib)  | | BacktestPortfolio        |
| Service        | | Analyzer  | |           | | results.summarise        |
+-------|--------+ +-----|-----+ +-----|-----+ +------------|-------------+
        |                |             |                    |
        |                v             |                    v
        |    +==================================================+
        |    |           TRADING ENGINE  (app/trading/)         |
        |    |                                                  |
        |    |   TradingEngine  (owns the transaction boundary) |
        |    |     |-- OrderManager        orders table         |
        |    |     |-- ExecutionEngine     fills + trades table |
        |    |     |     |-- SpreadModel                        |
        |    |     |     |-- SlippageModel                      |
        |    |     |     +-- FeeCalculator                      |
        |    |     |-- PositionManager  + apply_fill() (pure)   |
        |    |     |-- PortfolioManager    cash + valuation     |
        |    |     +-- PnLCalculator       pure arithmetic      |
        |    |                                                  |
        |    |   NOTE: there is NO RiskManager class. See §4.9. |
        |    +====================|=============================+
        |                         |
        v                         v
+---------------------+   +-------------------------------------+
| MARKET DATA         |   | REPOSITORIES / ORM                  |
| registry.get_       |   | WalletRepository (only repository)  |
|   provider()        |   | app/db/session.py  engine +         |
|  |-- YahooFinance-  |   |   SessionLocal + get_session()      |
|  |     Provider     |   | app/models/{wallet, trading,        |
|  +-- MockMarketData-|   |   portfolio_snapshot, enums}.py     |
|        Provider     |   +-----------------|-------------------+
+----------|----------+                     |
           |                                v
           |                +-------------------------------+
           |                |   PostgreSQL 16               |
           |                |   wallet | orders | trades |  |
           |                |   positions | portfolio_      |
           |                |   snapshots | alembic_version |
           |                +-------------------------------+
           v
   https://query1.finance.yahoo.com/v8/finance/chart   (external, keyless)

+===========================================================================+
|                    REAL-TIME + BACKGROUND JOBS                            |
|                                                                           |
|  app/realtime/price_stream.py     PriceStreamService                      |
|      PUSH mode : provider.subscribe_live_data()  (mock provider only)     |
|      POLL mode : APScheduler interval job "price-poll"  (yahoo)           |
|                        |                                                  |
|                        v                                                  |
|  app/realtime/connection_manager.py   ConnectionManager.broadcast()       |
|                        |                                                  |
|                        +--> every connected WebSocket client              |
|                                                                           |
|  app/analytics/scheduler.py       APScheduler interval job                |
|                                   "portfolio-snapshot"                    |
|                                   -> SnapshotService.capture()            |
+===========================================================================+
```

### 1.2 The two data paths

The system deliberately splits **market data** from **account state**:

```
  PRICE  (push, one-way, no DB)         COMMANDS + ACCOUNT (request/response)
  ------------------------------        ------------------------------------
  provider                              browser
    -> PriceStreamService                 -> fetch (api/client.ts)
    -> ConnectionManager                  -> FastAPI router
    -> WebSocket                          -> service / TradingEngine
    -> useLivePrice hook                  -> PostgreSQL
    -> tick.last_price                    -> response
    -> markPrice prop                     -> useAccount setState
```

`useLivePrice` never writes to the database. `useAccount` never listens to the
socket — it receives `markPrice` as a plain string prop from `Terminal.tsx`.

### 1.3 Startup / shutdown order

`app/main.py:lifespan` (an `asynccontextmanager`):

```
STARTUP                             SHUTDOWN (reverse)
  configure_logging()                 stop_snapshot_scheduler()
  log startup banner                  shutdown_price_stream()
  start_snapshot_scheduler()          close_provider()
  yield  <-- app serves               dispose_engine()
```

The **price stream is not started at boot.**
`app/api/v1/endpoints/stream.py` starts it lazily on the first WebSocket
connection (`if not service.is_running: await service.start()`), so an idle
server makes zero upstream calls.

---

## 2. Repository Structure

### 2.1 Complete tree (164 tracked files)

```
virtual-trading-lab/
├── .env.example                  docker-compose infrastructure vars
├── .gitignore
├── README.md                     1,173-line narrative guide (stage by stage)
├── ARCHITECTURE.md               <- this file
├── docker-compose.yml            postgres + backend + frontend
│
├── backend/
│   ├── Dockerfile                base / dev / prod targets
│   ├── .dockerignore
│   ├── .env.example              every backend setting, documented
│   ├── alembic.ini               URL injected at runtime from settings
│   ├── pyproject.toml            pytest config only (no build system)
│   ├── requirements.txt          runtime deps, pinned
│   ├── requirements-dev.txt      pytest + pytest-asyncio
│   │
│   ├── alembic/
│   │   ├── env.py                async migration env, reads app settings
│   │   ├── script.py.mako
│   │   └── versions/
│   │       ├── 20260825_0912_create_wallet_table.py                 ea97efd67efb
│   │       ├── 20260825_0956_create_orders_trades_and_positions.py  44b98124fbd4
│   │       ├── 20260825_1010_add_execution_costs_and_net_pnl.py     b41705c11d09
│   │       └── 20260825_1119_add_portfolio_snapshots.py             51917e5fa5f1  (head)
│   │
│   ├── app/
│   │   ├── main.py               ENTRY POINT — create_app(), lifespan
│   │   │
│   │   ├── core/
│   │   │   ├── config.py         Settings (pydantic-settings), settings singleton
│   │   │   ├── exceptions.py     DomainError hierarchy
│   │   │   └── logging.py        configure_logging(), get_logger()
│   │   │
│   │   ├── db/
│   │   │   ├── base.py           Base, TimestampMixin, NAMING_CONVENTION
│   │   │   └── session.py        engine, SessionLocal, get_session, dispose_engine
│   │   │
│   │   ├── api/
│   │   │   ├── deps.py           DbSession type alias
│   │   │   └── v1/
│   │   │       ├── router.py     api_router — includes all 8 modules
│   │   │       └── endpoints/
│   │   │           ├── health.py       GET /health, /health/ping
│   │   │           ├── wallet.py       GET/POST /wallet*
│   │   │           ├── market_data.py  GET /market-data/*  + get_market_data_service
│   │   │           ├── indicators.py   GET /indicators*
│   │   │           ├── trading.py      POST/GET /trading/*
│   │   │           ├── stream.py       WS /stream/prices, GET /stream/status
│   │   │           ├── portfolio.py    GET/POST /portfolio/*
│   │   │           └── backtest.py     GET /strategies, POST /strategies/backtest
│   │   │
│   │   ├── models/               SQLAlchemy ORM
│   │   │   ├── __init__.py       re-exports ALL models (Alembic autogenerate needs this)
│   │   │   ├── enums.py          OrderSide, OrderStatus, OrderType
│   │   │   ├── wallet.py         Wallet, WALLET_ID
│   │   │   ├── trading.py        Order, Trade, Position, MAX_ORDER_QUANTITY
│   │   │   └── portfolio_snapshot.py   PortfolioSnapshot, SnapshotSource
│   │   │
│   │   ├── schemas/              Pydantic request/response contracts
│   │   │   ├── health.py         HealthResponse, PingResponse, DatabaseHealth
│   │   │   ├── wallet.py         WalletResponse, WalletInitializeRequest, WalletResetRequest
│   │   │   ├── market_data.py    Interval, Quote, Candle, CandleSeries, ProviderCapabilities
│   │   │   ├── indicators.py     IndicatorResponse, IndicatorSetResponse, catalogue types
│   │   │   ├── trading.py        PlaceOrderRequest, OrderResponse, TradeResponse,
│   │   │   │                     PositionResponse, PortfolioResponse, ChargesResponse,
│   │   │   │                     OrderResultResponse, ExecutionCostPreview
│   │   │   ├── portfolio.py      SnapshotResponse, SnapshotSeriesResponse,
│   │   │   │                     PerformanceResponse, TradeExtremeResponse
│   │   │   └── backtest.py       BacktestRequest, BacktestResultSchema, StrategySchema
│   │   │
│   │   ├── repositories/
│   │   │   └── wallet_repository.py    WalletRepository (the ONLY repository)
│   │   │
│   │   ├── services/
│   │   │   ├── health_service.py       HealthService + health_service singleton
│   │   │   ├── wallet_service.py       WalletService
│   │   │   └── market_data_service.py  RelianceMarketDataService, MAX_CANDLES
│   │   │
│   │   ├── trading/              THE TRADING ENGINE
│   │   │   ├── engine.py         TradingEngine, OrderResult
│   │   │   ├── order_manager.py  OrderManager
│   │   │   ├── execution.py      ExecutionEngine, Fill
│   │   │   ├── position_manager.py  PositionManager, apply_fill, FillOutcome
│   │   │   ├── portfolio.py      PortfolioManager, PortfolioSnapshot (dataclass)
│   │   │   ├── pnl.py            PnLCalculator, to_money, to_average, CENT
│   │   │   ├── fees.py           FeeCalculator, ChargeBreakdown, Segment, to_rupee
│   │   │   ├── slippage.py       SlippageModel, SlippageResult, SlippageType
│   │   │   └── spread.py         SpreadModel, SpreadResult, BidAsk
│   │   │
│   │   ├── market_data/
│   │   │   ├── base.py           MarketDataProvider (ABC)
│   │   │   ├── yahoo.py          YahooFinanceProvider
│   │   │   ├── mock.py           MockMarketDataProvider
│   │   │   └── registry.py       _PROVIDERS, get_provider, create_provider, close_provider
│   │   │
│   │   ├── realtime/
│   │   │   ├── connection_manager.py   ConnectionManager, ConnectionStats,
│   │   │   │                           ConnectionLimitReached
│   │   │   └── price_stream.py         PriceStreamService, StreamMode, BidAskSource,
│   │   │                               get_price_stream, get_connection_manager,
│   │   │                               shutdown_price_stream
│   │   │
│   │   ├── indicators/
│   │   │   ├── definitions.py    CATALOGUE, IndicatorSpec, IndicatorType, Pane,
│   │   │   │                     parse_spec, parse_specs, InvalidIndicatorError
│   │   │   ├── library.py        CALCULATORS dispatch table, sma/ema/rsi/macd/
│   │   │   │                     bbands/vwap, warmup_for, to_decimal
│   │   │   └── service.py        IndicatorService, indicator_service, candles_to_frame
│   │   │
│   │   ├── strategies/
│   │   │   ├── base.py           Strategy (ABC), Signal, Decision, StrategyContext,
│   │   │   │                     StrategyParam
│   │   │   ├── ma_crossover.py   MovingAverageCrossover
│   │   │   └── registry.py       _STRATEGIES, create_strategy, describe_all,
│   │   │                         UnknownStrategyError, InvalidStrategyParamsError
│   │   │
│   │   ├── backtest/
│   │   │   ├── engine.py         BacktestEngine, BacktestConfig, PositionSizer,
│   │   │   │                     FillTiming, SizingMode
│   │   │   ├── portfolio.py      BacktestPortfolio, BacktestTrade, EquityPoint,
│   │   │   │                     InsufficientCash
│   │   │   └── results.py        BacktestResult, summarise, max_drawdown, DrawdownResult
│   │   │
│   │   └── analytics/
│   │       ├── snapshots.py      SnapshotService
│   │       ├── performance.py    PerformanceAnalyzer, PerformanceSummary, TradeExtreme
│   │       └── scheduler.py      start/stop_snapshot_scheduler, capture_periodic_snapshot
│   │
│   └── tests/
│       ├── conftest.py                    prepared_database, clean_tables, session, client
│       ├── fixtures/yahoo_payloads.py     canned Yahoo chart JSON
│       ├── _ws_probe.py                   manual WS probe script (not a pytest module)
│       ├── test_wallet_api.py             10 tests
│       ├── test_wallet_persistence.py      6 tests
│       ├── test_market_data_provider.py   20 tests
│       ├── test_market_data_api.py        18 tests
│       ├── test_indicators.py             47 tests
│       ├── test_position_accounting.py    23 tests
│       ├── test_trading_engine.py         38 tests
│       ├── test_execution_costs.py        29 tests
│       ├── test_realistic_execution.py    22 tests
│       ├── test_realtime.py               35 tests
│       ├── test_stream_endpoint.py        12 tests
│       ├── test_strategies.py             30 tests
│       ├── test_portfolio_history.py      31 tests
│       └── test_backtest.py               32 tests
│
└── frontend/
    ├── Dockerfile                deps / dev / build / prod (nginx) targets
    ├── .dockerignore
    ├── .env.example              VITE_API_BASE_URL, VITE_API_V1_PREFIX, VITE_WS_BASE_URL
    ├── index.html                #root mount point
    ├── nginx.conf                production SPA hosting
    ├── package.json              react 18.3, lightweight-charts 4.2, vite 5.4
    ├── tsconfig.json             strict, paths: @/* -> ./src/*
    ├── tsconfig.node.json
    ├── vite.config.ts            react plugin, @ alias, port 5173, polling under Docker
    └── src/
        ├── main.tsx              ENTRY POINT — createRoot + StrictMode
        ├── App.tsx               hash-route switch over 5 pages
        ├── vite-env.d.ts
        ├── api/
        │   ├── client.ts         apiGet/apiPost/apiUrl/wsUrl/ApiError
        │   ├── health.ts         fetchHealth
        │   ├── marketData.ts     fetchCandles
        │   ├── indicators.ts     fetchIndicators
        │   ├── trading.ts        placeOrder, fetchOrders, fetchTrades,
        │   │                     fetchPosition, fetchPortfolio
        │   ├── wallet.ts         fetchWallet, initializeWallet, resetWallet
        │   └── portfolio.ts      fetchSnapshots, fetchPerformance, captureSnapshot
        ├── hooks/
        │   ├── useHashRoute.ts   Route type, NAV, useHashRoute
        │   ├── useLivePrice.ts   WebSocket client + reconnect/backoff/staleness
        │   ├── useAccount.ts     wallet+position+portfolio+orders+trades, refresh()
        │   ├── useIndicators.ts  indicator selection (localStorage) + fetch
        │   └── useHealth.ts      health probe  [UNUSED by any rendered component]
        ├── components/
        │   ├── NavBar.tsx
        │   ├── StatusBadge.tsx        [only used by HealthCard]
        │   ├── HealthCard.tsx         [DEAD CODE — not referenced from App.tsx]
        │   ├── terminal/
        │   │   ├── Terminal.tsx       page composition + refresh orchestration
        │   │   ├── TerminalHeader.tsx price banner, provenance badges, reconnect
        │   │   ├── PriceChart.tsx     candles + volume + overlays + timeframe
        │   │   ├── OscillatorPane.tsx one chart per RSI/MACD, time scale synced
        │   │   ├── PositionPanel.tsx
        │   │   ├── TradingPanel.tsx   the ONLY place an order is submitted
        │   │   ├── WalletPanel.tsx
        │   │   ├── OrdersPanel.tsx
        │   │   └── TradeHistory.tsx
        │   └── history/
        │       ├── PageShell.tsx      shared title/loading/error frame
        │       ├── TradeHistoryPage.tsx
        │       ├── OrderHistoryPage.tsx
        │       ├── PortfolioHistoryPage.tsx
        │       ├── PerformancePage.tsx
        │       └── EquityCurve.tsx
        ├── types/
        │   ├── health.ts        mirrors schemas/health.py
        │   ├── marketData.ts    mirrors schemas/market_data.py + TIMEFRAMES
        │   ├── indicators.ts    mirrors schemas/indicators.py + INDICATOR_PRESETS
        │   ├── trading.ts       mirrors schemas/trading.py + SIDE_LABELS, isBullishSide
        │   ├── portfolio.ts     mirrors schemas/portfolio.py
        │   └── stream.ts        mirrors the payload built in price_stream.build_tick
        ├── utils/format.ts      formatRupees, formatMoney, formatQuantity,
        │                        formatPercent, formatTime, formatDateTime,
        │                        signClass, toNumber
        └── styles/
            ├── global.css       217 lines
            └── terminal.css     779 lines
```

### 2.2 Role identification

| Role | Location |
| ---- | -------- |
| **Backend entry point** | `backend/app/main.py` — `create_app()`, module-level `app` |
| **Frontend entry point** | `frontend/src/main.tsx` → `App.tsx` |
| **Controllers / routes** | `backend/app/api/v1/endpoints/` (8 modules), aggregated by `router.py` |
| **Services** | `backend/app/services/` + `app/analytics/` + `app/indicators/service.py` |
| **Models (ORM)** | `backend/app/models/` |
| **Schemas (Pydantic)** | `backend/app/schemas/` |
| **Repositories** | `backend/app/repositories/wallet_repository.py` — *the only one* |
| **Trading engine** | `backend/app/trading/` |
| **Market-data layer** | `backend/app/market_data/` |
| **Strategy layer** | `backend/app/strategies/` |
| **Backtesting** | `backend/app/backtest/` |
| **Frontend components** | `frontend/src/components/` |
| **State management** | React hooks only — `frontend/src/hooks/`. **No Redux, no Zustand, no Context, no React Query.** |
| **Configuration** | `backend/app/core/config.py`, `.env` files, `docker-compose.yml` |
| **Tests** | `backend/tests/` — backend only |

### 2.3 Per-directory detail

#### `backend/app/core/`

| File | Responsibility | Key symbols | Depends on | Depended on by |
| ---- | -------------- | ----------- | ---------- | -------------- |
| `config.py` | Single source of truth for every runtime setting. **Nothing else in the codebase reads `os.environ`.** | `Settings`, `get_settings()` (lru_cached), `settings` singleton, `Settings.DATABASE_URL` (computed field), `_parse_origins` validator | `pydantic`, `pydantic_settings` | almost everything |
| `exceptions.py` | Domain exception hierarchy, each carrying `status_code` + `code` | `DomainError`, `WalletNotFoundError`, `MarketDataError`, `MarketDataUnavailableError`, `UnsupportedSymbolError`, `UnsupportedIntervalError`, `LiveDataNotSupportedError`, `TradingError`, `InvalidOrderError`, `InsufficientFundsError`, `InvalidPositionOperationError` | — | services, engine, providers, `main.py` handler |
| `logging.py` | One stdout stream handler, aligned with uvicorn | `configure_logging()`, `get_logger()` | `config` | `main.py` + every module needing a logger |

#### `backend/app/db/`

| File | Responsibility | Key symbols | Depends on | Depended on by |
| ---- | -------------- | ----------- | ---------- | -------------- |
| `base.py` | Declarative base, naming convention, timestamp mixin | `Base`, `TimestampMixin`, `NAMING_CONVENTION` | `sqlalchemy.orm` | all models, `alembic/env.py` |
| `session.py` | Async engine, sessionmaker, request-scoped session dependency | `engine`, `SessionLocal`, `get_session()`, `dispose_engine()`, `_engine_options()` | `config` | `api/deps.py`, `analytics/scheduler.py`, tests |

`_engine_options()` switches to `NullPool` when `DB_USE_NULL_POOL=true`. This is
what makes the pytest suite work: each test may run in its own event loop, and a
pooled asyncpg connection cannot cross loops.

#### `backend/app/models/`

| File | Classes | Notes |
| ---- | ------- | ----- |
| `enums.py` | `OrderSide`, `OrderStatus`, `OrderType` | `OrderSide.direction` (+1/-1) and `.is_closing_only` drive the whole engine |
| `wallet.py` | `Wallet`, constant `WALLET_ID = 1` | `CHECK (id = 1)` makes the singleton a database guarantee |
| `trading.py` | `Order`, `Trade`, `Position`, `MAX_ORDER_QUANTITY = 10_000_000` | `Order.trades` relationship (`lazy="selectin"`, `cascade="all, delete-orphan"`) |
| `portfolio_snapshot.py` | `PortfolioSnapshot`, `SnapshotSource` | Append-only; `is_equivalent_to()` powers duplicate suppression |

`app/models/__init__.py` re-exports every model — **required** so
`Base.metadata` is complete before Alembic autogenerate inspects it.

#### `frontend/src/` highlights

| File | Responsibility | Depends on | Depended on by |
| ---- | -------------- | ---------- | -------------- |
| `api/client.ts` | The only place `fetch` is called. Builds URLs, unwraps the error envelope into `ApiError`. | `import.meta.env` | every `api/*.ts`, `useLivePrice` (for `wsUrl`) |
| `hooks/useLivePrice.ts` | WebSocket lifecycle, exponential backoff + jitter, ping heartbeat, staleness detection | `api/client.wsUrl`, `types/stream` | `Terminal.tsx`, `PortfolioHistoryPage.tsx` |
| `hooks/useAccount.ts` | Owns wallet + position + portfolio + orders + trades as one consistent set; throttled revaluation | `api/trading`, `api/wallet` | `Terminal.tsx` |
| `hooks/useIndicators.ts` | Enabled-preset selection persisted to `localStorage['vtrader.indicators']`, then fetches values | `api/indicators`, `types/indicators` | `PriceChart.tsx` |
| `utils/format.ts` | Display-only conversion of Decimal strings. **No arithmetic is ever done on money in JS.** | — | most components |

---

## 3. Backend Architecture

### 3.1 Application entry point — `backend/app/main.py`

```python
create_app() -> FastAPI          # application factory, side-effect free
app = create_app()               # module-level instance uvicorn imports
```

Run with `uvicorn app.main:app --reload` from `backend/`.

`create_app()` does exactly four things, in order:

1. Constructs `FastAPI(...)` with `title/version/debug` from `settings`, docs at
   `/docs`, `/redoc`, `/openapi.json`, and `lifespan=lifespan`.
2. Adds `CORSMiddleware` — `allow_origins=settings.CORS_ORIGINS`,
   `allow_credentials=True`, all methods, all headers.
3. Registers **one** exception handler: `@app.exception_handler(DomainError)`.
4. Includes `api_router` under `settings.API_V1_PREFIX` (`/api/v1`), then
   defines `GET /` — a banner listing the main sub-paths.

### 3.2 Routers

`app/api/v1/router.py` builds a single `api_router` and includes eight modules
in this order: `health`, `wallet`, `market_data`, `indicators`, `trading`,
`stream`, `portfolio`, `backtest`. Each module owns its own `prefix` and `tags`:

| Module | Prefix | Tag |
| ------ | ------ | --- |
| `health.py` | `/health` | health |
| `wallet.py` | `/wallet` | wallet |
| `market_data.py` | `/market-data` | market-data |
| `indicators.py` | `/indicators` | indicators |
| `trading.py` | `/trading` | trading |
| `stream.py` | `/stream` | stream |
| `portfolio.py` | `/portfolio` | portfolio |
| `backtest.py` | `/strategies` | strategies |

> Note the mismatch worth remembering: the **backtest module is mounted at
> `/strategies`**, not `/backtest`. The backtest route is
> `POST /api/v1/strategies/backtest`.

Every endpoint function is **transport only**. Each module's docstring says so
explicitly. Business rules live in services and in the trading engine.

### 3.3 Dependency injection

There are exactly **two** DI seams:

```python
# app/api/deps.py
DbSession = Annotated[AsyncSession, Depends(get_session)]

# app/api/v1/endpoints/market_data.py
def get_market_data_service(
    provider: Annotated[MarketDataProvider, Depends(get_provider)],
) -> RelianceMarketDataService:
    return RelianceMarketDataService(provider)

ServiceDep = Annotated[RelianceMarketDataService, Depends(get_market_data_service)]
```

`indicators.py` and `backtest.py` **import `get_market_data_service` from
`market_data.py`** and re-declare their own `ServiceDep`. That import is the
reason a `dependency_overrides[get_market_data_service]` in a test covers all
three modules at once.

Everything else is constructed inline inside the endpoint function:
`TradingEngine(session)`, `WalletService(session)`, `SnapshotService(session)`,
`PerformanceAnalyzer(session)`, `ExecutionEngine(session)`, `BacktestEngine(...)`.
`health_service` and `indicator_service` are module-level singletons.

There is **no DI container** and no `Depends()` for services other than the
market-data service.

### 3.4 Services

| Service | File | Owns | Transaction behaviour |
| ------- | ---- | ---- | --------------------- |
| `HealthService` | `services/health_service.py` | `ping()`, `check_database()`, `full_health()` | read-only `SELECT 1`; never raises |
| `WalletService` | `services/wallet_service.py` | `get_wallet()`, `initialize_wallet()`, `reset_wallet()` | **commits internally**; handles `IntegrityError` race on init |
| `RelianceMarketDataService` | `services/market_data_service.py` | symbol + interval validation, wraps provider results into `CandleSeries` | no database at all |
| `SnapshotService` | `analytics/snapshots.py` | `capture()`, `latest()`, `history()`, `count()`, `purge()` | `commit=True` by default, `commit=False` when enrolled in the engine's transaction |
| `PerformanceAnalyzer` | `analytics/performance.py` | `summary()` — five aggregate queries | read-only; all arithmetic runs in Postgres over `NUMERIC` |
| `IndicatorService` | `indicators/service.py` | `calculate()`, `catalogue()` | no database; pure over candles |

### 3.5 Database layer / ORM

```
app/db/session.py
    engine        = create_async_engine(settings.DATABASE_URL, **_engine_options())
    SessionLocal  = async_sessionmaker(bind=engine, autoflush=False,
                                       expire_on_commit=False)
    get_session() = async generator; rolls back on exception, then re-raises
```

* Driver: `postgresql+asyncpg`.
* `expire_on_commit=False` — ORM objects stay usable after `commit()`, which is
  what lets `TradingEngine.place_order` return live `Order`/`Trade`/`Position`
  objects for Pydantic to serialise.
* `autoflush=False` — flushes are explicit (`await session.flush()`), so the
  order of INSERTs inside the trading transaction is deterministic.
* Naming convention in `db/base.py` gives every index/constraint a stable,
  droppable name (`ix_`, `uq_`, `ck_`, `fk_`, `pk_`).

Migrations: Alembic, async `env.py`, URL injected from `settings.DATABASE_URL`
(never written into `alembic.ini`). Four revisions, head `51917e5fa5f1`.

### 3.6 Pydantic schemas

Every response model is a Pydantic v2 `BaseModel`. ORM-backed ones set
`model_config = ConfigDict(from_attributes=True)` and are populated via
`Model.model_validate(orm_row)`.

Money fields are `Decimal` with `max_digits=18, decimal_places=2` (the `_MONEY`
dict in `schemas/trading.py` and `schemas/wallet.py`), mirroring
`NUMERIC(18,2)` in the database. On the wire they serialise as **JSON strings**,
which is why `frontend/src/types/*.ts` types every money field as `string`.

### 3.7 Exception handling and the error envelope

```python
@app.exception_handler(DomainError)
async def domain_error_handler(_, exc: DomainError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": exc.message}},
    )
```

So every business failure is:

```json
{ "error": { "code": "insufficient_funds", "message": "Order needs 140042.00 ..." } }
```

FastAPI's own `RequestValidationError` is **not** overridden, so schema/query
validation failures return the stock FastAPI shape:

```json
{ "detail": [ { "loc": [...], "msg": "...", "type": "..." } ] }
```

`frontend/src/api/client.ts:toApiError` handles both shapes — it reads
`body.error.message` first, falls back to `body.detail` when it is a string,
and finally to a generic `HTTP <status>` message.

### 3.8 Middleware

**`CORSMiddleware` is the only middleware in the application.** There is no
auth middleware, no rate limiter, no request-ID/logging middleware, no GZip.

### 3.9 WebSocket implementation

`app/api/v1/endpoints/stream.py` declares `@router.websocket("/prices")`. The
socket handler is thin; the work is split between
`app/realtime/connection_manager.py` (membership + fan-out) and
`app/realtime/price_stream.py` (obtaining quotes). Full detail in §9.

### 3.10 Background jobs

Two independent `AsyncIOScheduler` instances (APScheduler 3.11), both
`timezone="UTC"`, both `max_instances=1, coalesce=True`:

| Job id | Created in | Interval | Function | Started |
| ------ | ---------- | -------- | -------- | ------- |
| `price-poll` | `PriceStreamService.start()` | `STREAM_POLL_INTERVAL_SECONDS` (5s) | `PriceStreamService._poll_once` | lazily, on first WebSocket client — **and only in POLL mode** |
| `portfolio-snapshot` | `analytics/scheduler.py:start_snapshot_scheduler()` | `SNAPSHOT_INTERVAL_SECONDS` (300s) | `capture_periodic_snapshot` | at app startup, if `SNAPSHOT_ENABLED` |

In PUSH mode (mock provider) there is no scheduler at all — a bare
`asyncio.Task` runs `PriceStreamService._run_push_loop()`.

`capture_periodic_snapshot` opens its **own** `SessionLocal()` because it runs
outside any request. It swallows `WalletNotFoundError` (nothing to snapshot yet)
and logs-and-continues on anything else, so a failure never kills the job.

### 3.11 Request flow diagrams

**A. Place an order (the full path)**

```
POST /api/v1/trading/orders   {"side":"BUY","quantity":10,"reference_price":"1400.00"}
   |
   v
FastAPI router  api/v1/endpoints/trading.py:place_order
   |
   +-- Depends(get_session) -> AsyncSession (transaction opens on first use)
   +-- PlaceOrderRequest validation  (gt=0, le=10_000_000, max_digits=18)
   |        on failure -> 422 {"detail":[...]}   <-- never reaches the engine
   v
TradingEngine(session).place_order(...)
   |
   +-- _resolve_symbol()        -> UnsupportedSymbolError (400)
   +-- _validate_request()      -> InvalidOrderError (400)
   +-- WalletRepository.get_for_update()      SELECT ... FOR UPDATE  (wallet)
   |        None -> WalletNotFoundError (404)
   +-- PositionManager.get_or_create_for_update()  SELECT ... FOR UPDATE (position)
   +-- OrderManager.create()                  INSERT orders  (status=PENDING)
   +-- ExecutionEngine.execute(order, ref)    pure: spread -> slippage -> fees
   +-- _validate_against_position()           -> InvalidPositionOperationError
   +-- PortfolioManager.assert_affordable()   -> InsufficientFundsError
   |        (on either: mark_rejected + COMMIT + raise)
   +-- apply_fill()                           pure position arithmetic
   +-- PositionManager.apply()                UPDATE positions
   +-- PortfolioManager.apply_cash()          UPDATE wallet
   +-- ExecutionEngine.record_trade()         INSERT trades
   +-- OrderManager.mark_filled()             UPDATE orders (status=FILLED)
   +-- SnapshotService.capture(commit=False)  INSERT portfolio_snapshots
   +-- session.commit()                       <-- ONE transaction for all of it
   +-- refresh(order, position, trade)
   v
OrderResult  ->  OrderResultResponse  ->  201 JSON
```

**B. Read the chart**

```
GET /api/v1/market-data/candles?interval=5m&limit=240
   -> market_data.get_candles
   -> Depends(get_market_data_service) -> Depends(get_provider) [process-wide singleton]
   -> RelianceMarketDataService.get_historical_candles()
        _require_supported_symbol()   -> UnsupportedSymbolError (400)
        _require_supported_interval() -> UnsupportedIntervalError (400)
        min(limit, MAX_CANDLES=5000)
   -> YahooFinanceProvider.get_historical_candles()
        _vendor_symbol("RELIANCE","NSE") -> "RELIANCE.NS"
        httpx GET query1.finance.yahoo.com/v8/finance/chart/RELIANCE.NS
        _parse_candles()  (drops null bars, never forward-fills)
   -> CandleSeries  -> 200 JSON
```

**C. Compute indicators**

```
GET /api/v1/indicators?indicators=sma:20,rsi:14&interval=5m&limit=240
   -> indicators.compute_indicators
   -> parse_specs("sma:20,rsi:14") -> [IndicatorSpec, ...]   (400 on bad spec)
   -> service.get_historical_candles(...)          [same path as B]
   -> indicator_service.calculate(candles, specs, interval)
        candles_to_frame()  Decimal -> float64 pandas frame
        CALCULATORS[spec.type](frame, spec)   -> TA-Lib / pandas
        _to_points()        drops warm-up NaNs entirely
   -> IndicatorSetResponse -> 200 JSON
```

**D. Run a backtest**

```
POST /api/v1/strategies/backtest  {"strategy":"ma_crossover","params":{...}}
   -> backtest.run_backtest
   -> create_strategy(name, params)   -> UnknownStrategyError /
                                         InvalidStrategyParamsError (400)
   -> service.get_historical_candles(...)          [same path as B]
   -> BacktestEngine(BacktestConfig(...)).run(strategy, candles, ...)
        _precompute()  indicators once over the whole series
        for each bar: record_equity -> strategy.on_bar -> _execute -> _settle
        _close_out() if close_at_end
        summarise()
   -> BacktestResultSchema -> 200 JSON     (no database writes at all)
```

---

## 4. Trading Engine Architecture

Everything in this section lives under `backend/app/trading/`. The package is
**independent by construction**: it imports no web framework and no market-data
provider. Execution prices are always supplied by the caller.

### 4.1 Component map — actual class names

```
TradingEngine                        app/trading/engine.py
  |
  |-- OrderManager                   app/trading/order_manager.py
  |     create / mark_filled / mark_rejected / get / list_recent
  |
  |-- ExecutionEngine                app/trading/execution.py
  |     price_fill / execute / record_trade / list_recent
  |     frictionless()  classmethod
  |     |-- SpreadModel              app/trading/spread.py
  |     |-- SlippageModel            app/trading/slippage.py
  |     +-- FeeCalculator            app/trading/fees.py
  |
  |-- PositionManager                app/trading/position_manager.py
  |     get / get_or_create_for_update / apply
  |     + module-level pure function  apply_fill()  -> FillOutcome
  |
  |-- PortfolioManager               app/trading/portfolio.py
  |     cash_delta / assert_affordable / apply_cash / snapshot
  |
  +-- PnLCalculator                  app/trading/pnl.py
        realized_pnl / unrealized_pnl / position_value /
        weighted_average_price
        + to_money() / to_average()

WalletRepository                     app/repositories/wallet_repository.py
        get / get_for_update / create
```

### 4.2 Component-by-component

| Component | File | Class / function | State | Purity |
| --------- | ---- | ---------------- | ----- | ------ |
| **OrderManager** | `order_manager.py` | `OrderManager` | holds `AsyncSession` | DB only, no arithmetic |
| **ExecutionEngine** | `execution.py` | `ExecutionEngine`, `Fill` (frozen dataclass) | holds session + 3 models | `price_fill()` is **pure**; `record_trade()` writes |
| **PositionManager** | `position_manager.py` | `PositionManager`, `apply_fill()`, `FillOutcome` | thin DB wrapper | `apply_fill()` is **pure arithmetic** |
| **PortfolioManager** | `portfolio.py` | `PortfolioManager`, `PortfolioSnapshot` (dataclass) | holds a `WalletRepository` | all methods are `@staticmethod`, pure |
| **PnLCalculator** | `pnl.py` | `PnLCalculator` | none | fully pure, all `@staticmethod` |
| **FeeCalculator** | `fees.py` | `FeeCalculator`, `ChargeBreakdown`, `Segment` | rates only | fully pure |
| **SlippageModel** | `slippage.py` | `SlippageModel`, `SlippageResult`, `SlippageType` | rate only | fully pure |
| **SpreadModel** | `spread.py` | `SpreadModel`, `SpreadResult`, `BidAsk` | bps only | fully pure |

### 4.3 Dependencies between them

```
TradingEngine
   depends on  OrderManager, ExecutionEngine, PositionManager,
               PortfolioManager, WalletRepository
   uses        apply_fill() directly (module function, not via PositionManager)
   imports     settings, exceptions, models.enums, models.trading
   also        SnapshotService  (LOCAL import inside place_order, to avoid a
                                 circular import: analytics -> trading -> analytics)

ExecutionEngine
   depends on  SpreadModel, SlippageModel, FeeCalculator, to_money, models.trading

PositionManager
   depends on  PnLCalculator (via apply_fill), settings, models.trading

PortfolioManager
   depends on  WalletRepository, PnLCalculator, Fill, models.wallet

PnLCalculator / SpreadModel / SlippageModel / FeeCalculator
   depend on   settings (only in their from_settings() classmethods) and Decimal
```

Every one of the three cost models is **injected** into `ExecutionEngine`, and
`ExecutionEngine` is injected into `TradingEngine`:

```python
TradingEngine(session, execution=ExecutionEngine.frictionless(session))
```

That constructor argument is how the whole test suite isolates position
accounting from execution cost.

### 4.4 The execution pipeline

```
reference_price (a MID price, supplied by the caller)
      |
      |  SpreadModel.apply(mid, direction, qty)
      |     bid = mid - (SPREAD_BPS/10000)/2 * mid
      |     ask = mid + (SPREAD_BPS/10000)/2 * mid
      |     buys lift the ask, sells hit the bid
      v
quoted price  (+ spread_cost)
      |
      |  SlippageModel.apply(base, direction, qty)
      |     always ADVERSE: buys pushed up, sells pushed down
      |     rate = SLIPPAGE_BPS/10000  or  SLIPPAGE_PERCENT/100  or 0
      v
execution price  (+ slippage_cost)
      |
      |  FeeCalculator.calculate(side, qty, price)
      |     brokerage (capped), STT, exchange, SEBI, stamp duty, GST, DP
      v
Fill(quantity, price, side, reference_price, quote, spread_cost,
     slippage_cost, charges)
```

`Fill` exposes derived properties used everywhere downstream:

| Property | Definition |
| -------- | ---------- |
| `signed_quantity` | `quantity * side.direction` |
| `notional` | `price * quantity` |
| `total_charges` | `charges.total` |
| `execution_cost` | `spread_cost + slippage_cost + total_charges` |

### 4.5 Charge model — `FeeCalculator`

| Charge | Intraday | Delivery | Rounding |
| ------ | -------- | -------- | -------- |
| Brokerage | `BROKERAGE_PERCENT` of turnover, capped at `BROKERAGE_MAX_PER_ORDER` | same | paise |
| STT | **sell leg only**, `STT_INTRADAY_SELL_PERCENT` | both legs, `STT_DELIVERY_PERCENT` | **whole rupee** |
| Exchange txn | both legs, `EXCHANGE_TXN_PERCENT` | same | paise |
| SEBI | both legs, `SEBI_CHARGES_PERCENT` | same | paise |
| Stamp duty | **buy leg only**, `STAMP_DUTY_INTRADAY_BUY_PERCENT` | buy only, delivery rate | **whole rupee** |
| GST | `GST_PERCENT` of (brokerage + exchange + SEBI) — *not* of STT/stamp duty | same | paise |
| DP charges | zero | `DP_CHARGES_PER_SELL`, sell leg only | paise |

`CHARGES_ENABLED=false`, or `FeeCalculator.disabled()`, returns
`ChargeBreakdown.zero()` for every fill.

### 4.6 Cash model — `PortfolioManager`

One rule covers all four sides:

```python
cash_delta(fill) = to_money(fill.notional * -fill.side.direction - fill.total_charges)
```

* BUY / BUY_TO_COVER → `direction = +1` → cash is **debited** notional, then charges.
* SELL / SHORT_SELL  → `direction = -1` → cash is **credited** notional, minus charges.

`assert_affordable()` runs **before** any mutation, so an unaffordable order
raises `InsufficientFundsError` instead of tripping the
`ck_wallet_cash_balance_non_negative` CHECK at COMMIT.

### 4.7 Position accounting — `apply_fill()`

Pure function, three cases (from the docstring in `position_manager.py`):

1. **Opening from flat** — the fill becomes the position at its own price.
2. **Adding in the same direction** — quantities add, entry price re-averaged by
   `PnLCalculator.weighted_average_price`. Nothing realized.
3. **Trading against the position** — `closed = min(|qty|, |fill_qty|)` units
   are closed at the existing average and P&L is realized on them. If the fill
   is larger, it **crosses zero**: the remainder opens the opposite direction at
   the fill price and the average resets to that price.

Returns `FillOutcome(new_quantity, new_average_price, realized_pnl,
closed_quantity, opened_quantity)`; `is_reversal` is true when both
`closed_quantity > 0` and `opened_quantity > 0`.

`PositionManager.apply()` then writes the outcome and **accumulates charges on
every fill, opening ones included**, so `net_realized_pnl = realized_pnl -
total_charges` reflects the full round trip.

### 4.8 Side validation — `TradingEngine._validate_against_position`

| Side | Rule | Can it reverse? |
| ---- | ---- | --------------- |
| `BUY` | none | **yes** — covers a short and opens a long in one order |
| `SHORT_SELL` | none | **yes** — closes a long and opens a short in one order |
| `SELL` | position must be `> 0` and `quantity <= position.quantity` | no |
| `BUY_TO_COVER` | position must be `< 0` and `quantity <= abs(position.quantity)` | no |

Violations raise `InvalidPositionOperationError` (HTTP 400, code
`invalid_position_operation`). The rejected order **is persisted** with
`status=REJECTED` and `rejection_reason` before the error propagates.

### 4.9 Components that DO NOT exist

| Requested name | Status |
| -------------- | ------ |
| `OrderManager` | ✅ exists — `app/trading/order_manager.py` |
| `ExecutionEngine` | ✅ exists — `app/trading/execution.py` |
| `PositionManager` | ✅ exists — `app/trading/position_manager.py` |
| `PortfolioManager` | ✅ exists — `app/trading/portfolio.py` |
| `PnLCalculator` | ✅ exists — `app/trading/pnl.py` |
| `FeeCalculator` | ✅ exists — `app/trading/fees.py` |
| `SlippageModel` | ✅ exists — `app/trading/slippage.py` |
| **`RiskManager`** | ❌ **NOT IMPLEMENTED.** No such class or module exists. |

What stands in for risk management today, and where:

* **Quantity bounds** — `TradingEngine._validate_request` +
  `MAX_ORDER_QUANTITY = 10_000_000` in `models/trading.py` + the
  `ck_orders_quantity_within_bounds` CHECK constraint.
* **Cash sufficiency** — `PortfolioManager.assert_affordable`.
* **Direction sanity** — `TradingEngine._validate_against_position`.
* **Non-negative cash** — `ck_wallet_cash_balance_non_negative` CHECK.

**No margin, no leverage, no exposure cap, no position limit, no stop-loss, no
daily-loss limit, no circuit breaker.** `app/trading/portfolio.py` documents
this explicitly as a "Known gap": short proceeds are credited as spendable cash
and nothing is reserved against an open short.

### 4.10 ASCII sequence diagrams

Common legend: `TE`=TradingEngine, `OM`=OrderManager, `EE`=ExecutionEngine,
`PM`=PositionManager, `PF`=PortfolioManager, `WR`=WalletRepository,
`DB`=PostgreSQL.

---

#### BUY — open a long from flat

```
Client   Router     TE        WR       PM       OM       EE       PF      DB
  |        |         |         |        |        |        |        |       |
  |-POST-->|         |         |        |        |        |        |       |
  |        |-place_order()-->  |        |        |        |        |       |
  |        |         |-_resolve_symbol / _validate_request         |       |
  |        |         |-get_for_update-->|        |        |        |       |
  |        |         |         |------------- SELECT wallet FOR UPDATE --->|
  |        |         |<--Wallet-|        |        |        |        |      |
  |        |         |-get_or_create_for_update->|        |        |       |
  |        |         |         |        |--- SELECT position FOR UPDATE -->|
  |        |         |         |        |    (INSERT flat row if absent)   |
  |        |         |<----------------Position(qty=0)    |        |       |
  |        |         |-create(BUY,10,PENDING)------------>|        |       |
  |        |         |         |        |        |--- INSERT orders ------>|
  |        |         |-execute(order, ref=1400.00)----------------->|      |
  |        |         |         |   SpreadModel -> ask 1400.14              |
  |        |         |         |   SlippageModel -> 1400.42                |
  |        |         |         |   FeeCalculator -> brokerage/stamp/GST... |
  |        |         |<---------------------------- Fill(price=1400.42) ---|
  |        |         |-_validate_against_position()  (BUY: no restriction) |
  |        |         |-assert_affordable(wallet, fill)------------>|       |
  |        |         |         |        |        |        |   cash_delta<0 |
  |        |         |         |        |        |        |   -> OK        |
  |        |         |-apply_fill(qty=0, fill=+10 @1400.42)               |
  |        |         |   -> FillOutcome(new_qty=+10, avg=1400.42,          |
  |        |         |                  realized=0, closed=0, opened=10)   |
  |        |         |-PM.apply(position, outcome, charges)---->|          |
  |        |         |         |        |--------- UPDATE positions ------>|
  |        |         |-PF.apply_cash(wallet, fill)---------------->|       |
  |        |         |         |        |        |        |--UPDATE wallet>|
  |        |         |-EE.record_trade(gross=0, closed=0)--------->|       |
  |        |         |         |        |        |        |--INSERT trades>|
  |        |         |-OM.mark_filled(order, 1400.42)---->|        |       |
  |        |         |         |        |        |--- UPDATE orders ------>|
  |        |         |-SnapshotService.capture(mark=1400.42, commit=False) |
  |        |         |         |        |        |   INSERT portfolio_snap>|
  |        |         |-session.commit()  <=== ONE TRANSACTION ============>|
  |        |<--OrderResult(gross=0, charges=C, net=-C, cash_delta=-N-C)    |
  |<--201--|         |         |        |        |        |        |       |
```

---

#### SELL — close a long (closing-only)

```
Client   Router     TE        WR       PM       OM       EE       PF      DB
  |-POST-->|         |         |        |        |        |        |       |
  |        |-place_order(SELL, 10, ref=1450.00)-->        |        |       |
  |        |         |-lock wallet + position (as above) ---------------->|
  |        |         |<--Position(qty=+10, avg=1400.42)   |        |       |
  |        |         |-OM.create(SELL,10,PENDING)-------->|--INSERT------->|
  |        |         |-EE.execute() : bid 1449.86 -> slip 1449.57          |
  |        |         |               STT charged (sell leg), no stamp duty |
  |        |         |-_validate_against_position(SELL, 10, pos)           |
  |        |         |    pos.quantity > 0        OK                       |
  |        |         |    10 <= 10                OK                       |
  |        |         |    (else -> mark_rejected + COMMIT + 400)           |
  |        |         |-assert_affordable()  cash_delta > 0 -> returns early|
  |        |         |-apply_fill(qty=+10, fill=-10 @1449.57)              |
  |        |         |   closed=10, direction=+1                           |
  |        |         |   realized = (1449.57 - 1400.42) * 10 = +491.50     |
  |        |         |   new_qty=0 -> new_average = 0.0000                 |
  |        |         |-PM.apply -> realized_pnl += 491.50                  |
  |        |         |             total_charges += this fill's charges    |
  |        |         |             net_realized_pnl = realized - charges   |
  |        |         |-PF.apply_cash  cash += notional - charges           |
  |        |         |-EE.record_trade(gross=+491.50, closed=10)           |
  |        |         |     net_pnl = 491.50 - charges                      |
  |        |         |-OM.mark_filled -> commit -----------------------> DB|
  |<--201--|<--OrderResult(gross=+491.50, charges=C, net=491.50-C)         |
```

---

#### SHORT — open a short (may cross zero from a long)

```
Client   Router     TE       PM        EE       PF       DB
  |-POST-->|         |        |         |        |        |
  |        |-place_order(SHORT_SELL, 30, ref=1400.00)     |
  |        |         |-lock wallet + position ----------->|
  |        |         |<--Position(qty=+10, avg=1400.42)   |
  |        |         |-EE.execute(): bid then adverse slip |
  |        |         |               -> price 1399.58      |
  |        |         |-_validate_against_position()        |
  |        |         |    SHORT_SELL has NO restriction    |
  |        |         |-assert_affordable() : credit -> OK  |
  |        |         |-apply_fill(qty=+10, fill=-30 @1399.58)
  |        |         |    same_direction = False           |
  |        |         |    closed  = min(10, 30) = 10       |
  |        |         |    realized= (1399.58-1400.42)*10*(+1) = -8.40
  |        |         |    new_qty = +10 + (-30) = -20      |
  |        |         |    opened  = 30 - 10 = 20  -> REVERSAL
  |        |         |    new_average = 1399.58  (reset to fill price)
  |        |         |-PM.apply -> Position(qty=-20, avg=1399.58)
  |        |         |-PF.apply_cash  cash += 30*1399.58 - charges
  |        |         |    NOTE: short proceeds are spendable cash.
  |        |         |          No margin is reserved. (§4.9, §17)
  |        |         |-EE.record_trade(gross=-8.40, closed=10)
  |        |         |-mark_filled -> commit ------------->|
  |<--201--|         |        |         |        |        |
```

---

#### COVER — close a short (closing-only)

```
Client   Router     TE       PM        EE       PF       DB
  |-POST-->|         |        |         |        |        |
  |        |-place_order(BUY_TO_COVER, 20, ref=1380.00)   |
  |        |         |-lock wallet + position ----------->|
  |        |         |<--Position(qty=-20, avg=1399.58)   |
  |        |         |-EE.execute(): ask then adverse slip |
  |        |         |               -> price 1380.41      |
  |        |         |               stamp duty charged (buy leg), no STT  |
  |        |         |-_validate_against_position(BUY_TO_COVER, 20, pos)
  |        |         |    pos.quantity < 0         OK
  |        |         |    20 <= abs(-20)           OK
  |        |         |    (if 21 -> InvalidPositionOperationError, 400,
  |        |         |     order persisted as REJECTED)
  |        |         |-assert_affordable(): debit 20*1380.41 + charges
  |        |         |    insufficient -> InsufficientFundsError (400)
  |        |         |-apply_fill(qty=-20, fill=+20 @1380.41)
  |        |         |    closed = 20, direction = -1
  |        |         |    realized = (1380.41-1399.58)*20*(-1) = +383.40
  |        |         |    new_qty = 0 -> new_average = 0.0000
  |        |         |-PM.apply / PF.apply_cash / record_trade / mark_filled
  |        |         |-SnapshotService.capture(commit=False)
  |        |         |-commit --------------------------->|
  |<--201--|         |        |         |        |        |
```

---

## 5. Market Data Architecture

### 5.1 The chain

```
   EXTERNAL PROVIDER
   https://query1.finance.yahoo.com/v8/finance/chart/RELIANCE.NS
        |  httpx.AsyncClient (one per process, pooled)
        v
   PROVIDER ABSTRACTION            app/market_data/base.py
   class MarketDataProvider(ABC)
        capabilities  (property, abstract)
        get_current_quote(symbol, exchange)         abstract
        get_historical_candles(...)                 abstract
        subscribe_live_data(symbol, exchange)       default: RAISES
        aclose()                                    default: no-op
        |
        +-- YahooFinanceProvider   app/market_data/yahoo.py
        +-- MockMarketDataProvider app/market_data/mock.py
        |
   REGISTRY                        app/market_data/registry.py
        _PROVIDERS = {"yahoo": _build_yahoo, "mock": _build_mock}
        get_provider()      process-wide singleton, built on first use
        create_provider(n)  by name
        close_provider()    shutdown
        |
        v
   MARKET DATA SERVICE             app/services/market_data_service.py
   RelianceMarketDataService(provider)
        symbol / exchange / capabilities properties
        _require_supported_symbol()    -> UnsupportedSymbolError
        _require_supported_interval()  -> UnsupportedIntervalError
        get_current_quote() / get_historical_candles() / subscribe_live_data()
        MAX_CANDLES = 5000
        |
        +-------------------------------+
        |                               |
        v                               v
   HTTP ENDPOINTS                  PRICE STREAM
   /market-data/quote              app/realtime/price_stream.py
   /market-data/candles            PriceStreamService (uses get_provider()
   /market-data/provider            DIRECTLY, not via the service)
   /indicators                          |
   /strategies/backtest                 v
                                   ConnectionManager.broadcast()
                                        |
                                        v
                                   WebSocket /api/v1/stream/prices
                                        |
                                        v
                                   useLivePrice hook -> Terminal.tsx
```

> **Important seam detail.** `PriceStreamService` is constructed in
> `get_price_stream()` with `provider=get_provider()` — it bypasses
> `RelianceMarketDataService` entirely and talks to the provider directly. So
> the streaming path does **not** go through the single-instrument validation
> that the HTTP path does; it uses `settings.TRADING_SYMBOL` /
> `settings.TRADING_EXCHANGE` directly instead.

### 5.2 Provider implementations

#### `YahooFinanceProvider` (`MARKET_DATA_PROVIDER=yahoo`, the default)

| Aspect | Implementation |
| ------ | -------------- |
| Endpoint | `https://query1.finance.yahoo.com/v8/finance/chart/{vendor_symbol}` |
| Auth | none (keyless) |
| Symbol mapping | `_EXCHANGE_SUFFIX = {"NSE": ".NS", "BSE": ".BO"}` → `RELIANCE.NS` |
| Interval mapping | `_INTERVAL` dict: all 8 platform intervals → Yahoo strings |
| Default lookback | `_DEFAULT_RANGE` per interval (`1m`→`1d` … `1mo`→`10y`) |
| Headers | `User-Agent: Mozilla/5.0 (compatible; VirtualTradingPlatform/0.1)` — Yahoo rejects requests without one |
| Quote source | `result["meta"]` — `regularMarketPrice`, `regularMarketTime`, `regularMarketVolume`, `regularMarketDayHigh/Low`, `previousClose` **or** `chartPreviousClose` |
| Day open | `_session_open()` — first non-null `open` in the accompanying bar series (there is no `meta` field for it) |
| Candles | `_parse_candles()` zips Yahoo's column-oriented arrays; **rows with any null OHLC are dropped, never forward-filled** |
| Float→Decimal | `_to_money()` goes via `str()` so the shortest round-trippable representation is quantised, not the full binary expansion |
| `bid` / `ask` | **always `None`** — depth lives on `/v7/finance/quote`, which now needs a session crumb |
| Streaming | **not supported** — `subscribe_live_data` is deliberately *not* overridden, so the base class raises `LiveDataNotSupportedError` |
| Client teardown | `aclose()` → `httpx.AsyncClient.aclose()` |

#### `MockMarketDataProvider` (`MARKET_DATA_PROVIDER=mock`)

A seeded random walk (`random.Random(seed)`), bounded to
`[base_price/2, base_price*2]`. It is the **only** provider that supports
`subscribe_live_data` (an async generator yielding a quote every
`MOCK_TICK_INTERVAL_SECONDS`) and the **only** one that produces bid/ask
(synthesised from `MOCK_SPREAD_BPS`).

Every mock quote carries `is_mock=True` and `provider="mock"`,
`capabilities.is_mock` is `True`, `registry.get_provider()` logs a loud warning
at startup, and `Terminal.tsx` renders a `SIMULATED` badge plus a warning
banner. Mock data cannot silently masquerade as real.

### 5.3 Models

`Quote` — `app/schemas/market_data.py`

| Field | Type | Notes |
| ----- | ---- | ----- |
| `symbol`, `exchange` | `str` | uppercased by the provider |
| `last_price` | `Decimal` | required |
| `bid`, `ask` | `Decimal \| None` | `None` on Yahoo, always |
| `volume` | `int` | cumulative session volume |
| `timestamp` | `datetime` | exchange timestamp, UTC |
| `previous_close`, `day_open`, `day_high`, `day_low` | `Decimal \| None` | optional context |
| `currency` | `str` | default `"INR"` |
| `provider` | `str` | provenance |
| `is_delayed` | `bool` | required — forces every provider to declare |
| `is_mock` | `bool` | default `False` |

`Candle` — `timestamp` (bar **opening** time, UTC), `open`, `high`, `low`,
`close` (`Decimal`), `volume` (`int`).

`CandleSeries` — `symbol`, `exchange`, `interval`, `provider`, `count`,
`candles` (**oldest first**).

`ProviderCapabilities` — `name`, `supports_quotes`, `supports_historical`,
`supports_bid_ask`, `supports_live_stream`, `is_delayed`,
`quote_delay_minutes`, `requires_credentials`, `is_mock`,
`supported_intervals`, `limitations: list[str]` (plain-language). Exposed at
`GET /api/v1/market-data/provider` so the feed's limits are discoverable at
runtime.

`Interval` (StrEnum): `1m`, `5m`, `15m`, `30m`, `1h`, `1d`, `1wk`, `1mo`.

### 5.4 Historical data

* Entry: `RelianceMarketDataService.get_historical_candles(interval, start, end, limit, symbol)`.
* `limit` is clamped: `min(limit or MAX_CANDLES, MAX_CANDLES)` where
  `MAX_CANDLES = 5000`. The endpoint additionally declares `Query(ge=1, le=5000)`.
* With `start`: Yahoo gets `period1`/`period2` epoch seconds (`end` defaults to now).
  Without `start`: Yahoo gets `range=_DEFAULT_RANGE[interval]`.
* Truncation keeps the **most recent** bars: `candles[-limit:]`.
* Known Yahoo limits (documented in the provider docstring): 1-minute history is
  retained ~30 days, and roughly 7 days maximum per request.

### 5.5 Live data

Two modes, chosen by `PriceStreamService.mode` from
`provider.capabilities.supports_live_stream`:

| Mode | Provider | Mechanism |
| ---- | -------- | --------- |
| `PUSH` | mock | `asyncio.create_task(_run_push_loop())` consuming the provider's async iterator |
| `POLL` | yahoo | APScheduler `interval` job, `STREAM_POLL_INTERVAL_SECONDS`, `max_instances=1`, `coalesce=True`, `misfire_grace_time=interval+5` |

`_poll_once()` short-circuits when `manager.has_listeners` is false — **an idle
server spends no rate limit**.

`build_tick(quote)` shapes the wire payload. When the provider has no depth and
`STREAM_MODEL_BID_ASK=true`, bid/ask are derived from `SpreadModel.from_settings()`
and the tick carries `bid_ask_source: "modelled"`. Otherwise `"provider"` or
`"unavailable"`. Change and change-percent are computed from `previous_close`.

### 5.6 Reconnection behaviour

Reconnection is **entirely client-side**. The server never retries a dropped
socket; it just reaps it.

| Layer | Behaviour |
| ----- | --------- |
| Browser → server | `useLivePrice.socket.onclose` → backoff `1s → 2s → 4s … capped 15s`, multiplied by jitter `0.85–1.15`, `attempt` counter incremented; a manual `reconnect()` resets the backoff to 1s |
| Server → provider (PUSH) | `_run_push_loop` catches any exception, broadcasts an `error` frame, sleeps `backoff` (1s doubling to a 30s cap), then re-attaches to `subscribe_live_data` |
| Server → provider (POLL) | no reconnect concept — the next scheduled tick simply tries again |
| Heartbeat | client sends `{"type":"ping"}` every 25s; server replies `{"type":"pong", ...}` |
| Staleness | client marks `isStale` when no tick has arrived for 30s, checked on a 5s interval. The socket can stay open while the feed has quietly stopped. |

### 5.7 Error handling in the market-data layer

| Failure | Raised where | Exception | HTTP |
| ------- | ------------ | --------- | ---- |
| Non-2xx from Yahoo | `_fetch_chart` catches `httpx.HTTPStatusError` | `MarketDataUnavailableError` | 503 |
| Network/DNS/timeout | `_fetch_chart` catches `httpx.HTTPError` | `MarketDataUnavailableError` | 503 |
| Non-JSON body | `_fetch_chart` catches `ValueError` | `MarketDataUnavailableError` | 503 |
| `chart.error` set, or empty `chart.result` | `_fetch_chart` | `MarketDataUnavailableError` | 503 |
| `meta.regularMarketPrice` missing | `get_current_quote` | `MarketDataUnavailableError` | 503 |
| Interval the provider does not serve | `RelianceMarketDataService._require_supported_interval` and `YahooFinanceProvider.get_historical_candles` | `UnsupportedIntervalError` | 400 |
| Symbol other than RELIANCE | `RelianceMarketDataService._require_supported_symbol` | `UnsupportedSymbolError` | 400 |
| Streaming asked of a provider without it | `MarketDataProvider.subscribe_live_data` (base) | `LiveDataNotSupportedError` | 501 |

Inside the stream, failures do **not** tear anything down:
`PriceStreamService._handle_failure` increments `error_count`, records
`last_error`, logs a warning and broadcasts:

```json
{"type":"error","data":{"message":"Upstream market data is unavailable.",
                        "detail":"MarketDataUnavailableError: ...",
                        "timestamp":"..."}}
```

---

## 6. Frontend Architecture

### 6.1 Pages (hash routes)

`frontend/src/hooks/useHashRoute.ts` defines `Route` and the `NAV` array;
`App.tsx` is a five-way switch. There is **no router library**.

| Hash | Route | Component | Data sources |
| ---- | ----- | --------- | ------------ |
| `#/` (or empty) | `terminal` | `Terminal` | `useLivePrice` + `useAccount` |
| `#/trades` | `trades` | `TradeHistoryPage` | `fetchTrades(200)` |
| `#/orders` | `orders` | `OrderHistoryPage` | `fetchOrders(200)` |
| `#/portfolio` | `portfolio` | `PortfolioHistoryPage` | `fetchSnapshots(1000)` + `useLivePrice` |
| `#/performance` | `performance` | `PerformancePage` | `fetchPerformance()` |

An unknown hash falls back to `terminal`.

### 6.2 Components

**Terminal (`components/terminal/`)**

| Component | Responsibility | Props in |
| --------- | -------------- | -------- |
| `Terminal` | Page composition; owns the `orders`/`trades` tab; calls `refresh()` after a fill | — |
| `TerminalHeader` | Symbol, last price, change, provenance badges (`SIMULATED`, `DELAYED`, `STALE`), connection chip that also acts as a manual reconnect button | `tick, status, connection, attempt, isStale, onReconnect` |
| `PriceChart` | Candlesticks + volume histogram + price-pane overlays + timeframe chips + indicator toggles | `symbol, exchange, tick` |
| `OscillatorPane` | One `lightweight-charts` instance per `pane: "separate"` indicator (RSI, MACD); registers itself with the parent for time-scale sync | `indicator, onChartReady, onChartDestroy` |
| `PositionPanel` | Open position table, `LONG/SHORT/FLAT` badge | `position, portfolio, currentPrice` |
| `TradingPanel` | **The only place an order is submitted.** Quantity input + 4 side buttons + fill receipt | `referencePrice, position, disabled, onFilled` |
| `WalletPanel` | Cash, portfolio value, realized gross **and** net, charges, unrealized, total net P&L; "Create wallet" CTA | `wallet, portfolio, needsWallet, onCreateWallet` |
| `OrdersPanel` | Recent orders table with status badge and rejection reason | `orders` |
| `TradeHistory` | Recent fills with gross / charges / net side by side | `trades` |

**History (`components/history/`)**

| Component | Responsibility |
| --------- | -------------- |
| `PageShell` | Shared frame: title, subtitle, actions, loading, error+retry |
| `TradeHistoryPage` | Full contract-note table, 200 rows |
| `OrderHistoryPage` | 200 rows + `ALL / FILLED / REJECTED` client-side filter |
| `PortfolioHistoryPage` | `EquityCurve` + snapshot table + "Snapshot now" button + `total_value`/`net_pnl` metric toggle |
| `PerformancePage` | Stat grid + best/worst closing trade cards |
| `EquityCurve` | Area chart; **collapses snapshots that share a second** to the last value, because Lightweight Charts requires strictly ascending times |

**Shared** — `NavBar` (anchors, so middle-click and back/forward work),
`StatusBadge`, `HealthCard`.

> `HealthCard.tsx` and `hooks/useHealth.ts` are **dead code**: nothing in
> `App.tsx` or any rendered component references them. `StatusBadge` is used
> only by `HealthCard`. Verified by grep across `frontend/src`.

### 6.3 Hooks (this is the state layer)

| Hook | Owns | Key mechanics |
| ---- | ---- | ------------- |
| `useLivePrice()` | `tick, status, error, connection, attempt, isStale, reconnect` | WebSocket lifecycle; refs for socket/timers/backoff/`activeRef`; drops any previous socket before dialling so two sockets can never feed the same state; nulls `onclose` before an intentional close so it does not schedule a reconnect |
| `useAccount(markPrice)` | `wallet, position, portfolio, orders, trades, loading, error, needsWallet, refresh, createWallet` | `refresh()` does **five parallel fetches** in one `Promise.all`; a 404 from `/wallet` or `/trading/portfolio` is treated as the expected first-run state (`needsWallet`), not an error |
| `useIndicators(interval, limit)` | `enabled, toggle, clear, indicators, loading, error` | Selection persisted in `localStorage['vtrader.indicators']`; unknown ids are filtered out on load; refetches when `interval`, `limit` or the spec list changes; aborts in-flight requests |
| `useHashRoute()` | `route, navigate` | `hashchange` listener |
| `useHealth()` | `state, data, error, refresh` | **unused** |

### 6.4 API client

`src/api/client.ts` is the single `fetch` chokepoint.

```ts
BASE_URL   = import.meta.env.VITE_API_BASE_URL   ?? 'http://localhost:8000'
V1_PREFIX  = import.meta.env.VITE_API_V1_PREFIX  ?? '/api/v1'

apiUrl(path)  -> `${BASE_URL}${V1_PREFIX}${path}`
wsUrl(path)   -> VITE_WS_BASE_URL, else BASE_URL with http->ws, + prefix + path
apiGet<T>(path, signal)
apiPost<T>(path, body?, signal?)
class ApiError extends Error { status?, code?, get isNotFound() }
```

`toApiError()` unwraps `{error:{code,message}}` first, then a string `detail`,
then falls back to `Request to {path} failed with HTTP {status}.` A thrown
network error (backend down / wrong port / CORS rejection) becomes
`Cannot reach the API at {BASE_URL}. Is the backend running?`.
`AbortError` is re-thrown unchanged so callers can ignore cancellations.

### 6.5 WebSocket client

`useLivePrice` only. Constants: `INITIAL_BACKOFF_MS = 1000`,
`MAX_BACKOFF_MS = 15000`, `PING_INTERVAL_MS = 25000`, `STALE_AFTER_MS = 30000`.
Message handling is a `switch` on `message.type` over
`'tick' | 'status' | 'error' | 'pong'`; anything that is not valid JSON is
silently ignored.

### 6.6 Chart components

`lightweight-charts` v4.2. v4 has **no multi-pane support**, so the design is:

* `PriceChart` creates one chart with a candlestick series, a histogram series on
  a separate `priceScaleId: 'volume'`, and N line series for `pane === 'price'`
  indicators.
* Each `pane === 'separate'` indicator (RSI, MACD) gets its **own chart** via
  `OscillatorPane`.
* Every chart registers itself into `syncedChartsRef` (a `Set<IChartApi>`), and
  a `useEffect` subscribes to `subscribeVisibleLogicalRangeChange` on each,
  applying the range to the others behind an `applying` re-entrancy guard.
* The chart instance is created **once**; only its *data* is replaced when the
  timeframe changes, so pan and zoom survive.
* Bollinger `Upper`/`Lower` sub-series draw thinner and dashed
  (`BAND_LABELS`); MACD `Histogram` colours by sign.

### 6.7 How frontend state updates after each event

#### Market price update

```
server tick
  -> WebSocket message
  -> useLivePrice: setTick(data), setError(null), lastTickAtRef = now, setIsStale(false)
  -> Terminal re-renders; markPrice = tick.last_price
     |
     +-> TerminalHeader        new price, change, badges
     +-> PriceChart (prop tick)
     |     useEffect([tick]) mutates lastBarRef in place:
     |       high = max(high, price); low = min(low, price); close = price
     |       series.update(updated)      <- same timestamp, no refetch
     +-> PositionPanel         "Current" column
     +-> TradingPanel          "Reference" row; enables the buttons
     +-> useAccount(markPrice) effect fires:
           if (Date.now() - lastRevaluedAt < 3000) return;   // throttle
           fetchPortfolio(markPrice) -> setPortfolio(...)
           -> WalletPanel + PositionPanel unrealized P&L refresh
```

Note: unrealized P&L is **never computed in JavaScript**. It is recomputed
server-side in `Decimal` on each throttled `GET /trading/portfolio?mark_price=…`.

#### Order submission

```
TradingPanel.submit(side)
  -> setPending(side); setError(null)      // all 4 buttons disable via `blocked`
  -> placeOrder({side, quantity, reference_price: markPrice})
  -> on success: setLastFill(result)  ->  fill receipt renders
                 onFilled(result)     ->  Terminal.handleFilled -> refresh()
  -> on failure: setError(message)    ->  "Order rejected" alert; setLastFill(null)
  -> finally:    setPending(null)
```

#### Trade execution / position update / wallet update

All three are the **same refresh**. `Terminal.handleFilled` calls
`useAccount.refresh()`, which reissues all five reads in one `Promise.all` and
sets `wallet`, `position`, `portfolio`, `orders`, `trades` together:

```
refresh()
  Promise.all([ fetchWallet(), fetchPosition(), fetchPortfolio(mark),
                fetchOrders(25), fetchTrades(25) ])
  -> setWallet / setNeedsWallet / setPosition / setPortfolio
     / setOrders / setTrades   (one consistent set of reads)
  -> WalletPanel, PositionPanel, OrdersPanel, TradeHistory all re-render
```

There is **no optimistic update and no partial patching** — the design choice is
that a fill changes four tables at once, so everything is reloaded together.

The **history pages do not auto-refresh**; each loads once on mount and has a
manual `Refresh` button. `PortfolioHistoryPage` reloads after a manual
`captureSnapshot()`.

---

## 7. Database Architecture

PostgreSQL 16 (`postgres:16-alpine`, `TZ=Asia/Kolkata`). Five domain tables plus
`alembic_version`. Four native enum types.

### 7.1 ER diagram

```
                    +--------------------------------------+
                    |              wallet                  |
                    |  (SINGLETON: CHECK id = 1)           |
                    +--------------------------------------+
                    | PK id                 INTEGER        |
                    |    currency           VARCHAR(3)     |
                    |    initial_balance    NUMERIC(18,2)  |
                    |    cash_balance       NUMERIC(18,2)  |
                    |    created_at         TIMESTAMPTZ    |
                    |    updated_at         TIMESTAMPTZ    |
                    +--------------------------------------+
                         ^  no FK anywhere. The wallet is
                         |  related to everything else only
                         |  through application logic.

  +---------------------------------+          +--------------------------------+
  |             orders              |          |            trades              |
  +---------------------------------+          +--------------------------------+
  | PK id            BIGSERIAL      |1        *| PK id             BIGSERIAL    |
  |    symbol        VARCHAR(32) IX |----------|<FK order_id       BIGINT    IX |
  |    exchange      VARCHAR(16)    | ON DELETE|    symbol         VARCHAR(32)IX|
  |    side          order_side     |  CASCADE |    exchange       VARCHAR(16)  |
  |    order_type    order_type     |          |    side           order_side   |
  |    quantity      INTEGER        |          |    quantity       INTEGER      |
  |    requested_price  NUM(18,2)   |          |    execution_price NUM(18,2)   |
  |    execution_price  NUM(18,2)   |          |    reference_price NUM(18,2)   |
  |    status        order_status IX|          |    bid_price      NUM(18,2)    |
  |    rejection_reason VARCHAR(500)|          |    ask_price      NUM(18,2)    |
  |    filled_at     TIMESTAMPTZ    |          |    spread_cost    NUM(18,2)    |
  |    created_at    TIMESTAMPTZ IX |          |    slippage_cost  NUM(18,2)    |
  |    updated_at    TIMESTAMPTZ    |          |    brokerage      NUM(18,2)    |
  +---------------------------------+          |    stt            NUM(18,2)    |
                                               |    exchange_charges NUM(18,2)  |
                                               |    sebi_charges   NUM(18,2)    |
                                               |    stamp_duty     NUM(18,2)    |
                                               |    gst            NUM(18,2)    |
                                               |    dp_charges     NUM(18,2)    |
                                               |    total_charges  NUM(18,2)    |
                                               |    gross_pnl      NUM(18,2)    |
                                               |    net_pnl        NUM(18,2)    |
                                               |    closed_quantity INTEGER     |
                                               |    created_at   TIMESTAMPTZ IX |
                                               |    updated_at   TIMESTAMPTZ    |
                                               +--------------------------------+

  +-------------------------------------+   +-------------------------------------+
  |             positions               |   |        portfolio_snapshots          |
  |  (one row per instrument;           |   |  (APPEND-ONLY equity curve)         |
  |   this platform has exactly one)    |   +-------------------------------------+
  +-------------------------------------+   | PK id             BIGSERIAL         |
  | PK symbol        VARCHAR(32)        |   |    captured_at   TIMESTAMPTZ    IX  |
  |    exchange      VARCHAR(16)        |   |    source        snapshot_source IX |
  |    quantity      INTEGER (signed)   |   |    symbol        VARCHAR(32)        |
  |    average_price NUMERIC(18,4)      |   |    quantity      INTEGER            |
  |    realized_pnl  NUMERIC(18,2)      |   |    average_price NUMERIC(18,4)      |
  |    total_charges NUMERIC(18,2)      |   |    mark_price    NUMERIC(18,2) NULL |
  |    net_realized_pnl NUMERIC(18,2)   |   |    cash          NUMERIC(18,2)      |
  |    created_at    TIMESTAMPTZ        |   |    position_value NUMERIC(18,2)     |
  |    updated_at    TIMESTAMPTZ        |   |    total_value   NUMERIC(18,2)      |
  +-------------------------------------+   |    realized_pnl  NUMERIC(18,2)      |
       ^   joined to orders/trades only      |    total_charges NUMERIC(18,2)      |
       |   by the `symbol` VALUE.            |    unrealized_pnl NUMERIC(18,2)     |
       |   There is NO foreign key.          |    net_pnl       NUMERIC(18,2)      |
                                             +-------------------------------------+
                                                  ^  no FK to anything.

  ENUM TYPES (native PostgreSQL):
    order_side      = BUY | SELL | SHORT_SELL | BUY_TO_COVER
    order_status    = PENDING | FILLED | REJECTED | CANCELLED
    order_type      = MARKET
    snapshot_source = PERIODIC | TRADE | MANUAL
```

**The only foreign key in the entire schema is `trades.order_id → orders.id`.**

### 7.2 Table: `wallet`

Model: `app/models/wallet.py:Wallet`. Migration: `ea97efd67efb`.

| Column | Type | Null | Default | Notes |
| ------ | ---- | ---- | ------- | ----- |
| `id` | `INTEGER` | no | `1` (app-side) | PK, `autoincrement=False` |
| `currency` | `VARCHAR(3)` | no | `'INR'` | |
| `initial_balance` | `NUMERIC(18,2)` | no | — | opening capital |
| `cash_balance` | `NUMERIC(18,2)` | no | — | available cash |
| `created_at` / `updated_at` | `TIMESTAMPTZ` | no | `now()` | `TimestampMixin` |

Constraints: `pk_wallet`; `ck_wallet_singleton` (`id = 1`);
`ck_wallet_initial_balance_positive` (`initial_balance > 0`);
`ck_wallet_cash_balance_non_negative` (`cash_balance >= 0`).
Indexes: PK only. Relationships: none (no FKs in or out).

### 7.3 Table: `orders`

Model: `app/models/trading.py:Order`. Migration: `44b98124fbd4`
(+ nothing later).

| Column | Type | Null | Notes |
| ------ | ---- | ---- | ----- |
| `id` | `BIGINT` autoincrement | no | PK |
| `symbol` | `VARCHAR(32)` | no | indexed |
| `exchange` | `VARCHAR(16)` | no | default `'NSE'` |
| `side` | `order_side` | no | native enum, `validate_strings=True` |
| `order_type` | `order_type` | no | default `MARKET` |
| `quantity` | `INTEGER` | no | |
| `requested_price` | `NUMERIC(18,2)` | yes | audit only; does not affect the fill |
| `execution_price` | `NUMERIC(18,2)` | yes | NULL until filled |
| `status` | `order_status` | no | default `PENDING`, indexed |
| `rejection_reason` | `VARCHAR(500)` | yes | truncated to 500 by `mark_rejected` |
| `filled_at` | `TIMESTAMPTZ` | yes | |
| `created_at` / `updated_at` | `TIMESTAMPTZ` | no | |

Constraints:
`pk_orders`;
`ck_orders_quantity_positive` (`quantity > 0`);
`ck_orders_quantity_within_bounds` (`quantity <= 10000000`);
`ck_orders_requested_price_positive`;
`ck_orders_execution_price_positive`;
`ck_orders_filled_orders_have_a_price` (`status <> 'FILLED' OR execution_price IS NOT NULL`).

Indexes: `ix_orders_symbol`, `ix_orders_status`, `ix_orders_created_at`.

Relationships: `Order.trades` → `list[Trade]`, `back_populates="order"`,
`cascade="all, delete-orphan"`, `lazy="selectin"`.

### 7.4 Table: `trades`

Model: `app/models/trading.py:Trade`. Created by `44b98124fbd4`, heavily
extended by `b41705c11d09` (execution costs + `realized_pnl` **renamed** to
`gross_pnl`).

Columns beyond the identifiers: `execution_price` (required), `reference_price`,
`bid_price`, `ask_price` (all nullable), then eleven non-null cost/P&L columns
each with `server_default=text("0")`: `spread_cost`, `slippage_cost`,
`brokerage`, `stt`, `exchange_charges`, `sebi_charges`, `stamp_duty`, `gst`,
`dp_charges`, `total_charges`, `gross_pnl`, `net_pnl`, plus
`closed_quantity INTEGER DEFAULT 0`.

Constraints: `pk_trades`; `fk_trades_order_id_orders` (`ON DELETE CASCADE`);
`ck_trades_quantity_positive`; `ck_trades_execution_price_positive`.
Indexes: `ix_trades_order_id`, `ix_trades_symbol`, `ix_trades_created_at`.

Relationship: `Trade.order` → `Order`, `back_populates="trades"`.

Semantics worth remembering:
* `gross_pnl` — P&L from price movement alone. **Zero on an opening fill.**
* `net_pnl` — `gross_pnl - total_charges`. An opening fill's net is simply the
  cost of entering (negative).
* `closed_quantity > 0` is the definition of a "closing trade" used by both
  `PerformanceAnalyzer` and `backtest/results.summarise`.

### 7.5 Table: `positions`

Model: `app/models/trading.py:Position`.

| Column | Type | Notes |
| ------ | ---- | ----- |
| `symbol` | `VARCHAR(32)` | **primary key** — natural key, one row per instrument |
| `exchange` | `VARCHAR(16)` | default `'NSE'` |
| `quantity` | `INTEGER` | **signed**: `>0` long, `0` flat, `<0` short |
| `average_price` | `NUMERIC(18,4)` | always positive; resets to 0 when flat |
| `realized_pnl` | `NUMERIC(18,2)` | cumulative gross; survives going flat |
| `total_charges` | `NUMERIC(18,2)` | cumulative, opening fills included |
| `net_realized_pnl` | `NUMERIC(18,2)` | `realized_pnl - total_charges` |

Constraints: `pk_positions`;
`ck_positions_average_price_non_negative`;
`ck_positions_average_price_matches_quantity` —
`(quantity = 0 AND average_price = 0) OR (quantity <> 0 AND average_price > 0)`.
That last one is the schema-level guarantee that a flat position cannot carry an
entry price and an open one must.

Helper properties: `is_long`, `is_short`, `is_flat`.

### 7.6 Table: `portfolio_snapshots`

Model: `app/models/portfolio_snapshot.py:PortfolioSnapshot`. Migration
`51917e5fa5f1`. **Append-only** — nothing in the codebase UPDATEs a snapshot row.

Constraints: `pk_portfolio_snapshots`;
`ck_portfolio_snapshots_cash_non_negative`;
`ck_portfolio_snapshots_mark_price_positive` (`mark_price IS NULL OR mark_price > 0`).
Indexes: `ix_portfolio_snapshots_captured_at` (explicit),
`ix_portfolio_snapshots_source` (from `index=True`).

`mark_price` is **NULL when the position is flat** — there is nothing to value.
`is_equivalent_to(other)` compares quantity, cash, position_value, total_value,
realized_pnl, unrealized_pnl and total_charges; it powers
`SNAPSHOT_SKIP_UNCHANGED`.

### 7.7 Migration history

| Revision | Down-revision | File | What it does |
| -------- | ------------- | ---- | ------------ |
| `ea97efd67efb` | — | `20260825_0912_create_wallet_table.py` | `wallet` + its three CHECKs |
| `44b98124fbd4` | `ea97efd67efb` | `20260825_0956_create_orders_trades_and_positions.py` | creates the three enums explicitly (`checkfirst`), then `orders`, `trades`, `positions`; drops the types on downgrade so re-upgrading does not hit `DuplicateObjectError` |
| `b41705c11d09` | `44b98124fbd4` | `20260825_1010_add_execution_costs_and_net_pnl.py` | adds every cost/charge column; **renames** `trades.realized_pnl` → `gross_pnl` (autogenerate wanted DROP+ADD, which would have discarded P&L); adds `server_default` so NOT NULL columns can be added to a populated table; backfills `positions.net_realized_pnl` from `realized_pnl` |
| `51917e5fa5f1` | `b41705c11d09` | `20260825_1119_add_portfolio_snapshots.py` | creates `snapshot_source` enum + `portfolio_snapshots`; aligns three server defaults so autogenerate stops reporting phantom drift |

**Head is `51917e5fa5f1`.** No branches, no merges.

### 7.8 Locking and transaction boundaries

| Operation | Locking | Commit |
| --------- | ------- | ------ |
| `TradingEngine.place_order` | `SELECT wallet FOR UPDATE` **then** `SELECT position FOR UPDATE` (always this order) | one commit at the end (or one commit on the rejection path) |
| `WalletService.reset_wallet` | `SELECT wallet FOR UPDATE` | commits |
| `WalletService.initialize_wallet` | none (relies on the `id=1` PK + `IntegrityError` catch) | commits |
| `SnapshotService.capture` | none | `commit=True` by default; `commit=False` when called from `place_order` |
| All reads (`list_orders`, `history`, `summary`, …) | none | none |

---

## 8. API Architecture

Base URL: `http://localhost:8000`. All v1 paths are prefixed
`/api/v1` (`settings.API_V1_PREFIX`).

### 8.1 Authentication — THERE IS NONE

> **There is no login system, no user model, no session, no token, no API key,
> no `Authorization` header handling, and no per-request authorisation check
> anywhere in this codebase.**
>
> Verified by grep across `backend/app` and `frontend/src`: the only matches for
> "auth"/"token"/"password" are `POSTGRES_PASSWORD` in `config.py`, a comment in
> `market_data/base.py`, and a Yahoo limitation string.
>
> Consequences you must design around:
> * **Every endpoint below is fully public** to anyone who can reach the port.
> * Anyone can place orders, reset the wallet to full capital, or purge history.
> * There is exactly **one** wallet and **one** position — the platform is
>   single-user *by construction*, not by access control.
> * The only network-level protection is `CORSMiddleware`, which restricts
>   browser origins (`CORS_ORIGINS`) but does **not** stop `curl`, Postman or
>   any non-browser client.
> * There is **no rate limiting** either.
>
> If authentication is ever added, §15.11 describes where it would go.
>
> For the rest of §8, read "**Auth: none required**" on every single row.

### 8.2 Endpoint index

| # | Method | Path | Purpose |
| - | ------ | ---- | ------- |
| 1 | GET | `/` | Service banner (not under `/api/v1`) |
| 2 | GET | `/docs`, `/redoc`, `/openapi.json` | FastAPI docs |
| 3 | GET | `/api/v1/health/ping` | Liveness |
| 4 | GET | `/api/v1/health` | Readiness incl. database |
| 5 | GET | `/api/v1/wallet` | Read the wallet |
| 6 | POST | `/api/v1/wallet/initialize` | Create the wallet (idempotent) |
| 7 | POST | `/api/v1/wallet/reset` | Restore cash to opening capital |
| 8 | GET | `/api/v1/market-data/provider` | Provider capabilities |
| 9 | GET | `/api/v1/market-data/quote` | Current quote |
| 10 | GET | `/api/v1/market-data/candles` | Historical OHLCV |
| 11 | GET | `/api/v1/indicators/catalogue` | Available indicators |
| 12 | GET | `/api/v1/indicators` | Compute indicators |
| 13 | POST | `/api/v1/trading/orders` | **Place an order** |
| 14 | GET | `/api/v1/trading/orders` | Order history |
| 15 | GET | `/api/v1/trading/trades` | Trade history |
| 16 | GET | `/api/v1/trading/position` | Current position |
| 17 | GET | `/api/v1/trading/portfolio` | Account valuation |
| 18 | GET | `/api/v1/trading/execution-cost` | Cost preview, no side effects |
| 19 | GET | `/api/v1/stream/status` | Stream status |
| 20 | **WS** | `/api/v1/stream/prices` | **Live price stream** |
| 21 | GET | `/api/v1/portfolio/snapshots` | Equity curve |
| 22 | POST | `/api/v1/portfolio/snapshots` | Capture a snapshot now |
| 23 | GET | `/api/v1/portfolio/performance` | Performance summary |
| 24 | GET | `/api/v1/strategies` | List strategies |
| 25 | POST | `/api/v1/strategies/backtest` | **Run a backtest** |

### 8.3 Health

**`GET /api/v1/health/ping`** — liveness, touches no dependency.
Params: none. Body: none. Response `PingResponse`
`{"message":"pong","timestamp":"..."}`. Status: `200`. Errors: none.

**`GET /api/v1/health`** — readiness. Runs `SELECT 1`.
Response `HealthResponse` `{status, app_name, version, environment, timestamp,
database:{status, detail, latency_ms}}`.
Status: **always `200`** — inspect `status` / `database.status` in the body.
`HealthService.check_database` catches every exception and reports
`status:"error"`, so this endpoint never raises.

### 8.4 Wallet

**`GET /api/v1/wallet`**
Params/body: none. Response `WalletResponse` `{id, currency, initial_balance,
cash_balance, created_at, updated_at}`.
`200` on success; `404` `{"error":{"code":"wallet_not_found",...}}` when never
initialised. Validation: none.

**`POST /api/v1/wallet/initialize`**
Body (optional) `WalletInitializeRequest`: `{"initial_balance": "500000.00"}` —
`Decimal`, `gt=0`, `max_digits=18`, `decimal_places=2`. Omit the body entirely to
use `WALLET_INITIAL_BALANCE`.
Response `WalletResponse`.
**`201`** when created, **`200`** when it already existed (the handler mutates
`response.status_code`). Idempotent — a repeat call never overwrites a balance.
`422` on a non-positive or over-precise amount. Concurrent double-init is
absorbed by catching `IntegrityError` and adopting the winner's row.

**`POST /api/v1/wallet/reset`**
Body (optional) `WalletResetRequest`: `{"initial_balance": "..."}`. Omitted →
restores the existing `initial_balance`; supplied → re-opens the account at the
new amount.
Response `WalletResponse`. `200`; `404` if not initialised; `422` on a bad amount.

> **This endpoint sets `cash_balance = initial_balance` and nothing else.** It
> does *not* flatten the position, delete orders/trades, or purge snapshots. See
> §17 for the consequence.

### 8.5 Market data

**`GET /api/v1/market-data/provider`** — no params. Response
`ProviderCapabilities`. `200`. Errors: none.

**`GET /api/v1/market-data/quote`**
Query: `symbol` (`str | None`, optional; must be `RELIANCE` if supplied).
Response `Quote`. `200`; `400 unsupported_symbol`; `503 market_data_unavailable`.

**`GET /api/v1/market-data/candles`**
Query:

| Name | Type | Default | Validation |
| ---- | ---- | ------- | ---------- |
| `interval` | `Interval` | `1d` | enum member |
| `start` | `datetime \| None` | `None` | ISO 8601 |
| `end` | `datetime \| None` | `None` | ISO 8601 |
| `limit` | `int \| None` | `None` | `ge=1, le=5000` |
| `symbol` | `str \| None` | `None` | must be `RELIANCE` |

Response `CandleSeries` (oldest candle first).
`200`; `400 unsupported_symbol` / `unsupported_interval`; `422` on a bad
`interval` value or out-of-range `limit`; `503 market_data_unavailable`.

### 8.6 Indicators

**`GET /api/v1/indicators/catalogue`** — no params. Response
`list[IndicatorCatalogueEntry]`. `200`.

**`GET /api/v1/indicators`**
Query: `indicators` (**required** `str`, comma-separated specs, e.g.
`sma:20,ema:21,rsi:14,macd:12:26:9,bbands:20:2,vwap`), `interval`
(default `1d`), `limit` (`ge=2, le=5000`, default `250`), `start`, `end`.
Response `IndicatorSetResponse`.
Validation happens in `parse_specs` → `parse_spec` → `_coerce` →
`_validate_relationships`: unknown name, too many parameters, non-numeric
parameter, out-of-bounds parameter, MACD `fast >= slow`, and more than
`MAX_INDICATORS = 10` specs all raise `InvalidIndicatorError`.
Duplicate specs are silently de-duplicated by `IndicatorSpec.key`.
`200`; `400 invalid_indicator`; `422` (missing `indicators`, bad `interval`,
`limit` out of range); `503 market_data_unavailable`.

An indicator whose warm-up exceeds the window is **still returned**, flagged
`insufficient_data: true` with an empty `series` — the caller asked for it and
deserves to know why nothing is drawn.

### 8.7 Trading

**`POST /api/v1/trading/orders`** — the only mutating trading endpoint.

Body `PlaceOrderRequest`:

| Field | Type | Required | Validation |
| ----- | ---- | -------- | ---------- |
| `side` | `OrderSide` | yes | `BUY` \| `SELL` \| `SHORT_SELL` \| `BUY_TO_COVER` |
| `quantity` | `int` | yes | `gt=0`, `le=10_000_000` |
| `reference_price` | `Decimal` | yes | `gt=0`, `max_digits=18`, `decimal_places=2` — a **mid** price |
| `requested_price` | `Decimal \| None` | no | `gt=0`; recorded for audit, does not affect the fill |
| `symbol` | `str \| None` | no | must be `RELIANCE` |

Response `OrderResultResponse` — `{order, trade, position, gross_pnl,
total_charges, net_pnl, cash_delta}`.

| Status | Meaning |
| ------ | ------- |
| `201` | Filled. All four tables moved in one transaction. |
| `400 invalid_order` | quantity ≤ 0 / over `MAX_ORDER_QUANTITY`, or `reference_price` ≤ 0 |
| `400 invalid_position_operation` | closing-only side that would do more than close |
| `400 insufficient_funds` | wallet cannot cover notional **plus charges** |
| `400 unsupported_symbol` | `symbol` other than `RELIANCE` |
| `404 wallet_not_found` | wallet not initialised |
| `422` | schema validation (negative quantity, `reference_price` ≤ 0, bad enum) |

Note the deliberate overlap: `quantity <= 0` is caught by Pydantic (`422`)
before it ever reaches `_validate_request`; the engine check is the safety net
for non-HTTP callers.

**`GET /api/v1/trading/orders`** — query `limit` (`ge=1, le=500`, default 100),
`offset` (`ge=0`), `status` (alias for the `order_status` parameter;
`OrderStatus | None`). Newest first, **rejected orders included**. Response
`list[OrderResponse]`. `200`; `422` on bad paging.

**`GET /api/v1/trading/trades`** — query `limit`, `offset` (same bounds).
Newest first. Response `list[TradeResponse]`. `200`; `422`.

**`GET /api/v1/trading/position`** — no params. Response `PositionResponse`;
`quantity` carries direction. When nothing has ever traded, a **flat position is
materialised in memory** (not persisted) so this never 404s. `200`.

**`GET /api/v1/trading/portfolio`** — query `mark_price` (`Decimal | None`,
`gt=0`). Response `PortfolioResponse`.
Without `mark_price`, `unrealized_pnl` and `position_value` are **zero by
design** — the engine never fetches prices itself. `200`; `404 wallet_not_found`;
`422` on `mark_price <= 0`.

**`GET /api/v1/trading/execution-cost`** — query `side` (**required**),
`quantity` (`ge=1, le=10_000_000`), `reference_price` (`gt=0`). Runs the same
spread/slippage/fee models and **writes nothing**. Response
`ExecutionCostPreview`. `200`; `422`.

### 8.8 Portfolio history and performance

**`GET /api/v1/portfolio/snapshots`** — query `start`, `end` (`datetime|None`),
`limit` (`ge=1, le=5000`, default 500), `source` (`SnapshotSource|None`).
Response `SnapshotSeriesResponse` — snapshots **oldest first**, ready to plot.
A narrow `limit` returns the most recent slice, not the oldest. `200`; `422`.

**`POST /api/v1/portfolio/snapshots`** — query `mark_price`
(`Decimal|None`, `gt=0`). Body: none. Records `source=MANUAL`. Without
`mark_price` an open position cannot be valued, so only the cash side is
recorded. Response `SnapshotResponse`. `201`; `404 wallet_not_found`; `422`.

**`GET /api/v1/portfolio/performance`** — no params. Response
`PerformanceResponse`. Wins/losses count **closing fills only**
(`closed_quantity > 0`), judged on **net** P&L. `200`. No 404 — an empty
database returns zeros and `null`s.

### 8.9 Strategies and backtesting

**`GET /api/v1/strategies`** — no params. Response `list[StrategySchema]`
(name, display_name, description, params with default/min/max). `200`.

**`POST /api/v1/strategies/backtest`**

Body `BacktestRequest`:

| Field | Type | Default | Validation |
| ----- | ---- | ------- | ---------- |
| `strategy` | `str` | **required** | must be registered |
| `params` | `dict[str, Any]` | `{}` | validated by the strategy constructor |
| `interval` | `Interval` | `1d` | |
| `limit` | `int` | `500` | `ge=10, le=5000` |
| `start` / `end` | `datetime \| None` | `None` | |
| `initial_capital` | `Decimal` | `1000000.00` | `gt=0`, 18/2 |
| `fill_timing` | `FillTiming` | `next_open` | `next_open` \| `current_close` |
| `sizing_mode` | `SizingMode` | `percent_of_equity` | + `fixed_quantity`, `fixed_value` |
| `equity_percent` | `Decimal` | `95` | `gt=0, le=100` |
| `fixed_quantity` | `int` | `100` | `ge=1, le=10_000_000` |
| `fixed_value` | `Decimal` | `100000.00` | `gt=0`, 18/2 |
| `close_at_end` | `bool` | `true` | |

Response `BacktestResultSchema` including the full `trades` and `equity_curve`
arrays. **Writes nothing to the database.**
`200`; `400 unknown_strategy` / `invalid_strategy_params`; `422` on schema
violations; `503 market_data_unavailable`.

### 8.10 Validation summary

Three layers, in this order:

1. **Pydantic / FastAPI `Query`** — types, bounds, enums, decimal precision →
   `422` with FastAPI's `{"detail": [...]}` shape.
2. **Service layer** — symbol, interval, indicator specs, strategy params →
   `DomainError` subclasses → `{"error":{"code","message"}}`.
3. **Database CHECK constraints** — the last line of defence
   (`ck_wallet_cash_balance_non_negative`,
   `ck_positions_average_price_matches_quantity`,
   `ck_orders_filled_orders_have_a_price`, …). Reaching one of these means a
   bug: nothing in the code is supposed to rely on it. An unhandled
   `IntegrityError` would surface as a bare **500**.

---

## 9. WebSocket Architecture

### 9.1 The endpoint

```
ws://localhost:8000/api/v1/stream/prices
```

Declared in `app/api/v1/endpoints/stream.py` as `@router.websocket("/prices")`.
There is exactly **one** WebSocket endpoint in the application.

Companion HTTP route: `GET /api/v1/stream/status` → `PriceStreamService.status()`.

### 9.2 Connection lifecycle

```
CLIENT                          SERVER (stream.py : price_stream)
  |                                |
  |---- WS handshake ------------->| manager = get_connection_manager()
  |                                | service = get_price_stream()
  |                                | await manager.connect(websocket)
  |                                |    if len(connections) >= STREAM_MAX_CONNECTIONS:
  |                                |        stats.total_rejected += 1
  |                                |        raise ConnectionLimitReached
  |                                |    await websocket.accept()
  |                                |    connections.add(ws); total_accepted += 1
  |<--- accepted ------------------|
  |                                | if not service.is_running: await service.start()
  |                                |    (lazy: the feed starts on the FIRST listener)
  |<--- {"type":"status", ...} ----| service.status() + server_time
  |<--- {"type":"tick",   ...} ----| service.last_tick  (if any — instant first price)
  |                                |
  |                                | while True: message = await websocket.receive_json()
  |---- {"type":"ping"} ---------->|
  |<--- {"type":"pong", ...} ------|
  |                                |
  |<--- {"type":"tick",   ...} ----| broadcast, every poll interval / push tick
  |<--- {"type":"error",  ...} ----| on upstream failure
  |                                |
  |---- close -------------------->| except WebSocketDisconnect:
  |                                |     await manager.disconnect(ws)
  |                                | except Exception:
  |                                |     await manager.close(ws)   # 1000
```

**Rejection path** (pool full): the server calls `websocket.accept()` *then*
sends `{"type":"error","data":{"message":"...","fatal":true}}` and closes with
code **1008** (`_POLICY_VIOLATION`) — so the client sees a reason rather than a
bare handshake failure.

**Shutdown**: `shutdown_price_stream()` (from `lifespan`) stops the service and
calls `ConnectionManager.disconnect_all(code=1001)`.

### 9.3 Message types

The socket is **read-only for market data**. The only client message understood
is `{"type": "ping"}`; anything else is silently ignored by the loop.

| Direction | `type` | When |
| --------- | ------ | ---- |
| S→C | `status` | once, immediately after accept |
| S→C | `tick` | every price update (poll interval or push tick), plus one replay of `last_tick` on connect |
| S→C | `error` | upstream failure, or connection-limit refusal (`fatal: true`) |
| S→C | `pong` | in reply to a client `ping` |
| C→S | `ping` | client heartbeat, every 25s |

### 9.4 Payload structures

Built by `PriceStreamService.build_tick()`; mirrored in
`frontend/src/types/stream.ts`. **Every monetary value is a JSON string.**

```jsonc
// tick
{
  "type": "tick",
  "data": {
    "symbol": "RELIANCE", "exchange": "NSE",
    "last_price": "1402.35",
    "bid": "1402.21", "ask": "1402.49",
    "bid_ask_source": "modelled",      // "provider" | "modelled" | "unavailable"
    "volume": 4821330,
    "timestamp": "2026-08-25T09:14:00+00:00",
    "previous_close": "1395.10", "day_open": "1396.00",
    "day_high": "1408.75", "day_low": "1391.20",
    "change": "7.25", "change_percent": "0.52",
    "currency": "INR", "provider": "yahoo",
    "is_mock": false, "is_delayed": false,
    "mode": "poll",                    // "push" | "poll"
    "server_time": "2026-08-25T09:14:03.117441+00:00"
  }
}

// status  (also the body of GET /api/v1/stream/status, plus server_time)
{ "type": "status",
  "data": { "running": true, "mode": "poll", "provider": "yahoo",
            "is_mock": false, "is_delayed": false,
            "symbol": "RELIANCE", "exchange": "NSE",
            "poll_interval_seconds": 5.0, "connections": 1,
            "ticks_broadcast": 12, "errors": 0, "last_error": null,
            "server_time": "..." } }

// error
{ "type": "error",
  "data": { "message": "Upstream market data is unavailable.",
            "detail": "MarketDataUnavailableError: ...",
            "timestamp": "..." } }

// error (connection limit)
{ "type": "error", "data": { "message": "Refusing connection: ...", "fatal": true } }

// pong
{ "type": "pong", "data": { "server_time": "..." } }
```

### 9.5 Broadcasting

`ConnectionManager.broadcast(message)` in
`app/realtime/connection_manager.py`:

1. Takes a **snapshot** of the connection set under `asyncio.Lock` — the set is
   never mutated while being iterated.
2. `asyncio.gather(*(send_to(s, message) for s in targets),
   return_exceptions=True)` — sends run **concurrently**, so one slow client
   cannot stall the rest.
3. `send_to` catches any exception, increments `stats.send_failures`, and
   **drops that client** via `disconnect()` — dead sockets are reaped rather
   than left to fail on every future tick.
4. Returns the delivered count; logs when `delivered < len(targets)`.

`ConnectionStats` tracks `total_accepted`, `total_rejected`,
`total_disconnected`, `messages_sent`, `send_failures`, `started_at`.

### 9.6 Reconnection

**Server side: none.** The server never dials a client. It removes the socket
and moves on. `STREAM_MAX_CONNECTIONS` (default 50) caps the pool.

**Client side:** `useLivePrice` (§5.6) — backoff 1s→15s with 0.85–1.15 jitter,
`attempt` counter surfaced in `TerminalHeader`, and a manual reconnect button
that resets the backoff.

### 9.7 Error handling

| Failure | Handling |
| ------- | -------- |
| Upstream provider error during a poll | `_poll_once` catches `MarketDataError` **and** bare `Exception` → `_handle_failure` → error frame broadcast; the scheduler keeps running |
| Upstream error in push mode | `_run_push_loop` catches, broadcasts, sleeps `backoff` (1s→30s), re-attaches |
| Send to one client fails | that client is dropped; the broadcast continues |
| Client sends malformed JSON | `websocket.receive_json()` raises → caught by the endpoint's bare `except Exception` → `manager.close(ws)` |
| Pool full | `ConnectionLimitReached` → fatal error frame + close 1008 |
| Socket already closed during `close()` | `RuntimeError`/`ConnectionError` swallowed in `ConnectionManager.close`/`disconnect_all` |

Comment from the source, worth preserving: `except Exception` in the endpoint is
deliberate — *"one client must not take others down"*.

---

## 10. Data Flow

### 10.1 Live market data

```
[1] Browser mounts Terminal
       useLivePrice() -> new WebSocket(wsUrl('/stream/prices'))

[2] stream.py:price_stream
       ConnectionManager.connect()      accept + add to pool
       if not service.is_running: service.start()      <- LAZY START

[3a] POLL mode (yahoo)                 [3b] PUSH mode (mock)
     AsyncIOScheduler job "price-poll"      asyncio.Task _run_push_loop()
     every STREAM_POLL_INTERVAL_SECONDS     async for quote in
     -> _poll_once()                            provider.subscribe_live_data()
        if not manager.has_listeners:
            return          <-- no listeners, no upstream call
        provider.get_current_quote()

[4] PriceStreamService._broadcast_quote(quote)
       payload = build_tick(quote)
           bid/ask null?  -> SpreadModel.quote(last_price)
                             bid_ask_source = "modelled"
           change / change_percent from previous_close
       self.last_tick = payload      <- replayed to the next new client
       self.tick_count += 1
       ConnectionManager.broadcast(payload)

[5] ConnectionManager.broadcast
       snapshot the set under lock
       asyncio.gather(send_to(...))  concurrent, failures dropped

[6] useLivePrice.onmessage  case 'tick'
       setTick(data); setError(null); lastTickAtRef = now; setIsStale(false)

[7] Terminal re-render, markPrice = tick.last_price
       TerminalHeader / PriceChart.series.update() / PositionPanel /
       TradingPanel / useAccount throttled revaluation  (see §6.7)
```

### 10.2 Historical market data

```
[1] PriceChart mounts, or the timeframe chip changes
       timeframe = TIMEFRAMES.find(interval)     e.g. {interval:'5m', limit:240}
       useEffect([timeframe]) -> new AbortController()

[2] fetchCandles('5m', 240, signal)
       GET /api/v1/market-data/candles?interval=5m&limit=240

[3] market_data.get_candles
       Depends(get_market_data_service) -> Depends(get_provider)  [singleton]
       RelianceMarketDataService.get_historical_candles()
           _require_supported_symbol / _require_supported_interval
           effective_limit = min(240, MAX_CANDLES=5000)

[4] YahooFinanceProvider.get_historical_candles()
       vendor_interval = _INTERVAL[Interval.FIVE_MINUTES]  -> "5m"
       no start -> params = {"interval":"5m", "range": _DEFAULT_RANGE[...]="5d"}
       vendor_symbol = "RELIANCE.NS"
       httpx GET /RELIANCE.NS
       _fetch_chart: raise_for_status, unwrap chart.result[0]
       _parse_candles: zip timestamp[] with indicators.quote[0].{open,high,low,close,volume}
                       skip any bar with a null OHLC
       candles[-240:]     keep the most recent

[5] CandleSeries -> JSON (Decimals as strings)

[6] PriceChart .then(series => ...)
       candleSeries.setData(candles.map(toCandlestick))
       volumeSeries.setData(candles.map(toVolume))
       lastBarRef.current = toCandlestick(last)      <- live ticks mutate this
       setBarCount(); chart.timeScale().fitContent()
```

In parallel, `useIndicators(interval, limit)` issues
`GET /api/v1/indicators?...` over the **same** interval and limit, so the study
and the price are computed from the same candle window.

### 10.3 BUY order

```
FRONTEND
  TradingPanel: click "Buy" -> submit('BUY')
     blocked = disabled || noPrice || invalidQuantity || pending !== null
     placeOrder({side:'BUY', quantity:10, reference_price: markPrice})
     POST /api/v1/trading/orders

BACKEND  (single transaction — see the §4.10 BUY diagram for the call sequence)
  PlaceOrderRequest validation
  TradingEngine.place_order
     lock wallet (FOR UPDATE)            -> WalletNotFoundError -> 404
     lock/create position (FOR UPDATE)
     INSERT orders (PENDING)
     ExecutionEngine.execute:
        SpreadModel  ask = mid + half-spread
        SlippageModel price * (1 + rate)       (adverse: up for a buy)
        FeeCalculator brokerage + exchange + SEBI + stamp duty + GST
                      (intraday buy: NO STT)
     _validate_against_position   BUY: unrestricted, may reverse a short
     assert_affordable            cash_delta < 0 -> need notional + charges
     apply_fill                   flat -> qty=+10, avg=fill price, realized=0
                                  long -> re-average
                                  short -> close then possibly reverse
     UPDATE positions / UPDATE wallet / INSERT trades / UPDATE orders(FILLED)
     INSERT portfolio_snapshots (source=TRADE, mark=fill price, commit=False)
     COMMIT

FRONTEND
  201 -> setLastFill(result) -> fill receipt
      -> onFilled -> Terminal.handleFilled -> useAccount.refresh()
      -> 5 parallel GETs -> every panel updates together
```

### 10.4 SELL order

Identical transport and transaction shape. Differences:

* `_validate_against_position` **enforces**: `position.quantity > 0` and
  `quantity <= position.quantity`, else `InvalidPositionOperationError` (400,
  order persisted as `REJECTED`).
* `SpreadModel` uses the **bid**; slippage pushes the price **down**.
* `FeeCalculator`: intraday **STT is charged** on the sell leg; **no stamp duty**.
* `assert_affordable` returns immediately — `cash_delta >= 0` on a sell.
* `apply_fill` realizes P&L on `closed = min(|qty|, |fill_qty|)` units at
  `direction = +1`; if the position goes flat, `average_price` resets to `0.0000`.

### 10.5 SHORT order

* `_validate_against_position` imposes **no restriction** — `SHORT_SELL` may
  cross zero, closing a long and opening a short in one order.
* Same bid-side pricing and STT treatment as SELL.
* `apply_fill` on a reversal: `closed = min(|qty|, |fill_qty|)`,
  `opened = |fill_qty| - closed`, `new_average = fill_price`.
* **Short proceeds are credited as spendable cash.** No margin is reserved. See
  §4.9 and §17.4.

### 10.6 COVER order

* `_validate_against_position` **enforces**: `position.quantity < 0` and
  `quantity <= abs(position.quantity)`.
* Ask-side pricing, slippage upward, buy-leg charges (stamp duty, no intraday STT).
* `assert_affordable` applies — a cover is a debit and can be rejected for funds.
* `apply_fill` realizes at `direction = -1`:
  `realized = (exit - entry) * qty * (-1)`.

### 10.7 Backtest

```
POST /api/v1/strategies/backtest
  create_strategy(name, params)     registry -> MovingAverageCrossover(**params)
  service.get_historical_candles()  same provider path as §10.2
  BacktestEngine(config).run(strategy, candles, symbol, exchange, interval)
     |
     strategy.reset()
     portfolio = BacktestPortfolio(initial_cash=config.initial_capital)
     indicators = _precompute(strategy, candles, interval)
         IndicatorService.calculate() once over the WHOLE series
         values aligned BY TIMESTAMP back onto the candle index
         (warm-up stays None rather than shifting everything left)
     |
     for index, candle in enumerate(candles):
         portfolio.record_equity(index, candle.timestamp, candle.close)
         if index < strategy.warmup_bars(): continue
         if index >= len(candles) - 1:      continue   # no "next open" to fill on
         decision = strategy.on_bar(StrategyContext(...))
         if not decision.signal.is_actionable: continue
         _execute:
             reference_price = candles[index+1].open      (FillTiming.NEXT_OPEN)
                            or candles[index].close        (CURRENT_CLOSE = lookahead)
             quantity = decision.quantity or _order_quantity(signal, portfolio, price)
                 PositionSizer.target_size(equity, price)
                     FIXED_QUANTITY   -> config.fixed_quantity
                     FIXED_VALUE      -> int(fixed_value / price)
                     PERCENT_OF_EQUITY-> int(equity * equity_percent/100 / price)
                 BUY   -> max(target - current, 0)
                 SHORT -> max(target + current, 0)     # covers the long too
                 SELL  -> max(current, 0)
                 COVER -> max(-current, 0)
             _settle:
                 ExecutionEngine.price_fill(...)     <-- THE LIVE PRICING CODE
                 portfolio.apply(fill, ...)
                     can_afford? else InsufficientCash -> rejected_orders += 1,
                                                          logged, run continues
                     apply_fill(...)                 <-- THE LIVE ACCOUNTING CODE
     |
     if config.close_at_end: _close_out(candles, portfolio)
         flatten on the last bar at its close
         pop the last equity point and re-record it, so the curve ends realized
     |
     summarise(...)  -> BacktestResult
         closing = [t for t in trades if t.closed_quantity > 0]
         wins    = [t for t in closing if t.net_pnl > 0]      <- NET, not gross
         max_drawdown(curve), exposure_pct, profit_factor, ...
  BacktestResultSchema -> 200
```

**Nothing is persisted.** `BacktestEngine` constructs
`ExecutionEngine(session=None, ...)` — safe because only `price_fill()` is ever
called on it, and that method touches no session. The parity suite in
`tests/test_backtest.py` runs the same order sequence through both the live
database-backed engine and the in-memory backtester and asserts the numbers
match exactly.

### 10.8 Strategy execution

```
Strategy (app/strategies/base.py)
   name / display_name / description / params: tuple[StrategyParam, ...]
   required_indicators() -> list[IndicatorSpec]      (abstract)
   on_bar(context) -> Decision                       (abstract)
   warmup_bars() -> int                              (default 0)
   reset()                                           (default no-op)
   describe() -> dict                                (metadata for the API)

StrategyContext  (frozen dataclass — the ONLY thing a strategy can see)
   index, candle, candles[: index+1], position, average_price, cash, equity
   indicator(key, offset=0)  -> Decimal | None
       offset < 0 raises ValueError:
           "Negative offsets would read future bars, which is lookahead bias."

Signal (StrEnum)      -> OrderSide via .order_side
   BUY   -> OrderSide.BUY
   SELL  -> OrderSide.SELL
   SHORT -> OrderSide.SHORT_SELL
   COVER -> OrderSide.BUY_TO_COVER
   HOLD  -> None   (.is_actionable == False)

Decision(signal, quantity=None, reason="")
   quantity=None means "let PositionSizer decide"
```

`MovingAverageCrossover` (the only registered strategy):

```
params: fast=10 (2..200), slow=30 (3..500), allow_short=1 (0..1)
required_indicators() -> [SMA(fast), SMA(slow)]
warmup_bars()         -> slow

on_bar:
   read fast/slow at offset 0 and offset 1
   any None            -> HOLD "indicators still warming up"
   crossed_up   = fast_prev <= slow_prev and fast_now >  slow_now
   crossed_down = fast_prev >= slow_prev and fast_now <  slow_now
   crossed_up:   already long -> HOLD; else BUY   (a BUY covers a short and
                                                   opens the long in one order)
   crossed_down: already short -> HOLD
                 allow_short   -> SHORT           (closes a long and opens a
                                                   short in one order)
                 else is_long  -> SELL
                 else          -> HOLD
```

Comparing *only* the current bar would re-fire the same signal every bar; the
previous-bar comparison is what makes it a **cross**.

> **Strategies are backtest-only.** There is no live strategy runner, no
> scheduler that calls `on_bar` against the real market, and no path from a
> `Signal` to `TradingEngine.place_order`. See §15.4.

---

## 11. Configuration Architecture

### 11.1 Where configuration lives

| File | Consumed by | Committed? |
| ---- | ----------- | ---------- |
| `.env` (repo root) | `docker-compose.yml` variable substitution | **no** (gitignored) |
| `.env.example` (repo root) | template | yes |
| `backend/.env` | `Settings(env_file=".env")` **and** compose `env_file:` | **no** |
| `backend/.env.example` | template, 92 lines, every setting documented | yes |
| `frontend/.env` | Vite (`VITE_`-prefixed only) | **no** |
| `frontend/.env.example` | template | yes |
| `backend/app/core/config.py` | the code — defaults for everything | yes |
| `docker-compose.yml` | container topology + env overrides | yes |
| `backend/alembic.ini` | Alembic, **without** a URL | yes |
| `frontend/vite.config.ts` | dev server, `@` alias, polling | yes |
| `backend/pyproject.toml` | pytest configuration only | yes |

`.gitignore` covers `.env` and `*.env` while re-including `!.env.example`.
**No real secret is committed anywhere in this repository**, and none is quoted
in this document.

### 11.2 The `Settings` class

`backend/app/core/config.py`. `BaseSettings` with
`env_file=".env"`, `case_sensitive=False`, `extra="ignore"`.

> **`app/core/config.py` is the only module that reads the environment.** Every
> other module imports `settings`. Keep it that way.

Two details that will bite you if you forget them:

* `settings = get_settings()` runs **at import time**, and `get_settings` is
  `@lru_cache`d. Anything that needs to override a setting (notably
  `tests/conftest.py`) must set the environment variable **before the first
  import of any `app.*` module**.
* `CORS_ORIGINS` is annotated `Annotated[list[str], NoDecode]` so
  pydantic-settings does not JSON-decode it before `_parse_origins` runs. That
  validator accepts a comma-separated string, a JSON array, or a real list.

### 11.3 Environment variables

**Application**

| Variable | Default | Notes |
| -------- | ------- | ----- |
| `APP_NAME` | `Virtual Trading Platform` | |
| `APP_VERSION` | `0.1.0` | |
| `ENVIRONMENT` | `development` | `development` \| `staging` \| `production` |
| `DEBUG` | `true` | drives log level |
| `API_V1_PREFIX` | `/api/v1` | |
| `BACKEND_HOST` / `BACKEND_PORT` | `0.0.0.0` / `8000` | declared but not read by `main.py` — uvicorn takes them on the CLI |

**Database**

| Variable | Default |
| -------- | ------- |
| `POSTGRES_USER` | `vtrader` |
| `POSTGRES_PASSWORD` | `vtrader_dev_password` *(development placeholder — replace it anywhere real)* |
| `POSTGRES_DB` | `virtual_trading` |
| `POSTGRES_HOST` | `localhost` (compose overrides to `postgres`) |
| `POSTGRES_PORT` | `5432` |
| `DB_ECHO` | `false` |
| `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` | `5` / `10` |
| `DB_POOL_PRE_PING` | `true` |
| `DB_USE_NULL_POOL` | `false` — **must be `true` under pytest** |

`Settings.DATABASE_URL` is a computed field:
`postgresql+asyncpg://USER:PASSWORD@HOST:PORT/DB`. It is never written to a file
and is injected into Alembic at runtime by `alembic/env.py`.

**CORS** — `CORS_ORIGINS`, default `["http://localhost:5173"]`.

**Domain** — `TRADING_SYMBOL=RELIANCE`, `TRADING_EXCHANGE=NSE`.

**Market data** — `MARKET_DATA_PROVIDER` (`yahoo` | `mock`),
`MARKET_DATA_TIMEOUT_SECONDS=15.0`, `MARKET_DATA_API_KEY`,
`MARKET_DATA_API_SECRET`.

> Both credential fields are typed `SecretStr | None` so the value never appears
> in logs, tracebacks or `repr()`. **The default `yahoo` provider needs neither,
> and no code path currently reads them** — they exist for a future provider.

**Execution realism** — `EXECUTION_SEGMENT` (`INTRADAY` | `DELIVERY`),
`SPREAD_BPS=2`, `SLIPPAGE_MODEL` (`NONE` | `FIXED_BPS` | `PERCENT`),
`SLIPPAGE_BPS=2`, `SLIPPAGE_PERCENT=0`.

**Charges** — `CHARGES_ENABLED=true`, `BROKERAGE_PERCENT=0.03`,
`BROKERAGE_MAX_PER_ORDER=20`, `STT_INTRADAY_SELL_PERCENT=0.025`,
`STT_DELIVERY_PERCENT=0.1`, `EXCHANGE_TXN_PERCENT=0.00297`,
`SEBI_CHARGES_PERCENT=0.0001`, `STAMP_DUTY_INTRADAY_BUY_PERCENT=0.003`,
`STAMP_DUTY_DELIVERY_BUY_PERCENT=0.015`, `GST_PERCENT=18`,
`DP_CHARGES_PER_SELL=0`. All are **percentages of turnover** (`0.03` = 0.03%)
and all are `Decimal`.

**Wallet** — `WALLET_INITIAL_BALANCE=1000000.00`, `WALLET_CURRENCY=INR`.

**Streaming** — `STREAM_POLL_INTERVAL_SECONDS=5.0`,
`STREAM_MAX_CONNECTIONS=50`, `STREAM_MODEL_BID_ASK=true`.

**Snapshots** — `SNAPSHOT_ENABLED=true`, `SNAPSHOT_INTERVAL_SECONDS=300.0`,
`SNAPSHOT_ON_TRADE=true`, `SNAPSHOT_SKIP_UNCHANGED=true`.

**Mock provider** — `MOCK_BASE_PRICE=1400`, `MOCK_VOLATILITY_BPS=15`,
`MOCK_SPREAD_BPS=4`, `MOCK_TICK_INTERVAL_SECONDS=2.0`, `MOCK_SEED` (unset).

**Frontend (build-time, baked into the bundle)** — `VITE_API_BASE_URL`,
`VITE_API_V1_PREFIX`, `VITE_WS_BASE_URL` (blank → derived from the API base by
swapping `http`→`ws`).

**Compose-only** — `POSTGRES_HOST_PORT`, `BACKEND_HOST_PORT`,
`FRONTEND_HOST_PORT`.

### 11.4 Container topology

`docker-compose.yml` — three services, one named volume.

| Service | Image / target | Host port | Notes |
| ------- | -------------- | --------- | ----- |
| `postgres` | `postgres:16-alpine` | `${POSTGRES_HOST_PORT:-5432}` | `TZ`/`PGTZ` `Asia/Kolkata`; `pg_isready` healthcheck; volume `vtrader_postgres_data` |
| `backend` | `./backend`, target `dev` | `${BACKEND_HOST_PORT:-8000}` | `env_file: ./backend/.env` **plus** explicit `POSTGRES_HOST: postgres` overrides (real env vars outrank `.env`); source bind-mounted for `--reload`; healthcheck hits `/api/v1/health/ping`; `depends_on: postgres service_healthy` |
| `frontend` | `./frontend`, target `dev` | `${FRONTEND_HOST_PORT:-5173}` | `VITE_API_BASE_URL: http://localhost:${BACKEND_HOST_PORT}` — the bundle runs in the **host** browser, so it must use the published port, not the service name; `CHOKIDAR_USEPOLLING=true` for bind-mount watching |

**Redis is intentionally absent** (stated in the compose header comment).

Production targets exist but are not wired into compose: `backend` `prod`
(source baked in, no reload, no test tooling) and `frontend` `prod`
(nginx serving `/app/dist` with `nginx.conf`).

---

## 12. Error Handling

### 12.1 Custom exception hierarchy

```
Exception
 └── DomainError                       app/core/exceptions.py
     |   status_code = 400, code = "domain_error"
     |   .message attribute
     |
     ├── WalletNotFoundError           404  wallet_not_found
     |
     ├── MarketDataError               502  market_data_error
     |   ├── MarketDataUnavailableError    503  market_data_unavailable
     |   ├── UnsupportedSymbolError        400  unsupported_symbol
     |   ├── UnsupportedIntervalError      400  unsupported_interval
     |   └── LiveDataNotSupportedError     501  live_data_not_supported
     |
     ├── TradingError                  400  trading_error
     |   ├── InvalidOrderError             400  invalid_order
     |   ├── InsufficientFundsError        400  insufficient_funds
     |   └── InvalidPositionOperationError 400  invalid_position_operation
     |
     ├── InvalidIndicatorError         400  invalid_indicator
     |       (declared in app/indicators/definitions.py)
     |
     ├── UnknownStrategyError          400  unknown_strategy
     └── InvalidStrategyParamsError    400  invalid_strategy_params
             (both declared in app/strategies/registry.py)

Exception (NOT a DomainError — never crosses the HTTP boundary)
 ├── ConnectionLimitReached            app/realtime/connection_manager.py
 └── InsufficientCash                  app/backtest/portfolio.py
```

Two subclasses are declared outside `core/exceptions.py` — `InvalidIndicatorError`
in `indicators/definitions.py` and the two strategy errors in
`strategies/registry.py` — but both still inherit `DomainError`, so the single
handler in `main.py` catches them.

`ConnectionLimitReached` and `InsufficientCash` deliberately do **not** inherit
`DomainError`: the first is handled inside the WebSocket endpoint, the second is
caught by `BacktestEngine._settle` and counted as a rejected order.

### 12.2 Validation errors

| Layer | Produces | Wire shape |
| ----- | -------- | ---------- |
| Pydantic body models, `Query(...)` constraints | `RequestValidationError` | `422 {"detail":[{"loc","msg","type"}]}` (FastAPI default — **not overridden**) |
| Domain validators (symbol, interval, indicator spec, strategy params, order rules) | `DomainError` subclass | `4xx {"error":{"code","message"}}` |

### 12.3 Database errors

| Situation | Handling |
| --------- | -------- |
| Any exception inside a request | `get_session()` rolls back before re-raising, so a dirty session never returns to the pool |
| Concurrent wallet init | `WalletService.initialize_wallet` catches `IntegrityError`, rolls back, adopts the existing row, returns `created=False` |
| Concurrent position create | `PositionManager.get_or_create_for_update` catches `IntegrityError`, rolls back, re-locks the winner's row |
| Health probe failure | `HealthService.check_database` catches everything → `{"status":"error","detail":"<Type>: <msg>"}`, still HTTP 200 |
| CHECK constraint violation | **Unhandled.** Would surface as a bare `500`. Nothing is supposed to reach one — the engine checks first. |
| Connection lost mid-request | Unhandled → `500`. `DB_POOL_PRE_PING=true` mitigates stale pooled connections. |

### 12.4 Market-data errors

Fully tabulated in §5.7. Key property: `YahooFinanceProvider._fetch_chart`
converts **every** `httpx` failure mode plus malformed JSON plus an empty
`chart.result` into `MarketDataUnavailableError`, so nothing vendor-specific
leaks upward.

### 12.5 Trading errors

| Error | Raised by | Order row outcome |
| ----- | --------- | ----------------- |
| `InvalidOrderError` | `TradingEngine._validate_request` | **no row** — raised before the order is created |
| `UnsupportedSymbolError` | `TradingEngine._resolve_symbol` | **no row** |
| `WalletNotFoundError` | `TradingEngine.place_order` | **no row** |
| `InvalidPositionOperationError` | `_validate_against_position` | row persisted as `REJECTED` + reason, committed |
| `InsufficientFundsError` | `PortfolioManager.assert_affordable` | row persisted as `REJECTED` + reason, committed |

So the audit trail records *rejected orders that were validly formed*, but not
malformed ones. `rejection_reason` is truncated to 500 characters.

### 12.6 Frontend error handling

| Layer | Behaviour |
| ----- | --------- |
| `api/client.ts` | Unwraps both envelopes into `ApiError(message, status, code)`; network failure → "Cannot reach the API…"; `AbortError` re-thrown untouched |
| `useAccount` | 404 from `/wallet` or `/trading/portfolio` → `needsWallet = true` (an expected first-run state, not an error); anything else → `error` string |
| `useAccount` revaluation | Failures are **swallowed** — the next tick retries |
| `useIndicators` | Sets `error`, ignores aborted requests |
| `useLivePrice` | `error` frames → `error` state; unparseable JSON ignored; `onclose` → reconnect with backoff |
| `Terminal` | Renders an error banner with a `Retry` button |
| `TradingPanel` | Renders an "Order rejected" alert with the server's message; clears `lastFill` |
| `PageShell` | Renders "Could not load this page" + `Retry` for every history page |

---

## 13. Testing Architecture

### 13.1 Layout and philosophy

`backend/tests/` — 13 pytest modules, ~353 test functions, plus
`fixtures/yahoo_payloads.py` and `_ws_probe.py` (a manual probe script, not
collected). Configuration lives in `backend/pyproject.toml`:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "function"
addopts = "-q --strict-markers"
cache_dir = "/tmp/.pytest_cache"
filterwarnings = ["error::DeprecationWarning:app.*"]
```

`asyncio_mode = "auto"` means `async def test_*` needs no marker.
`filterwarnings` turns any `DeprecationWarning` raised **from `app.*`** into an
error.

### 13.2 Fixtures — `tests/conftest.py`

| Fixture | Scope | Does |
| ------- | ----- | ---- |
| `prepared_database` | session, **autouse** | Sets `POSTGRES_DB=virtual_trading_test` and `DB_USE_NULL_POOL=true` **before any `app.*` import**, drops/creates the test DB via raw asyncpg (CREATE DATABASE cannot run in a transaction), runs `alembic upgrade head`, and drops it afterwards |
| `clean_tables` | function, **autouse** | `TRUNCATE portfolio_snapshots, trades, orders, positions, wallet RESTART IDENTITY CASCADE` before every test |
| `session` | function | a raw `AsyncSession` for service-layer tests |
| `client` | function | `httpx.AsyncClient(transport=ASGITransport(app=app))` — drives the ASGI app directly, **no network** |

> Tests run against **real PostgreSQL, never SQLite** — the code relies on
> `NUMERIC` precision, CHECK constraints, native enums and `SELECT … FOR UPDATE`.
> A dedicated `virtual_trading_test` database is created and dropped around the
> session, so development data is untouched.

### 13.3 What each module covers

**Pure unit tests (no DB, no network, no event loop):**

| Module | Tests | Subject |
| ------ | ----- | ------- |
| `test_position_accounting.py` | 23 | `apply_fill` and `PnLCalculator` as pure arithmetic; every expected value hand-worked |
| `test_execution_costs.py` | 29 | `SpreadModel`, `SlippageModel`, `FeeCalculator` in isolation |
| `test_indicators.py` | 47 | Spec parsing + every indicator; expectations derived from defining identities (Bollinger's middle band *is* the SMA; MACD's histogram *is* the difference) |
| `test_strategies.py` | 30 | `Signal`/`Decision`/`StrategyContext` (including the lookahead guard), `MovingAverageCrossover`, the registry |

**Integration tests against real PostgreSQL:**

| Module | Tests | Subject |
| ------ | ----- | ------- |
| `test_trading_engine.py` | 38 | Cash movement, persistence, atomicity, DB constraints. Runs on a **frictionless** engine (`ExecutionEngine.frictionless`) so accounting is isolated from cost |
| `test_realistic_execution.py` | 22 | Four outcomes — profitable/losing long, profitable/losing short — traced from reference price through spread, slippage and charges to gross/charges/net, with the wallet checked against the arithmetic. Models configured **explicitly**, not from settings, so editing `.env` cannot silently change expectations |
| `test_portfolio_history.py` | 31 | Snapshots + `PerformanceAnalyzer`; persistence verified by reading back through a **brand-new engine**, which is what a restart looks like to the database |
| `test_wallet_api.py` / `test_wallet_persistence.py` | 10 / 6 | Wallet endpoints; persistence through a fresh engine |

**API / provider / realtime tests (offline):**

| Module | Tests | Subject |
| ------ | ----- | ------- |
| `test_market_data_provider.py` | 20 | `YahooFinanceProvider` against `httpx.MockTransport` + canned payloads |
| `test_market_data_api.py` | 18 | Service + endpoints with the provider replaced via `app.dependency_overrides[get_market_data_service]` |
| `test_realtime.py` | 35 | `ConnectionManager`, `MockMarketDataProvider`, `PriceStreamService` |
| `test_stream_endpoint.py` | 12 | The WebSocket endpoint via Starlette `TestClient`, with a fast seeded mock provider |
| `test_backtest.py` | 32 | `PositionSizer`, `FillTiming`, `max_drawdown`, `summarise`, **plus a live-vs-backtest parity suite** |

### 13.4 The parity suite (the important one)

`tests/test_backtest.py` runs the same order sequence through the live
database-backed `TradingEngine` **and** the in-memory `BacktestPortfolio` and
asserts the numbers are identical. That is what makes the backtester comparable
to real trading rather than merely similar to it — it is only possible because
both paths call the same `ExecutionEngine.price_fill()` and the same
`apply_fill()`.

### 13.5 Frontend tests

> **There are no frontend tests.** No Vitest, no Jest, no Testing Library, no
> Playwright, no Cypress. `package.json` has no `test` script.
>
> The only automated frontend check is:
>
> ```
> npm run typecheck    # tsc --noEmit -p tsconfig.json && tsc --noEmit -p tsconfig.node.json
> ```
>
> which also runs as part of `npm run build`. TypeScript is `strict` with
> `noUnusedLocals` and `noUnusedParameters`, so it catches a fair amount — but
> **no component behaviour is tested anywhere.**

### 13.6 How to run the tests

**Backend, inside Docker (the intended path):**

```bash
docker compose up -d                        # postgres + backend must be running
docker compose exec backend pytest          # whole suite
docker compose exec backend pytest -v
docker compose exec backend pytest tests/test_trading_engine.py
docker compose exec backend pytest tests/test_backtest.py -k parity
```

**Backend, on the host:**

```bash
docker compose up -d postgres               # a real PostgreSQL is required
cd backend
pip install -r requirements-dev.txt
pytest
```

The suite creates and drops `virtual_trading_test` itself; `POSTGRES_*` in
`backend/.env` must point at a reachable server with permission to
`CREATE DATABASE`.

**Frontend:**

```bash
docker compose exec frontend npm run typecheck
# or on the host:
cd frontend && npm install && npm run typecheck
```

**Migrations:**

```bash
docker compose exec backend alembic current
docker compose exec backend alembic upgrade head
docker compose exec backend alembic history --verbose
docker compose exec backend alembic downgrade -1
docker compose exec backend alembic revision --autogenerate -m "describe change"
```

**Manual WebSocket probe:**

```bash
docker compose exec backend python tests/_ws_probe.py ws://localhost:8000/api/v1/stream/prices 3
```

---

## 14. Dependency Map

### 14.1 Import direction (arrows point *towards the dependency*)

```
frontend/src/components/**  ──►  frontend/src/hooks/**  ──►  frontend/src/api/**
        │                                 │                        │
        └────────────────────►  frontend/src/types/**  ◄───────────┘
                                (hand-mirrored from backend/app/schemas/**)
                                          ║
                                     HTTP + WS
                                          ║
                                          ▼
                        backend/app/api/v1/endpoints/**
                                 │        │        │
             ┌───────────────────┘        │        └───────────────┐
             ▼                            ▼                        ▼
     app/services/**              app/trading/engine.py      app/analytics/**
             │                            │                        │
             ▼                            ▼                        │
     app/market_data/**        OrderManager  ExecutionEngine       │
             │                 PositionManager PortfolioManager    │
             │                            │         │              │
             │                            ▼         ▼              │
             │                    SpreadModel  SlippageModel       │
             │                    FeeCalculator  PnLCalculator     │
             │                            │                        │
             └──────────────┬─────────────┴────────────────────────┘
                            ▼
                 app/repositories/**  ──►  app/models/**  ──►  app/db/**
                            │                                     │
                            └──────────► app/core/config ◄────────┘
                                         app/core/exceptions
                                         app/core/logging
                                              ▲
                                              │  (everything)

     app/backtest/**  ──►  app/trading/{execution,position_manager,pnl,
                                        spread,slippage,fees}
                      ──►  app/strategies/**  ──►  app/indicators/definitions
                      ──►  app/indicators/service

     app/realtime/price_stream  ──►  app/market_data/{base,registry}
                                ──►  app/trading/{spread,pnl}
                                ──►  app/realtime/connection_manager
```

### 14.2 Layer rules that the code actually obeys

| Rule | Enforced how |
| ---- | ------------ |
| `app/trading/**` imports **no** web framework and **no** market-data provider | verifiable by grep; `TradingEngine`'s docstring states it |
| Services never import `fastapi` | true today for `WalletService`, `RelianceMarketDataService`, `HealthService`, `SnapshotService`, `PerformanceAnalyzer`, `IndicatorService` |
| Endpoints contain no business logic | every endpoint module's docstring says "transport only" |
| `app/core/config.py` is the only reader of the environment | no other `os.environ` access in `app/**` |
| Strategies know nothing about wallet/DB/web | `StrategyContext` is the only input they receive |
| The backtester reuses live pricing and accounting | `BacktestEngine` calls `ExecutionEngine.price_fill`; `BacktestPortfolio` calls `apply_fill` |

### 14.3 Deliberate exceptions to those rules

| Exception | Where | Why |
| --------- | ----- | --- |
| `TradingEngine` imports `SnapshotService` **inside** `place_order` | `app/trading/engine.py` | a module-level import would be circular (`analytics` → `trading` → `analytics`) |
| `analytics/scheduler.py` imports `get_price_stream` and `get_provider` **inside** `_current_mark_price` | `app/analytics/scheduler.py` | same reason, plus it keeps the module importable without the realtime stack |
| `market_data/mock.py` imports `to_money` from `app/trading/pnl` | `app/market_data/mock.py` | reuses the rounding helper; a downward dependency from market-data into trading |
| `realtime/price_stream.py` imports `SpreadModel` and `to_money` from `app/trading` | `app/realtime/price_stream.py` | modelled bid/ask must use the same spread model the engine uses |
| `indicators.py` and `backtest.py` import `get_market_data_service` from `market_data.py` | `app/api/v1/endpoints/` | one DI override in a test covers all three |

### 14.4 Tightly coupled areas

| Coupling | Detail | Consequence |
| -------- | ------ | ----------- |
| **Backend schemas ↔ frontend types** | `frontend/src/types/*.ts` are **hand-written mirrors** of `backend/app/schemas/*.py`. There is no codegen and no shared OpenAPI client. | Renaming a response field silently breaks the UI at runtime. `tsc` cannot see it. |
| **`TradingEngine` ↔ its five collaborators** | `TradingEngine.place_order` calls them in a fixed order and owns the transaction | Reordering the calls, or committing in the middle, breaks atomicity |
| **`apply_fill` ↔ everything that accounts** | `PositionManager`, `BacktestPortfolio` and the whole parity guarantee depend on it | Changing its semantics changes live trading, backtests, snapshots and the performance summary at once |
| **`Trade` columns ↔ `PerformanceAnalyzer` ↔ `backtest/results`** | Both win/loss definitions read `closed_quantity > 0` and `net_pnl > 0` | Changing the definition in one place makes live and backtest metrics disagree |
| **`price_stream.build_tick` ↔ `types/stream.ts` ↔ `Terminal`/`PriceChart`** | The tick payload is built by hand, not from a Pydantic model | No schema validation on either end of the socket |
| **`INDICATOR_PRESETS` ↔ the backend catalogue** | The frontend hard-codes spec strings (`sma:20`, `macd:12:26:9`) rather than reading `/indicators/catalogue` | Changing a parameter's bounds server-side can 400 a preset the UI still offers |
| **Config defaults ↔ `FeeCalculator`/`SpreadModel`/`SlippageModel` defaults** | Each model's `__init__` repeats the numeric defaults that `config.py` also declares | Two places to edit; drift is silent |

### 14.5 Loosely coupled areas (safe seams)

| Seam | Mechanism |
| ---- | --------- |
| **Market-data provider** | `MarketDataProvider` ABC + `_PROVIDERS` registry. Swapping vendors is a config change. |
| **Execution cost models** | Injected into `ExecutionEngine`; `SpreadModel.disabled()`, `SlippageModel.disabled()`, `FeeCalculator.disabled()`, `ExecutionEngine.frictionless()` |
| **`ExecutionEngine` into `TradingEngine`** | `TradingEngine(session, execution=…)` |
| **Strategies** | `_STRATEGIES` registry + the `Strategy` ABC; nothing else imports a concrete strategy |
| **Indicators** | `CATALOGUE` + `CALCULATORS` dispatch tables; adding one is two entries |
| **Mark price into the engine** | Always a caller-supplied parameter; the engine never fetches prices |
| **`SnapshotService.capture(commit=…)`** | Works standalone or enrolled in a caller's transaction |
| **`IndicatorService`** | Is handed candles, never fetches them |

---

## 15. Modification Guide — "Where do I modify X?"

Every entry follows the same five-part shape:
**(1) files to modify · (2) classes/functions · (3) do NOT modify · (4) tests to
update · (5) side effects.**

### 15.1 Add a new stock (make the platform multi-instrument)

This is the **largest** change in this list. The single-instrument assumption is
structural, not cosmetic.

1. **Files** — `app/core/config.py` (`TRADING_SYMBOL`), `app/services/market_data_service.py`,
   `app/trading/engine.py`, `app/models/trading.py`, `app/analytics/snapshots.py`,
   `app/analytics/scheduler.py`, `app/realtime/price_stream.py`,
   `app/api/v1/endpoints/{trading,market_data,portfolio,stream}.py`,
   a new Alembic revision, and most of `frontend/src`.
2. **Classes/functions** — `RelianceMarketDataService._require_supported_symbol`
   (currently rejects everything but one symbol; it would become a lookup),
   `TradingEngine._resolve_symbol`, `TradingEngine.get_position` /
   `get_portfolio` (they default the symbol), `PositionManager.get` /
   `get_or_create_for_update`, `SnapshotService.capture` (hard-codes
   `settings.TRADING_SYMBOL`), `capture_periodic_snapshot`,
   `PriceStreamService.__init__` (one symbol per instance).
3. **Do NOT modify** — `app/trading/pnl.py`, `apply_fill()`, `fees.py`,
   `spread.py`, `slippage.py`. They are already symbol-agnostic; they take
   numbers.
4. **Tests** — `test_trading_engine.py`, `test_realistic_execution.py`,
   `test_market_data_api.py`, `test_portfolio_history.py`, `test_realtime.py`
   all assume one symbol.
5. **Side effects** — `positions.symbol` is the **primary key** (fine for
   multi-instrument), but `wallet` is a singleton shared by all instruments;
   `portfolio_snapshots` has one `symbol` column and one `mark_price`, so a
   multi-instrument equity curve needs a schema change; `PerformanceAnalyzer`
   aggregates across *all* trades with no symbol filter; the WebSocket
   broadcasts one instrument to all clients with no subscription model.

### 15.2 Add a new exchange

1. **Files** — `app/market_data/yahoo.py` (`_EXCHANGE_SUFFIX`),
   `app/core/config.py` (`TRADING_EXCHANGE`), possibly `app/trading/fees.py`
   if the charge schedule differs (NSE/BSE share it; a non-Indian exchange does not).
2. **Classes/functions** — `_EXCHANGE_SUFFIX` dict, `YahooFinanceProvider._vendor_symbol`,
   `FeeCalculator` if charges differ, `INTRADAY_INTERVALS` /
   `SESSION_TIMEZONE = "Asia/Kolkata"` in `app/indicators/library.py` (VWAP
   session anchoring is exchange-local).
3. **Do NOT modify** — `MarketDataProvider` ABC; the engine; the ORM (`exchange`
   is already a plain `VARCHAR(16)` column with no constraint).
4. **Tests** — `test_market_data_provider.py` (symbol mapping),
   `test_indicators.py` (VWAP session anchoring).
5. **Side effects** — `docker-compose.yml` sets `TZ=Asia/Kolkata` on Postgres;
   `Position.exchange`/`Order.exchange`/`Trade.exchange` default to `'NSE'` in
   the model **and** in the migration.

### 15.3 Add a new indicator

The cleanest extension point in the codebase — **two entries, nothing else**.

1. **Files** — `app/indicators/definitions.py`, `app/indicators/library.py`.
   Optionally `frontend/src/types/indicators.ts` to expose a preset.
2. **Classes/functions** —
   * add a member to `IndicatorType`;
   * add an `IndicatorDef` to `CATALOGUE` (display name, `Pane`, `ParamDef`s,
     description, optional `scale_min`/`scale_max`);
   * write `def my_indicator(frame, spec) -> dict[str, np.ndarray]` in
     `library.py` and register it in `CALCULATORS`;
   * extend `warmup_for()` if it has a warm-up;
   * add cross-parameter rules to `_validate_relationships()` if needed;
   * for a multi-line indicator, add suffix labels to `_SERIES_LABELS` and, for
     a histogram, to `_HISTOGRAM_SUFFIXES` in `app/indicators/service.py`.
3. **Do NOT modify** — `app/api/v1/endpoints/indicators.py`,
   `IndicatorService.calculate` (it dispatches through `CALCULATORS`),
   `app/schemas/indicators.py` (`IndicatorType` is re-exported, not redefined).
4. **Tests** — add cases to `test_indicators.py`. Derive expectations from a
   defining identity where possible, as the existing tests do.
5. **Side effects** — the frontend only offers what is in `INDICATOR_PRESETS`;
   a new indicator is invisible in the UI until added there with a colour and a
   `pane`. A `pane: 'separate'` indicator adds another chart instance to the
   time-scale sync set.

### 15.4 Add a new strategy

1. **Files** — a new module in `app/strategies/`, plus one line in
   `app/strategies/registry.py`.
2. **Classes/functions** — subclass `Strategy`; set `name`, `display_name`,
   `description`, `params: tuple[StrategyParam, ...]`; implement
   `required_indicators()` and `on_bar(context) -> Decision`; override
   `warmup_bars()` and `reset()` if stateful. Validate cross-parameter rules in
   `__init__` and raise `ValueError` — `create_strategy` converts that into
   `InvalidStrategyParamsError` (400). Add the class to `_STRATEGIES`.
3. **Do NOT modify** — `app/backtest/engine.py`, `app/api/v1/endpoints/backtest.py`,
   `app/schemas/backtest.py`, `StrategyContext`. The engine already precomputes
   whatever `required_indicators()` returns.
4. **Tests** — add a module or extend `test_strategies.py`; a run through
   `BacktestEngine` in `test_backtest.py` is worthwhile.
5. **Side effects** — `_coerce()` in the registry converts JSON numbers to
   `int` when whole, and treats any parameter named `allow_*`/`use_*` as a
   boolean. **Name your boolean parameters accordingly** or they will arrive as
   ints. Strategies are backtest-only: adding one does **not** make it trade
   live (there is no live strategy runner — see §15.16).

### 15.5 Add a new order type (LIMIT, STOP, …)

Currently `OrderType.MARKET` is the only member and the enum is a **native
PostgreSQL type**, so this needs a migration.

1. **Files** — `app/models/enums.py`, a new Alembic revision
   (`ALTER TYPE order_type ADD VALUE 'LIMIT'`), `app/schemas/trading.py`
   (`PlaceOrderRequest` needs a `limit_price` / `trigger_price`),
   `app/trading/order_manager.py` (`create()` takes `order_type`),
   `app/trading/engine.py` (`place_order` hard-codes `order_type=OrderType.MARKET`),
   `app/trading/execution.py` (**the seam where matching would live**),
   `frontend/src/types/trading.ts` (`OrderType = 'MARKET'`),
   `frontend/src/components/terminal/TradingPanel.tsx`.
2. **Classes/functions** — `OrderType`, `OrderManager.create`,
   `TradingEngine.place_order`, `ExecutionEngine.price_fill` / `execute`.
   A resting order also needs somewhere to *live* between placement and fill —
   there is no order book and no matching loop today.
3. **Do NOT modify** — `apply_fill`, `PnLCalculator`, `FeeCalculator`,
   `SpreadModel`, `SlippageModel`. Order type does not change how a fill is
   priced once it happens.
4. **Tests** — `test_trading_engine.py` (order lifecycle),
   `test_realistic_execution.py`, plus new tests for triggering.
5. **Side effects** — `ck_orders_filled_orders_have_a_price` assumes a filled
   order has a price; `OrderStatus` has a `CANCELLED` member that **nothing
   currently sets** — resting orders would finally need it. `ALTER TYPE … ADD
   VALUE` cannot run inside a transaction block in older PostgreSQL; write the
   migration accordingly.

### 15.6 Change brokerage

1. **Files** — `backend/.env` (`BROKERAGE_PERCENT`, `BROKERAGE_MAX_PER_ORDER`).
   For a *different shape* of brokerage (slab-based, per-share, flat):
   `app/trading/fees.py`.
2. **Classes/functions** — `FeeCalculator._brokerage()` and the corresponding
   `__init__` parameters + `from_settings()` mapping. GST is computed on
   brokerage + exchange + SEBI in `FeeCalculator.calculate`, so a brokerage
   change moves GST automatically.
3. **Do NOT modify** — `ExecutionEngine`, `TradingEngine`,
   `PortfolioManager.cash_delta`, the `Trade` model. `brokerage` and
   `total_charges` are already persisted columns.
4. **Tests** — `test_execution_costs.py` (hand-worked expectations) and
   `test_realistic_execution.py` (which configures models **explicitly**, so an
   `.env` edit does not break it — keep that property).
5. **Side effects** — a config-only change affects **new fills only**; historical
   `trades` rows keep the charges they were written with. Backtests re-price
   from the current settings, so old backtest results are not reproducible after
   a rate change.

### 15.7 Change slippage

1. **Files** — `backend/.env` (`SLIPPAGE_MODEL`, `SLIPPAGE_BPS`,
   `SLIPPAGE_PERCENT`). For a new *model* (volume-dependent, square-root impact):
   `app/trading/slippage.py`.
2. **Classes/functions** — `SlippageType` (add a member), `SlippageModel.rate()`,
   `SlippageModel.apply()`, `from_settings()`. `apply()` already receives
   `quantity`, so a size-dependent model needs no signature change.
3. **Do NOT modify** — `SpreadModel` (a different, independent cost),
   `ExecutionEngine.price_fill`'s ordering (spread **then** slippage),
   `Trade.slippage_cost` (already persisted).
4. **Tests** — `test_execution_costs.py`, `test_realistic_execution.py`.
5. **Side effects** — slippage must stay **adverse in both directions**;
   `apply()` multiplies by `direction`, so a signed rate would silently make
   fills *better* and flatter every backtest. `BacktestEngine` reads the same
   settings, so live and backtest move together.

### 15.8 Change P&L calculation

The highest-blast-radius change in the system.

1. **Files** — `app/trading/pnl.py` and/or
   `app/trading/position_manager.py:apply_fill`.
2. **Classes/functions** — `PnLCalculator.realized_pnl`, `.unrealized_pnl`,
   `.position_value`, `.weighted_average_price`, `to_money`, `to_average`,
   `apply_fill`.
3. **Do NOT modify** — the endpoints, the schemas, or the ORM columns unless the
   *meaning* of a field changes. Do not duplicate the arithmetic anywhere:
   `PositionManager`, `PortfolioManager`, `SnapshotService`, `BacktestPortfolio`
   and `analytics/performance.py` all go through these functions.
4. **Tests** — `test_position_accounting.py` (23 hand-worked cases),
   `test_trading_engine.py`, `test_realistic_execution.py`,
   `test_portfolio_history.py`, `test_backtest.py` **including the parity suite**.
5. **Side effects** — **historical rows are not recomputed.** `trades.gross_pnl`,
   `trades.net_pnl`, `positions.realized_pnl`, `positions.net_realized_pnl` and
   every `portfolio_snapshots` row keep their old values, so the equity curve
   would have a discontinuity at the deploy. If the change is a correction, plan
   a data migration. Also note `PerformanceAnalyzer` re-derives its totals in
   SQL from those stored columns — it will report the *old* arithmetic for old
   rows.

### 15.9 Change wallet behaviour

1. **Files** — `app/services/wallet_service.py`, `app/models/wallet.py`,
   `app/repositories/wallet_repository.py`, `app/api/v1/endpoints/wallet.py`,
   `app/schemas/wallet.py`, a migration if columns or constraints change.
2. **Classes/functions** — `WalletService.initialize_wallet` /
   `reset_wallet` / `get_wallet`; `WalletRepository.get` / `get_for_update` /
   `create`; the `Wallet` CHECK constraints.
3. **Do NOT modify** — `PortfolioManager.cash_delta` / `apply_cash` /
   `assert_affordable` unless you are deliberately changing the **cash model**
   (that is §15.8 territory, and it changes backtests too via
   `BacktestPortfolio.cash_delta`).
4. **Tests** — `test_wallet_api.py`, `test_wallet_persistence.py`,
   `test_trading_engine.py` (funding rejections), `test_portfolio_history.py`.
5. **Side effects** — **`POST /wallet/reset` currently resets cash only.** It
   leaves `positions`, `orders`, `trades` and `portfolio_snapshots` untouched, so
   after a reset the account can hold a position it no longer paid for and the
   equity curve jumps. `SnapshotService.purge()` exists but **is not called from
   any endpoint**. If you make reset a true "start over", wire in `purge()` and
   flatten the position — and do it in one transaction.

### 15.10 Change the chart

1. **Files** — `frontend/src/components/terminal/PriceChart.tsx`,
   `OscillatorPane.tsx`, `frontend/src/types/marketData.ts` (`TIMEFRAMES`),
   `frontend/src/types/indicators.ts` (`INDICATOR_PRESETS`),
   `frontend/src/styles/terminal.css`, and `EquityCurve.tsx` for the portfolio chart.
2. **Classes/functions** — the chart-creation `useEffect` in `PriceChart`
   (created once, deliberately), `toCandlestick`/`toVolume`/`toSeconds`,
   `colorFor`, the overlay-drawing effect, the live-tick effect that mutates
   `lastBarRef`, the time-scale sync effect (`registerChart`/`unregisterChart`/
   `syncedChartsRef`).
3. **Do NOT modify** — anything under `backend/`. Indicators are computed
   server-side from the same candles the chart draws; recomputing them in the
   browser would break that guarantee.
4. **Tests** — none exist (§13.5). `npm run typecheck` is your only automated
   check.
5. **Side effects** — `lightweight-charts` v4 has **no panes**; each oscillator
   is a separate chart kept in step by the sync effect, whose dependency array is
   `[oscillators.length]`. Changing how oscillators are keyed or counted can
   break panning. Adding a `TIMEFRAMES` entry with an interval the provider does
   not serve produces a 400 (`unsupported_interval`).

### 15.11 Add a new API endpoint

1. **Files** — the relevant module in `app/api/v1/endpoints/` (or a new module
   plus one `include_router` line in `app/api/v1/router.py`), a schema in
   `app/schemas/`, a service/engine method, then `frontend/src/api/*.ts` and
   `frontend/src/types/*.ts`.
2. **Classes/functions** — the route function (**transport only**), request and
   response Pydantic models, the service method that holds the logic. Use
   `DbSession` for a database session; use `ServiceDep` for market data.
3. **Do NOT modify** — `app/main.py` (unless you need new middleware or a new
   exception handler), `app/api/deps.py`, `app/core/exceptions.py` (unless the
   endpoint introduces a genuinely new failure mode).
4. **Tests** — add a module in `backend/tests/` using the `client` fixture; use
   `app.dependency_overrides[get_market_data_service]` if it touches market data.
5. **Side effects** — **there is no authentication (§8.1), so a new endpoint is
   public.** Anything mutating must be safe to call from the open internet, or
   auth must be introduced first. If you do add auth, the natural places are a
   middleware in `create_app()` plus a `CurrentUser` dependency in
   `app/api/deps.py` — and note that the WebSocket route would need it too, which
   `CORSMiddleware` does not cover.

### 15.12 Change the market-data provider

**Switching between existing providers is config only:**
set `MARKET_DATA_PROVIDER=mock` (or `yahoo`) in `backend/.env` and restart.
Note the compose caveat: `docker compose restart` does **not** re-read
`env_file` — use `docker compose up -d --force-recreate backend`.

**Adding a new provider:**

1. **Files** — a new module in `app/market_data/`, plus a factory + one
   `_PROVIDERS` entry in `app/market_data/registry.py`. Credentials go in
   `app/core/config.py` (there are already unused `MARKET_DATA_API_KEY` /
   `MARKET_DATA_API_SECRET` `SecretStr` fields) and `backend/.env`.
2. **Classes/functions** — subclass `MarketDataProvider`; implement
   `capabilities` (declare limitations **honestly** — the whole stack reads it),
   `get_current_quote`, `get_historical_candles`, `aclose`. Override
   `subscribe_live_data` **only if the provider genuinely pushes** — the base
   class raising `LiveDataNotSupportedError` is the truthful behaviour otherwise.
3. **Do NOT modify** — `RelianceMarketDataService`, any endpoint,
   `PriceStreamService`, `app/schemas/market_data.py`. They depend only on the ABC.
4. **Tests** — a new module modelled on `test_market_data_provider.py`, using
   `httpx.MockTransport` so it runs offline.
5. **Side effects** — `capabilities.supports_live_stream` **decides** whether
   `PriceStreamService` runs in PUSH or POLL mode. `supports_bid_ask=False`
   makes the stream synthesise bid/ask from `SpreadModel` and label them
   `"modelled"`. `get_provider()` caches one instance process-wide; changing the
   provider requires a restart. `is_mock=True` triggers the startup warning and
   the `SIMULATED` UI badge — set it correctly.

### 15.13 Add a new database table

1. **Files** — a new module in `app/models/`, an export line in
   `app/models/__init__.py` (**mandatory** — autogenerate cannot see the table
   otherwise), a generated migration in `backend/alembic/versions/`, plus a
   schema, a repository/service and an endpoint if it is user-facing.
2. **Classes/functions** — subclass `Base` (add `TimestampMixin` if it wants
   created/updated), declare `__tablename__` and `__table_args__` with CHECKs and
   `Index(...)`. Generate with
   `docker compose exec backend alembic revision --autogenerate -m "..."`, then
   **read the generated file** — the existing revisions show three things
   autogenerate got wrong (enum create/drop, a rename emitted as DROP+ADD, and
   missing `server_default` on new NOT NULL columns).
3. **Do NOT modify** — existing migrations. Ever. Add a new revision.
4. **Tests** — extend the `TRUNCATE` statement in
   `tests/conftest.py:clean_tables` to include the new table, or tests will leak
   state between each other.
5. **Side effects** — a native `Enum` type must be created and dropped
   **explicitly** with `checkfirst`, as `44b98124fbd4` and `51917e5fa5f1` do;
   left to `create_table`, it is emitted once per referencing table and a
   downgrade strands the type so the next upgrade fails with
   `DuplicateObjectError`. New NOT NULL columns on a populated table need a
   `server_default`.

### 15.14 Change WebSocket messages

1. **Files** — `app/realtime/price_stream.py` (`build_tick`, `status`,
   `_handle_failure`), `app/api/v1/endpoints/stream.py` (the `status` frame and
   the `ping`/`pong` handling), `frontend/src/types/stream.ts`,
   `frontend/src/hooks/useLivePrice.ts` (the `switch` on `message.type`), and any
   component reading the changed field.
2. **Classes/functions** — `PriceStreamService.build_tick`,
   `PriceStreamService.status`, `BidAskSource`, `StreamMode`,
   `ConnectionManager.broadcast` (only if the envelope shape changes).
3. **Do NOT modify** — `ConnectionManager`'s membership/locking logic; it is
   payload-agnostic by design.
4. **Tests** — `test_realtime.py`, `test_stream_endpoint.py`.
5. **Side effects** — **the tick payload is a hand-built dict, not a Pydantic
   model**, so nothing validates it on either end (§14.4). A renamed field fails
   silently in the browser as `undefined`. Keep money as **strings** — the
   frontend treats every monetary field as a Decimal-bearing string and never
   does arithmetic on it. `status()` is also the body of
   `GET /api/v1/stream/status`, so changing it changes that endpoint too.

### 15.15 Add ML prediction — **nothing exists today**

There is **no ML code, no model, no inference path, and no ML dependency** in
this repository (`requirements.txt` has `numpy`, `pandas` and `TA-Lib` only).
If you add one, the architecture already offers two clean seams:

* **As a strategy** (recommended) — implement `Strategy` in `app/strategies/`,
  load the model in `__init__`, return a `Decision` from `on_bar`. You get the
  backtester, the lookahead guard, position sizing and the parity guarantee for
  free. Constraint: `StrategyContext` exposes candles and precomputed
  indicators only, so features must be derivable from those (or fetched in
  `__init__`, not per-bar).
* **As a service + endpoint** — a new `app/ml/` package plus a
  `app/api/v1/endpoints/predictions.py`, following the
  `IndicatorService` pattern (handed candles, never fetching them).

1. **Files** — new `app/strategies/<model>.py` **or** new `app/ml/` + endpoint;
   `requirements.txt`; `.gitignore` (model artefacts); `Dockerfile` if the
   runtime grows.
2. **Do NOT modify** — `app/trading/**`. A prediction is a *signal*, not an
   accounting change.
3. **Tests** — a new module; pin any randomness so results are reproducible, the
   way `MOCK_SEED` does for the mock provider.
4. **Side effects** — model inference inside `on_bar` runs once per bar and
   would make backtests slow; prefer a vectorised precompute in
   `required_indicators()`-style fashion. Anything heavy inside a request blocks
   the event loop — FastAPI here is fully async with no thread pool offloading.

### 15.16 Change backtesting behaviour

1. **Files** — `app/backtest/engine.py`, `app/backtest/portfolio.py`,
   `app/backtest/results.py`, `app/schemas/backtest.py`,
   `app/api/v1/endpoints/backtest.py`.
2. **Classes/functions** — `BacktestConfig` (a new knob needs a matching field on
   `BacktestRequest` **and** a line in `run_backtest`, which copies them one by
   one), `PositionSizer.target_size`, `BacktestEngine._reference_price`,
   `._order_quantity`, `._execute`, `._settle`, `._close_out`,
   `summarise()`, `max_drawdown()`.
3. **Do NOT modify** — `ExecutionEngine.price_fill` or `apply_fill`. The entire
   value of this backtester is that it calls the **live** pricing and accounting
   code. Reimplementing either inside `app/backtest/` destroys the parity
   guarantee.
4. **Tests** — `test_backtest.py`, **especially the parity suite**. If parity
   breaks, the change is wrong.
5. **Side effects** — `FillTiming.CURRENT_CLOSE` is deliberately available and
   deliberately unrealistic (lookahead). Do not make it the default. The main
   loop skips `index >= last_index` because there is no "next open" to fill
   against; `_close_out` handles the final bar instead and pops-and-re-records
   the last equity point so the curve ends on a realized figure. Win/loss rules
   in `summarise()` must stay identical to `PerformanceAnalyzer`, or live and
   backtest metrics stop being comparable.

### 15.17 Bonus: run a strategy live

**NOT IMPLEMENTED.** There is no live strategy runner. Nothing calls
`Strategy.on_bar` outside `BacktestEngine.run`, and no code path turns a
`Signal` into `TradingEngine.place_order`.

The pieces that would be needed: a scheduler job (pattern:
`app/analytics/scheduler.py`), a way to obtain candles outside a request
(`SessionLocal()` + `get_provider()`), `Signal.order_side` (already exists),
and a sizing decision (`PositionSizer` currently lives in `app/backtest/` and
would need to move or be duplicated). Also note the strategy would be operating
on the **same** wallet and position as the human UI, with no coordination.

---

## 16. Safe Modification Rules

1. **Money is `Decimal`. Everywhere. Always.**
   Never introduce a `float` into a price, a charge, a P&L or a balance. The
   only sanctioned float conversion is `candles_to_frame()` in
   `app/indicators/service.py`, because TA-Lib requires `float64` and those are
   statistical studies, not money. On the frontend, money arrives as a
   **string** and `utils/format.ts` converts it to a number *only at the moment
   of rendering* — never for arithmetic.

2. **Round through `to_money()` / `to_average()` / `to_rupee()`.**
   Two decimals for cash and prices, four for derived averages, whole rupees for
   STT and stamp duty (as a contract note does). Do not call `.quantize()`
   ad hoc.

3. **Do not break the transaction boundary in `TradingEngine.place_order`.**
   One order = one commit. Locks are taken **wallet first, then position** —
   keep that order everywhere or you invite a deadlock. Do not add an
   intermediate `commit()`, and do not call an outside service that commits on
   its own (this is exactly why `SnapshotService.capture` takes `commit=False`).

4. **Keep the layers pointing one way.**
   Endpoints are transport only. Services hold rules. The trading engine imports
   no web framework and no market-data provider. `app/core/config.py` is the
   only reader of the environment. If a new import would violate one of these,
   the design is wrong, not the rule.

5. **The engine never fetches a price.**
   `mark_price` and `reference_price` are always parameters. This is what lets
   the same engine be driven by HTTP, a backtest and a test.

6. **Extend through the registries, not with an `if`.**
   `_PROVIDERS` (market data), `_STRATEGIES` (strategies), `CATALOGUE` +
   `CALCULATORS` (indicators). Adding a branch to a caller instead is the
   regression.

7. **Injected models, not edited ones.**
   To change execution cost for a caller, pass a different `SpreadModel` /
   `SlippageModel` / `FeeCalculator` into `ExecutionEngine`, or a different
   `ExecutionEngine` into `TradingEngine`. Do not add flags to the models.

8. **Never edit an applied migration.** Add a new revision. Always read what
   `--autogenerate` produced before applying it — this repo has three documented
   cases where it was wrong.

9. **Update `app/models/__init__.py` when you add a model**, or Alembic will not
   see the table.

10. **Extend `clean_tables` in `tests/conftest.py`** when you add a table, or
    tests leak state into each other.

11. **Schemas and TS types are hand-mirrored.** Change
    `backend/app/schemas/x.py` → change `frontend/src/types/x.ts` in the same
    commit. `tsc` cannot catch this for you.

12. **Providers must declare their limits honestly.**
    `ProviderCapabilities` drives real behaviour: PUSH vs POLL, modelled vs real
    bid/ask, the `SIMULATED` badge. A provider that overstates itself corrupts
    the layers above it.

13. **Never make an execution cost favourable.** Spread and slippage are always
    adverse. A model that can improve a fill flatters every backtest built on it.

14. **Keep backtest and live metrics defined identically.**
    `backtest/results.summarise` and `analytics/performance.PerformanceAnalyzer`
    must agree: a closing fill is `closed_quantity > 0`; a win is `net_pnl > 0`.

15. **Run the parity suite after touching pricing or accounting.**
    `pytest tests/test_backtest.py` — if live and backtest diverge, stop.

16. **Do not compute derived money in the browser.** Ask the server
    (`GET /trading/portfolio?mark_price=…`) so the arithmetic stays in `Decimal`.

17. **Assume no authentication.** Any new mutating endpoint is public. Weigh
    that before adding one.

---

## 17. Architecture Risks

Only issues that are actually present in the code, with the file and the
mechanism.

### 17.1 Tight coupling

* **Hand-mirrored contracts** — `frontend/src/types/*.ts` duplicate
  `backend/app/schemas/*.py` with no codegen and no runtime validation. A
  renamed or retyped response field breaks the UI silently at runtime;
  `npm run typecheck` passes because the types still describe *something*.
  Highest-frequency source of avoidable breakage in this repo.
* **The WebSocket tick is a hand-built dict** — `PriceStreamService.build_tick`
  returns a raw `dict`, not a Pydantic model. Neither end validates it.
* **Duplicated defaults** — `FeeCalculator.__init__`, `SpreadModel.__init__` and
  `SlippageModel.__init__` repeat the numeric defaults that `config.py` also
  declares. They can drift apart without any test noticing, because
  `test_realistic_execution.py` deliberately configures models explicitly.
* **Frontend hard-codes indicator specs** — `INDICATOR_PRESETS` in
  `types/indicators.ts` embeds `sma:20`, `macd:12:26:9`, … rather than reading
  `GET /indicators/catalogue`. Tightening a bound server-side 400s a preset the
  UI still offers.

### 17.2 Technical debt

* **Dead code** — `frontend/src/components/HealthCard.tsx` and
  `frontend/src/hooks/useHealth.ts` are unreferenced; `StatusBadge.tsx` is used
  only by `HealthCard`. `GET /api/v1/health` therefore has no UI consumer.
* **`SnapshotService.purge()` is never called** by any endpoint or job. It is
  reachable only from code/tests.
* **`OrderStatus.CANCELLED` is never set** by anything — no cancellation path
  exists.
* **`MARKET_DATA_API_KEY` / `MARKET_DATA_API_SECRET` are never read.** They are
  declared for a future provider.
* **`BACKEND_HOST` / `BACKEND_PORT` are declared but unused** — `main.py` does
  not read them; uvicorn takes them on the command line.
* **`ExecutionEngine(session=None)`** in `BacktestEngine.__init__` with a
  `# type: ignore[arg-type]`. Safe today because only `price_fill()` is called,
  but any future `ExecutionEngine` method that touches the session will
  `AttributeError` at runtime rather than being caught by the type checker.
* **Only one repository exists.** `WalletRepository` is the sole member of
  `app/repositories/`; `OrderManager`, `PositionManager`, `ExecutionEngine`,
  `SnapshotService` and `PerformanceAnalyzer` all write their own SQL directly.
  The "repositories own all SQL" statement in `app/repositories/__init__.py` is
  aspirational, not descriptive.
* **`README.md` is stage-narrative, not reference.** 1,173 lines organised by
  build stage; several docstrings still say "Stage 1/2/4", and
  `app/db/base.py` claims "Stage 1 defines no domain tables" which is no longer
  true of the codebase around it.

### 17.3 Potential race conditions

* **Connection-limit check is not atomic.**
  `ConnectionManager.connect()` checks `len(self._connections) >= max` under the
  lock, **releases the lock**, `await websocket.accept()`, then re-acquires the
  lock to add. Several coroutines can pass the check concurrently, so the pool
  can exceed `STREAM_MAX_CONNECTIONS`. Bounded by concurrency, not unbounded.
* **`PositionManager.get_or_create_for_update` calls `session.rollback()`.**
  On the `IntegrityError` path (a concurrent order created the position row
  first) it rolls back the **whole session**, which releases the
  `SELECT wallet FOR UPDATE` taken moments earlier in
  `TradingEngine.place_order` and expires the `wallet` ORM object. The engine
  then continues with a wallet that is no longer locked. This can only happen on
  the very first two concurrent orders for a symbol, but it is a real hole in
  the "both rows are locked" guarantee.
* **Snapshot job vs. an in-flight order.** `capture_periodic_snapshot` opens its
  own session and takes **no locks**. It can read `wallet` and `positions` while
  an order's transaction is mid-flight. It will read the pre-commit state
  (Postgres default `READ COMMITTED`), so the row is consistent — but the
  snapshot can be slightly stale relative to a trade that commits immediately
  after.
* **Frontend revaluation vs. refresh.** `useAccount`'s throttled
  `fetchPortfolio(markPrice)` and its `refresh()` both `setPortfolio(...)`. A
  slow revaluation started before a fill can land after the post-fill refresh
  and overwrite it with pre-trade numbers until the next tick. There is no
  request-sequence guard.
* **Lazy singletons without locks** — `registry.get_provider()`,
  `price_stream.get_price_stream()`, `get_connection_manager()` all use the
  `if _x is None: _x = ...` pattern. Safe under a single-threaded asyncio loop
  because no `await` sits between the check and the assignment; it would **not**
  be safe if any of them became `async` or were called from a thread pool.

### 17.4 Database / transaction risks

* **`POST /wallet/reset` is not a full reset.** It sets
  `cash_balance = initial_balance` and touches nothing else — `positions`,
  `orders`, `trades` and `portfolio_snapshots` survive. The account can end up
  holding a position it no longer paid for, and the equity curve gets a
  discontinuity. (§15.9)
* **No margin on shorts.** `app/trading/portfolio.py` documents it: short
  proceeds are credited as spendable cash and nothing is reserved. Short size is
  bounded only by `assert_affordable` on the *cover*, so an account can open a
  short far larger than its equity and then be unable to close it.
* **`positions` has no FK to `orders`/`trades`**, and `portfolio_snapshots` has
  no FK to anything. Referential integrity across the trading tables is
  application-enforced only.
* **CHECK constraints are unhandled at the API layer.** Nothing catches
  `IntegrityError` in `TradingEngine.place_order`, so if a bug ever drove the
  engine past its own validation, the user would see a bare `500`.
* **Rejected orders are committed mid-request.** The rejection path calls
  `mark_rejected` then `commit()` then raises. That is intentional (nothing else
  has been written yet), but it means a rejection **releases the wallet and
  position locks** — correct, and worth knowing before adding writes earlier in
  the flow.
* **No pagination cap on snapshots relative to growth.** With
  `SNAPSHOT_INTERVAL_SECONDS=300` and `SNAPSHOT_ON_TRADE=true`,
  `portfolio_snapshots` grows monotonically forever; `SNAPSHOT_SKIP_UNCHANGED`
  only suppresses duplicates while the account is genuinely idle. There is no
  retention policy and no scheduled purge.

### 17.5 WebSocket risks

* **The socket is unauthenticated and unthrottled.** Any origin can connect —
  `CORSMiddleware` does not apply to WebSocket handshakes — up to
  `STREAM_MAX_CONNECTIONS`.
* **All clients share one stream.** There is no subscription model; every client
  receives every tick for the one configured instrument.
* **`PriceStreamService` is a process-wide singleton.** Under multiple uvicorn
  workers each process would poll independently, multiplying upstream calls, and
  a client would only receive ticks from the worker it happened to land on.
  **This design assumes a single worker process.**
* **The stream never stops.** Once started it keeps polling for the process
  lifetime. `_poll_once` skips the upstream call when there are no listeners, so
  the cost is one no-op timer tick every 5s — but `is_running` stays `True` and
  `stop()` is only called at shutdown.
* **React StrictMode double-mounts effects in development**, so `useLivePrice`
  opens and closes a socket twice on mount. Handled correctly (`activeRef`,
  `onclose = null` before an intentional close) but it inflates
  `total_accepted`/`total_disconnected`.
* **Two live sockets when the portfolio page is open.** `PortfolioHistoryPage`
  calls `useLivePrice()` independently of `Terminal`; navigating between them
  churns connections.

### 17.6 State-synchronisation risks

* **Full-reload-after-fill.** `Terminal.handleFilled` triggers five parallel
  GETs. Correct and simple, but on a slow link the panels briefly show
  pre-trade state, and there is no optimistic feedback beyond the fill receipt.
* **Throttled revaluation can show stale unrealized P&L.** `REVALUE_THROTTLE_MS
  = 3000`; if a tick arrives inside the window the effect returns **without
  scheduling a retry**, so the value waits for the next tick.
* **History pages never auto-refresh.** `TradeHistoryPage`,
  `OrderHistoryPage`, `PerformancePage` and `PortfolioHistoryPage` load once on
  mount. Trading in another tab leaves them silently stale.
* **The forming candle is client-side only.** `PriceChart` mutates
  `lastBarRef` from live ticks; that bar is never reconciled against the server.
  Switching timeframes refetches and discards it, which is the only correction.
* **`EquityCurve` collapses same-second snapshots** to the last value, because
  Lightweight Charts requires strictly ascending times. A `TRADE` and a
  `PERIODIC` snapshot landing in the same second means one is not plotted.

### 17.7 Performance bottlenecks

* **Yahoo is called on every chart/indicator request.** There is **no caching
  layer at all** — no Redis (deliberately absent), no in-process cache, no
  HTTP cache headers honoured. `GET /indicators` fetches candles *again* even
  when `GET /market-data/candles` just fetched the same window, so opening the
  terminal with three indicators issues four separate upstream requests.
  This is also the main rate-limit exposure, since the endpoint is unofficial.
* **`useAccount.refresh()` fires five requests per fill**, each opening its own
  database session.
* **TA-Lib runs synchronously on the event loop.** `IndicatorService.calculate`
  is a plain `def` called from an `async` endpoint with no
  `run_in_threadpool`/`to_thread`. A 5,000-bar multi-indicator request blocks
  every other request, including WebSocket broadcasts, for its duration.
* **Backtests run synchronously on the event loop too.** `BacktestEngine.run` is
  a bar-by-bar Python loop; `limit` allows 5,000 bars. Same blocking exposure.
* **`Order.trades` is `lazy="selectin"`** — every order list issues a second
  query to load trades that `OrderResponse` does not even expose.
* **`GET /portfolio/snapshots` allows `limit=5000`** and the frontend requests
  1,000 rows, all serialised as JSON with ~13 Decimal fields each.
* **`PerformanceAnalyzer.summary()` issues five separate queries** and none of
  the aggregated columns (`net_pnl`, `closed_quantity`) is indexed; the
  `closed_quantity > 0` filter is a sequential scan.
* **`_parse_candles` builds Pydantic `Candle` objects one at a time** for up to
  5,000 bars, each with `Decimal` conversion.

### 17.8 Security concerns

* **No authentication or authorisation of any kind** (§8.1). Every endpoint,
  including `POST /trading/orders` and `POST /wallet/reset`, is fully public to
  anyone who can reach the port.
* **No rate limiting** on any endpoint, HTTP or WebSocket.
* **`allow_credentials=True` with `allow_methods=["*"]` and
  `allow_headers=["*"]`** in `create_app()`. There are no credentials to send
  today, but the combination is a bad default to inherit if auth is added.
  `CORS_ORIGINS` is the only restriction, and it is browser-only.
* **`DEBUG=true` by default**, and `ENVIRONMENT` defaults to `development`.
  Nothing in the code refuses to start in a production-looking configuration
  with debug on, and nothing gates `/docs` behind an environment check.
* **Default database credentials are committed in `.env.example` and are the
  defaults in `config.py`.** They are clearly development placeholders, but a
  deployment that never overrides them ships with a known password.
* **The Yahoo endpoint is unofficial and unlicensed for commercial
  redistribution** — stated in `YahooFinanceProvider.capabilities.limitations`.
  It can rate-limit or change shape without notice; there is no fallback
  provider and no circuit breaker.
* **No request size limits, no timeouts on the application side.** Only
  `MARKET_DATA_TIMEOUT_SECONDS` bounds the outbound HTTP call.
* **`rejection_reason` is stored verbatim** (truncated to 500 chars) and
  rendered into the DOM by `OrdersPanel`/`OrderHistoryPage`. React escapes it,
  so this is not XSS today — but the message is server-generated and includes
  user-supplied quantities, which is worth remembering if it is ever rendered
  with `dangerouslySetInnerHTML` or exported.
* **Mock data cannot be mistaken for real** — this one is handled well:
  `is_mock` on the quote, on `capabilities`, on every tick, a loud startup
  warning in `registry.get_provider()`, a `SIMULATED` badge and a warning
  banner in the UI.

---

*End of document. Generated from a full read of the repository at commit
`1f0a749`; no application code was modified.*

---

## 18. Automatic Orders (stop-loss & price triggers)

Added after the original document. Integrates with the existing engine rather
than replacing any part of it.

### 18.1 Where it sits

```
 Market Data (yahoo/mock)
        |
 PriceStreamService._broadcast_quote()      app/realtime/price_stream.py
        |  tick broadcast to clients first, THEN:
        v
 PriceStreamService._run_automation(last_price)
        |
        v
 AutomaticOrderMonitor.on_price()           app/automation/monitor.py
        |
        +-- condition_is_met()              app/automation/evaluator.py   (pure)
        |
        +-- _claim_next()   SELECT ... FOR UPDATE SKIP LOCKED
        |                   status ACTIVE -> TRIGGERED, COMMIT   <-- the claim
        |
        +-- _execute()
              |
              v
        TradingEngine.place_order()         app/trading/engine.py  (UNCHANGED path)
              |-- OrderManager / ExecutionEngine / PositionManager /
              |   PortfolioManager / SnapshotService
              +-- AutomaticOrderService.reconcile_for_position()  <-- NEW, same txn
              |
              v
        orders / trades / positions / wallet / portfolio_snapshots
              |
              v
 ConnectionManager.broadcast({"type":"automatic_order", ...})
              |
              v
 useLivePrice -> Terminal -> useAccount.refresh() + trigger list reload
```

**There is exactly one execution path.** A fired trigger becomes an ordinary
`Order` + `Trade` through `TradingEngine.place_order`. No parallel execution
code exists.

### 18.2 Files added

| File | Responsibility |
| ---- | -------------- |
| `app/models/automatic_order.py` | `AutomaticOrder`, `AutomaticOrderType`, `TriggerCondition`, `AutomaticOrderStatus` |
| `app/automation/evaluator.py` | **Pure** trigger arithmetic: `condition_is_met`, `closing_side_for`, `stop_loss_condition_for`, `protects_position` |
| `app/automation/service.py` | `AutomaticOrderService` — create/validate/list/cancel/**reconcile** |
| `app/automation/monitor.py` | `AutomaticOrderMonitor` — claim + execute; `get_automatic_order_monitor()` singleton |
| `app/schemas/automatic_order.py` | `CreateAutomaticOrderRequest`, `AutomaticOrderResponse` |
| `app/api/v1/endpoints/automatic_orders.py` | 5 routes |
| `alembic/versions/20260827_0900_add_automatic_orders.py` | revision `7c4e1a9b2d55` |
| `tests/test_automatic_orders.py` | 43 tests |

### 18.3 Files modified (minimally)

| File | Change |
| ---- | ------ |
| `app/trading/engine.py` | one call to `reconcile_for_position()` after `mark_filled`, **inside the existing transaction**. Local import, as `SnapshotService` already does. |
| `app/realtime/price_stream.py` | `_broadcast_quote` calls new `_run_automation`; `status()` gains an `automation` block |
| `app/core/exceptions.py` | `AutomaticOrderError`, `InvalidAutomaticOrderError`, `AutomaticOrderNotFoundError` |
| `app/models/__init__.py`, `app/api/v1/router.py` | registration |
| `tests/conftest.py` | `automatic_orders` added to the TRUNCATE list |

No existing function's behaviour was changed. BUY/SELL/SHORT/COVER are untouched.

### 18.4 Stop-loss semantics

Direction is **derived from the position**, never trusted from the request:

| Position | Condition | Action | Fires when |
| -------- | --------- | ------ | ---------- |
| LONG (`quantity > 0`) | `LTE` | `SELL` | price falls to/through the trigger |
| SHORT (`quantity < 0`) | `GTE` | `BUY_TO_COVER` | price rises to/through the trigger |
| FLAT | — | — | rejected: nothing to protect |

Boundaries are **inclusive** (`>= 1450` fires at exactly 1450).

Validation also rejects a stop that would fire on the next tick — but only when
a live price is available. Entry price is deliberately *not* used as the
reference: a stop above entry is a legitimate profit-protecting stop once price
has moved in your favour.

`PRICE_TRIGGER` has no position requirement and accepts any condition/action.
If the engine later refuses it (no position, no cash) it becomes `FAILED`.

### 18.5 Duplicate-execution protection

Two-phase claim in `AutomaticOrderMonitor`:

1. `SELECT ... FOR UPDATE SKIP LOCKED`, re-check `status == ACTIVE` under the
   lock, stamp `TRIGGERED` + `triggered_at` + `trigger_market_price`, **commit**.
2. Only then execute.

The committed transition removes the row from the ACTIVE set before any trade
happens, so a price that stays past the trigger for many ticks cannot re-fire
it. An `asyncio.Lock` additionally skips a tick if the previous evaluation is
still executing. Verified live: 13 evaluations, 1 execution.

Execution failures go to `FAILED`, never back to `ACTIVE` — otherwise a doomed
trigger would retry on every tick forever.

### 18.6 Position interaction

`AutomaticOrderService.reconcile_for_position()` runs **inside the order's own
transaction**, so a stop can never briefly outlive the position it protects.

| Position change | Stop-loss outcome |
| --------------- | ----------------- |
| Goes flat | `CANCELLED`, reason "Position closed…" |
| Reverses direction | `CANCELLED`, reason "Position reversed…" |
| **Reduced** (partial close) | **quantity clamped** to what remains |
| Grown | left alone |

**Partial-position decision.** Clamping was chosen over cancel-and-recreate
because the user's intent ("get me out of this position") survives a partial
exit; cancelling would silently leave the remainder unprotected. LONG 100 with
a 100-share stop, sell 40 manually → the stop becomes 60. Growing the position
does *not* raise the quantity, since that would protect shares the user never
asked to protect.

`PRICE_TRIGGER` orders are never reconciled — they are standalone conditions,
not attached to a position.

### 18.7 Statuses

`ACTIVE` → `TRIGGERED` | `CANCELLED` | `FAILED`. All three are terminal.

`EXPIRED` from the brief is **not implemented**: nothing in this platform
carries session or good-till-date semantics, so no order could ever reach it.
`FAILED` was added instead, because an execution the engine rejects must be
terminal rather than retried.

### 18.8 How to modify

| Task | File |
| ---- | ---- |
| Change when a trigger fires | `app/automation/evaluator.py:condition_is_met` (pure, fully unit-tested) |
| Change stop-loss validation rules | `app/automation/service.py:_validate_stop_loss` |
| Change partial-position behaviour | `app/automation/service.py:reconcile_for_position` |
| Change claim/duplicate protection | `app/automation/monitor.py:_claim_next` |
| Change the WebSocket frame | `app/automation/monitor.py:_event` **and** `frontend/src/types/stream.ts` |
| Add a condition (e.g. crossing) | `TriggerCondition` enum + a migration + `condition_is_met` |

**Do not** add execution logic to `app/automation/`. Firing decides *whether*;
`TradingEngine` decides *what happens*. Keeping that split is what guarantees
automatic and manual orders are accounted identically.
