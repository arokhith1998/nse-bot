"""
NSE Market Intelligence Platform - Application Entry Point
==========================================================
Creates the FastAPI application, mounts routers, configures middleware,
and manages the application lifespan (startup / shutdown).

Run with::

    uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
"""
from __future__ import annotations

import asyncio
import logging
import os
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
    """Application lifespan manager."""
    # -- Startup --------------------------------------------------------
    logger.info("Starting NSE Market Intelligence Platform ...")
    await init_db()
    logger.info("Database initialised at %s", settings.resolved_db_path)

    # Load persisted capital from DB (if any)
    try:
        from backend.database import AsyncSessionLocal
        from backend.models import UserSettings
        from sqlalchemy import select
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(UserSettings.value).where(UserSettings.key == "capital")
            )
            row = result.scalar_one_or_none()
            if row:
                settings.capital = float(row)
                logger.info("Loaded capital from DB: Rs %.0f", settings.capital)
    except Exception:
        logger.debug("No persisted capital found, using default: Rs %.0f", settings.capital)

    # Start the scheduler
    sched = None
    try:
        from backend.scheduler import start_scheduler, shutdown_scheduler
        sched = await start_scheduler()
        logger.info("Scheduler started with %d jobs.", len(sched.get_jobs()))
    except Exception:
        logger.exception("Failed to start scheduler.")

    # Run initial scan in background (don't block startup)
    asyncio.create_task(_initial_scan())

    yield

    # -- Shutdown -------------------------------------------------------
    try:
        from backend.scheduler import shutdown_scheduler
        await shutdown_scheduler()
    except Exception:
        pass

    await close_db()
    logger.info("NSE Market Intelligence Platform stopped.")


async def _initial_scan() -> None:
    """Run a full scan on startup to populate the database."""
    await asyncio.sleep(2)  # Let the app finish starting
    logger.info("Running initial scan to populate database...")
    try:
        from backend.modules.scanner import run_full_scan
        summary = await run_full_scan()
        logger.info("Initial scan complete: %s", summary)
    except Exception:
        logger.exception("Initial scan failed (non-fatal, scheduler will retry)")


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

_cors_origins = [
    "http://localhost:3000",       # Next.js dev server
    "http://127.0.0.1:3000",
    "http://localhost:8000",       # Same-origin
    "http://127.0.0.1:8000",
]
# Add the Vercel frontend URL when deployed
_frontend_url = os.environ.get("FRONTEND_URL", "")
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

from backend.api.frontend_api import router as frontend_router     # noqa: E402
from backend.api.dashboard_api import router as dashboard_router  # noqa: E402
from backend.api.webhook_routes import router as webhook_router    # noqa: E402
from backend.api.backtest_routes import router as backtest_router  # noqa: E402

# Frontend-compatible routes first (match the frontend's expected paths/shapes)
app.include_router(frontend_router)
# Original detailed API routes (accessible via /api/picks/live, /api/regime/current, etc.)
app.include_router(dashboard_router)
app.include_router(webhook_router)
app.include_router(backtest_router)


# =====================================================================
# Static files
# =====================================================================

_data_dir = Path(__file__).resolve().parent / "data"
_data_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static/data", StaticFiles(directory=str(_data_dir)), name="static-data")


# =====================================================================
# Root & health endpoints
# =====================================================================

@app.get("/", include_in_schema=False)
async def root() -> JSONResponse:
    return JSONResponse(
        content={
            "name": "NSE Market Intelligence",
            "version": "1.0.0",
            "docs": "/docs",
            "health": "/health",
        }
    )


@app.get("/health", tags=["system"])
async def health_check() -> JSONResponse:
    health: dict = {
        "status": "ok",
        "database": "unknown",
        "scheduler": "unknown",
    }

    try:
        from backend.database import AsyncSessionLocal
        from sqlalchemy import text
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        health["database"] = "connected"
    except Exception as exc:
        health["database"] = f"error: {exc}"
        health["status"] = "degraded"

    try:
        from backend.scheduler import scheduler as sched
        health["scheduler"] = "running" if (sched and sched.running) else "stopped"
    except Exception:
        health["scheduler"] = "unavailable"

    try:
        from backend.api.dashboard_api import ws_manager
        health["websocket_clients"] = ws_manager.active_count
    except Exception:
        health["websocket_clients"] = 0

    health["config"] = {
        "capital": settings.capital,
        "max_open_positions": settings.max_open_positions,
        "scan_interval_min": settings.scan_interval_min,
        "db_path": str(settings.resolved_db_path),
    }

    status_code = 200 if health["status"] == "ok" else 503
    return JSONResponse(content=health, status_code=status_code)
