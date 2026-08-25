"""FastAPI application entrypoint.

Run with:  uvicorn app.main:app --reload
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.exceptions import DomainError
from app.core.logging import configure_logging, get_logger
from app.db.session import dispose_engine
from app.market_data.registry import close_provider
from app.analytics.scheduler import (
    start_snapshot_scheduler,
    stop_snapshot_scheduler,
)
from app.realtime.price_stream import shutdown_price_stream

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging()
    logger.info(
        "Starting %s v%s [%s] — instrument %s:%s",
        settings.APP_NAME,
        settings.APP_VERSION,
        settings.ENVIRONMENT,
        settings.TRADING_EXCHANGE,
        settings.TRADING_SYMBOL,
    )
    start_snapshot_scheduler()

    yield
    logger.info("Shutting down.")
    await stop_snapshot_scheduler()
    await shutdown_price_stream()
    await close_provider()
    await dispose_engine()


def create_app() -> FastAPI:
    """Application factory — keeps construction testable and side-effect free."""
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        debug=settings.DEBUG,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(DomainError)
    async def domain_error_handler(_: Request, exc: DomainError) -> JSONResponse:
        """Translate business-rule failures into structured HTTP responses."""
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message}},
        )

    app.include_router(api_router, prefix=settings.API_V1_PREFIX)

    @app.get("/", tags=["root"], summary="Service banner")
    async def root() -> dict[str, str]:
        return {
            "service": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "docs": "/docs",
            "health": f"{settings.API_V1_PREFIX}/health",
            "wallet": f"{settings.API_V1_PREFIX}/wallet",
            "market_data": f"{settings.API_V1_PREFIX}/market-data",
            "indicators": f"{settings.API_V1_PREFIX}/indicators",
            "trading": f"{settings.API_V1_PREFIX}/trading",
            "stream": f"{settings.API_V1_PREFIX}/stream/prices",
            "portfolio_history": f"{settings.API_V1_PREFIX}/portfolio/snapshots",
        }

    return app


app = create_app()
