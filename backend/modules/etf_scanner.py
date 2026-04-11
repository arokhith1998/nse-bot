"""
etf_scanner.py
==============
ETF-specific scoring engine with 5 factors designed for ETF intraday trading.

Unlike stocks (which use trend/momentum/breakout/volatility/volume/news),
ETF scoring is built around arbitrage-adjacent mean reversion and flow-following:

  1. NAV discount/premium  (~35%) - core mean-reversion signal
  2. Spread & liquidity    (~20%) - tighter spread + higher volume = better
  3. Regime alignment      (~25%) - sector/index regime context
  4. FII/DII flow          (~15%) - institutional flow as directional bias
  5. Time-of-day liquidity ( ~5%) - penalize midday dead zone

No RSI, Stochastic, Bollinger Bands, breakout proximity, or gap% - those are
stock-picking tools. ETF intraday is about arbitrage-adjacent mean reversion
and flow-following.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default ETF weights
# ---------------------------------------------------------------------------

ETF_DEFAULT_WEIGHTS: Dict[str, float] = {
    "nav_discount": 0.35,
    "spread_liquidity": 0.20,
    "regime_alignment": 0.25,
    "fii_dii_flow": 0.15,
    "time_of_day": 0.05,
}

# Per-category weight adjustments (multiply base weight)
_CATEGORY_WEIGHT_MODS: Dict[str, Dict[str, float]] = {
    "broad_index": {
        "nav_discount": 1.0,
        "spread_liquidity": 1.0,
        "regime_alignment": 1.2,  # broad market ETFs track regime closely
        "fii_dii_flow": 1.3,      # FII/DII most relevant for Nifty/Bank ETFs
        "time_of_day": 1.0,
    },
    "sector": {
        "nav_discount": 1.1,
        "spread_liquidity": 0.9,
        "regime_alignment": 1.3,  # sector rotation is key
        "fii_dii_flow": 0.8,
        "time_of_day": 1.0,
    },
    "commodity": {
        "nav_discount": 1.2,       # gold/silver ETFs can have persistent premium
        "spread_liquidity": 1.0,
        "regime_alignment": 0.7,   # less tied to equity regime
        "fii_dii_flow": 0.5,       # FII/DII less relevant for gold
        "time_of_day": 1.2,
    },
    "liquid_bond": {
        "nav_discount": 0.5,       # near-zero NAV deviation
        "spread_liquidity": 1.5,   # spread is everything for liquid ETFs
        "regime_alignment": 0.3,
        "fii_dii_flow": 0.3,
        "time_of_day": 1.5,        # time matters a lot for near-zero-vol instruments
    },
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ETFScoreBreakdown:
    nav_discount: float = 0.0
    spread_liquidity: float = 0.0
    regime_alignment: float = 0.0
    fii_dii_flow: float = 0.0
    time_of_day: float = 0.0


@dataclass
class ETFPick:
    symbol: str
    name: str
    category: str
    ltp: float = 0.0
    nav: float = 0.0
    nav_discount_pct: float = 0.0
    spread_pct: float = 0.0
    volume: int = 0
    avg_volume: int = 0
    score: float = 0.0
    breakdown: ETFScoreBreakdown = field(default_factory=ETFScoreBreakdown)
    bias: str = "LONG"
    entry: float = 0.0
    stop_loss: float = 0.0
    target: float = 0.0
    qty: int = 0
    capital_needed: float = 0.0
    fits_budget: bool = True
    net_rr: float = 0.0
    notes: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Scoring functions
# ---------------------------------------------------------------------------

def score_nav_discount(ltp: float, nav: float) -> float:
    """Score based on NAV discount/premium.

    A discount (LTP < NAV) is a buy signal for mean-reversion.
    Returns 0-100 where higher = better opportunity.
    """
    if nav <= 0 or ltp <= 0:
        return 50.0  # neutral if we can't compute

    discount_pct = ((nav - ltp) / nav) * 100

    # Strong discount (>0.5%) = very bullish
    # Small discount (0.1-0.5%) = mildly bullish
    # At NAV = neutral
    # Premium (LTP > NAV) = bearish for long
    if discount_pct >= 1.0:
        return min(95, 70 + discount_pct * 25)
    elif discount_pct >= 0.5:
        return 65 + (discount_pct - 0.5) * 10
    elif discount_pct >= 0.1:
        return 55 + (discount_pct - 0.1) * 25
    elif discount_pct >= -0.1:
        return 50  # at NAV
    elif discount_pct >= -0.5:
        return 40 + (discount_pct + 0.5) * 25
    else:
        return max(10, 30 + discount_pct * 10)


def score_spread_liquidity(
    spread_pct: float,
    volume: int,
    avg_volume: int,
) -> float:
    """Score based on bid-ask spread tightness and volume.

    Tighter spread + higher volume = better tradability.
    """
    # Spread score (0-50): < 0.05% is excellent, > 0.5% is poor
    if spread_pct <= 0.02:
        spread_score = 50
    elif spread_pct <= 0.05:
        spread_score = 45
    elif spread_pct <= 0.10:
        spread_score = 35
    elif spread_pct <= 0.20:
        spread_score = 25
    elif spread_pct <= 0.50:
        spread_score = 15
    else:
        spread_score = 5

    # Volume score (0-50): relative to average
    if avg_volume <= 0:
        vol_score = 25  # neutral
    else:
        vol_ratio = volume / avg_volume
        if vol_ratio >= 2.0:
            vol_score = 50
        elif vol_ratio >= 1.5:
            vol_score = 42
        elif vol_ratio >= 1.0:
            vol_score = 35
        elif vol_ratio >= 0.5:
            vol_score = 20
        else:
            vol_score = 10

    return spread_score + vol_score


def score_regime_alignment(
    category: str,
    regime_label: str,
    regime_modifier: float = 1.0,
) -> float:
    """Score based on how well the ETF category aligns with current regime.

    Broad index ETFs love trending markets.
    Sector ETFs love rotation plays.
    Commodity ETFs are somewhat regime-independent.
    """
    # Base regime scores by label
    regime_scores: Dict[str, Dict[str, float]] = {
        "broad_index": {
            "TRENDING_UP": 85, "RISK_ON": 80, "RANGE_BOUND": 50,
            "TRENDING_DOWN": 30, "RISK_OFF": 25, "HIGH_VOL": 35,
            "EXHAUSTION": 40,
        },
        "sector": {
            "TRENDING_UP": 75, "RISK_ON": 80, "RANGE_BOUND": 55,
            "TRENDING_DOWN": 40, "RISK_OFF": 35, "HIGH_VOL": 45,
            "EXHAUSTION": 35,
        },
        "commodity": {
            "TRENDING_UP": 55, "RISK_ON": 50, "RANGE_BOUND": 60,
            "TRENDING_DOWN": 65, "RISK_OFF": 75, "HIGH_VOL": 60,
            "EXHAUSTION": 55,
        },
        "liquid_bond": {
            "TRENDING_UP": 40, "RISK_ON": 35, "RANGE_BOUND": 60,
            "TRENDING_DOWN": 70, "RISK_OFF": 80, "HIGH_VOL": 55,
            "EXHAUSTION": 65,
        },
    }

    cat_scores = regime_scores.get(category, regime_scores["broad_index"])
    base = cat_scores.get(regime_label, 50.0)

    # Apply regime modifier (from regime engine)
    return min(100, max(0, base * regime_modifier))


def score_fii_dii_flow(
    fii_net: float,
    dii_net: float,
    category: str,
) -> float:
    """Score based on FII/DII net flow direction.

    Positive FII = bullish for broad market ETFs.
    Positive DII = bullish, but often contra-FII.
    Combined positive = strong signal.
    """
    # For commodity/bond ETFs, flows are less relevant
    if category in ("commodity", "liquid_bond"):
        return 50.0  # neutral

    # Combined flow signal
    combined = fii_net + dii_net

    # Score: big positive flow = bullish, big negative = bearish
    if combined > 5000:       # Rs 5000 crore+ net inflow
        return 85
    elif combined > 2000:
        return 75
    elif combined > 500:
        return 65
    elif combined > -500:
        return 50  # neutral
    elif combined > -2000:
        return 35
    elif combined > -5000:
        return 25
    else:
        return 15

    # FII direction matters more for broad index
    # (already handled by category weight mods)


def score_time_of_day() -> float:
    """Score based on current time of day (IST).

    Opening (9:15-10:00) and closing (2:30-3:30) windows have better liquidity.
    Midday (12:00-1:30) is a dead zone for ETFs.
    """
    from datetime import timezone, timedelta
    ist = timezone(timedelta(hours=5, minutes=30))
    now = datetime.now(ist)
    hour = now.hour
    minute = now.minute
    time_mins = hour * 60 + minute

    # Pre-market / post-market
    if time_mins < 555 or time_mins > 930:  # before 9:15 or after 15:30
        return 30  # market closed

    # Opening window (9:15-10:00) - best liquidity
    if 555 <= time_mins <= 600:
        return 85

    # Morning session (10:00-12:00) - good
    if 600 < time_mins <= 720:
        return 70

    # Midday dead zone (12:00-13:30) - poor ETF liquidity
    if 720 < time_mins <= 810:
        return 35

    # Afternoon pickup (13:30-14:30)
    if 810 < time_mins <= 870:
        return 60

    # Closing window (14:30-15:30) - excellent
    if 870 < time_mins <= 930:
        return 80

    return 50


# ---------------------------------------------------------------------------
# Main scoring function
# ---------------------------------------------------------------------------

def score_etf(
    symbol: str,
    name: str,
    category: str,
    ltp: float,
    nav: float,
    spread_pct: float,
    volume: int,
    avg_volume: int,
    regime_label: str = "RANGE_BOUND",
    regime_modifier: float = 1.0,
    fii_net: float = 0.0,
    dii_net: float = 0.0,
    weights: Optional[Dict[str, float]] = None,
) -> ETFPick:
    """Score a single ETF and return an ETFPick."""
    w = weights or ETF_DEFAULT_WEIGHTS.copy()

    # Apply category weight modifications
    cat_mods = _CATEGORY_WEIGHT_MODS.get(category, {})
    adjusted_w = {}
    for factor, base_weight in w.items():
        mod = cat_mods.get(factor, 1.0)
        adjusted_w[factor] = base_weight * mod

    # Normalize so weights sum to 1
    total_w = sum(adjusted_w.values())
    if total_w > 0:
        adjusted_w = {k: v / total_w for k, v in adjusted_w.items()}

    # Score each factor
    nav_score = score_nav_discount(ltp, nav)
    spread_score = score_spread_liquidity(spread_pct, volume, avg_volume)
    regime_score = score_regime_alignment(category, regime_label, regime_modifier)
    flow_score = score_fii_dii_flow(fii_net, dii_net, category)
    time_score = score_time_of_day()

    breakdown = ETFScoreBreakdown(
        nav_discount=round(nav_score, 1),
        spread_liquidity=round(spread_score, 1),
        regime_alignment=round(regime_score, 1),
        fii_dii_flow=round(flow_score, 1),
        time_of_day=round(time_score, 1),
    )

    # Weighted composite score
    composite = (
        adjusted_w.get("nav_discount", 0) * nav_score
        + adjusted_w.get("spread_liquidity", 0) * spread_score
        + adjusted_w.get("regime_alignment", 0) * regime_score
        + adjusted_w.get("fii_dii_flow", 0) * flow_score
        + adjusted_w.get("time_of_day", 0) * time_score
    )

    # Liquidity gate: if spread is too wide, cap score
    if spread_pct > 0.50:
        composite = min(composite, 40)

    # Volume gate: if volume is very low, cap score
    if volume < 1000:
        composite = min(composite, 35)

    # Determine bias and levels
    nav_discount_pct = ((nav - ltp) / nav * 100) if nav > 0 else 0
    bias = "LONG" if nav_discount_pct > -0.2 else "SHORT"

    # Entry/SL/Target based on NAV reversion
    if nav > 0:
        entry = ltp
        # SL: 0.3% below LTP for liquid ETFs, wider for others
        sl_pct = 0.003 if category in ("broad_index", "liquid_bond") else 0.005
        stop_loss = round(entry * (1 - sl_pct), 2)
        # Target: revert toward NAV, or 0.3% above for liquid
        if abs(nav_discount_pct) > 0.1:
            target = round(nav, 2)
        else:
            target = round(entry * (1 + sl_pct * 1.5), 2)
    else:
        entry = ltp
        stop_loss = round(ltp * 0.995, 2)
        target = round(ltp * 1.005, 2)

    risk = entry - stop_loss
    reward = target - entry
    rr = round(reward / risk, 2) if risk > 0 else 0

    # Notes
    notes: List[str] = []
    if nav_discount_pct > 0.3:
        notes.append(f"Trading at {nav_discount_pct:.2f}% discount to NAV - reversion likely")
    elif nav_discount_pct < -0.3:
        notes.append(f"Trading at {abs(nav_discount_pct):.2f}% premium to NAV - caution")
    if spread_pct < 0.05:
        notes.append("Tight spread - good execution expected")
    elif spread_pct > 0.30:
        notes.append("Wide spread - execution risk, use limit orders")
    if volume > avg_volume * 1.5 and avg_volume > 0:
        notes.append(f"Volume {volume/avg_volume:.1f}x above average")

    return ETFPick(
        symbol=symbol,
        name=name,
        category=category,
        ltp=round(ltp, 2),
        nav=round(nav, 2),
        nav_discount_pct=round(nav_discount_pct, 2),
        spread_pct=round(spread_pct, 4),
        volume=volume,
        avg_volume=avg_volume,
        score=round(composite, 1),
        breakdown=breakdown,
        bias=bias,
        entry=round(entry, 2),
        stop_loss=stop_loss,
        target=target,
        qty=0,  # filled by API layer based on capital
        capital_needed=0,
        fits_budget=True,
        net_rr=rr,
        notes=notes,
    )


# ---------------------------------------------------------------------------
# Scan all ETFs
# ---------------------------------------------------------------------------

async def scan_etf_universe(
    regime_label: str = "RANGE_BOUND",
    regime_modifier: float = 1.0,
    fii_net: float = 0.0,
    dii_net: float = 0.0,
) -> List[ETFPick]:
    """Scan all ETFs in the universe and return scored picks.

    Uses yfinance for price data. NAV is approximated from previous close
    (true iNAV would require NSE's real-time iNAV feed which isn't publicly
    available via free APIs).
    """
    from backend.modules.etf_universe import ETF_UNIVERSE, ETFCategory
    from backend.modules.market_data_provider import CompositeProvider

    provider = CompositeProvider()
    picks: List[ETFPick] = []

    category_map = {
        ETFCategory.BROAD_INDEX: "broad_index",
        ETFCategory.SECTOR: "sector",
        ETFCategory.COMMODITY: "commodity",
        ETFCategory.LIQUID_BOND: "liquid_bond",
    }

    for cat, etfs in ETF_UNIVERSE.items():
        cat_str = category_map.get(cat, "broad_index")
        for etf_info in etfs:
            symbol = etf_info["symbol"]
            name = etf_info["name"]

            try:
                quote = provider.get_quote(symbol)
                if quote is None or quote.ltp <= 0:
                    continue

                # Get history for avg volume
                hist = provider.get_history(symbol, days=20, interval="1d")
                avg_vol = 0
                if hist is not None and "Volume" in hist.columns and len(hist) > 5:
                    avg_vol = int(hist["Volume"].mean())

                # NAV approximation: use previous close as proxy for iNAV
                # Real iNAV would come from AMC/NSE feed
                nav_approx = quote.close if quote.close > 0 else quote.ltp

                # Spread from bid/ask
                spread = 0.0
                if quote.bid > 0 and quote.ask > 0:
                    spread = (quote.ask - quote.bid) / quote.ltp * 100
                elif quote.ltp > 0:
                    # Estimate spread from daily range if no bid/ask
                    if quote.high > 0 and quote.low > 0:
                        spread = min(0.5, (quote.high - quote.low) / quote.ltp * 100 * 0.1)
                    else:
                        spread = 0.15  # default estimate

                pick = score_etf(
                    symbol=symbol,
                    name=name,
                    category=cat_str,
                    ltp=quote.ltp,
                    nav=nav_approx,
                    spread_pct=spread,
                    volume=quote.volume,
                    avg_volume=avg_vol,
                    regime_label=regime_label,
                    regime_modifier=regime_modifier,
                    fii_net=fii_net,
                    dii_net=dii_net,
                )
                picks.append(pick)

            except Exception as exc:
                logger.warning("ETF scan failed for %s: %s", symbol, exc)
                continue

    # Sort by score descending
    picks.sort(key=lambda p: p.score, reverse=True)
    logger.info("ETF scan complete: %d ETFs scored", len(picks))
    return picks
