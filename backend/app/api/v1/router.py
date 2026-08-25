"""Aggregates every v1 endpoint module into a single router."""

from fastapi import APIRouter

from app.api.v1.endpoints import health, market_data, stream, trading, wallet

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(wallet.router)
api_router.include_router(market_data.router)
api_router.include_router(trading.router)
api_router.include_router(stream.router)
