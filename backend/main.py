"""
NSE Market Intelligence Platform - Application Entry Point
==========================================================
Creates the FastAPI application, mounts routers, configures middleware,
and manages the application lifespan (startup / shutdown).

Run with::

    uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.config import settings
from backend.database import close_db, init_db

logger = logging.getLogger(__name__)

# Configure root logger for the platform
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


# =====================================================================
# Lifespan (startup / shutdown)
# =====================================================================

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan manager.

    On startup:
        - Initialise the database (create tables if needed).
        - Start the background scheduler (scan, news refresh, etc.).

    On shutdown:
        - Stop the scheduler gracefully.
        - Close the database connection pool.
    """
    # -- Startup --------------------------------------------------------
    logger.info("Starting NSE Market Intelligence Platform ...")
    await init_db()
    logger.info("Database initialised at %s", settings.resolved_db_path)

    # Start the scheduler if available
    scheduler = None
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore[import-untyped]

        scheduler = AsyncIOScheduler()
        # TODO: Register scheduled jobs here:
        # scheduler.add_job(scan_universe, "interval", minutes=settings.scan_interval_min)
        # scheduler.add_job(refresh_news, "interval", minutes=settings.news_refresh_interval_min)
        # scheduler.add_job(regime_snapshot, "interval", minutes=5)
        scheduler.start()
        logger.info("APScheduler started.")
    except ImportError:
        logger.warning(
            "apscheduler not installed. Background scheduler disabled. "
            "Install with: pip install apscheduler"
        )
    except Exception:
        logger.exception("Failed to start scheduler.")

    yield

    # -- Shutdown -------------------------------------------------------
    if scheduler is not None:
        scheduler.shutdown(wait=False)
        logger.info("APScheduler shut down.")

    await close_db()
    logger.info("NSE Market Intelligence Platform stopped.")


# =====================================================================
# Application factory
# =====================================================================

app = FastAPI(
    title="NSE Market Intelligence",
    description=(
        "Unified API for the NSE Market Intelligence paper-trading platform. "
        "Provides live picks, trade management, regime analysis, performance "
        "metrics, news feeds, and TradingView webhook ingestion."
    ),
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)


# =====================================================================
# CORS middleware
# =====================================================================

import os as _os

_cors_origins = [
    "http://localhost:3000",       # Next.js dev server
    "http://127.0.0.1:3000",
    "http://localhost:8000",       # Same-origin
    "http://127.0.0.1:8000",
]
# Add the Vercel frontend URL when deployed
_frontend_url = _os.environ.get("FRONTEND_URL", "")
if _frontend_url:
    _cors_origins.append(_frontend_url.rstrip("/"))

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =====================================================================
# Mount routers
# =====================================================================

from backend.api.dashboard_api import router as dashboard_router  # noqa: E402
from backend.api.webhook_routes import router as webhook_router    # noqa: E402
from backend.api.backtest_routes import router as backtest_router  # noqa: E402

app.include_router(dashboard_router)
app.include_router(webhook_router)
app.include_router(backtest_router)


# =====================================================================
# Static files
# =====================================================================

# Serve files from backend/data/ (exports, reports, etc.)
_data_dir = Path(__file__).resolve().parent / "data"
_data_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static/data", StaticFiles(directory=str(_data_dir)), name="static-data")


# =====================================================================
# Root & health endpoints
# =====================================================================

@app.get("/", include_in_schema=False)
async def root() -> JSONResponse:
    """Root endpoint with link to API documentation."""
    return JSONResponse(
        content={
            "name": "NSE Market Intelligence",
            "version": "1.0.0",
            "docs": "/docs",
            "redoc": "/redoc",
            "health": "/health",
        }
    )


@app.get("/health", tags=["system"])
async def health_check() -> JSONResponse:
    """Health check endpoint for monitoring and load balancers."""
    health: dict = {
        "status": "ok",
        "database": "unknown",
        "scheduler": "unknown",
    }

    # Check database connectivity
    try:
        from backend.database import AsyncSessionLocal
        from sqlalchemy import text

        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        health["database"] = "connected"
    except Exception as exc:
        health["database"] = f"error: {exc}"
        health["status"] = "degraded"

    # Check WebSocket manager
    try:
        from backend.api.dashboard_api import ws_manager
        health["websocket_clients"] = ws_manager.active_count
    except Exception:
        health["websocket_clients"] = 0

    # Settings summary
    health["config"] = {
        "capital": settings.capital,
        "max_open_positions": settings.max_open_positions,
        "scan_interval_min": settings.scan_interval_min,
        "db_path": str(settings.resolved_db_path),
    }

    status_code = 200 if health["status"] == "ok" else 503
    return JSONResponse(content=health, status_code=status_code)
