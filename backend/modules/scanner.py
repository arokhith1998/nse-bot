"""
NSE Market Intelligence Platform - Scanner Module
==================================================
Orchestrates the full scan pipeline: regime detection, news fetching,
stock universe scanning, indicator computation, and signal generation.
Saves all results to the database.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import traceback
from typing import Dict, List, Optional

import pytz

from backend.config import settings
from backend.database import AsyncSessionLocal
from backend.models import (
    NewsItem as NewsItemModel,
    RegimeSnapshot,
    Signal,
    Trade,
    WeightsHistory,
)

logger = logging.getLogger(__name__)

IST = pytz.timezone("Asia/Kolkata")

# Default scoring weights
DEFAULT_WEIGHTS: Dict[str, float] = {
    "trend": 0.25,
    "momentum": 0.20,
    "volume": 0.15,
    "breakout": 0.15,
    "volatility": 0.10,
    "news": 0.15,
}


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

# Module-level cache for news scores (populated before each scan)
_news_score_cache: Dict[str, float] = {}


async def _refresh_news_scores():
    """Load recent news items from DB and build a symbol->score (0-100) map."""
    global _news_score_cache
    try:
        from sqlalchemy import select, func
        async with AsyncSessionLocal() as session:
            cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=24)
            result = await session.execute(
                select(NewsItemModel.symbol, func.max(NewsItemModel.weighted_impact))
                .where(NewsItemModel.timestamp >= cutoff)
                .where(NewsItemModel.symbol.isnot(None))
                .group_by(NewsItemModel.symbol)
            )
            rows = result.all()
            _news_score_cache.clear()
            for sym, impact in rows:
                if sym:
                    # weighted_impact is 0.0-1.0, scale to 0-100
                    _news_score_cache[sym.upper()] = min(float(impact) * 100, 100.0)
            logger.info("[scanner] Loaded news scores for %d symbols", len(_news_score_cache))
    except Exception:
        logger.warning("[scanner] Failed to refresh news scores")


async def _save_signals(signals: List[Dict], regime_label: str) -> int:
    """Expire old pending signals and save new ones to DB."""
    from backend.config import pick_count_for_capital

    # Expire old pending signals
    async with AsyncSessionLocal() as session:
        from sqlalchemy import update
        await session.execute(
            update(Signal)
            .where(Signal.status == "pending")
            .values(status="expired")
        )
        await session.commit()

    n_picks = pick_count_for_capital(settings.capital)
    count = 0
    async with AsyncSessionLocal() as session:
        now = dt.datetime.now(dt.timezone.utc)

        for sig in signals[:n_picks * 2]:  # top + stretch
            try:
                price = sig.get("price", 0)
                atr = sig.get("atr", price * 0.02)
                if price <= 0:
                    continue

                sl = round(price - 1.5 * atr, 2)
                target1 = round(price + 2.0 * atr, 2)
                target2 = round(price + 3.0 * atr, 2)
                risk = price - sl
                if risk <= 0:
                    continue

                risk_amount = settings.capital * settings.risk_per_trade_pct / 100
                base_qty = max(1, int(risk_amount / risk))
                confidence = min(sig.get("score", 50) / 100, 0.95)
                qty = max(1, int(base_qty * (0.5 + 0.5 * confidence)))
                pos_size_pct = (qty * price / settings.capital) * 100

                signal = Signal(
                    timestamp=now,
                    symbol=sig["symbol"],
                    instrument_type="stock",
                    direction="long",
                    score=sig.get("score", 50.0),
                    strategy=sig.get("strategy", "MOMENTUM"),
                    regime_at_entry=regime_label,
                    source="scanner",
                    entry_zone_low=round(price * 0.998, 2),
                    entry_zone_high=round(price * 1.002, 2),
                    stop_loss=sl,
                    target1=target1,
                    target2=target2,
                    confidence=confidence,
                    position_size_pct=round(pos_size_pct, 1),
                    do_not_enter_after=now + dt.timedelta(hours=6),
                    best_exit_window="14:30-15:00 IST",
                    explanation=sig.get("explanation", ""),
                    status="pending",
                )
                session.add(signal)
                count += 1
            except Exception:
                logger.warning("[scanner] Failed to save signal for %s", sig.get("symbol"))

        await session.commit()

    return count


async def run_premarket_full_scan(regime_label: str = "RANGE_CHOP") -> int:
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
        signals = _generate_signals(universe, regime_label)
        count = await _save_signals(signals, regime_label)
        logger.info("[scanner] Pre-market scan generated %d signals", count)
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


async def run_stock_scan(regime_label: str = "RANGE_CHOP") -> int:
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
        signals = _generate_signals(universe, regime_label)
        count = await _save_signals(signals, regime_label)
        logger.info("[scanner] Intraday scan generated %d signals", count)
        return count
    except Exception:
        logger.exception("[scanner] Stock scan failed")
        return 0


def _build_universe(symbols: List[str]) -> List[Dict]:
    """Fetch daily data and compute indicators for each symbol."""
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

                # Liquidity hard filter: min 50,000 shares/day avg volume
                avg_vol_20d = float(np.mean(volume[-20:])) if len(volume) >= 20 else float(np.mean(volume))
                if avg_vol_20d < 50_000:
                    continue
                # Also filter by minimum daily turnover (Rs 1 Cr = 10M)
                avg_turnover = avg_vol_20d * price
                if avg_turnover < 10_000_000:
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

                # Day range
                day_high = float(high[-1])
                day_low = float(low[-1])
                day_change_pct = ((price / prev_close) - 1) * 100

                # EMA 20
                ema20_val = sma20

                # Score components
                trend_score = min(max((price - ema20_val) / ema20_val * 100 * 10 + 50, 0), 100)
                momentum_score = min(max(rsi, 0), 100)
                volume_score = min(vol_ratio * 50, 100)
                breakout_score = 80 if near_20d_high and vol_ratio > 1.2 else 30
                volatility_score = min(max(100 - atr_pct * 20, 0), 100)
                # News score: 0-100 based on whether symbol has recent news
                news_score = _news_score_cache.get(symbol.upper(), 0.0)

                # Composite score (6 factors)
                score = (
                    trend_score * DEFAULT_WEIGHTS["trend"]
                    + momentum_score * DEFAULT_WEIGHTS["momentum"]
                    + volume_score * DEFAULT_WEIGHTS["volume"]
                    + breakout_score * DEFAULT_WEIGHTS["breakout"]
                    + volatility_score * DEFAULT_WEIGHTS["volatility"]
                    + news_score * DEFAULT_WEIGHTS["news"]
                )

                # Determine strategy
                if near_20d_high and vol_ratio > 1.2:
                    strategy = "BREAKOUT"
                elif rsi > 50 and ret5d > 2:
                    strategy = "MOMENTUM"
                elif bb_position < 0.2 and rsi < 35:
                    strategy = "MEAN_REVERSION"
                elif gap_pct > 0.5 and vol_ratio > 1.5:
                    strategy = "GAP_AND_GO"
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

                # Cost model (Groww intraday) with confidence-weighted sizing + slippage
                from backend.services.cost_model import estimate_slippage

                confidence = min(score / 100, 0.95)
                base_qty = max(1, int((settings.capital * settings.risk_per_trade_pct / 100) / (1.5 * atr)))
                qty = max(1, int(base_qty * (0.5 + 0.5 * confidence)))
                buy_val = price * qty
                slippage_pct = estimate_slippage(price, qty, avg_vol_20d)
                slippage_cost = buy_val * slippage_pct / 100 * 2  # both legs
                cost_roundtrip = 40 + buy_val * 0.0005 + slippage_cost
                net_profit = round((2.0 * atr * qty) - cost_roundtrip, 2)
                net_loss = round((-1.5 * atr * qty) - cost_roundtrip, 2)
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
                    "score": round(score, 1),
                    "strategy": strategy,
                    "explanation": "; ".join(notes) if notes else f"{strategy} setup",
                    "qty": qty,
                    "capital_needed": round(buy_val, 2),
                    "cost_roundtrip": round(cost_roundtrip, 2),
                    "net_profit": net_profit,
                    "net_loss": net_loss,
                    "net_rr": net_rr,
                })

            except Exception:
                continue

    # Sort by score descending
    universe.sort(key=lambda x: x["score"], reverse=True)
    logger.info("[scanner] Built universe: %d stocks with data", len(universe))
    return universe


def _generate_signals(universe: List[Dict], regime_label: str) -> List[Dict]:
    """Score and filter universe into actionable signals."""
    # Apply regime adjustments
    regime_mult = {
        "TREND_UP": 1.1,
        "TREND_DOWN": 0.7,
        "RANGE_CHOP": 0.9,
        "HIGH_VOL_EVENT": 0.6,
        "GAP_AND_GO": 1.0,
        "GAP_FILL": 0.85,
        "LOW_LIQ_DRIFT": 0.75,
    }
    mult = regime_mult.get(regime_label, 1.0)

    for stock in universe:
        stock["score"] = round(stock["score"] * mult, 1)

    # Re-sort
    universe.sort(key=lambda x: x["score"], reverse=True)

    # Filter: minimum score threshold
    min_score = 35
    filtered = [s for s in universe if s["score"] >= min_score and s["net_rr"] >= 1.0]

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
    """Run the complete scan pipeline: regime → news → stocks.

    Returns a summary dict.
    """
    summary = {"regime": None, "news_count": 0, "signal_count": 0, "errors": []}

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
        summary["signal_count"] = await run_premarket_full_scan(regime_label)
    except Exception as e:
        summary["errors"].append(f"stocks: {e}")

    logger.info("[scanner] Full scan complete: %s", summary)
    return summary
