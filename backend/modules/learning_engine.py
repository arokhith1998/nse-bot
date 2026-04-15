"""
learning_engine.py
==================
Adaptive learning system for the NSE Market Intelligence platform.

Grades completed trades, attributes outcomes to scoring features, and
nudges component weights toward configurations that empirically produce
better results.  Maintains regime-specific weight sets and exports
multi-dimensional performance analytics.

Learning constraints:
- Rolling 20-session window
- Exponential decay (lambda=0.9)
- Max daily weight drift: +/-2% per component
- Min 10 graded trades before updating a feature weight
- Hard weight bounds: [0.02, 0.40]
- Regime-specific weight learning

PAPER TRADING ONLY. Not investment advice.
"""
from __future__ import annotations

import json
import logging
import math
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration constants
# ---------------------------------------------------------------------------

ROLLING_WINDOW_SESSIONS = 50    # extended from 20 for more stable estimates
DECAY_FACTOR = 0.9
MAX_DAILY_DRIFT = 0.015         # reduced from 0.02 to slow down adaptation
MIN_SAMPLE_THRESHOLD = 25       # increased from 10 to require more evidence
WEIGHT_FLOOR = 0.02
WEIGHT_CEILING = 0.40


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class TradeGrade:
    """Complete grading record for a single completed trade."""

    trade_id: str
    symbol: str

    # ---- P&L ---------------------------------------------------------------
    pnl_pct: float = 0.0
    pnl_abs: float = 0.0           # absolute INR P&L
    was_winner: bool = False

    # ---- Quality metrics ---------------------------------------------------
    entry_quality: float = 0.0      # 0-100, how close to ideal entry zone
    exit_quality: float = 0.0       # 0-100, how close to optimal exit
    slippage_pct: float = 0.0       # estimated slippage as %

    # ---- Attribution -------------------------------------------------------
    feature_contributions: Dict[str, float] = field(default_factory=dict)
    # e.g. {"trend": 0.15, "momentum": 0.25, ...} -> how much each feature
    # contributed to the raw score of this trade.

    # ---- Context -----------------------------------------------------------
    regime: str = ""
    setup_type: str = ""
    time_window: str = ""           # e.g. "09:15-10:45"
    instrument_type: str = "EQ"
    news_category: str = ""         # e.g. "earnings", "macro", "sector"
    confidence_at_entry: float = 0.0

    # ---- Timestamps --------------------------------------------------------
    entry_time: str = ""
    exit_time: str = ""
    graded_at: str = field(
        default_factory=lambda: datetime.now().isoformat(timespec="seconds"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class UpdatedWeights:
    """Result of a weight-update cycle."""

    weights_dict: Dict[str, float]
    changes_dict: Dict[str, float]  # component -> delta applied
    reasoning: str                   # human-readable summary of what changed and why

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Time-window classification
# ---------------------------------------------------------------------------

_TIME_WINDOWS = [
    ("09:15-10:45", (9, 15), (10, 45)),
    ("10:45-12:00", (10, 45), (12, 0)),
    ("12:00-13:30", (12, 0), (13, 30)),
    ("13:30-15:00", (13, 30), (15, 0)),
    ("15:00-15:30", (15, 0), (15, 30)),
]


def _classify_time_window(time_str: str) -> str:
    """Classify an ISO timestamp or HH:MM string into a named window."""
    try:
        if "T" in time_str:
            t = datetime.fromisoformat(time_str).time()
        else:
            parts = time_str.split(":")
            from datetime import time as dt_time
            t = dt_time(int(parts[0]), int(parts[1]))
    except Exception:
        return "UNKNOWN"

    hm = (t.hour, t.minute)
    for label, start, end in _TIME_WINDOWS:
        if start <= hm < end:
            return label
    return "UNKNOWN"


# ---------------------------------------------------------------------------
# LearningEngine
# ---------------------------------------------------------------------------

class LearningEngine:
    """Grades trades, learns from outcomes, and tracks multi-level performance.

    Parameters
    ----------
    data_dir : Path | str
        Directory where learning artefacts are stored (learning_log.jsonl,
        setup_performance.json, feature_performance.json, weights by regime).
    """

    def __init__(self, data_dir: Path | str = "data") -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self._log_path = self.data_dir / "learning_log.jsonl"
        self._setup_perf_path = self.data_dir / "setup_performance.json"
        self._feature_perf_path = self.data_dir / "feature_performance.json"
        self._regime_weights_path = self.data_dir / "regime_weights.json"

    # ------------------------------------------------------------------
    # Trade grading
    # ------------------------------------------------------------------

    def grade_trade(self, trade: Dict[str, Any]) -> TradeGrade:
        """Grade a completed trade and append the result to the learning log.

        Parameters
        ----------
        trade : dict
            Must contain:
              - trade_id, symbol
              - entry_price, exit_price
              - qty
              - stop_loss, target1
              - score_breakdown: dict[str, float]
              - regime_at_entry: str
              - setup_type: str
              - entry_time: str (ISO or HH:MM)
              - exit_time: str
            Optional:
              - instrument_type: str
              - news_catalyst: str
              - confidence_score: float

        Returns
        -------
        TradeGrade
        """
        entry = float(trade.get("entry_price", 0))
        exit_p = float(trade.get("exit_price", 0))
        qty = int(trade.get("qty", 0))
        sl = float(trade.get("stop_loss", 0))
        t1 = float(trade.get("target1", 0))

        # ---- P&L -----------------------------------------------------------
        pnl_pct = ((exit_p - entry) / entry * 100) if entry > 0 else 0.0
        pnl_abs = (exit_p - entry) * qty

        # ---- Entry quality (how close to the low of entry zone?) -----------
        entry_zone_low = float(trade.get("entry_zone_low", entry * 0.998))
        entry_zone_high = float(trade.get("entry_zone_high", entry * 1.004))
        zone_width = max(entry_zone_high - entry_zone_low, 0.01)
        entry_quality = max(
            0.0,
            min(100.0, (1 - abs(entry - entry_zone_low) / zone_width) * 100),
        )

        # ---- Exit quality (0 = exited at stop, 100 = exited at T1+) -------
        if t1 > entry and sl < entry:
            full_range = t1 - sl
            exit_quality = max(
                0.0,
                min(100.0, ((exit_p - sl) / full_range) * 100),
            )
        else:
            exit_quality = 50.0  # can't assess without levels

        # ---- Slippage estimate ---------------------------------------------
        # Rough: assume 0.05% typical slippage for liquid NSE equities
        slippage_pct = 0.05

        # ---- Feature attribution -------------------------------------------
        breakdown = trade.get("score_breakdown", {})
        total_raw = sum(breakdown.values()) or 1.0
        contributions = {
            k: round(v / total_raw, 4) for k, v in breakdown.items()
        }

        # ---- Time window ---------------------------------------------------
        entry_time = trade.get("entry_time", "")
        tw = _classify_time_window(entry_time) if entry_time else "UNKNOWN"

        # ---- News category -------------------------------------------------
        news = trade.get("news_catalyst") or ""
        news_cat = _classify_news_category(news)

        grade = TradeGrade(
            trade_id=str(trade.get("trade_id", "")),
            symbol=trade.get("symbol", ""),
            pnl_pct=round(pnl_pct, 4),
            pnl_abs=round(pnl_abs, 2),
            was_winner=pnl_pct > 0,
            entry_quality=round(entry_quality, 1),
            exit_quality=round(exit_quality, 1),
            slippage_pct=round(slippage_pct, 4),
            feature_contributions=contributions,
            regime=trade.get("regime_at_entry", ""),
            setup_type=trade.get("setup_type", ""),
            time_window=tw,
            instrument_type=trade.get("instrument_type", "EQ"),
            news_category=news_cat,
            confidence_at_entry=float(trade.get("confidence_score", 0)),
            entry_time=entry_time,
            exit_time=trade.get("exit_time", ""),
        )

        self.export_learning_log(grade.to_dict())
        return grade

    # ------------------------------------------------------------------
    # Weight updating
    # ------------------------------------------------------------------

    def update_weights(
        self,
        recent_trades: List[TradeGrade],
        current_weights: Dict[str, float],
        regime: Optional[str] = None,
    ) -> UpdatedWeights:
        """Nudge weights toward features that predict wins.

        Parameters
        ----------
        recent_trades : list[TradeGrade]
            Graded trades from the rolling window.
        current_weights : dict[str, float]
            Current component weights.
        regime : str | None
            If provided, load / store regime-specific weight sets.

        Returns
        -------
        UpdatedWeights
        """
        # ---- Filter to rolling window -----------------------------------
        cutoff = datetime.now() - timedelta(days=ROLLING_WINDOW_SESSIONS)
        windowed = [
            t for t in recent_trades
            if self._parse_time(t.graded_at) >= cutoff
        ]

        if len(windowed) < MIN_SAMPLE_THRESHOLD:
            return UpdatedWeights(
                weights_dict=dict(current_weights),
                changes_dict={},
                reasoning=(
                    f"Insufficient data: {len(windowed)} trades in window "
                    f"(need {MIN_SAMPLE_THRESHOLD}). Weights unchanged."
                ),
            )

        # ---- Load regime-specific base if applicable --------------------
        if regime:
            base_weights = self._load_regime_weights(regime, current_weights)
        else:
            base_weights = dict(current_weights)

        old_weights = dict(base_weights)  # snapshot for audit trail

        # ---- Compute feature win-rate with exponential decay ------------
        feature_stats: Dict[str, Dict[str, float]] = defaultdict(
            lambda: {"weighted_wins": 0.0, "weighted_total": 0.0},
        )

        # Sort oldest-first so decay index 0 = oldest
        windowed_sorted = sorted(windowed, key=lambda t: t.graded_at)

        for i, trade in enumerate(windowed_sorted):
            decay = DECAY_FACTOR ** (len(windowed_sorted) - 1 - i)  # recent=higher
            for feat, contrib in trade.feature_contributions.items():
                feature_stats[feat]["weighted_total"] += decay * contrib
                if trade.was_winner:
                    feature_stats[feat]["weighted_wins"] += decay * contrib

        # ---- Compute desired drift per feature --------------------------
        changes: Dict[str, float] = {}
        reasoning_parts: List[str] = []
        feature_attribution: Dict[str, Dict[str, float]] = {}

        wins = [t for t in windowed if t.was_winner]
        win_rate = len(wins) / len(windowed) * 100 if windowed else 0.0

        for feat, stats in feature_stats.items():
            if feat not in base_weights:
                continue
            total = stats["weighted_total"]
            if total < 0.01:
                continue

            win_ratio = stats["weighted_wins"] / total  # 0..1
            # Centre at 0.5: positive delta if feature predicts wins
            raw_delta = (win_ratio - 0.5) * 0.10  # scale factor

            # Clamp to max daily drift
            clamped = max(-MAX_DAILY_DRIFT, min(MAX_DAILY_DRIFT, raw_delta))

            new_val = base_weights[feat] + clamped
            new_val = max(WEIGHT_FLOOR, min(WEIGHT_CEILING, new_val))
            actual_change = new_val - base_weights[feat]

            feature_attribution[feat] = {
                "win_ratio": round(win_ratio, 4),
                "raw_delta": round(raw_delta, 6),
                "clamped_delta": round(clamped, 6),
                "applied_delta": round(actual_change, 6),
            }

            if abs(actual_change) > 1e-6:
                changes[feat] = round(actual_change, 6)
                base_weights[feat] = new_val
                direction = "UP" if actual_change > 0 else "DOWN"
                reasoning_parts.append(
                    f"{feat}: {direction} {abs(actual_change):.4f} "
                    f"(win_ratio={win_ratio:.2f})"
                )

        # ---- Renormalise to sum=1 ----------------------------------------
        total_w = sum(base_weights.values())
        if total_w > 0:
            base_weights = {
                k: round(v / total_w, 6) for k, v in base_weights.items()
            }

        # ---- Persist regime-specific weights ----------------------------
        if regime:
            self._save_regime_weights(regime, base_weights)

        # ---- Learning safeguard: compare adaptive vs static baseline ----
        # (M5: real comparison using actual counterfactual PnLs from DB)
        static_baseline = {
            "trend": 0.25, "momentum": 0.20, "volume": 0.15,
            "breakout": 0.15, "volatility": 0.10, "news": 0.15,
        }

        adaptive_pnls = [t.pnl_abs for t in windowed]
        # Load static counterfactual PnLs from DB
        static_pnls = self._load_static_counterfactual_pnls(len(windowed))

        if len(adaptive_pnls) >= 10 and len(static_pnls) >= 10:
            import numpy as np
            adapt_arr = np.array(adaptive_pnls[-len(static_pnls):])
            static_arr = np.array(static_pnls[-len(adapt_arr):])

            adaptive_sharpe = float(
                np.mean(adapt_arr) / max(np.std(adapt_arr), 1e-6) * math.sqrt(252)
            )
            baseline_sharpe = float(
                np.mean(static_arr) / max(np.std(static_arr), 1e-6) * math.sqrt(252)
            )

            if not hasattr(self, '_static_underperform_count'):
                self._static_underperform_count = 0

            if adaptive_sharpe <= baseline_sharpe and len(windowed) >= 30:
                self._static_underperform_count += 1
                logger.info(
                    "[learning] Adaptive Sharpe %.3f <= static %.3f "
                    "(consecutive underperform: %d/30)",
                    adaptive_sharpe, baseline_sharpe,
                    self._static_underperform_count,
                )
                if self._static_underperform_count >= 30:
                    base_weights = dict(static_baseline)
                    changes = {
                        k: base_weights[k] - old_weights.get(k, 0)
                        for k in base_weights
                    }
                    reasoning_parts.append(
                        "AUTO-REVERT: adaptive Sharpe (%.3f) <= static baseline "
                        "(%.3f) for %d consecutive sessions. Reverted to defaults."
                        % (adaptive_sharpe, baseline_sharpe,
                           self._static_underperform_count)
                    )
                    logger.warning(
                        "[learning] AUTO-REVERT to static baseline weights — "
                        "adaptive Sharpe %.3f <= static %.3f for %d sessions",
                        adaptive_sharpe, baseline_sharpe,
                        self._static_underperform_count,
                    )
                    self._static_underperform_count = 0
            else:
                self._static_underperform_count = 0

        reasoning = (
            f"Updated from {len(windowed)} trades (window={ROLLING_WINDOW_SESSIONS} "
            f"sessions, decay={DECAY_FACTOR}). "
            + (" | ".join(reasoning_parts) if reasoning_parts else "No significant drift.")
        )

        # ---- Audit trail: write to WeightsHistory -----------------------
        if changes:
            self._write_audit_trail(
                old_weights=old_weights,
                new_weights=base_weights,
                sample_size=len(windowed),
                win_rate=round(win_rate, 2),
                feature_attribution=feature_attribution,
                regime=regime,
                reasoning=reasoning,
            )

        return UpdatedWeights(
            weights_dict=base_weights,
            changes_dict=changes,
            reasoning=reasoning,
        )

    # ------------------------------------------------------------------
    # Veto-driven weight penalty (M12)
    # ------------------------------------------------------------------

    @staticmethod
    def get_veto_penalties(
        regime: Optional[str] = None,
        lookback_sessions: int = 60,
    ) -> Dict[str, float]:
        """Load vetoes from UserVeto table and compute per-strategy weight penalties.

        Returns dict of {strategy: penalty_multiplier} where 1.0 = no penalty,
        0.7 = max penalty (capped to prevent spammy users from zeroing weights).
        """
        try:
            import asyncio
            from sqlalchemy import select, func
            from backend.database import AsyncSessionLocal
            from backend.models import UserVeto

            async def _fetch():
                async with AsyncSessionLocal() as session:
                    cutoff = datetime.now() - timedelta(days=lookback_sessions)
                    # Group vetoes by reason (used as strategy proxy)
                    result = await session.execute(
                        select(
                            UserVeto.reason,
                            func.count(UserVeto.id),
                        )
                        .where(UserVeto.timestamp >= cutoff)
                        .group_by(UserVeto.reason)
                    )
                    rows = result.all()
                    penalties: Dict[str, float] = {}
                    for reason, count in rows:
                        # Each 5 vetoes reduces weight by 10%, capped at 0.7x
                        penalty = max(0.7, 1.0 - (int(count) // 5) * 0.10)
                        penalties[reason] = penalty
                    return penalties

            try:
                loop = asyncio.get_running_loop()
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    return pool.submit(asyncio.run, _fetch()).result(timeout=10)
            except RuntimeError:
                return asyncio.run(_fetch())
        except Exception:
            logger.debug("[learning] Could not load veto penalties")
            return {}

    # ------------------------------------------------------------------
    # Learned hit rate for EV gate (M8)
    # ------------------------------------------------------------------

    @staticmethod
    def hit_rate_for(strategy: str, regime: str, min_sample: int = 20) -> Optional[float]:
        """Return trailing 60-session win rate for (strategy, regime) combo.

        Returns None if sample < min_sample (falls back to hardcoded 0.45).
        """
        try:
            import asyncio
            from sqlalchemy import select, func, and_
            from backend.database import AsyncSessionLocal
            from backend.models import Trade, Signal

            async def _fetch():
                async with AsyncSessionLocal() as session:
                    result = await session.execute(
                        select(
                            func.count(Trade.id),
                            func.sum(
                                # 1 if winner, 0 if loser
                                func.case(
                                    (Trade.net_pnl > 0, 1),
                                    else_=0,
                                )
                            ),
                        )
                        .join(Signal, Signal.id == Trade.signal_id)
                        .where(
                            and_(
                                Trade.status == "closed",
                                Signal.strategy == strategy,
                                Signal.regime_at_entry == regime,
                            )
                        )
                        .limit(60)
                    )
                    row = result.one()
                    total = int(row[0] or 0)
                    wins = int(row[1] or 0)
                    if total < min_sample:
                        return None
                    return round(wins / total, 4)

            try:
                loop = asyncio.get_running_loop()
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    return pool.submit(asyncio.run, _fetch()).result(timeout=10)
            except RuntimeError:
                return asyncio.run(_fetch())
        except Exception:
            logger.debug("[learning] Could not load hit rate for %s/%s", strategy, regime)
            return None

    # ------------------------------------------------------------------
    # Static counterfactual PnL loader (M5)
    # ------------------------------------------------------------------

    @staticmethod
    def _load_static_counterfactual_pnls(limit: int = 60) -> List[float]:
        """Load pnl_static_counterfactual from the last N closed trades.

        Returns a list of floats. Falls back to empty list if DB unavailable.
        """
        try:
            import asyncio
            from sqlalchemy import select, desc
            from backend.database import AsyncSessionLocal
            from backend.models import Trade

            async def _fetch():
                async with AsyncSessionLocal() as session:
                    result = await session.execute(
                        select(Trade.pnl_static_counterfactual)
                        .where(Trade.status == "closed")
                        .where(Trade.pnl_static_counterfactual.isnot(None))
                        .order_by(desc(Trade.exit_time))
                        .limit(limit)
                    )
                    rows = result.scalars().all()
                    return [float(r) for r in reversed(rows)]  # oldest-first

            try:
                loop = asyncio.get_running_loop()
                # If loop is running, create task and block — but this is called
                # from a sync context within update_weights, so use thread
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    return pool.submit(asyncio.run, _fetch()).result(timeout=10)
            except RuntimeError:
                return asyncio.run(_fetch())
        except Exception:
            logger.warning("[learning] Could not load static counterfactual PnLs")
            return []

    # ------------------------------------------------------------------
    # Audit trail
    # ------------------------------------------------------------------

    def _write_audit_trail(
        self,
        old_weights: Dict[str, float],
        new_weights: Dict[str, float],
        sample_size: int,
        win_rate: float,
        feature_attribution: Dict[str, Dict[str, float]],
        regime: Optional[str],
        reasoning: str,
    ) -> None:
        """Write a row to the WeightsHistory table for every weight update.

        Falls back to logging if the DB write fails (e.g. during backtests
        where the async DB may not be available).
        """
        audit_notes = json.dumps({
            "old_weights": old_weights,
            "new_weights": new_weights,
            "sample_size": sample_size,
            "win_rate": win_rate,
            "feature_attribution": feature_attribution,
            "regime": regime,
        }, default=str)

        # Try async DB write via background thread
        try:
            import asyncio
            from backend.database import AsyncSessionLocal
            from backend.models import WeightsHistory

            async def _persist():
                async with AsyncSessionLocal() as session:
                    wh = WeightsHistory(
                        weights_json=json.dumps(new_weights),
                        trigger="eod_learning",
                        notes=audit_notes,
                    )
                    session.add(wh)
                    await session.commit()

            # If an event loop is running, schedule; otherwise run sync
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(_persist())
            except RuntimeError:
                asyncio.run(_persist())

            logger.info(
                "Audit trail saved: sample_size=%d, win_rate=%.1f%%, "
                "changes=%d factors, regime=%s",
                sample_size, win_rate,
                len(feature_attribution), regime or "global",
            )
        except Exception:
            # Fallback: log the audit data so it's not lost
            logger.warning(
                "Could not write audit trail to DB, logging instead: %s",
                audit_notes,
            )

    # ------------------------------------------------------------------
    # Performance tracking
    # ------------------------------------------------------------------

    def compute_performance(
        self,
        grades: List[TradeGrade],
    ) -> Dict[str, Any]:
        """Compute multi-level performance metrics from graded trades.

        Returns a dict with sections:
        - feature_importance
        - regime_performance
        - setup_performance
        - time_window_performance
        - stock_vs_etf_performance
        - news_category_performance
        - overall

        Parameters
        ----------
        grades : list[TradeGrade]
            All graded trades to analyse.

        Returns
        -------
        dict
        """
        if not grades:
            return {"overall": {"trades": 0}, "note": "No trades to analyse."}

        result: Dict[str, Any] = {}

        # ---- Overall -------------------------------------------------
        wins = [g for g in grades if g.was_winner]
        losses = [g for g in grades if not g.was_winner]
        avg_pnl = sum(g.pnl_pct for g in grades) / len(grades)
        avg_win = sum(g.pnl_pct for g in wins) / len(wins) if wins else 0.0
        avg_loss = sum(g.pnl_pct for g in losses) / len(losses) if losses else 0.0
        result["overall"] = {
            "trades": len(grades),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(len(wins) / len(grades) * 100, 2),
            "avg_pnl_pct": round(avg_pnl, 4),
            "avg_win_pct": round(avg_win, 4),
            "avg_loss_pct": round(avg_loss, 4),
            "profit_factor": round(
                abs(sum(g.pnl_pct for g in wins))
                / max(abs(sum(g.pnl_pct for g in losses)), 0.01),
                2,
            ),
        }

        # ---- Feature importance --------------------------------------
        result["feature_importance"] = self._feature_importance(grades)

        # ---- Per-dimension breakdowns --------------------------------
        result["regime_performance"] = self._group_performance(
            grades, key_fn=lambda g: g.regime or "UNKNOWN",
        )
        result["setup_performance"] = self._group_performance(
            grades, key_fn=lambda g: g.setup_type or "UNKNOWN",
        )
        result["time_window_performance"] = self._group_performance(
            grades, key_fn=lambda g: g.time_window or "UNKNOWN",
        )
        result["stock_vs_etf_performance"] = self._group_performance(
            grades, key_fn=lambda g: g.instrument_type or "EQ",
        )
        result["news_category_performance"] = self._group_performance(
            grades, key_fn=lambda g: g.news_category or "NONE",
        )

        return result

    # ------------------------------------------------------------------
    # Export helpers
    # ------------------------------------------------------------------

    def export_performance(self, grades: List[TradeGrade]) -> None:
        """Compute and write setup_performance.json and feature_performance.json."""
        perf = self.compute_performance(grades)

        self._setup_perf_path.write_text(
            json.dumps(perf.get("setup_performance", {}), indent=2),
            encoding="utf-8",
        )
        self._feature_perf_path.write_text(
            json.dumps(perf.get("feature_importance", {}), indent=2),
            encoding="utf-8",
        )
        logger.info(
            "Exported performance to %s and %s",
            self._setup_perf_path, self._feature_perf_path,
        )

    def export_learning_log(self, record: Dict[str, Any]) -> None:
        """Append a single record (trade grade dict) to learning_log.jsonl."""
        with self._log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")

    def load_learning_log(self) -> List[Dict[str, Any]]:
        """Load all records from learning_log.jsonl."""
        records: List[Dict[str, Any]] = []
        if not self._log_path.exists():
            return records
        with self._log_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        return records

    # ------------------------------------------------------------------
    # Regime-specific weight persistence
    # ------------------------------------------------------------------

    def _load_regime_weights(
        self,
        regime: str,
        fallback: Dict[str, float],
    ) -> Dict[str, float]:
        """Load regime-specific weights, falling back to *fallback*."""
        if not self._regime_weights_path.exists():
            return dict(fallback)
        try:
            all_regimes = json.loads(
                self._regime_weights_path.read_text(encoding="utf-8"),
            )
            return all_regimes.get(regime, dict(fallback))
        except Exception:
            return dict(fallback)

    def _save_regime_weights(
        self,
        regime: str,
        weights: Dict[str, float],
    ) -> None:
        """Persist regime-specific weights."""
        all_regimes: Dict[str, Any] = {}
        if self._regime_weights_path.exists():
            try:
                all_regimes = json.loads(
                    self._regime_weights_path.read_text(encoding="utf-8"),
                )
            except Exception:
                pass
        all_regimes[regime] = weights
        self._regime_weights_path.write_text(
            json.dumps(all_regimes, indent=2),
            encoding="utf-8",
        )

    # ------------------------------------------------------------------
    # Internal analytics helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _feature_importance(grades: List[TradeGrade]) -> Dict[str, Any]:
        """Compute per-feature win/loss attribution.

        For each feature, calculate:
        - avg contribution in winning vs losing trades
        - "importance" = difference (positive = feature predicts wins)
        """
        from collections import defaultdict

        win_contribs: Dict[str, List[float]] = defaultdict(list)
        loss_contribs: Dict[str, List[float]] = defaultdict(list)

        for g in grades:
            target = win_contribs if g.was_winner else loss_contribs
            for feat, val in g.feature_contributions.items():
                target[feat].append(val)

        all_features = set(win_contribs.keys()) | set(loss_contribs.keys())
        result: Dict[str, Any] = {}

        for feat in sorted(all_features):
            w = win_contribs.get(feat, [])
            l = loss_contribs.get(feat, [])
            avg_w = sum(w) / len(w) if w else 0.0
            avg_l = sum(l) / len(l) if l else 0.0
            importance = avg_w - avg_l  # positive = predicts wins
            result[feat] = {
                "avg_contribution_winners": round(avg_w, 4),
                "avg_contribution_losers": round(avg_l, 4),
                "importance": round(importance, 4),
                "sample_wins": len(w),
                "sample_losses": len(l),
            }

        return result

    @staticmethod
    def _group_performance(
        grades: List[TradeGrade],
        key_fn,
    ) -> Dict[str, Any]:
        """Group grades by a key function and compute win-rate + avg P&L."""
        from collections import defaultdict

        groups: Dict[str, List[TradeGrade]] = defaultdict(list)
        for g in grades:
            groups[key_fn(g)].append(g)

        result: Dict[str, Any] = {}
        for key, group in sorted(groups.items()):
            wins = [g for g in group if g.was_winner]
            avg_pnl = sum(g.pnl_pct for g in group) / len(group)
            result[key] = {
                "trades": len(group),
                "wins": len(wins),
                "losses": len(group) - len(wins),
                "win_rate": round(len(wins) / len(group) * 100, 2),
                "avg_pnl_pct": round(avg_pnl, 4),
            }

        return result

    @staticmethod
    def _parse_time(iso_str: str) -> datetime:
        """Parse an ISO timestamp, returning epoch on failure."""
        try:
            return datetime.fromisoformat(iso_str)
        except Exception:
            return datetime(2000, 1, 1)


# ---------------------------------------------------------------------------
# News category heuristic
# ---------------------------------------------------------------------------

_NEWS_KEYWORDS: Dict[str, List[str]] = {
    "earnings": ["earnings", "profit", "revenue", "quarterly", "q1", "q2", "q3", "q4", "results", "EPS"],
    "macro": ["rbi", "fed", "gdp", "inflation", "rate cut", "rate hike", "policy", "fiscal"],
    "sector": ["sector", "industry", "outlook", "upgrade", "downgrade", "target"],
    "corporate": ["merger", "acquisition", "buyback", "split", "dividend", "bonus", "ipo"],
    "regulatory": ["sebi", "regulation", "compliance", "ban", "penalty", "fine"],
    "global": ["us market", "china", "crude", "oil", "gold", "dollar", "fii", "dii"],
}


def _classify_news_category(headline: str) -> str:
    """Classify a news headline into a category using keyword matching."""
    if not headline:
        return "NONE"
    hl = headline.lower()
    for category, keywords in _NEWS_KEYWORDS.items():
        if any(kw.lower() in hl for kw in keywords):
            return category
    return "general"
