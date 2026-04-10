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
    "news": 0.10,
    "liquidity": 0.05,
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

# Nifty 50 symbols for scanning
NIFTY_50 = [
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK",
    "HINDUNILVR", "ITC", "SBIN", "BHARTIARTL", "KOTAKBANK",
    "LT", "AXISBANK", "BAJFINANCE", "ASIANPAINT", "MARUTI",
    "HCLTECH", "SUNPHARMA", "TITAN", "ULTRACEMCO", "WIPRO",
    "NESTLEIND", "TATAMOTORS", "NTPC", "INDUSINDBK", "POWERGRID",
    "M&M", "ADANIENT", "ADANIPORTS", "JSWSTEEL", "TATASTEEL",
    "BAJAJFINSV", "TECHM", "ONGC", "HDFCLIFE", "COALINDIA",
    "DIVISLAB", "DRREDDY", "BRITANNIA", "CIPLA", "EICHERMOT",
    "APOLLOHOSP", "SBILIFE", "BPCL", "TATACONSUM", "GRASIM",
    "HEROMOTOCO", "BAJAJ-AUTO", "HINDALCO", "UPL", "SHRIRAMFIN",
]


async def run_stock_scan(regime_label: str = "RANGE_CHOP") -> int:
    """Scan Nifty 50 stocks, compute indicators, generate signals.

    Returns the number of signals generated.
    """
    logger.info("[scanner] Running stock scan for %d symbols...", len(NIFTY_50))
    try:
        # Fetch data and compute indicators in thread
        universe = await asyncio.to_thread(_build_universe, NIFTY_50)
        if not universe:
            logger.warning("[scanner] No stock data fetched")
            return 0

        # Expire old pending signals
        async with AsyncSessionLocal() as session:
            from sqlalchemy import update
            await session.execute(
                update(Signal)
                .where(Signal.status == "pending")
                .values(status="expired")
            )
            await session.commit()

        # Generate and save new signals
        signals = _generate_signals(universe, regime_label)

        count = 0
        async with AsyncSessionLocal() as session:
            now = dt.datetime.now(dt.timezone.utc)
            ist_now = dt.datetime.now(IST)

            for sig in signals[:settings.max_open_positions * 2]:  # Top N signals
                try:
                    # Compute entry, SL, target from ATR
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

                    # Position sizing
                    risk_amount = settings.capital * settings.risk_per_trade_pct / 100
                    qty = max(1, int(risk_amount / risk))
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
                        confidence=min(sig.get("score", 50) / 100, 0.95),
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

        logger.info("[scanner] Generated %d signals", count)
        return count
    except Exception:
        logger.exception("[scanner] Stock scan failed")
        return 0


def _build_universe(symbols: List[str]) -> List[Dict]:
    """Fetch daily data and compute indicators for each symbol."""
    import yfinance as yf
    import numpy as np

    universe = []

    # Batch download
    tickers_str = " ".join(f"{s}.NS" for s in symbols)
    try:
        data = yf.download(tickers_str, period="60d", group_by="ticker",
                          progress=False, threads=True)
    except Exception:
        logger.exception("[scanner] yfinance batch download failed")
        return []

    for symbol in symbols:
        try:
            ticker = f"{symbol}.NS"
            if len(symbols) == 1:
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

            # Compute indicators
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
            for i in range(-14, 0):
                tr = max(high[i] - low[i],
                        abs(high[i] - close[i-1]),
                        abs(low[i] - close[i-1]))
                tr_vals.append(tr)
            atr = float(np.mean(tr_vals))
            atr_pct = (atr / price) * 100

            # Volume ratio (current vs 20d avg)
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
            ema20_val = sma20  # approximation

            # Score components
            trend_score = min(max((price - ema20_val) / ema20_val * 100 * 10 + 50, 0), 100)
            momentum_score = min(max(rsi, 0), 100)
            volume_score = min(vol_ratio * 50, 100)
            breakout_score = 80 if near_20d_high and vol_ratio > 1.2 else 30
            volatility_score = min(max(100 - atr_pct * 20, 0), 100)

            # Composite score
            score = (
                trend_score * DEFAULT_WEIGHTS["trend"]
                + momentum_score * DEFAULT_WEIGHTS["momentum"]
                + volume_score * DEFAULT_WEIGHTS["volume"]
                + breakout_score * DEFAULT_WEIGHTS["breakout"]
                + volatility_score * DEFAULT_WEIGHTS["volatility"]
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

            # Cost model (Groww intraday)
            qty = max(1, int((settings.capital * settings.risk_per_trade_pct / 100) / (1.5 * atr)))
            buy_val = price * qty
            cost_roundtrip = 40 + buy_val * 0.0005  # ~brokerage + STT + others
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

    # 3. Stock scan
    try:
        regime_label = summary["regime"] or "RANGE_CHOP"
        summary["signal_count"] = await run_stock_scan(regime_label)
    except Exception as e:
        summary["errors"].append(f"stocks: {e}")

    logger.info("[scanner] Full scan complete: %s", summary)
    return summary
