"""
backtest_routes.py
==================
FastAPI router for historical backtesting endpoints.

Provides async backtest execution via background tasks, progress polling,
result retrieval, and history listing.

Endpoints
---------
- POST /api/backtest/run       -- Start a backtest (returns job ID)
- GET  /api/backtest/status/{job_id}  -- Check backtest progress
- GET  /api/backtest/result/{job_id}  -- Get completed backtest result
- GET  /api/backtest/history          -- List previous backtest runs
"""
from __future__ import annotations

import json
import logging
import threading
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field

from backend.backtester.engine import (
    BacktestConfig, BacktestEngine, walk_forward_backtest,
)
from backend.backtester.report import generate_json_report, save_report

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/backtest", tags=["backtest"])

# In-memory job store (for simplicity; could be replaced with Redis/DB)
_jobs: Dict[str, Dict[str, Any]] = {}
_RESULTS_DIR = Path(__file__).resolve().parent.parent / "data" / "backtest"
_RESULTS_DIR.mkdir(parents=True, exist_ok=True)


# ═══════════════════════════════════════════════════════════════════════
# Request / Response models
# ═══════════════════════════════════════════════════════════════════════

class BacktestRequest(BaseModel):
    """Request body for POST /api/backtest/run."""

    start_date: str = Field(
        default="2025-01-01",
        description="Backtest start date (YYYY-MM-DD).",
    )
    end_date: str = Field(
        default="",
        description="Backtest end date (YYYY-MM-DD). Defaults to today.",
    )
    universe: str = Field(
        default="nifty50",
        description="Symbol universe: nifty50, nifty200, full, or comma-separated symbols.",
    )
    capital: float = Field(default=100_000, ge=10_000, le=100_000_000)
    risk_pct: float = Field(default=1.0, ge=0.1, le=10.0)
    max_positions: int = Field(default=6, ge=1, le=30)
    slippage_pct: float = Field(default=0.05, ge=0.0, le=1.0)
    cost_model: str = Field(default="groww", pattern="^(groww|zerodha)$")
    top_n: int = Field(default=6, ge=1, le=30)
    use_regime_filter: bool = Field(default=True)
    benchmark: str = Field(default="^NSEI")


class WalkForwardRequest(BaseModel):
    """Request body for POST /api/backtest/walk-forward."""

    start_date: str = Field(default="2025-01-01")
    end_date: str = Field(default="")
    universe: str = Field(default="nifty50")
    capital: float = Field(default=100_000, ge=10_000, le=100_000_000)
    risk_pct: float = Field(default=1.0, ge=0.1, le=10.0)
    max_positions: int = Field(default=6, ge=1, le=30)
    cost_model: str = Field(default="groww", pattern="^(groww|zerodha)$")
    top_n: int = Field(default=6, ge=1, le=30)
    use_regime_filter: bool = Field(default=True)
    benchmark: str = Field(default="^NSEI")
    train_months: int = Field(default=3, ge=1, le=12)
    test_months: int = Field(default=1, ge=1, le=6)


class BacktestJobResponse(BaseModel):
    """Response for POST /api/backtest/run."""

    job_id: str
    status: str
    message: str


class BacktestStatusResponse(BaseModel):
    """Response for GET /api/backtest/status/{job_id}."""

    job_id: str
    status: str  # "pending" | "running" | "completed" | "failed"
    progress_pct: int = 0
    progress_msg: str = ""
    error: Optional[str] = None


class BacktestHistoryItem(BaseModel):
    """Single item in backtest history listing."""

    job_id: str
    status: str
    start_date: str
    end_date: str
    universe: str
    capital: float
    total_trades: int = 0
    total_pnl: float = 0.0
    win_rate_pct: float = 0.0
    created_at: str = ""


# ═══════════════════════════════════════════════════════════════════════
# Background task runner
# ═══════════════════════════════════════════════════════════════════════

def _run_backtest_job(job_id: str, config: BacktestConfig) -> None:
    """Execute a backtest in a background thread."""
    try:
        _jobs[job_id]["status"] = "running"

        engine = BacktestEngine(config)

        # Wire up progress reporting
        def on_progress(pct: int, msg: str) -> None:
            _jobs[job_id]["progress_pct"] = pct
            _jobs[job_id]["progress_msg"] = msg

        engine.on_progress = on_progress

        result = engine.run()

        # Generate JSON report and save
        json_report = generate_json_report(result)
        paths = save_report(result, output_dir=str(_RESULTS_DIR), prefix=job_id)

        _jobs[job_id]["status"] = "completed"
        _jobs[job_id]["progress_pct"] = 100
        _jobs[job_id]["progress_msg"] = "Complete"
        _jobs[job_id]["result"] = json_report
        _jobs[job_id]["paths"] = paths

        # Store summary for history
        s = result.summary
        _jobs[job_id]["total_trades"] = s.total_trades
        _jobs[job_id]["total_pnl"] = s.total_pnl
        _jobs[job_id]["win_rate_pct"] = s.win_rate_pct

        logger.info("Backtest job %s completed: %d trades, PnL=%.2f",
                     job_id, s.total_trades, s.total_pnl)

    except Exception as exc:
        logger.exception("Backtest job %s failed", job_id)
        _jobs[job_id]["status"] = "failed"
        _jobs[job_id]["error"] = str(exc)


