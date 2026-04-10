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

ROLLING_WINDOW_SESSIONS = 20
DECAY_FACTOR = 0.9
MAX_DAILY_DRIFT = 0.02          # +/- 2% per component per update
MIN_SAMPLE_THRESHOLD = 10       # need at least this many trades to update a weight
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

        reasoning = (
            f"Updated from {len(windowed)} trades (window={ROLLING_WINDOW_SESSIONS} "
            f"sessions, decay={DECAY_FACTOR}). "
            + (" | ".join(reasoning_parts) if reasoning_parts else "No significant drift.")
        )

        return UpdatedWeights(
            weights_dict=base_weights,
            changes_dict=changes,
            reasoning=reasoning,
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
