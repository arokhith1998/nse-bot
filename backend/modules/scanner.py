"""
NSE Market Intelligence Platform - Scanner Module
==================================================
Orchestrates the full scan pipeline: regime detection, news fetching,
stock universe scanning, indicator computation, and signal generation.
Saves all results to the database.

Incorporates expert intraday trader review improvements:
- Regime-aware strategy gating
- Structural stops (max of day_low, sma20-0.25*ATR, prev_close*0.985)
- EV-positive gate on every pick
- Breadth gate on longs
- Time-of-day bucketing with strategy multipliers
- Tightened liquidity gates (ADV >= 5 Cr, circuit filter)
- Capital tier gating
- Scale-out levels (1R/1.5R/2R)
- Improved slippage model (spread + impact + illiquidity premium)
- Continuous news scoring with negative-news block
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import math
import traceback
from typing import Dict, List, Optional, Set, Tuple

import pytz

from backend.config import settings, pick_count_for_capital
from backend.database import AsyncSessionLocal
from backend.models import (
    NewsItem as NewsItemModel,
    RegimeSnapshot,
    Signal,
    Trade,
    WeightsHistory,
)
from backend.services.cost_model import groww_intraday_cost, estimate_slippage

logger = logging.getLogger(__name__)

IST = pytz.timezone("Asia/Kolkata")

# Singleton intraday manager reference (set by scheduler on startup)
_intraday_mgr = None

def set_intraday_manager(mgr) -> None:
    """Called by scheduler to register the global IntraDayManager instance."""
    global _intraday_mgr
    _intraday_mgr = mgr

def _get_intraday_manager():
    """Return the global IntraDayManager, or None if not started."""
    return _intraday_mgr

# Default scoring weights
DEFAULT_WEIGHTS: Dict[str, float] = {
    "trend": 0.25,
    "momentum": 0.20,
    "volume": 0.15,
    "breakout": 0.15,
    "volatility": 0.10,
    "news": 0.15,
}

# ─── Regime-aware strategy gating (Review Item 2) ─────────────────────

# Maps regime_label -> set of allowed strategies.
# Strategies not in the allowed set are vetoed for that regime.
REGIME_ALLOWED_STRATEGIES: Dict[str, Set[str]] = {
    "trend_up":       {"BREAKOUT", "MOMENTUM", "GAP_AND_GO", "SWING", "RANGE_PLAY"},
    "trend_down":     {"MEAN_REVERSION"},
    "range_chop":     {"MEAN_REVERSION", "SWING", "RANGE_PLAY"},  # V5-3: + RANGE_PLAY
    "high_vol_event": {"SWING"},
    "low_liq_drift":  {"SWING", "RANGE_PLAY"},
    "gap_and_go":     {"GAP_AND_GO", "MOMENTUM"},
    "gap_fill":       {"MEAN_REVERSION", "SWING", "RANGE_PLAY"},
    "unknown":        {"MEAN_REVERSION", "SWING", "RANGE_PLAY"},  # V5-3: + RANGE_PLAY
}

# Regime-level sizing multipliers (e.g. reduced sizing in volatile regimes)
REGIME_SIZE_MULT: Dict[str, float] = {
    "trend_up":       1.0,
    "trend_down":     0.7,
    "range_chop":     0.9,
    "high_vol_event": 0.5,
    "low_liq_drift":  0.3,
    "gap_and_go":     1.0,
    "gap_fill":       0.85,
    "unknown":        0.7,  # conservative sizing on bad data
}

# ─── Time-of-day buckets (Review Item 12) ──────────────────────────────

def _time_of_day_multiplier(strategy: str) -> Tuple[float, str]:
    """Return (multiplier, bucket_name) for the current IST time and strategy.

    Buckets:
      09:15-09:30  Opening volatility - only MOMENTUM, mult 0.6
      09:30-11:00  Prime breakout window - BREAKOUT/MOMENTUM favored, mult 1.0
      11:00-13:30  Midday range - MEAN_REVERSION/SWING favored, BREAKOUT*0.3
      13:30-14:45  Afternoon trend - BREAKOUT if trend holds, mult 0.9
      After 14:45  No new picks (mult 0.0)
    """
    now_ist = dt.datetime.now(IST)
    t = now_ist.time()

    if t < dt.time(9, 15):
        # Cannot score live intraday features on a market that hasn't opened.
        # Pre-market scan uses status="watchlist" via _save_signals.
        return (0.0, "pre_market")
    elif t < dt.time(9, 30):
        # Opening volatility: only MOMENTUM allowed
        if strategy == "MOMENTUM":
            return (0.6, "opening_vol")
        return (0.0, "opening_vol")
    elif t < dt.time(11, 0):
        # Prime window: BREAKOUT and MOMENTUM favored
        if strategy in ("BREAKOUT", "MOMENTUM"):
            return (1.0, "prime_window")
        return (0.8, "prime_window")
    elif t < dt.time(13, 30):
        # Midday range: MEAN_REVERSION and SWING favored
        if strategy in ("MEAN_REVERSION", "SWING"):
            return (1.0, "midday_range")
        if strategy == "BREAKOUT":
            return (0.3, "midday_range")
        return (0.7, "midday_range")
    elif t < dt.time(14, 45):
        # Afternoon trend
        return (0.9, "afternoon_trend")
    else:
        # No new picks after 14:45 IST — MIS square-off at 15:15,
        # insufficient time to reach 1.5R through widening spreads.
        # The don't-expire-on-empty logic in _save_signals prevents UI-flicker.
        return (0.0, "late_session")


# ─── Improved slippage model (Review Item 6) ───────────────────────────

def _estimate_slippage(price: float, qty: int, adv_shares: float, adv_rupees: float) -> float:
    """Estimate total one-way slippage cost in INR.

    Components:
      1. Spread cost: half the estimated bid-ask spread
      2. Market impact: sqrt-law participation impact
      3. Illiquidity premium: extra cost for thinly traded names (ADV < 5 Cr)

    Returns the total slippage cost in INR (NOT percentage).
    """
    spread_bps = max(5, 1000 / price)
    spread_cost = 0.5 * (spread_bps / 10_000) * price * qty
    impact = 0.1 * math.sqrt(qty / max(adv_shares, 1)) * price * qty
    illiquidity_premium = (price * qty * 0.002) if adv_rupees < 5_00_00_000 else 0
    return spread_cost + impact + illiquidity_premium


# ─── Capital tier gating (Review Item 15) ──────────────────────────────

def _capital_tier(capital: float) -> Tuple[int, float]:
    """Return (max_picks, min_adv_rupees) based on capital.

    Smaller accounts are restricted to fewer, more liquid picks.
    """
    if capital < 10_000:
        return (2, 50_00_00_000)    # max 2 picks, ADV >= 50 Cr
    elif capital < 25_000:
        return (3, 25_00_00_000)    # max 3 picks, ADV >= 25 Cr
    elif capital < 50_000:
        return (4, 5_00_00_000)     # max 4 picks, ADV >= 5 Cr
    else:
        return (settings.max_open_positions * 2, 5_00_00_000)


# ─── Regime Scan ────────────────────────────────────────────────────────

async def run_regime_scan() -> Optional[Dict]:
    """Run the regime engine and save a snapshot to the database.

    Returns the regime data dict or None on failure.
    """
    logger.info("[scanner] Running regime scan...")
    try:
        # RegimeEngine is synchronous (uses yfinance), run in thread
        regime_data = await asyncio.to_thread(_classify_regime)
        if regime_data is None:
            logger.warning("[scanner] Regime classification returned None")
            return None

        # V4-1 + V5-2: Detect garbage data at the WRITE path.
        # Only store UNKNOWN if BOTH VIX and breadth are unavailable (both fallbacks).
        # A single fallback is acceptable — the regime_engine decision tree already
        # skips VIX-dependent branches when VIX is fallback.
        vix_val = regime_data.get("vix", 0.0)
        breadth_val = regime_data.get("breadth_pct", 50.0)
        notes = regime_data.get("notes", "") or ""
        vix_is_fallback = "vix_fallback" in notes or (vix_val is None or vix_val <= 0.5)
        breadth_is_fallback = "breadth_fallback" in notes
        breadth_zero = breadth_val is None or breadth_val == 0

        if (vix_is_fallback and breadth_is_fallback) or breadth_zero:
            logger.warning(
                "[regime] WARN: VIX=%.1f (fallback=%s) breadth=%.1f (fallback=%s) "
                "— both feeds unavailable, storing as UNKNOWN",
                vix_val or 0, vix_is_fallback, breadth_val or 0, breadth_is_fallback,
            )
            regime_data["label"] = "unknown"
            regime_data["sub_regime"] = "bad_data"
            regime_data["confidence"] = 0.0

        # Save to database
        async with AsyncSessionLocal() as session:
            snapshot = RegimeSnapshot(
                timestamp=dt.datetime.now(dt.timezone.utc),
                vix=regime_data.get("vix", 0.0),
                advance_decline=regime_data.get("advance_decline", 1.0),
                breadth_pct=regime_data.get("breadth_pct", 50.0),
                nifty_trend=regime_data.get("nifty_trend", "sideways"),
                bank_nifty_trend=regime_data.get("bank_nifty_trend", "sideways"),
                regime_label=regime_data.get("label", "RANGE_CHOP"),
                sub_regime=regime_data.get("sub_regime"),
                confidence=regime_data.get("confidence", 0.5),
                nifty_close=regime_data.get("nifty_close", 0.0),
                nifty_change_pct=regime_data.get("nifty_change_pct", 0.0),
                sensex_close=regime_data.get("sensex_close", 0.0),
                sensex_change_pct=regime_data.get("sensex_change_pct", 0.0),
            )
            session.add(snapshot)
            await session.commit()
            regime_data["id"] = snapshot.id
            logger.info("[scanner] Regime snapshot saved: %s (confidence=%.2f)",
                       regime_data.get("label"), regime_data.get("confidence", 0))
        return regime_data
    except Exception:
        logger.exception("[scanner] Regime scan failed")
        return None


def _classify_regime() -> Optional[Dict]:
    """Synchronous regime classification wrapper."""
    try:
        from backend.modules.regime_engine import RegimeEngine
        import yfinance as yf

        engine = RegimeEngine()
        state = engine.classify()

        # Convert RegimeState to dict
        if hasattr(state, '__dict__'):
            data = {}
            data["label"] = getattr(state, 'label', 'RANGE_CHOP')
            if hasattr(state.label, 'value'):
                data["label"] = state.label.value
            elif hasattr(state.label, 'name'):
                data["label"] = state.label.name
            else:
                data["label"] = str(state.label)
            data["sub_regime"] = getattr(state, 'sub_regime', None)
            data["confidence"] = getattr(state, 'confidence', 0.5)
            data["vix"] = getattr(state, 'vix', 0.0)
            data["nifty_price"] = getattr(state, 'nifty_price', 0.0)
            data["ema20"] = getattr(state, 'ema20', 0.0)
            data["ema50"] = getattr(state, 'ema50', 0.0)
            data["adx"] = getattr(state, 'adx', 0.0)
            data["breadth_pct"] = getattr(state, 'breadth_pct', 50.0)
            data["gap_pct"] = getattr(state, 'gap_pct', 0.0)
            data["volume_ratio"] = getattr(state, 'volume_ratio', 1.0)
            data["advance_decline"] = getattr(state, 'advance_decline', 1.0)
            data["scoring_adjustments"] = getattr(state, 'scoring_adjustments', {})
            # V5-1/V5-2: carry data-quality notes through for UNKNOWN detection
            data["notes"] = getattr(state, 'notes', '') or ''

            # Derive trends from price vs EMAs
            nifty = data["nifty_price"]
            ema20 = data["ema20"]
            ema50 = data["ema50"]
            if nifty > ema20 > ema50:
                data["nifty_trend"] = "up"
            elif nifty < ema20 < ema50:
                data["nifty_trend"] = "down"
            else:
                data["nifty_trend"] = "sideways"
            data["bank_nifty_trend"] = data["nifty_trend"]  # approximation

            # ── Fetch Nifty & Sensex prices ──────────────────────────
            try:
                idx = yf.download("^NSEI ^BSESN", period="5d",
                                  group_by="ticker", progress=False, threads=True)
                if idx is not None and not idx.empty:
                    # Nifty 50
                    try:
                        nifty_df = idx["^NSEI"].dropna()
                        if len(nifty_df) >= 2:
                            data["nifty_close"] = round(float(nifty_df["Close"].iloc[-1]), 2)
                            prev = float(nifty_df["Close"].iloc[-2])
                            data["nifty_change_pct"] = round(
                                ((data["nifty_close"] - prev) / prev) * 100, 2
                            ) if prev > 0 else 0.0
                        elif len(nifty_df) == 1:
                            data["nifty_close"] = round(float(nifty_df["Close"].iloc[-1]), 2)
                    except Exception:
                        logger.warning("[scanner] Could not parse Nifty index data")

                    # Sensex
                    try:
                        sensex_df = idx["^BSESN"].dropna()
                        if len(sensex_df) >= 2:
                            data["sensex_close"] = round(float(sensex_df["Close"].iloc[-1]), 2)
                            prev = float(sensex_df["Close"].iloc[-2])
                            data["sensex_change_pct"] = round(
                                ((data["sensex_close"] - prev) / prev) * 100, 2
                            ) if prev > 0 else 0.0
                        elif len(sensex_df) == 1:
                            data["sensex_close"] = round(float(sensex_df["Close"].iloc[-1]), 2)
                    except Exception:
                        logger.warning("[scanner] Could not parse Sensex index data")
            except Exception:
                logger.warning("[scanner] Index price fetch failed (non-fatal)")

            # If regime engine already got nifty price, use that as fallback
            if not data.get("nifty_close") and data["nifty_price"] > 0:
                data["nifty_close"] = round(data["nifty_price"], 2)

            return data
        return None
    except Exception:
        logger.exception("[scanner] _classify_regime error")
        return None


# ─── News Scan ──────────────────────────────────────────────────────────

async def run_news_scan() -> int:
    """Fetch news from RSS feeds and save to database.

    Returns the number of new news items saved.
    """
    logger.info("[scanner] Running news scan...")
    try:
        news_items = await asyncio.to_thread(_fetch_news)
        if not news_items:
            logger.info("[scanner] No new news items found")
            return 0

        count = 0
        async with AsyncSessionLocal() as session:
            for item in news_items:
                try:
                    news_row = NewsItemModel(
                        timestamp=dt.datetime.now(dt.timezone.utc),
                        symbol=item.get("symbol"),
                        headline=item.get("headline", ""),
                        source=item.get("source", "unknown"),
                        source_quality=item.get("source_quality", 0.5),
                        event_type=item.get("event_type"),
                        sentiment_score=item.get("sentiment", 0.0),
                        relevance_score=item.get("relevance", 0.0),
                        freshness_hours=item.get("freshness_hours", 0.0),
                        ticker_specificity=item.get("ticker_specificity", 0.0),
                        materiality=item.get("materiality", 0.0),
                        multi_source_count=item.get("multi_source_count", 1),
                        weighted_impact=item.get("weighted_impact", 0.0),
                    )
                    session.add(news_row)
                    count += 1
                except Exception:
                    logger.warning("[scanner] Failed to save news item: %s",
                                 item.get("headline", "")[:60])
            await session.commit()

        logger.info("[scanner] Saved %d news items", count)
        return count
    except Exception:
        logger.exception("[scanner] News scan failed")
        return 0


def _fetch_news() -> List[Dict]:
    """Synchronous news fetch wrapper."""
    try:
        from backend.modules.news_ranker import NewsRanker
        ranker = NewsRanker()
        ranked = ranker.fetch_all_news(force=True)

        items = []
        for news in ranked:
            item = {}
            if hasattr(news, '__dict__'):
                item["headline"] = getattr(news, 'headline', '')
                item["source"] = getattr(news, 'source', 'unknown')
                item["source_quality"] = getattr(news, 'source_quality', 0.5)
                item["sentiment"] = getattr(news, 'sentiment_magnitude', 0.0)
                item["freshness_hours"] = getattr(news, 'freshness_hours', 0.0)
                item["ticker_specificity"] = getattr(news, 'ticker_specificity', 0.0)
                item["materiality"] = getattr(news, 'materiality', 0.0)
                item["weighted_impact"] = getattr(news, 'weighted_impact', 0.0)
                item["multi_source_count"] = getattr(news, 'multi_source_count', 1)
                item["event_type"] = getattr(news, 'event_type', None)
                item["symbol"] = getattr(news, 'symbol', None)
                item["relevance"] = getattr(news, 'relevance_score',
                                           getattr(news, 'ticker_specificity', 0.0))
            elif isinstance(news, dict):
                item = news
            else:
                continue

            if item.get("headline"):
                items.append(item)

        return items
    except Exception:
        logger.exception("[scanner] _fetch_news error")
        return []


# ─── Stock Universe Scan ────────────────────────────────────────────────

# Universe management: two-phase scanning
# Pre-market scans the full watchlist (~200-300), caches top 100 for intraday
from backend.backtester.data_loader import NIFTY200_SYMBOLS, load_full_nse_universe

SCAN_UNIVERSE = list(NIFTY200_SYMBOLS)  # default, updated by pre-market scan
SCAN_UNIVERSE_TOP: List[str] = []       # top scorers from pre-market, used for intraday

# Module-level caches for news scores and sentiment (populated before each scan)
_news_score_cache: Dict[str, float] = {}
_news_sentiment_cache: Dict[str, float] = {}  # symbol -> sentiment (-1 to +1)

# Last scan veto breakdown (M6) — read by frontend_api for empty-state card
last_veto_breakdown: Dict[str, int] = {}
last_candidates_scanned: int = 0


async def _refresh_news_scores():
    """Load recent news items from DB and build symbol->score (0-100)
    and symbol->sentiment (-1 to +1) maps.

    Implements Review Item 10: continuous news scoring with negative-news gate.
    """
    global _news_score_cache, _news_sentiment_cache
    try:
        from sqlalchemy import select, func
        async with AsyncSessionLocal() as session:
            cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=24)
            result = await session.execute(
                select(
                    NewsItemModel.symbol,
                    func.max(NewsItemModel.weighted_impact),
                    func.avg(NewsItemModel.sentiment_score),
                )
                .where(NewsItemModel.timestamp >= cutoff)
                .where(NewsItemModel.symbol.isnot(None))
                .group_by(NewsItemModel.symbol)
            )
            rows = result.all()
            _news_score_cache.clear()
            _news_sentiment_cache.clear()
            for sym, impact, sentiment in rows:
                if sym:
                    sym_upper = sym.upper()
                    # weighted_impact is 0.0-1.0, scale to 0-100
                    _news_score_cache[sym_upper] = min(float(impact or 0) * 100, 100.0)
                    # sentiment_score: keep as-is (-1 to +1 range)
                    _news_sentiment_cache[sym_upper] = float(sentiment or 0)
            logger.info("[scanner] Loaded news scores for %d symbols", len(_news_score_cache))
    except Exception:
        logger.warning("[scanner] Failed to refresh news scores")


async def _save_signals(signals: List[Dict], regime_label: str,
                        signal_status: str = "pending") -> int:
    """Expire old signals of the same status and save new ones to DB.

    Applies capital tier gating (Review Item 15) and structural stops
    (Review Item 3) with scale-out levels (Review Item 4).

    Parameters
    ----------
    signal_status : str
        "pending" for live picks, "watchlist" for pre-market picks.
    """
    # Capital tier gating
    max_picks, min_adv = _capital_tier(settings.capital)
    base_picks = pick_count_for_capital(settings.capital)
    n_picks = min(base_picks, max_picks)

    # Only expire old signals if we have new ones to replace them
    if not signals:
        logger.info("[scanner] No new signals — keeping existing %s picks", signal_status)
        return 0

    async with AsyncSessionLocal() as session:
        from sqlalchemy import update
        await session.execute(
            update(Signal)
            .where(Signal.status == signal_status)
            .values(status="expired")
        )
        await session.commit()

    count = 0
    async with AsyncSessionLocal() as session:
        now = dt.datetime.now(dt.timezone.utc)

        for sig in signals[:n_picks * 2]:  # top + stretch
            try:
                price = sig.get("price", 0)
                atr = sig.get("atr", price * 0.02)
                if price <= 0:
                    continue

                # Capital tier: enforce minimum ADV for smaller accounts
                adv_rupees = sig.get("adv_rupees", 0)
                if adv_rupees < min_adv:
                    continue

                # ── Structural stops (Review Item 3) ──────────────────
                day_low = sig.get("day_low", price * 0.98)
                sma20 = sig.get("sma20", price)
                prev_close = sig.get("prev_close", price)

                stop = max(
                    day_low,
                    sma20 - 0.25 * atr,
                    prev_close * 0.985,
                )
                stop = round(stop, 2)

                # Sanity cap: reject if (entry - stop) > 2 * ATR (too noisy)
                risk = price - stop
                if risk <= 0:
                    continue
                if risk > 2 * atr:
                    logger.debug("[scanner] Rejecting %s: risk %.2f > 2*ATR %.2f",
                                 sig["symbol"], risk, 2 * atr)
                    continue

                # Size off the stop (Review Item 3)
                risk_amount = settings.capital * settings.risk_per_trade_pct / 100
                qty = max(1, int(risk_amount / risk))

                # Apply regime sizing multiplier
                regime_lower = regime_label.lower()
                size_mult = REGIME_SIZE_MULT.get(regime_lower, 1.0)
                qty = max(1, int(qty * size_mult))

                confidence = min(sig.get("score", 50) / 100, 0.95)
                pos_size_pct = (qty * price / settings.capital) * 100

                # ── Scale-out levels (Review Item 4) ──────────────────
                scale_out_1 = round(price + 1.0 * risk, 2)   # 1R - book 50%
                scale_out_2 = round(price + 1.5 * risk, 2)   # 1.5R - book 25%
                trail_from  = round(price + 2.0 * risk, 2)   # 2R - trail remaining 25%

                target1 = scale_out_1
                target2 = scale_out_2

                # Build explanation with scale-out info
                base_explanation = sig.get("explanation", "")
                ev_note = f"EV={sig.get('ev', 0):.1f}"
                scale_note = (f"Scale: 50% at {scale_out_1}, "
                              f"25% at {scale_out_2}, "
                              f"trail from {trail_from}")
                explanation = f"{base_explanation}; {ev_note}; {scale_note}"

                signal = Signal(
                    timestamp=now,
                    symbol=sig["symbol"],
                    instrument_type="stock",
                    direction="long",
                    score=sig.get("score", 50.0),
                    static_score=sig.get("static_score"),
                    ev=sig.get("ev"),
                    strategy=sig.get("strategy", "MOMENTUM"),
                    regime_at_entry=regime_label,
                    source="scanner",
                    entry_zone_low=round(price * 0.998, 2),
                    entry_zone_high=round(price * 1.002, 2),
                    stop_loss=stop,
                    target1=target1,
                    target2=target2,
                    confidence=confidence,
                    position_size_pct=round(pos_size_pct, 1),
                    do_not_enter_after=now + dt.timedelta(hours=6),
                    best_exit_window="14:30-15:00 IST",
                    explanation=explanation,
                    status=signal_status,
                )
                session.add(signal)
                count += 1
            except Exception:
                logger.warning("[scanner] Failed to save signal for %s", sig.get("symbol"))

        await session.commit()

    return count


async def run_premarket_full_scan(regime_label: str = "RANGE_CHOP",
                                  regime_data: Optional[Dict] = None) -> int:
    """Pre-market scan: score full watchlist, cache top 100 for intraday.

    This runs at 08:45 IST. Scores all ~200-300 watchlist symbols and
    saves the top 100 for fast intraday refreshes every 15 min.
    """
    global SCAN_UNIVERSE_TOP
    logger.info("[scanner] Running PRE-MARKET full scan...")
    try:
        await _refresh_news_scores()
        universe = await asyncio.to_thread(_build_universe, SCAN_UNIVERSE)
        if not universe:
            logger.warning("[scanner] Pre-market scan: no data")
            return 0

        # Cache top 100 scored symbols for intraday
        SCAN_UNIVERSE_TOP = [s["symbol"] for s in universe[:100]]
        logger.info(
            "[scanner] Pre-market cached top %d symbols for intraday refresh",
            len(SCAN_UNIVERSE_TOP),
        )

        # Generate and save signals from the full scan
        # Before 09:15 IST, save as "watchlist" — not tradeable yet
        now_ist = dt.datetime.now(IST)
        pre_market = now_ist.time() < dt.time(9, 15)
        status = "watchlist" if pre_market else "pending"

        signals = _generate_signals(universe, regime_label, regime_data=regime_data,
                                     skip_tod_gate=pre_market)
        count = await _save_signals(signals, regime_label, signal_status=status)
        logger.info("[scanner] Pre-market scan generated %d %s signals", count, status)
        return count
    except Exception:
        logger.exception("[scanner] Pre-market full scan failed")
        return 0


async def fetch_daily_movers() -> List[str]:
    """Fetch NSE daily top gainers, losers, and volume spikes.

    Scrapes NSE's public market status endpoints for the day's most active
    symbols (~20-30 total). Returns symbols NOT already in SCAN_UNIVERSE_TOP,
    and merges them in as dynamic additions for intraday scanning.
    """
    import httpx

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
    }

    movers: set[str] = set()

    # NSE endpoints for gainers/losers/most active
    urls = [
        "https://www.nseindia.com/api/live-analysis-variations?index=gainers",
        "https://www.nseindia.com/api/live-analysis-variations?index=losers",
        "https://www.nseindia.com/api/live-analysis-most-active-securities?index=volume",
    ]

    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            # First hit the homepage to get cookies (NSE requires this)
            try:
                await client.get("https://www.nseindia.com", headers=headers)
            except Exception:
                pass

            for url in urls:
                try:
                    resp = await client.get(url, headers=headers)
                    if resp.status_code != 200:
                        continue
                    data = resp.json()

                    # Extract symbols from the response
                    # NSE returns different structures; handle both
                    if isinstance(data, dict):
                        # Try 'data' key first, then 'NIFTY' or other index keys
                        items = data.get("data", [])
                        if not items:
                            for key in data:
                                if isinstance(data[key], list):
                                    items = data[key]
                                    break
                    elif isinstance(data, list):
                        items = data
                    else:
                        continue

                    for item in items[:15]:  # top 15 from each list
                        sym = item.get("symbol") or item.get("Symbol") or ""
                        sym = sym.strip().upper()
                        if sym and len(sym) <= 20:
                            movers.add(sym)

                except Exception as e:
                    logger.debug("[scanner] Failed to fetch movers from %s: %s", url, e)
                    continue

    except Exception:
        logger.warning("[scanner] Failed to fetch daily movers (network error)")
        return []

    # Filter out symbols already in the intraday universe
    existing = set(SCAN_UNIVERSE_TOP) | set(SCAN_UNIVERSE)
    new_movers = [s for s in movers if s not in existing]

    if new_movers:
        SCAN_UNIVERSE_TOP.extend(new_movers)
        logger.info(
            "[scanner] Dynamic additions: %d new movers added to intraday universe: %s",
            len(new_movers), ", ".join(new_movers[:10]),
        )
    else:
        logger.info("[scanner] No new movers outside existing universe (%d checked)", len(movers))

    return new_movers


async def run_stock_scan(regime_label: str = "RANGE_CHOP",
                         regime_data: Optional[Dict] = None) -> int:
    """Intraday scan: re-score top 100 symbols from pre-market cache.

    Returns the number of signals generated.
    """
    # Use cached top symbols if available, else fall back to full universe
    scan_symbols = SCAN_UNIVERSE_TOP if SCAN_UNIVERSE_TOP else SCAN_UNIVERSE
    logger.info("[scanner] Running intraday scan for %d symbols...", len(scan_symbols))
    try:
        # Load news scores before scoring stocks
        await _refresh_news_scores()

        # Fetch data and compute indicators in thread
        universe = await asyncio.to_thread(_build_universe, scan_symbols)
        if not universe:
            logger.warning("[scanner] No stock data fetched")
            return 0

        # Generate and save new signals
        signals = _generate_signals(universe, regime_label, regime_data=regime_data)
        count = await _save_signals(signals, regime_label)
        logger.info("[scanner] Intraday scan generated %d signals", count)
        return count
    except Exception:
        logger.exception("[scanner] Stock scan failed")
        return 0


def _build_universe(symbols: List[str]) -> List[Dict]:
    """Fetch daily data and compute indicators for each symbol.

    Implements Review Item 8 (liquidity gate):
    - Require average daily turnover >= 5 Cr (50,000,000)
    - Skip stocks within 2% of upper/lower circuit (collapsed range)
    """
    import yfinance as yf
    import numpy as np

    universe = []

    # Batch download in chunks of 50 for reliability
    BATCH_SIZE = 50
    all_data = {}

    for i in range(0, len(symbols), BATCH_SIZE):
        batch = symbols[i:i + BATCH_SIZE]
        tickers_str = " ".join(f"{s}.NS" for s in batch)
        logger.info("[scanner] Downloading batch %d/%d (%d symbols)...",
                    i // BATCH_SIZE + 1, (len(symbols) + BATCH_SIZE - 1) // BATCH_SIZE, len(batch))
        try:
            data = yf.download(tickers_str, period="60d", group_by="ticker",
                              progress=False, threads=True)
            if data is not None and not data.empty:
                all_data[i] = (data, batch)
        except Exception:
            logger.warning("[scanner] Batch %d download failed, skipping", i // BATCH_SIZE + 1)
            continue

    for batch_idx, (data, batch) in all_data.items():
        for symbol in batch:
            try:
                ticker = f"{symbol}.NS"
                if len(batch) == 1:
                    df = data
                else:
                    if ticker not in data.columns.get_level_values(0):
                        continue
                    df = data[ticker].dropna()

                if df.empty or len(df) < 20:
                    continue

                close = df["Close"].values
                high = df["High"].values
                low = df["Low"].values
                volume = df["Volume"].values

                if len(close) < 20:
                    continue

                price = float(close[-1])
                prev_close = float(close[-2]) if len(close) > 1 else price

                if price <= 0:
                    continue

                # ── Liquidity gate (Review Item 8) ────────────────────
                avg_vol_20d = float(np.mean(volume[-20:])) if len(volume) >= 20 else float(np.mean(volume))
                if avg_vol_20d < 50_000:
                    continue

                # Require average daily turnover >= 5 Cr (50,000,000)
                avg_turnover = avg_vol_20d * price
                if avg_turnover < 50_000_000:
                    continue

                # Day range
                day_high = float(high[-1])
                day_low = float(low[-1])

                # ── M10: Strengthen circuit / T2T / impact-cost filter ──
                day_range = day_high - day_low
                if day_range <= 0 or (day_range / price) < 0.001:
                    continue
                if day_high == day_low:
                    continue

                # Near circuit detection: if price within 2% of day's extreme
                # and range is collapsed (< 1% of price), likely circuit-hit
                range_pct = (day_range / price) * 100
                if range_pct < 1.0:
                    # Check if LTP near upper or lower extreme
                    if (price >= day_high * 0.98) or (price <= day_low * 1.02):
                        continue

                # Check for circuit hits in recent 5 sessions
                recent_ranges = []
                for k in range(-5, 0):
                    if abs(k) < len(high):
                        r = (float(high[k]) - float(low[k])) / max(float(close[k]), 1) * 100
                        recent_ranges.append(r)
                if recent_ranges and sum(1 for r in recent_ranges if r < 0.5) >= 2:
                    # 2+ days with <0.5% range in last 5 sessions → likely circuit/T2T
                    continue

                # Non-Nifty impact cost proxy: reject if ADV < 10Cr for non-Nifty200
                from backend.backtester.data_loader import NIFTY200_SYMBOLS
                if symbol not in NIFTY200_SYMBOLS and avg_turnover < 10_00_00_000:
                    continue

                # RSI (14)
                deltas = np.diff(close[-15:])
                gains = np.where(deltas > 0, deltas, 0)
                losses = np.where(deltas < 0, -deltas, 0)
                avg_gain = np.mean(gains) if len(gains) > 0 else 0
                avg_loss = np.mean(losses) if len(losses) > 0 else 0.001
                rs = avg_gain / avg_loss if avg_loss > 0 else 100
                rsi = 100 - (100 / (1 + rs))

                # ATR (14)
                tr_vals = []
                for j in range(-14, 0):
                    tr = max(high[j] - low[j],
                            abs(high[j] - close[j-1]),
                            abs(low[j] - close[j-1]))
                    tr_vals.append(tr)
                atr = float(np.mean(tr_vals))
                atr_pct = (atr / price) * 100

                # Volume ratio
                vol_20d = float(np.mean(volume[-20:]))
                vol_ratio = float(volume[-1] / vol_20d) if vol_20d > 0 else 1.0

                # Bollinger Bands position
                sma20 = float(np.mean(close[-20:]))
                std20 = float(np.std(close[-20:]))
                upper_bb = sma20 + 2 * std20
                lower_bb = sma20 - 2 * std20
                bb_range = upper_bb - lower_bb
                bb_position = (price - lower_bb) / bb_range if bb_range > 0 else 0.5

                # Stochastic %K (14)
                h14 = float(np.max(high[-14:]))
                l14 = float(np.min(low[-14:]))
                stoch_k = ((price - l14) / (h14 - l14) * 100) if (h14 - l14) > 0 else 50

                # Returns
                ret5d = ((price / float(close[-6])) - 1) * 100 if len(close) >= 6 else 0
                ret20d = ((price / float(close[-21])) - 1) * 100 if len(close) >= 21 else 0

                # Gap %
                gap_pct = ((float(df["Open"].values[-1]) / prev_close) - 1) * 100

                # Near 20d high
                high_20d = float(np.max(high[-20:]))
                near_20d_high = price >= high_20d * 0.97

                day_change_pct = ((price / prev_close) - 1) * 100

                # EMA 20
                ema20_val = sma20

                # Score components
                trend_score = min(max((price - ema20_val) / ema20_val * 100 * 10 + 50, 0), 100)
                momentum_score = min(max(rsi, 0), 100)
                volume_score = min(vol_ratio * 50, 100)
                breakout_score = 80 if near_20d_high and vol_ratio > 1.2 else 30
                volatility_score = min(max(100 - atr_pct * 20, 0), 100)

                # ── Improved news scoring (Review Item 10) ────────────
                # Continuous score 0-100 based on weighted impact
                news_score = _news_score_cache.get(symbol.upper(), 0.0)
                # Sentiment: -1 (very negative) to +1 (very positive)
                news_sentiment = _news_sentiment_cache.get(symbol.upper(), 0.0)

                # Composite score (6 factors) — uses current (possibly adapted) weights
                score = (
                    trend_score * DEFAULT_WEIGHTS["trend"]
                    + momentum_score * DEFAULT_WEIGHTS["momentum"]
                    + volume_score * DEFAULT_WEIGHTS["volume"]
                    + breakout_score * DEFAULT_WEIGHTS["breakout"]
                    + volatility_score * DEFAULT_WEIGHTS["volatility"]
                    + news_score * DEFAULT_WEIGHTS["news"]
                )

                # Static baseline score for learning safeguard (M5)
                STATIC_WEIGHTS = {
                    "trend": 0.25, "momentum": 0.20, "volume": 0.15,
                    "breakout": 0.15, "volatility": 0.10, "news": 0.15,
                }
                static_score = (
                    trend_score * STATIC_WEIGHTS["trend"]
                    + momentum_score * STATIC_WEIGHTS["momentum"]
                    + volume_score * STATIC_WEIGHTS["volume"]
                    + breakout_score * STATIC_WEIGHTS["breakout"]
                    + volatility_score * STATIC_WEIGHTS["volatility"]
                    + news_score * STATIC_WEIGHTS["news"]
                )

                # ── M7: Blend intraday features when available ────────
                intraday_contrib = 0.0
                daily_contrib = score
                try:
                    from backend.modules.intraday_stream import IntraDayManager
                    now_ist = dt.datetime.now(IST)
                    t = now_ist.time()
                    if t >= dt.time(9, 30):
                        # Try to get live features from the global manager
                        mgr = _get_intraday_manager()
                        if mgr is not None:
                            features = mgr.get_live_features(symbol)
                            if features:
                                # Intraday score components
                                vwap_score = 60 + features["price_vs_vwap_pct"] * 10  # above VWAP = bullish
                                vwap_score = min(max(vwap_score, 0), 100)
                                rs_score = 50 + features["rs_vs_nifty_15m"] * 20
                                rs_score = min(max(rs_score, 0), 100)
                                delta_score = 50 + (features["delta_proxy_5m"] / max(avg_vol_20d, 1)) * 100
                                delta_score = min(max(delta_score, 0), 100)
                                orb_score = 70 if (features["orb_high_15m"] > 0 and
                                                   price > features["orb_high_15m"]) else 40

                                intraday_avg = (vwap_score + rs_score + delta_score + orb_score) / 4

                                # Session-phase blending: 09:30+ = 70% intraday, 30% daily
                                if t >= dt.time(9, 30):
                                    score = intraday_avg * 0.7 + score * 0.3
                                    intraday_contrib = round(intraday_avg * 0.7, 1)
                                    daily_contrib = round(score * 0.3, 1)
                except Exception:
                    pass  # graceful fallback to daily-only scoring

                # V5-3: Determine strategy — widened MR criteria, added RANGE_PLAY
                if near_20d_high and vol_ratio > 1.2:
                    strategy = "BREAKOUT"
                elif rsi > 60 and ret5d > 3:          # V5-3: tighter — only strong momentum
                    strategy = "MOMENTUM"
                elif bb_position < 0.35 and rsi < 45:  # V5-3: wider — catch more MR setups
                    strategy = "MEAN_REVERSION"
                elif gap_pct > 0.5 and vol_ratio > 1.5:
                    strategy = "GAP_AND_GO"
                elif 0.3 < bb_position < 0.7 and 40 < rsi < 60:
                    strategy = "RANGE_PLAY"            # V5-3: NEW — range-bound names
                else:
                    strategy = "SWING"

                # Explanation
                notes = []
                if near_20d_high:
                    notes.append("Near 20-day high")
                if vol_ratio > 1.5:
                    notes.append(f"Volume surge {vol_ratio:.1f}x")
                if rsi > 60:
                    notes.append(f"Strong RSI {rsi:.0f}")
                if ret5d > 2:
                    notes.append(f"5d momentum +{ret5d:.1f}%")
                if news_sentiment < -0.3:
                    notes.append(f"Neg news sentiment {news_sentiment:.2f}")
                elif news_sentiment > 0.3:
                    notes.append(f"Pos news catalyst {news_sentiment:.2f}")

                # ── Improved slippage model (Review Item 6) ───────────
                adv_shares = avg_vol_20d
                adv_rupees = avg_turnover

                # Structural stop for cost calculation
                structural_stop = max(
                    day_low,
                    sma20 - 0.25 * atr,
                    prev_close * 0.985,
                )
                risk_per_share = price - structural_stop
                if risk_per_share <= 0:
                    continue

                risk_amount = settings.capital * settings.risk_per_trade_pct / 100
                qty = max(1, int(risk_amount / risk_per_share))

                buy_val = price * qty
                slippage_cost = _estimate_slippage(price, qty, adv_shares, adv_rupees)
                slippage_cost_rt = slippage_cost * 2  # round-trip

                cost_breakdown = groww_intraday_cost(price, qty)
                cost_roundtrip = cost_breakdown.total + slippage_cost_rt

                # Scale-out targets for cost estimation
                reward_per_share = 1.0 * risk_per_share  # target at 1R for conservative EV
                target_price = price + reward_per_share

                net_profit = round((reward_per_share * qty) - cost_roundtrip, 2)
                net_loss = round((-risk_per_share * qty) - cost_roundtrip, 2)
                net_rr = round(abs(net_profit / net_loss), 2) if net_loss != 0 else 0

                universe.append({
                    "symbol": symbol,
                    "price": round(price, 2),
                    "prev_close": round(prev_close, 2),
                    "day_high": round(day_high, 2),
                    "day_low": round(day_low, 2),
                    "day_change_pct": round(day_change_pct, 2),
                    "atr": round(atr, 2),
                    "atr_pct": round(atr_pct, 2),
                    "rsi": round(rsi, 1),
                    "stoch_k": round(stoch_k, 1),
                    "bb_position": round(bb_position, 2),
                    "vol_ratio": round(vol_ratio, 2),
                    "ret5d_pct": round(ret5d, 2),
                    "ret20d_pct": round(ret20d, 2),
                    "gap_pct": round(gap_pct, 2),
                    "near_20d_high": near_20d_high,
                    "sma20": round(sma20, 2),
                    "score": round(score, 1),
                    "static_score": round(static_score, 1),
                    "strategy": strategy,
                    "explanation": "; ".join(notes) if notes else f"{strategy} setup",
                    "qty": qty,
                    "capital_needed": round(buy_val, 2),
                    "cost_roundtrip": round(cost_roundtrip, 2),
                    "slippage_cost": round(slippage_cost_rt, 2),
                    "net_profit": net_profit,
                    "net_loss": net_loss,
                    "net_rr": net_rr,
                    "adv_shares": round(adv_shares, 0),
                    "adv_rupees": round(adv_rupees, 0),
                    "news_score": round(news_score, 1),
                    "news_sentiment": round(news_sentiment, 2),
                })

            except Exception:
                continue

    # Sort by score descending
    universe.sort(key=lambda x: x["score"], reverse=True)
    logger.info("[scanner] Built universe: %d stocks with data", len(universe))
    return universe


def _generate_signals(universe: List[Dict], regime_label: str,
                      regime_data: Optional[Dict] = None,
                      skip_tod_gate: bool = False) -> List[Dict]:
    """Score and filter universe into actionable signals.

    Implements:
    - Review Item 2:  Regime-aware strategy gating
    - Review Item 5:  EV-positive gate (HIGHEST PRIORITY)
    - Review Item 10: Negative-news gate on longs
    - Review Item 11: Breadth gate on longs
    - Review Item 12: Time-of-day bucketing
    """
    regime_lower = regime_label.lower()

    # ── Resolve allowed strategies for this regime (Review Item 2) ─────
    allowed_strategies = REGIME_ALLOWED_STRATEGIES.get(regime_lower, None)
    # If regime not in map, allow all strategies
    if allowed_strategies is None:
        allowed_strategies = {"BREAKOUT", "MOMENTUM", "MEAN_REVERSION", "GAP_AND_GO", "SWING"}

    # ── Breadth gate on longs (Review Item 11) ─────────────────────────
    nifty_change_pct = 0.0
    breadth_pct = 50.0
    if regime_data:
        nifty_change_pct = regime_data.get("nifty_change_pct", 0.0)
        breadth_pct = regime_data.get("breadth_pct", 50.0)

    breadth_disabled_strategies: Set[str] = set()
    if nifty_change_pct < 0 and breadth_pct < 35:
        # Weak breadth in a down market: disable aggressive long strategies
        breadth_disabled_strategies = {"BREAKOUT", "MOMENTUM"}
        logger.info("[scanner] Breadth gate active: nifty_chg=%.2f%%, breadth=%.1f%% "
                    "-> disabling BREAKOUT, MOMENTUM for longs",
                    nifty_change_pct, breadth_pct)

    # Apply regime score multiplier
    regime_mult = {
        "trend_up": 1.1,
        "trend_down": 0.7,
        "range_chop": 0.9,
        "high_vol_event": 0.6,
        "gap_and_go": 1.0,
        "gap_fill": 0.85,
        "low_liq_drift": 0.75,
    }
    mult = regime_mult.get(regime_lower, 1.0)

    filtered = []
    regime_veto_count = 0
    breadth_veto_count = 0
    tod_veto_count = 0
    ev_veto_count = 0
    news_veto_count = 0
    min_score = 35

    for stock in universe:
        strategy = stock.get("strategy", "SWING")

        # ── Regime strategy gating (Review Item 2) ────────────────────
        if strategy not in allowed_strategies:
            regime_veto_count += 1
            continue

        # ── Breadth gate (Review Item 11) ─────────────────────────────
        if strategy in breadth_disabled_strategies:
            breadth_veto_count += 1
            continue

        # ── Negative-news gate (Review Item 10) ──────────────────────
        news_sentiment = stock.get("news_sentiment", 0.0)
        if news_sentiment < -0.5:
            # Strong negative sentiment: block longs entirely
            news_veto_count += 1
            continue

        # ── Time-of-day bucketing (Review Item 12) ────────────────────
        if skip_tod_gate:
            tod_mult, tod_bucket = 1.0, "pre_market_bypass"
        else:
            tod_mult, tod_bucket = _time_of_day_multiplier(strategy)
            if tod_mult <= 0:
                tod_veto_count += 1
                continue

        # Apply multipliers to score
        adjusted_score = round(stock["score"] * mult * tod_mult, 1)

        # Boost/penalise based on news sentiment (continuous, Review Item 10)
        # Positive sentiment adds up to +10% score, negative subtracts up to -10%
        sentiment_adjustment = news_sentiment * 10  # -10 to +10
        adjusted_score = round(adjusted_score + sentiment_adjustment, 1)

        stock["score"] = adjusted_score

        # Minimum score threshold
        if adjusted_score < min_score:
            continue

        # ── EV-positive gate (Review Item 5) — HIGHEST PRIORITY ──────
        price = stock.get("price", 0)
        atr = stock.get("atr", price * 0.02)
        qty = stock.get("qty", 1)
        cost_roundtrip = stock.get("cost_roundtrip", 0)
        slippage_cost = stock.get("slippage_cost", 0)

        # Structural stop risk
        day_low = stock.get("day_low", price * 0.98)
        sma20 = stock.get("sma20", price)
        prev_close = stock.get("prev_close", price)
        stop = max(day_low, sma20 - 0.25 * atr, prev_close * 0.985)
        risk_per_share = price - stop
        if risk_per_share <= 0:
            continue

        # V5-6: Reward at 2.0R — scale-out trails can exceed 2R on winners
        reward_per_share = 2.0 * risk_per_share

        # V5-6: Strategy-dependent p_win priors when no learned data
        # Reflects reality: BREAKOUT low hit rate / high payoff,
        # MEAN_REVERSION higher hit rate / lower payoff
        _STRATEGY_PRIOR_PWIN = {
            "BREAKOUT": 0.42,
            "MOMENTUM": 0.48,
            "MEAN_REVERSION": 0.52,
            "GAP_AND_GO": 0.45,
            "RANGE_PLAY": 0.50,
            "SWING": 0.47,
        }

        # M8: Use learned hit rate if available, else strategy-specific prior
        p_win = _STRATEGY_PRIOR_PWIN.get(strategy, 0.45)
        learned_p_win = None
        try:
            from backend.modules.learning_engine import LearningEngine
            learned = LearningEngine.hit_rate_for(strategy, regime_lower)
            if learned is not None:
                p_win = learned
                learned_p_win = learned
        except Exception:
            pass
        ev = ((p_win * reward_per_share * qty)
              - ((1 - p_win) * risk_per_share * qty)
              - cost_roundtrip
              - slippage_cost)

        if ev <= 0:
            ev_veto_count += 1
            continue   # hard block — EV-negative picks must never reach users

        stock["ev"] = round(ev, 2)
        stock["tod_bucket"] = tod_bucket
        stock["learned_p_win"] = learned_p_win
        stock["p_win_used"] = round(p_win, 4)
        logger.debug("[scanner] Accepted %s: score=%.1f, EV=%.2f, strategy=%s, "
                     "regime=%s, tod=%s",
                     stock["symbol"], adjusted_score, ev, strategy,
                     regime_label, tod_bucket)

        filtered.append(stock)

    # ── Persist veto breakdown for M6 empty-state card ──────────────
    global last_veto_breakdown, last_candidates_scanned
    last_candidates_scanned = len(universe)
    last_veto_breakdown = {
        "regime": regime_veto_count,
        "breadth": breadth_veto_count,
        "time_of_day": tod_veto_count,
        "ev": ev_veto_count,
        "news": news_veto_count,
    }

    # ── Logging ───────────────────────────────────────────────────────
    logger.info("[scanner] Signal generation: %d candidates -> %d accepted "
                "(regime_veto=%d, breadth_veto=%d, tod_veto=%d, ev_veto=%d, "
                "news_veto=%d)",
                len(universe), len(filtered), regime_veto_count,
                breadth_veto_count, tod_veto_count, ev_veto_count,
                news_veto_count)

    # Re-sort by score descending after adjustments
    filtered.sort(key=lambda x: x["score"], reverse=True)

    # Also filter by minimum net R:R
    filtered = [s for s in filtered if s.get("net_rr", 0) >= 1.0]

    return filtered


# ─── EOD Grading ────────────────────────────────────────────────────────

async def run_eod_grade() -> int:
    """Close all open trades at current prices, compute P&L."""
    logger.info("[scanner] Running EOD grading...")
    try:
        closed = 0
        async with AsyncSessionLocal() as session:
            from sqlalchemy import select
            result = await session.execute(
                select(Trade, Signal)
                .join(Signal, Signal.id == Trade.signal_id)
                .where(Trade.status.in_(["open", "partial"]))
            )
            rows = result.all()

            if not rows:
                logger.info("[scanner] No open trades to grade")
                return 0

            # Fetch current prices
            symbols = list(set(t.symbol for t, _ in rows))
            prices = await asyncio.to_thread(_get_current_prices, symbols)

            now = dt.datetime.now(dt.timezone.utc)
            for trade, signal in rows:
                exit_price = prices.get(trade.symbol, trade.entry_price)
                direction_mult = 1.0 if signal.direction == "long" else -1.0
                gross_pnl = direction_mult * (exit_price - trade.entry_price) * trade.qty
                cost = 40 + (trade.entry_price + exit_price) * trade.qty * 0.0003
                net_pnl = gross_pnl - cost

                trade.exit_price = exit_price
                trade.exit_time = now
                trade.gross_pnl = round(gross_pnl, 2)
                trade.net_pnl = round(net_pnl, 2)
                trade.cost = round(cost, 2)
                trade.status = "closed"
                trade.exit_reason = "eod_square_off"

                # M5: static counterfactual — scale PnL by static/adaptive score ratio
                adaptive_score = signal.score or 50.0
                static_score = signal.static_score or adaptive_score
                if adaptive_score > 0:
                    score_ratio = static_score / adaptive_score
                    # Counterfactual qty would differ proportionally to score
                    trade.pnl_static_counterfactual = round(net_pnl * score_ratio, 2)
                else:
                    trade.pnl_static_counterfactual = round(net_pnl, 2)

                closed += 1

            await session.commit()

        logger.info("[scanner] EOD graded %d trades", closed)
        return closed
    except Exception:
        logger.exception("[scanner] EOD grading failed")
        return 0


def _get_current_prices(symbols: List[str]) -> Dict[str, float]:
    """Fetch current prices for a list of symbols."""
    import yfinance as yf

    prices = {}
    tickers_str = " ".join(f"{s}.NS" for s in symbols)
    try:
        data = yf.download(tickers_str, period="1d", progress=False, threads=True)
        if not data.empty:
            if len(symbols) == 1:
                prices[symbols[0]] = float(data["Close"].iloc[-1])
            else:
                for sym in symbols:
                    ticker = f"{sym}.NS"
                    try:
                        prices[sym] = float(data[ticker]["Close"].iloc[-1])
                    except (KeyError, IndexError):
                        pass
    except Exception:
        logger.warning("[scanner] Price fetch failed for EOD grading")

    return prices


# ─── Full Scan Pipeline ─────────────────────────────────────────────────

async def run_full_scan() -> Dict:
    """Run the complete scan pipeline: regime -> news -> stocks.

    Returns a summary dict. Passes regime data through to signal generation
    so breadth gate and other regime-aware logic can use it.
    """
    summary = {"regime": None, "news_count": 0, "signal_count": 0, "errors": []}

    regime_data = None

    # 1. Regime
    try:
        regime_data = await run_regime_scan()
        if regime_data:
            summary["regime"] = regime_data.get("label", "RANGE_CHOP")
    except Exception as e:
        summary["errors"].append(f"regime: {e}")

    # 2. News
    try:
        summary["news_count"] = await run_news_scan()
    except Exception as e:
        summary["errors"].append(f"news: {e}")

    # 3. Stock scan (uses pre-market full scan to also cache top symbols)
    try:
        regime_label = summary["regime"] or "RANGE_CHOP"
        summary["signal_count"] = await run_premarket_full_scan(
            regime_label, regime_data=regime_data
        )
    except Exception as e:
        summary["errors"].append(f"stocks: {e}")

    logger.info("[scanner] Full scan complete: %s", summary)
    return summary
