"""
ETF Picks API
=============
Endpoints for ETF-specific scoring and picks, using the 5-factor ETF model.
"""
from __future__ import annotations

import datetime as dt
import logging
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings, pick_count_for_capital
from backend.database import get_db
from backend.models import RegimeSnapshot
from backend.modules.etf_scanner import (
    ETF_DEFAULT_WEIGHTS,
    scan_etf_universe,
)
from backend.modules.etf_universe import ETF_UNIVERSE

logger = logging.getLogger(__name__)

router = APIRouter(tags=["etf"])


@router.get("/api/etf-picks")
async def get_etf_picks(
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Return scored ETF picks using the 5-factor ETF model."""

    # Get current regime
    regime_result = await db.execute(
        select(RegimeSnapshot).order_by(desc(RegimeSnapshot.timestamp)).limit(1)
    )
    regime_snap = regime_result.scalar_one_or_none()

    # Map regime label
    label_map = {
        "TREND_UP": "TRENDING_UP", "TREND_DOWN": "TRENDING_DOWN",
        "RANGE_CHOP": "RANGE_BOUND", "HIGH_VOL_EVENT": "HIGH_VOL",
        "GAP_AND_GO": "RISK_ON", "GAP_FILL": "RANGE_BOUND",
        "LOW_LIQ_DRIFT": "EXHAUSTION",
        "trend_up": "TRENDING_UP", "trend_down": "TRENDING_DOWN",
        "range_chop": "RANGE_BOUND", "high_vol_event": "HIGH_VOL",
        "gap_and_go": "RISK_ON", "gap_fill": "RANGE_BOUND",
        "low_liq_drift": "EXHAUSTION",
    }

    regime_label = "RANGE_BOUND"
    regime_modifier = 1.0
    if regime_snap:
        regime_label = label_map.get(regime_snap.regime_label, regime_snap.regime_label)

    scoring_mults = {
        "TRENDING_UP": 1.1, "TRENDING_DOWN": 0.7, "RANGE_BOUND": 0.9,
        "HIGH_VOL": 0.6, "RISK_ON": 1.15, "RISK_OFF": 0.65,
        "EXHAUSTION": 0.75,
    }
    regime_modifier = scoring_mults.get(regime_label, 1.0)

    # Scan ETFs
    try:
        raw_picks = await scan_etf_universe(
            regime_label=regime_label,
            regime_modifier=regime_modifier,
        )
    except Exception as exc:
        logger.exception("ETF scan failed: %s", exc)
        raw_picks = []

    # Dynamic pick count (ETFs get slightly fewer than stocks)
    n_picks = max(3, pick_count_for_capital(settings.capital) - 2)

    # Build response picks with capital-based sizing
    all_picks: List[Dict[str, Any]] = []
    for pick in raw_picks:
        # Skip if a single unit exceeds 30% of capital
        if pick.ltp > settings.capital * 0.30:
            continue

        # Position sizing
        risk = pick.entry - pick.stop_loss
        if risk > 0:
            confidence = min(pick.score / 100, 0.95)
            base_qty = max(1, int((settings.capital * settings.risk_per_trade_pct / 100) / risk))
            qty = max(1, int(base_qty * (0.5 + 0.5 * confidence)))
        else:
            qty = max(1, int(settings.capital * 0.05 / max(pick.ltp, 1)))

        capital_needed = round(pick.ltp * qty, 2)

        all_picks.append({
            "symbol": pick.symbol,
            "name": pick.name,
            "category": pick.category,
            "ltp": pick.ltp,
            "nav": pick.nav,
            "nav_discount_pct": pick.nav_discount_pct,
            "spread_pct": pick.spread_pct,
            "volume": pick.volume,
            "avg_volume": pick.avg_volume,
            "score": pick.score,
            "breakdown": {
                "nav_discount": pick.breakdown.nav_discount,
                "spread_liquidity": pick.breakdown.spread_liquidity,
                "regime_alignment": pick.breakdown.regime_alignment,
                "fii_dii_flow": pick.breakdown.fii_dii_flow,
                "time_of_day": pick.breakdown.time_of_day,
            },
            "bias": pick.bias,
            "entry": pick.entry,
            "stop_loss": pick.stop_loss,
            "target": pick.target,
            "qty": qty,
            "capital_needed": capital_needed,
            "fits_budget": capital_needed <= settings.capital,
            "net_rr": pick.net_rr,
            "notes": pick.notes,
        })

    top_picks = all_picks[:n_picks]
    stretch_picks = all_picks[n_picks:n_picks * 2]

    # Advisory
    advisory = _build_etf_advisory(top_picks, settings.capital, n_picks, regime_label)

    return {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "trade_for": dt.datetime.now(dt.timezone.utc).strftime("%A %d %b %Y"),
        "universe_size": sum(len(etfs) for etfs in ETF_UNIVERSE.values()),
        "scored": len(raw_picks),
        "weights": ETF_DEFAULT_WEIGHTS,
        "top_picks": top_picks,
        "stretch_picks": stretch_picks,
        "advisory": advisory,
        "recommended_pick_count": n_picks,
        "regime": regime_label,
        "disclaimer": (
            "PAPER TRADING ONLY. ETF picks are educational, generated by a "
            "5-factor scoring model (NAV discount, spread, regime, flows, time). "
            "Always verify with your broker's data before trading."
        ),
    }


def _build_etf_advisory(
    picks: List[Dict],
    capital: float,
    n_picks: int,
    regime_label: str,
) -> List[str]:
    """Generate advisory text for ETF picks."""
    lines: List[str] = []

    lines.append(
        f"ETF picks scaled for Rs {capital:,.0f} capital ({n_picks} picks)."
    )

    # Regime context for ETFs
    regime_advice = {
        "TRENDING_UP": "Broad index ETFs (NIFTYBEES, BANKBEES) are favoured in uptrends.",
        "TRENDING_DOWN": "Consider defensive ETFs (GOLDBEES, LIQUIDBEES) in downtrends.",
        "RANGE_BOUND": "Sector ETFs may offer rotation opportunities in range-bound markets.",
        "HIGH_VOL": "Stick to liquid ETFs (NIFTYBEES, LIQUIDBEES) during high volatility.",
        "RISK_ON": "Broad market ETFs track risk-on sentiment well.",
        "RISK_OFF": "Gold and liquid ETFs are safer during risk-off periods.",
        "EXHAUSTION": "Reduce ETF position sizes in exhaustion regimes.",
    }
    if regime_label in regime_advice:
        lines.append(regime_advice[regime_label])

    # NAV discount opportunities
    discounted = [p for p in picks if p.get("nav_discount_pct", 0) > 0.2]
    if discounted:
        syms = ", ".join(p["symbol"] for p in discounted[:3])
        lines.append(f"NAV discount opportunity: {syms}")

    # Wide spread warnings
    wide_spread = [p for p in picks if p.get("spread_pct", 0) > 0.30]
    if wide_spread:
        syms = ", ".join(p["symbol"] for p in wide_spread[:3])
        lines.append(f"Wide spread warning: {syms} - use limit orders only")

    return lines
