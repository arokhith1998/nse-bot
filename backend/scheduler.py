"""
NSE Market Intelligence Platform - Scheduler
=============================================
APScheduler (AsyncIOScheduler) with Asia/Kolkata timezone.
Each job is a thin wrapper that delegates to the scanner module.
"""
from __future__ import annotations

import logging
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from backend.config import settings

logger = logging.getLogger(__name__)

_TZ = "Asia/Kolkata"

scheduler: Optional[AsyncIOScheduler] = None


# ─── Job implementations ────────────────────────────────────────────────


async def job_pre_market_scan() -> None:
    """08:45 IST - Pre-market analysis: regime snapshot, universe filter, signal generation."""
    logger.info("[scheduler] Running pre-market scan …")
    try:
        from backend.modules.scanner import run_full_scan
        summary = await run_full_scan()
        logger.info("[scheduler] Pre-market scan complete: %s", summary)
    except Exception:
        logger.exception("[scheduler] Pre-market scan failed")


async def job_market_hours_scan() -> None:
    """Every 15 min during 09:15-15:15 IST - Intraday signal refresh."""
    logger.info("[scheduler] Running intraday scan …")
    try:
        from backend.modules.scanner import run_regime_scan, run_stock_scan
        regime = await run_regime_scan()
        regime_label = regime.get("label", "RANGE_CHOP") if regime else "RANGE_CHOP"
        count = await run_stock_scan(regime_label)
        logger.info("[scheduler] Intraday scan complete: %d signals, regime=%s", count, regime_label)
    except Exception:
        logger.exception("[scheduler] Intraday scan failed")


async def job_news_refresh() -> None:
    """Every 30 min - Refresh news feeds and recompute weighted impact scores."""
    logger.info("[scheduler] Refreshing news feeds …")
    try:
        from backend.modules.scanner import run_news_scan
        count = await run_news_scan()
        logger.info("[scheduler] News refresh complete: %d items", count)
    except Exception:
        logger.exception("[scheduler] News refresh failed")


async def job_eod_grade() -> None:
    """16:00 IST - Grade the day's trades against actual close prices."""
    logger.info("[scheduler] Running EOD grading …")
    try:
        from backend.modules.scanner import run_eod_grade
        closed = await run_eod_grade()
        logger.info("[scheduler] EOD grading complete: %d trades closed", closed)
    except Exception:
        logger.exception("[scheduler] EOD grading failed")


async def job_learning_run() -> None:
    """16:30 IST - Self-learning: analyse today's trades and adjust weights."""
    logger.info("[scheduler] Running learning loop …")
    try:
        from backend.modules.scanner import DEFAULT_WEIGHTS
        from backend.database import AsyncSessionLocal
        from backend.models import WeightsHistory
        import json
        import datetime as dt

        # For now, just save current weights as a snapshot
        async with AsyncSessionLocal() as session:
            wh = WeightsHistory(
                timestamp=dt.datetime.now(dt.timezone.utc),
                weights_json=json.dumps(DEFAULT_WEIGHTS),
                trigger="eod_learning",
                notes="Daily weights snapshot",
            )
            session.add(wh)
            await session.commit()
        logger.info("[scheduler] Learning loop complete (weights snapshot saved)")
    except Exception:
        logger.exception("[scheduler] Learning loop failed")


async def job_eod_cleanup() -> None:
    """17:00 IST - End-of-day housekeeping."""
    logger.info("[scheduler] Running EOD cleanup …")
    try:
        from backend.database import AsyncSessionLocal
        from backend.models import Signal, NewsItem
        from sqlalchemy import update, delete
        import datetime as dt

        async with AsyncSessionLocal() as session:
            # Expire stale signals
            await session.execute(
                update(Signal)
                .where(Signal.status == "pending")
                .values(status="expired")
            )
            # Delete news older than 3 days
            cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=3)
            await session.execute(
                delete(NewsItem).where(NewsItem.timestamp < cutoff)
            )
            await session.commit()
        logger.info("[scheduler] EOD cleanup complete.")
    except Exception:
        logger.exception("[scheduler] EOD cleanup failed")


# ─── Lifecycle ───────────────────────────────────────────────────────────

def _register_jobs(sched: AsyncIOScheduler) -> None:
    """Register all scheduled jobs on the given scheduler instance."""

    # Pre-market scan at 08:45 IST, Mon-Fri
    sched.add_job(
        job_pre_market_scan,
        CronTrigger(hour=8, minute=45, day_of_week="mon-fri", timezone=_TZ),
        id="pre_market_scan",
        name="Pre-market scan (08:45 IST)",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # Intraday scan every N minutes during market hours, Mon-Fri
    open_h, open_m = (int(x) for x in settings.market_open.split(":"))
    close_h, close_m = (int(x) for x in settings.market_close.split(":"))
    end_h, end_m = close_h, close_m - 15
    if end_m < 0:
        end_h -= 1
        end_m += 60

    sched.add_job(
        job_market_hours_scan,
        IntervalTrigger(
            minutes=settings.scan_interval_min,
            start_date=f"2024-01-01 {open_h:02d}:{open_m:02d}:00",
            timezone=_TZ,
        ),
        id="market_hours_scan",
        name=f"Intraday scan (every {settings.scan_interval_min}min)",
        replace_existing=True,
        misfire_grace_time=120,
    )

    # News refresh every N minutes
    sched.add_job(
        job_news_refresh,
        IntervalTrigger(
            minutes=settings.news_refresh_interval_min,
            timezone=_TZ,
        ),
        id="news_refresh",
        name=f"News refresh (every {settings.news_refresh_interval_min}min)",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # EOD grade at 16:00 IST, Mon-Fri
    sched.add_job(
        job_eod_grade,
        CronTrigger(hour=16, minute=0, day_of_week="mon-fri", timezone=_TZ),
        id="eod_grade",
        name="EOD grading (16:00 IST)",
        replace_existing=True,
        misfire_grace_time=600,
    )

    # Learning run at 16:30 IST, Mon-Fri
    sched.add_job(
        job_learning_run,
        CronTrigger(hour=16, minute=30, day_of_week="mon-fri", timezone=_TZ),
        id="learning_run",
        name="Learning loop (16:30 IST)",
        replace_existing=True,
        misfire_grace_time=600,
    )

    # EOD cleanup at 17:00 IST, Mon-Fri
    sched.add_job(
        job_eod_cleanup,
        CronTrigger(hour=17, minute=0, day_of_week="mon-fri", timezone=_TZ),
        id="eod_cleanup",
        name="EOD cleanup (17:00 IST)",
        replace_existing=True,
        misfire_grace_time=600,
    )


def create_scheduler() -> AsyncIOScheduler:
    """Create and configure the scheduler (does NOT start it)."""
    global scheduler
    sched = AsyncIOScheduler(timezone=_TZ)
    _register_jobs(sched)
    scheduler = sched
    logger.info("Scheduler created with %d jobs.", len(sched.get_jobs()))
    return sched


async def start_scheduler() -> AsyncIOScheduler:
    """Create (if needed) and start the scheduler."""
    global scheduler
    if scheduler is None:
        scheduler = create_scheduler()
    if not scheduler.running:
        scheduler.start()
        logger.info("Scheduler started.")
    return scheduler


async def shutdown_scheduler() -> None:
    """Gracefully shut down the scheduler."""
    global scheduler
    if scheduler is not None and scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler shut down.")
    scheduler = None
