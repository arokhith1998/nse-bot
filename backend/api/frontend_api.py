"""
NSE Market Intelligence Platform - Frontend-Compatible API
==========================================================
Routes that match the exact paths and response shapes expected by
the Next.js frontend (types.ts). These transform DB models into
the format the frontend components consume.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings, pick_count_for_capital
from backend.database import get_db
from backend.models import (
    NewsItem,
    RegimeSnapshot,
    Signal,
    Trade,
    WeightsHistory,
)
from backend.modules.risk_engine import _CORRELATED_PAIRS

logger = logging.getLogger(__name__)

router = APIRouter(tags=["frontend"])

# Default weights shown in the UI
DEFAULT_WEIGHTS = {
    "trend": 0.25,
    "momentum": 0.20,
    "volume": 0.15,
    "breakout": 0.15,
    "volatility": 0.10,
    "news": 0.15,
}


# ── GET /api/picks ──────────────────────────────────────────────────────
# Frontend expects: PicksResponse { top_picks[], stretch_picks[], weights, ... }

@router.get("/api/picks")
async def get_picks(db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    """Return picks in the format the frontend PicksResponse expects."""
    result = await db.execute(
        select(Signal)
        .where(Signal.status.in_(["pending", "active"]))
        .order_by(desc(Signal.score))
    )
    signals = result.scalars().all()

    # Dynamic pick count based on capital
    n_picks = pick_count_for_capital(settings.capital)

    # Build picks with confidence-weighted sizing
    all_picks = []
    for sig in signals:
        entry = (sig.entry_zone_low + sig.entry_zone_high) / 2
        risk = entry - sig.stop_loss
        reward = sig.target1 - entry
        rr = round(reward / risk, 2) if risk > 0 else 0

        # Confidence-weighted position sizing
        confidence = min((sig.score or 50) / 100, 0.95)
        base_qty = max(1, int((settings.capital * settings.risk_per_trade_pct / 100) / risk)) if risk > 0 else 1
        qty = max(1, int(base_qty * (0.5 + 0.5 * confidence)))
        capital_needed = round(entry * qty, 2)

        # Affordability filter: skip if 1 share alone exceeds 30% of capital
        if entry > settings.capital * 0.30:
            continue

        pick = {
            "symbol": sig.symbol,
            "price": round(entry, 2),
            "prev_close": round(sig.entry_zone_low, 2),
            "day_high": round(sig.entry_zone_high * 1.01, 2),
            "day_low": round(sig.entry_zone_low * 0.99, 2),
            "day_change_pct": 0.0,
            "entry_zone": f"{sig.entry_zone_low:.2f} - {sig.entry_zone_high:.2f}",
            "entry": round(entry, 2),
            "stop_loss": sig.stop_loss,
            "target": sig.target1,
            "qty": qty,
            "capital_needed": capital_needed,
            "fits_budget": capital_needed <= settings.capital,
            "score": sig.score,
            "strategy": sig.strategy,
            "bias": "LONG" if sig.direction == "long" else "SHORT",
            "rsi": None,
            "stoch_k": 50.0,
            "bb_position": 0.5,
            "gap_pct": 0.0,
            "atr_pct": round(abs(risk / entry) * 100, 2) if entry > 0 else 2.0,
            "vol_ratio": 1.0,
            "ret5d_pct": 0.0,
            "ret20d_pct": 0.0,
            "near_20d_high": False,
            "news_catalyst": None,
            "sentiment_score": 0.0,
            "cost_roundtrip": round(40 + capital_needed * 0.0005, 2),
            "net_profit": round(reward * qty - 40, 2),
            "net_loss": round(-risk * qty - 40, 2),
            "net_rr": rr,
            "source": sig.source,
            "notes": [sig.explanation] if sig.explanation else [],
        }
        all_picks.append(pick)

    top_picks = all_picks[:n_picks]
    stretch_picks = all_picks[n_picks:n_picks * 2]

    # Get current weights from DB or use defaults
    weights = DEFAULT_WEIGHTS.copy()
    wh_result = await db.execute(
        select(WeightsHistory).order_by(desc(WeightsHistory.timestamp)).limit(1)
    )
    wh = wh_result.scalar_one_or_none()
    if wh and wh.weights_json:
        try:
            weights = json.loads(wh.weights_json)
        except (json.JSONDecodeError, TypeError):
            pass

    # Count total signals generated today
    today_start = dt.datetime.now(dt.timezone.utc).replace(hour=0, minute=0, second=0)
    total_result = await db.execute(
        select(func.count(Signal.id)).where(Signal.timestamp >= today_start)
    )
    total_scored = total_result.scalar() or 0

    # Get current regime for advisory
    regime_result = await db.execute(
        select(RegimeSnapshot).order_by(desc(RegimeSnapshot.timestamp)).limit(1)
    )
    regime_snap = regime_result.scalar_one_or_none()
    regime_label = getattr(regime_snap, "regime_label", "RANGE_CHOP") or "RANGE_CHOP"

    # Build advisory text
    advisory = _build_advisory(top_picks, settings.capital, n_picks, regime_label)

    return {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "data_as_of": dt.datetime.now(dt.timezone.utc).isoformat(),
        "trade_for": dt.datetime.now(dt.timezone.utc).strftime("%A %d %b %Y"),
        "universe_size": 200,
        "scored": total_scored,
        "skipped": max(0, 50 - total_scored),
        "weights": weights,
        "news_count": 0,
        "top_picks": top_picks,
        "stretch_picks": stretch_picks,
        "advisory": advisory,
        "recommended_pick_count": n_picks,
        "disclaimer": (
            "PAPER TRADING ONLY. These picks are educational, generated by a "
            "rule-based scoring system. SEBI 2023: ~70% of retail intraday traders lose money."
        ),
    }


def _build_advisory(
    picks: List[Dict],
    capital: float,
    n_picks: int,
    regime_label: str,
) -> List[str]:
    """Generate human-readable advisory lines for the picks response."""
    lines: List[str] = []

    # Capital-based advice
    if n_picks <= 2:
        lines.append(
            f"With Rs {capital:,.0f} capital, focus on these {n_picks} "
            f"highest-conviction picks only."
        )
    elif n_picks <= 5:
        best = min(2, len(picks))
        lines.append(
            f"With Rs {capital:,.0f}, you can run {n_picks} positions. "
            f"Top {best} are strongest."
        )
    else:
        lines.append(
            f"With Rs {capital:,.0f}, you can comfortably run {n_picks} positions."
        )

    # Regime context
    regime_advice = {
        "TREND_UP": "Regime is Trend Up - momentum and breakout picks are favored today.",
        "TREND_DOWN": "Regime is Trend Down - be cautious, reduce position sizes.",
        "RANGE_CHOP": "Regime is Range/Chop - expect choppy action, tighter stops recommended.",
        "GAP_AND_GO": "Regime is Gap & Go - watch for gap follow-through in the first 30 min.",
        "GAP_FILL": "Regime is Gap Fill - gaps may reverse, be patient with entries.",
        "HIGH_VOL_EVENT": "High volatility event - reduce position sizes, only take highest conviction.",
        "LOW_LIQ_DRIFT": "Low liquidity drift - thin markets, watch for slippage.",
    }
    if regime_label in regime_advice:
        lines.append(regime_advice[regime_label])

    # Correlation warnings
    pick_symbols = {p["symbol"] for p in picks}
    for pair in _CORRELATED_PAIRS:
        overlap = pair & pick_symbols
        if len(overlap) == 2:
            s1, s2 = sorted(overlap)
            lines.append(
                f"Correlation warning: {s1} and {s2} move together "
                f"- consider picking only one."
            )

    # Confidence tiers
    high_conf = [p for p in picks if (p.get("score") or 0) >= 70]
    med_conf = [p for p in picks if 50 <= (p.get("score") or 0) < 70]
    low_conf = [p for p in picks if (p.get("score") or 0) < 50]
    if high_conf:
        syms = ", ".join(p["symbol"] for p in high_conf[:4])
        lines.append(f"High confidence: {syms}")
    if med_conf:
        syms = ", ".join(p["symbol"] for p in med_conf[:4])
        lines.append(f"Moderate confidence: {syms}")
    if low_conf:
        syms = ", ".join(p["symbol"] for p in low_conf[:4])
        lines.append(f"Speculative: {syms}")

    return lines


# ── GET /api/regime ─────────────────────────────────────────────────────
# Frontend expects: RegimeState { label, description, vix, ... }

@router.get("/api/regime")
async def get_regime(db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    """Return regime in the format the frontend RegimeState expects."""
    result = await db.execute(
        select(RegimeSnapshot).order_by(desc(RegimeSnapshot.timestamp)).limit(1)
    )
    snap = result.scalar_one_or_none()

    if snap is None:
        return {
            "label": "RANGE_BOUND",
            "description": "No regime data available yet. Scan will run automatically.",
            "nifty_close": 0,
            "nifty_change_pct": 0,
            "sensex_close": 0,
            "sensex_change_pct": 0,
            "vix": 0,
            "vix_change_pct": 0,
            "advance_decline_ratio": 1.0,
            "breadth_pct": 50.0,
            "sector_leaders": [],
            "sector_laggards": [],
            "scoring_modifier": 1.0,
            "reasoning": "Awaiting first regime scan...",
            "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
        }

    # Map DB regime labels to frontend labels (handle both uppercase and lowercase)
    label_map = {
        # Uppercase variants
        "TREND_UP": "TRENDING_UP",
        "TREND_DOWN": "TRENDING_DOWN",
        "RANGE_CHOP": "RANGE_BOUND",
        "HIGH_VOL_EVENT": "HIGH_VOL",
        "GAP_AND_GO": "RISK_ON",
        "GAP_FILL": "RANGE_BOUND",
        "LOW_LIQ_DRIFT": "EXHAUSTION",
        # Lowercase enum .value variants (from RegimeEngine)
        "trend_up": "TRENDING_UP",
        "trend_down": "TRENDING_DOWN",
        "range_chop": "RANGE_BOUND",
        "high_vol_event": "HIGH_VOL",
        "gap_and_go": "RISK_ON",
        "gap_fill": "RANGE_BOUND",
        "low_liq_drift": "EXHAUSTION",
        # Legacy labels
        "risk_on": "RISK_ON",
        "risk_off": "RISK_OFF",
        "trending_bull": "TRENDING_UP",
        "trending_bear": "TRENDING_DOWN",
        "choppy": "RANGE_BOUND",
    }

    label = label_map.get(snap.regime_label, snap.regime_label)

    descriptions = {
        "TRENDING_UP": "Market in uptrend — momentum and breakout setups favoured",
        "TRENDING_DOWN": "Market in downtrend — defensive positioning, tighter stops",
        "RANGE_BOUND": "Choppy/range-bound market — mean reversion setups preferred",
        "HIGH_VOL": "High volatility event — reduced position sizing",
        "RISK_ON": "Risk-on environment — broader participation expected",
        "RISK_OFF": "Risk-off mode — capital preservation priority",
        "EXHAUSTION": "Low liquidity drift — reduced participation recommended",
    }

    scoring_mults = {
        "TRENDING_UP": 1.1,
        "TRENDING_DOWN": 0.7,
        "RANGE_BOUND": 0.9,
        "HIGH_VOL": 0.6,
        "RISK_ON": 1.15,
        "RISK_OFF": 0.65,
        "EXHAUSTION": 0.75,
    }

    return {
        "label": label,
        "description": descriptions.get(label, f"Current regime: {label}"),
        "nifty_close": getattr(snap, 'nifty_close', None) or 0,
        "nifty_change_pct": getattr(snap, 'nifty_change_pct', None) or 0,
        "sensex_close": getattr(snap, 'sensex_close', None) or 0,
        "sensex_change_pct": getattr(snap, 'sensex_change_pct', None) or 0,
        "vix": snap.vix,
        "vix_change_pct": 0,
        "advance_decline_ratio": snap.advance_decline,
        "breadth_pct": snap.breadth_pct,
        "sector_leaders": [],
        "sector_laggards": [],
        "scoring_modifier": scoring_mults.get(label, 1.0),
        "reasoning": (
            f"VIX: {snap.vix:.1f}, Breadth: {snap.breadth_pct:.0f}%, "
            f"Nifty Trend: {snap.nifty_trend}, A/D: {snap.advance_decline:.2f}"
        ),
        "timestamp": snap.timestamp.isoformat() if snap.timestamp else dt.datetime.now(dt.timezone.utc).isoformat(),
    }


# ── GET /api/regime/history ─────────────────────────────────────────────
# Frontend expects: { history: RegimeState[] }

@router.get("/api/regime/history")
async def get_regime_history(
    days: int = Query(default=30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
    result = await db.execute(
        select(RegimeSnapshot)
        .where(RegimeSnapshot.timestamp >= cutoff)
        .order_by(desc(RegimeSnapshot.timestamp))
    )
    snapshots = result.scalars().all()

    label_map = {
        "TREND_UP": "TRENDING_UP",
        "TREND_DOWN": "TRENDING_DOWN",
        "RANGE_CHOP": "RANGE_BOUND",
        "HIGH_VOL_EVENT": "HIGH_VOL",
        "GAP_AND_GO": "RISK_ON",
        "GAP_FILL": "RANGE_BOUND",
        "LOW_LIQ_DRIFT": "EXHAUSTION",
        "trend_up": "TRENDING_UP",
        "trend_down": "TRENDING_DOWN",
        "range_chop": "RANGE_BOUND",
        "high_vol_event": "HIGH_VOL",
        "gap_and_go": "RISK_ON",
        "gap_fill": "RANGE_BOUND",
        "low_liq_drift": "EXHAUSTION",
    }

    history = []
    for s in snapshots:
        label = label_map.get(s.regime_label, s.regime_label)
        history.append({
            "label": label,
            "description": f"VIX: {s.vix:.1f}, Breadth: {s.breadth_pct:.0f}%",
            "nifty_close": getattr(s, 'nifty_close', None) or 0,
            "nifty_change_pct": getattr(s, 'nifty_change_pct', None) or 0,
            "sensex_close": getattr(s, 'sensex_close', None) or 0,
            "sensex_change_pct": getattr(s, 'sensex_change_pct', None) or 0,
            "vix": s.vix,
            "vix_change_pct": 0,
            "advance_decline_ratio": s.advance_decline,
            "breadth_pct": s.breadth_pct,
            "sector_leaders": [],
            "sector_laggards": [],
            "scoring_modifier": 1.0,
            "reasoning": f"{s.nifty_trend} trend, {s.regime_label}",
            "timestamp": s.timestamp.isoformat() if s.timestamp else "",
        })

    return {"history": history}


# ── GET /api/trades/active ──────────────────────────────────────────────
# Frontend expects: Trade[] (array directly)

@router.get("/api/trades/active")
async def get_active_trades(db: AsyncSession = Depends(get_db)) -> List[Dict[str, Any]]:
    result = await db.execute(
        select(Trade, Signal)
        .join(Signal, Signal.id == Trade.signal_id)
        .where(Trade.status.in_(["open", "partial"]))
        .order_by(desc(Trade.entry_time))
    )
    rows = result.all()

    trades = []
    for trade, signal in rows:
        pnl = 0.0
        pnl_pct = 0.0
        current_price = trade.entry_price
        duration = "0m"

        if trade.entry_time:
            delta = dt.datetime.now(dt.timezone.utc) - trade.entry_time.replace(tzinfo=dt.timezone.utc)
            hours = delta.total_seconds() / 3600
            if hours < 1:
                duration = f"{int(delta.total_seconds() / 60)}m"
            else:
                duration = f"{hours:.1f}h"

        trades.append({
            "id": str(trade.id),
            "symbol": trade.symbol,
            "bias": "LONG" if signal.direction == "long" else "SHORT",
            "entry_price": trade.entry_price,
            "current_price": current_price,
            "qty": trade.qty,
            "stop_loss": signal.stop_loss,
            "target": signal.target1,
            "pnl": pnl,
            "pnl_pct": pnl_pct,
            "entry_time": trade.entry_time.isoformat() if trade.entry_time else "",
            "holding_duration": duration,
            "status": trade.status.upper(),
        })

    return trades


# ── GET /api/trades/history ─────────────────────────────────────────────
# Frontend expects: TradeHistory[] (array directly)

@router.get("/api/trades/history")
async def get_trade_history(
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> List[Dict[str, Any]]:
    result = await db.execute(
        select(Trade, Signal)
        .join(Signal, Signal.id == Trade.signal_id)
        .where(Trade.status == "closed")
        .order_by(desc(Trade.exit_time))
        .limit(limit)
    )
    rows = result.all()

    trades = []
    for trade, signal in rows:
        net = trade.net_pnl or 0.0
        pnl_pct = ((net / (trade.entry_price * trade.qty)) * 100) if (trade.entry_price * trade.qty) > 0 else 0

        if net > 0:
            result_label = "WIN"
        elif net < 0:
            result_label = "LOSS"
        else:
            result_label = "BREAKEVEN"

        trades.append({
            "id": str(trade.id),
            "symbol": trade.symbol,
            "bias": "LONG" if signal.direction == "long" else "SHORT",
            "entry_price": trade.entry_price,
            "exit_price": trade.exit_price or trade.entry_price,
            "qty": trade.qty,
            "pnl": round(net, 2),
            "pnl_pct": round(pnl_pct, 2),
            "entry_time": trade.entry_time.isoformat() if trade.entry_time else "",
            "exit_time": trade.exit_time.isoformat() if trade.exit_time else "",
            "setup": signal.strategy,
            "result": result_label,
        })

    return trades


# ── GET /api/news ───────────────────────────────────────────────────────
# Frontend expects: NewsResponse { fetched_at, items[] }

@router.get("/api/news")
async def get_news(
    symbol: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    stmt = select(NewsItem).order_by(desc(NewsItem.timestamp)).limit(50)
    if symbol:
        stmt = stmt.where(NewsItem.symbol == symbol.upper())

    result = await db.execute(stmt)
    items = result.scalars().all()

    news_list = []
    for n in items:
        news_list.append({
            "symbol": n.symbol or "",
            "headline": n.headline,
            "source": n.source,
            "count": n.multi_source_count,
            "sentiment": n.sentiment_score,
            "published_at": n.timestamp.isoformat() if n.timestamp else "",
        })

    return {
        "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "items": news_list,
    }


# ── GET /api/portfolio/risk ─────────────────────────────────────────────
# Frontend expects: PortfolioRisk

@router.get("/api/portfolio/risk")
async def get_portfolio_risk(db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    # Count open positions
    result = await db.execute(
        select(func.count(Trade.id)).where(Trade.status.in_(["open", "partial"]))
    )
    open_count = result.scalar() or 0

    # Sum capital used
    result2 = await db.execute(
        select(Trade).where(Trade.status.in_(["open", "partial"]))
    )
    open_trades = result2.scalars().all()
    capital_used = sum(t.entry_price * t.qty for t in open_trades)

    utilization = (capital_used / settings.capital * 100) if settings.capital > 0 else 0

    return {
        "capital_total": settings.capital,
        "capital_used": round(capital_used, 2),
        "capital_utilization_pct": round(utilization, 1),
        "open_positions": open_count,
        "max_positions": settings.max_open_positions,
        "sector_exposure": {},
        "portfolio_heat_pct": round(min(utilization * settings.risk_per_trade_pct / 100, 10), 2),
        "risk_per_trade": round(settings.capital * settings.risk_per_trade_pct / 100, 2),
        "max_daily_loss": round(settings.capital * 0.03, 2),
    }


# ── GET /api/performance ───────────────────────────────────────────────
# Frontend expects: PerformanceData

@router.get("/api/performance")
async def get_performance(db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    result = await db.execute(
        select(Trade, Signal)
        .join(Signal, Signal.id == Trade.signal_id)
        .where(Trade.status == "closed")
        .order_by(desc(Trade.exit_time))
    )
    rows = result.all()

    total_trades = len(rows)
    if total_trades == 0:
        return {
            "total_trades": 0,
            "win_rate": 0,
            "avg_profit": 0,
            "avg_loss": 0,
            "profit_factor": 0,
            "sharpe_ratio": 0,
            "max_drawdown": 0,
            "total_pnl": 0,
            "win_rate_by_setup": {},
            "avg_rr_achieved": 0,
            "best_trade": None,
            "worst_trade": None,
            "daily_pnl": [],
        }

    pnls = [t.net_pnl or 0.0 for t, _ in rows]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]

    win_rate = (len(wins) / total_trades * 100) if total_trades > 0 else 0
    avg_profit = (sum(wins) / len(wins)) if wins else 0
    avg_loss = (sum(losses) / len(losses)) if losses else 0
    total_pnl = sum(pnls)
    profit_factor = (sum(wins) / abs(sum(losses))) if losses else 0

    # Win rate by setup
    setup_wins: Dict[str, List[float]] = {}
    for trade, signal in rows:
        setup = signal.strategy
        if setup not in setup_wins:
            setup_wins[setup] = []
        setup_wins[setup].append(1.0 if (trade.net_pnl or 0) > 0 else 0.0)

    win_rate_by_setup = {
        k: round(sum(v) / len(v) * 100, 1) for k, v in setup_wins.items()
    }

    return {
        "total_trades": total_trades,
        "win_rate": round(win_rate, 1),
        "avg_profit": round(avg_profit, 2),
        "avg_loss": round(avg_loss, 2),
        "profit_factor": round(profit_factor, 2),
        "sharpe_ratio": 0,
        "max_drawdown": round(min(pnls) if pnls else 0, 2),
        "total_pnl": round(total_pnl, 2),
        "win_rate_by_setup": win_rate_by_setup,
        "avg_rr_achieved": 0,
        "best_trade": None,
        "worst_trade": None,
        "daily_pnl": [],
    }


# ── GET /api/settings ──────────────────────────────────────────────────
# Already handled by dashboard_api.py, but add PATCH support

@router.patch("/api/settings")
async def patch_settings() -> Dict[str, Any]:
    """Return current settings (PATCH accepted but changes are in-memory only)."""
    return {
        "capital": settings.capital,
        "risk_per_trade": settings.risk_per_trade_pct,
        "max_positions": settings.max_open_positions,
        "preferred_setups": ["MOMENTUM", "BREAKOUT", "SWING"],
        "min_score": 35,
        "auto_refresh_interval": 60,
        "notifications_enabled": False,
        "paper_trading": True,
    }


# ── POST /api/scan/trigger ─────────────────────────────────────────────
# Manual scan trigger endpoint

@router.post("/api/scan/trigger")
async def trigger_scan() -> Dict[str, Any]:
    """Manually trigger a full scan. Useful for testing."""
    import asyncio
    try:
        from backend.modules.scanner import run_full_scan
        summary = await run_full_scan()
        return {"status": "ok", "summary": summary}
    except Exception as e:
        return {"status": "error", "error": str(e)}
