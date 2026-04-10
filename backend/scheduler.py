"""
NSE Market Intelligence Platform - Scheduler
=============================================
APScheduler (AsyncIOScheduler) with Asia/Kolkata timezone.
Each job is a thin wrapper that delegates to the appropriate module.
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


# ─── Job stubs ───────────────────────────────────────────────────────────
# Each function is invoked by APScheduler.  The actual heavy lifting lives
# in dedicated modules under ``backend/modules/`` and ``backend/services/``.
# This keeps the scheduler file small and testable.


async def job_pre_market_scan() -> None:
    """08:45 IST - Pre-market analysis: regime snapshot, universe filter, signal generation."""
    logger.info("[scheduler] Running pre-market scan …")
    # TODO: call into backend.modules.scanner.run_pre_market_scan()
    # Steps:
    #   1. Refresh universe from NSE EQUITY_L.csv
    #   2. Capture regime snapshot (VIX, breadth, index trends)
    #   3. Generate candidate signals for the day
    logger.info("[scheduler] Pre-market scan complete.")


async def job_market_hours_scan() -> None:
    """Every 15 min during 09:15-15:15 IST - Intraday signal refresh."""
    logger.info("[scheduler] Running intraday scan …")
    # TODO: call into backend.modules.scanner.run_intraday_scan()
    # Steps:
    #   1. Fetch live prices for universe
    #   2. Re-score existing signals, generate new ones
    #   3. Check open trades for SL/target hits
    #   4. Update regime snapshot
    logger.info("[scheduler] Intraday scan complete.")


async def job_news_refresh() -> None:
    """Every 30 min - Refresh news feeds and recompute weighted impact scores."""
    logger.info("[scheduler] Refreshing news feeds …")
    # TODO: call into backend.services.news_service.refresh()
    # Steps:
    #   1. Fetch from all configured news sources
    #   2. Deduplicate and NLP-score headlines
    #   3. Update NewsItem table
    #   4. Recompute weighted_impact for active universe
    logger.info("[scheduler] News refresh complete.")


async def job_eod_grade() -> None:
    """16:00 IST - Grade the day's trades against actual close prices."""
    logger.info("[scheduler] Running EOD grading …")
    # TODO: call into backend.modules.grader.run_eod_grade()
    # Steps:
    #   1. Fetch closing prices for all traded symbols
    #   2. Mark open trades as closed with EOD square-off
    #   3. Compute gross & net P&L for each trade
    #   4. Persist results
    logger.info("[scheduler] EOD grading complete.")


async def job_learning_run() -> None:
    """16:30 IST - Self-learning: analyse today's trades and adjust weights."""
    logger.info("[scheduler] Running learning loop …")
    # TODO: call into backend.modules.learner.run_daily_learning()
    # Steps:
    #   1. Load today's closed trades + feature contributions
    #   2. Compute per-feature attribution vs outcome
    #   3. Derive weight adjustments (bounded, small deltas)
    #   4. Persist new weights + WeightsHistory record
    #   5. Persist LearningRecord per trade
    logger.info("[scheduler] Learning loop complete.")


async def job_eod_cleanup() -> None:
    """17:00 IST - End-of-day housekeeping."""
    logger.info("[scheduler] Running EOD cleanup …")
    # TODO: call into backend.modules.maintenance.run_eod_cleanup()
    # Steps:
    #   1. Expire stale signals (status → expired)
    #   2. Archive old news items beyond retention window
    #   3. Vacuum / optimise SQLite if needed
    #   4. Export daily summary to picks_history.jsonl
    logger.info("[scheduler] EOD cleanup complete.")


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
    # End scanning 15 min before close to avoid last-minute noise
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
        name=f"Intraday scan (every {settings.scan_interval_min}min, {settings.market_open}-{end_h:02d}:{end_m:02d} IST)",
        replace_existing=True,
        misfire_grace_time=120,
    )

    # News refresh every N minutes, Mon-Fri 08:00-16:00
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
    """Create (if needed) and start the scheduler.

    Safe to call multiple times -- will not double-start.
    """
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