# ═══════════════════════════════════════════════════════════════════════
# Endpoints
# ═══════════════════════════════════════════════════════════════════════

@router.post("/run", response_model=BacktestJobResponse)
async def start_backtest(req: BacktestRequest) -> BacktestJobResponse:
    """Start a backtest run in the background.

    Returns a job ID that can be used to poll progress and retrieve results.
    """
    job_id = str(uuid.uuid4())[:8]

    # Parse dates
    try:
        start = datetime.strptime(req.start_date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(400, f"Invalid start_date: {req.start_date}")

    if req.end_date:
        try:
            end = datetime.strptime(req.end_date, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(400, f"Invalid end_date: {req.end_date}")
    else:
        end = date.today()

    # Resolve symbols
    universe = req.universe
    if "," in universe:
        symbols: Any = [s.strip().upper() for s in universe.split(",") if s.strip()]
    else:
        symbols = universe

    config = BacktestConfig(
        symbols=symbols,
        start_date=start,
        end_date=end,
        capital=req.capital,
        risk_per_trade_pct=req.risk_pct,
        max_open_positions=req.max_positions,
        slippage_pct=req.slippage_pct,
        cost_model=req.cost_model,
        top_n=req.top_n,
        use_regime_filter=req.use_regime_filter,
        benchmark=req.benchmark,
    )

    # Register job
    _jobs[job_id] = {
        "status": "pending",
        "progress_pct": 0,
        "progress_msg": "Initialising...",
        "error": None,
        "result": None,
        "paths": None,
        "config": {
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "universe": req.universe,
            "capital": req.capital,
        },
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "total_trades": 0,
        "total_pnl": 0.0,
        "win_rate_pct": 0.0,
    }

    # Launch in background thread (not asyncio -- backtest is CPU-bound)
    thread = threading.Thread(
        target=_run_backtest_job,
        args=(job_id, config),
        daemon=True,
    )
    thread.start()

    return BacktestJobResponse(
        job_id=job_id,
        status="pending",
        message=f"Backtest job {job_id} started. Poll /api/backtest/status/{job_id} for progress.",
    )


@router.get("/status/{job_id}", response_model=BacktestStatusResponse)
async def get_backtest_status(job_id: str) -> BacktestStatusResponse:
    """Check the progress of a running backtest job."""
    if job_id not in _jobs:
        raise HTTPException(404, f"Job {job_id} not found.")

    job = _jobs[job_id]
    return BacktestStatusResponse(
        job_id=job_id,
        status=job["status"],
        progress_pct=job.get("progress_pct", 0),
        progress_msg=job.get("progress_msg", ""),
        error=job.get("error"),
    )


@router.get("/result/{job_id}")
async def get_backtest_result(job_id: str) -> dict:
    """Retrieve the full result of a completed backtest.

    Returns 404 if the job does not exist, or 202 if still running.
    """
    if job_id not in _jobs:
        # Check if there's a saved JSON file on disk
        saved = _find_saved_result(job_id)
        if saved:
            return saved
        raise HTTPException(404, f"Job {job_id} not found.")

    job = _jobs[job_id]

    if job["status"] == "failed":
        raise HTTPException(500, f"Job failed: {job.get('error', 'unknown')}")

    if job["status"] != "completed":
        raise HTTPException(
            202,
            f"Job {job_id} is still {job['status']}. "
            f"Progress: {job.get('progress_pct', 0)}%.",
        )

    result = job.get("result")
    if result is None:
        raise HTTPException(500, "Result not available.")

    return result


@router.get("/history")
async def list_backtest_history() -> List[dict]:
    """List all backtest runs (in-memory and saved on disk).

    Returns a list of summary records sorted by creation time (newest first).
    """
    items: List[dict] = []

    # In-memory jobs
    for job_id, job in _jobs.items():
        cfg = job.get("config", {})
        items.append({
            "job_id": job_id,
            "status": job["status"],
            "start_date": cfg.get("start_date", ""),
            "end_date": cfg.get("end_date", ""),
            "universe": cfg.get("universe", ""),
            "capital": cfg.get("capital", 0),
            "total_trades": job.get("total_trades", 0),
            "total_pnl": job.get("total_pnl", 0.0),
            "win_rate_pct": job.get("win_rate_pct", 0.0),
            "created_at": job.get("created_at", ""),
        })

    # Saved JSON files on disk
    disk_ids = {item["job_id"] for item in items}
    for json_file in sorted(_RESULTS_DIR.glob("*.json"), reverse=True):
        # Extract job_id from filename pattern: {job_id}_{timestamp}.json
        stem = json_file.stem
        parts = stem.split("_")
        if len(parts) >= 2:
            potential_id = parts[0]
            if potential_id in disk_ids or potential_id == "backtest":
                continue

            try:
                data = json.loads(json_file.read_text(encoding="utf-8"))
                cfg = data.get("config", {})
                summary = data.get("summary", {})
                items.append({
                    "job_id": potential_id,
                    "status": "completed",
                    "start_date": cfg.get("start_date", ""),
                    "end_date": cfg.get("end_date", ""),
                    "universe": cfg.get("symbols", ""),
                    "capital": cfg.get("capital", 0),
                    "total_trades": summary.get("total_trades", 0),
                    "total_pnl": summary.get("total_pnl", 0.0),
                    "win_rate_pct": summary.get("win_rate_pct", 0.0),
                    "created_at": data.get("generated_at", ""),
                })
            except Exception:
                continue

    # Sort newest first
    items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return items


# ═══════════════════════════════════════════════════════════════════════
# Walk-forward backtest
# ═══════════════════════════════════════════════════════════════════════

def _run_walk_forward_job(job_id: str, config: BacktestConfig,
                          train_months: int, test_months: int) -> None:
    """Execute a walk-forward backtest in a background thread."""
    try:
        _jobs[job_id]["status"] = "running"

        def on_progress(pct: int, msg: str) -> None:
            _jobs[job_id]["progress_pct"] = pct
            _jobs[job_id]["progress_msg"] = msg

        wf_result = walk_forward_backtest(
            config, train_months=train_months, test_months=test_months,
            on_progress=on_progress,
        )

        result_dict = wf_result.to_dict()
        _jobs[job_id]["status"] = "completed"
        _jobs[job_id]["progress_pct"] = 100
        _jobs[job_id]["progress_msg"] = "Complete"
        _jobs[job_id]["result"] = result_dict
        _jobs[job_id]["total_trades"] = wf_result.aggregate_trades
        _jobs[job_id]["total_pnl"] = wf_result.aggregate_pnl
        _jobs[job_id]["win_rate_pct"] = wf_result.aggregate_win_rate_pct

        logger.info(
            "Walk-forward job %s completed: %d folds, %d trades, "
            "Sharpe=%.4f vs single-pass=%.4f",
            job_id, len(wf_result.folds), wf_result.aggregate_trades,
            wf_result.aggregate_sharpe, wf_result.single_pass_sharpe,
        )

    except Exception as exc:
        logger.exception("Walk-forward job %s failed", job_id)
        _jobs[job_id]["status"] = "failed"
        _jobs[job_id]["error"] = str(exc)


@router.post("/walk-forward", response_model=BacktestJobResponse)
async def start_walk_forward(req: WalkForwardRequest) -> BacktestJobResponse:
    """Start a walk-forward backtest in the background.

    Returns a job ID. Poll /api/backtest/status/{job_id} for progress,
    then GET /api/backtest/result/{job_id} for the full result.
    """
    job_id = "wf-" + str(uuid.uuid4())[:8]

    try:
        start = datetime.strptime(req.start_date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(400, f"Invalid start_date: {req.start_date}")

    if req.end_date:
        try:
            end = datetime.strptime(req.end_date, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(400, f"Invalid end_date: {req.end_date}")
    else:
        end = date.today()

    universe = req.universe
    if "," in universe:
        symbols: Any = [s.strip().upper() for s in universe.split(",") if s.strip()]
    else:
        symbols = universe

    config = BacktestConfig(
        symbols=symbols,
        start_date=start,
        end_date=end,
        capital=req.capital,
        risk_per_trade_pct=req.risk_pct,
        max_open_positions=req.max_positions,
        cost_model=req.cost_model,
        top_n=req.top_n,
        use_regime_filter=req.use_regime_filter,
        benchmark=req.benchmark,
    )

    _jobs[job_id] = {
        "status": "pending",
        "progress_pct": 0,
        "progress_msg": "Initialising walk-forward...",
        "error": None,
        "result": None,
        "paths": None,
        "config": {
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "universe": req.universe,
            "capital": req.capital,
            "train_months": req.train_months,
            "test_months": req.test_months,
        },
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "total_trades": 0,
        "total_pnl": 0.0,
        "win_rate_pct": 0.0,
    }

    thread = threading.Thread(
        target=_run_walk_forward_job,
        args=(job_id, config, req.train_months, req.test_months),
        daemon=True,
    )
    thread.start()

    return BacktestJobResponse(
        job_id=job_id,
        status="pending",
        message=f"Walk-forward job {job_id} started. Poll /api/backtest/status/{job_id} for progress.",
    )


# ═══════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════

def _find_saved_result(job_id: str) -> Optional[dict]:
    """Look for a saved JSON result file matching *job_id*."""
    for json_file in _RESULTS_DIR.glob(f"{job_id}_*.json"):
        try:
            return json.loads(json_file.read_text(encoding="utf-8"))
        except Exception:
            continue
    return None
