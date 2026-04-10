"""
Comprehensive scoring engine for NSE Market Intelligence.

Architecture
------------
final_score = (
    premarket_score  * 0.30  +   # overnight setup quality
    live_score       * 0.25  +   # intraday confirmation
    regime_score     * 0.20  +   # market context alignment
    news_score       * 0.15  +   # catalyst presence
    execution_score  * 0.10      # cost / liquidity feasibility
)

Each component is normalised to a 0-100 scale.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable, Optional

import numpy as np
import pandas as pd

from backend.services import indicators as ind


# ── Helpers ──────────────────────────────────────────────────────────

def normalize(value: float, lo: float, hi: float) -> float:
    """Linearly map *value* into the 0-100 range clamped at the bounds.

    >>> normalize(75, 50, 100)
    50.0
    """
    if hi == lo:
        return 50.0
    return float(np.clip((value - lo) / (hi - lo) * 100, 0, 100))


# ── Dataclasses ──────────────────────────────────────────────────────

@dataclass
class PremarketDetail:
    trend_alignment: float = 0.0
    momentum: float = 0.0
    breakout_proximity: float = 0.0
    volume_trend: float = 0.0
    bollinger_position: float = 0.0
    gap_quality: float = 0.0

    @property
    def composite(self) -> float:
        """Weighted blend of sub-components."""
        return (
            self.trend_alignment * 0.25
            + self.momentum * 0.20
            + self.breakout_proximity * 0.20
            + self.volume_trend * 0.15
            + self.bollinger_position * 0.10
            + self.gap_quality * 0.10
        )


@dataclass
class LiveDetail:
    opening_range_break: float = 0.0
    vwap_position: float = 0.0
    pullback_quality: float = 0.0
    time_of_day_factor: float = 0.0
    volume_confirmation: float = 0.0

    @property
    def composite(self) -> float:
        return (
            self.opening_range_break * 0.30
            + self.vwap_position * 0.25
            + self.pullback_quality * 0.15
            + self.time_of_day_factor * 0.15
            + self.volume_confirmation * 0.15
        )


@dataclass
class RegimeDetail:
    regime_alignment: float = 0.0
    regime_confidence: float = 0.0
    regime_persistence: float = 0.0

    @property
    def composite(self) -> float:
        return (
            self.regime_alignment * 0.50
            + self.regime_confidence * 0.30
            + self.regime_persistence * 0.20
        )


@dataclass
class NewsDetail:
    weighted_impact: float = 0.0
    freshness_decay: float = 0.0
    price_confirmation_bonus: float = 0.0

    @property
    def composite(self) -> float:
        return (
            self.weighted_impact * 0.50
            + self.freshness_decay * 0.30
            + self.price_confirmation_bonus * 0.20
        )


@dataclass
class ExecutionDetail:
    spread_estimate: float = 0.0
    liquidity_score: float = 0.0
    cost_efficiency: float = 0.0

    @property
    def composite(self) -> float:
        return (
            self.spread_estimate * 0.30
            + self.liquidity_score * 0.40
            + self.cost_efficiency * 0.30
        )


@dataclass
class ScoreBreakdown:
    """Full score card for a single stock at a point in time."""

    symbol: str
    timestamp: datetime

    premarket: PremarketDetail = field(default_factory=PremarketDetail)
    live: LiveDetail = field(default_factory=LiveDetail)
    regime: RegimeDetail = field(default_factory=RegimeDetail)
    news: NewsDetail = field(default_factory=NewsDetail)
    execution: ExecutionDetail = field(default_factory=ExecutionDetail)

    @property
    def premarket_score(self) -> float:
        return self.premarket.composite

    @property
    def live_score(self) -> float:
        return self.live.composite

    @property
    def regime_score(self) -> float:
        return self.regime.composite

    @property
    def news_score(self) -> float:
        return self.news.composite

    @property
    def execution_score(self) -> float:
        return self.execution.composite

    @property
    def final_score(self) -> float:
        return (
            self.premarket_score * 0.30
            + self.live_score * 0.25
            + self.regime_score * 0.20
            + self.news_score * 0.15
            + self.execution_score * 0.10
        )


# ── Component scorers ───────────────────────────────────────────────

def _score_premarket(df: pd.DataFrame, gap_pct: float = 0.0) -> PremarketDetail:
    """Score the overnight / pre-market setup from daily OHLCV data.

    Parameters
    ----------
    df : DataFrame
        Daily OHLCV with at least 200 rows for full EMA coverage.
    gap_pct : float
        Overnight gap as a percentage (positive = gap-up).
    """
    close = df["Close"]
    detail = PremarketDetail()

    # -- trend alignment (EMA stacking) --
    ema20 = ind.ema(close, 20)
    ema50 = ind.ema(close, 50)
    ema200 = ind.ema(close, 200)

    last_close = close.iloc[-1]
    e20, e50, e200 = ema20.iloc[-1], ema50.iloc[-1], ema200.iloc[-1]

    alignment = 0.0
    if e20 > e50:
        alignment += 30
    if e50 > e200:
        alignment += 30
    if last_close > e20:
        alignment += 20
    if last_close > e200:
        alignment += 20
    detail.trend_alignment = alignment

    # -- momentum: RSI sweet spot + short-term returns --
    rsi_val = ind.rsi(close, 14).iloc[-1]
    # Bullish sweet spot: 40-70
    if 40 <= rsi_val <= 70:
        rsi_score = 100 - abs(rsi_val - 55) * (100 / 15)  # peak at 55
    elif rsi_val < 40:
        rsi_score = normalize(rsi_val, 10, 40)
    else:
        rsi_score = normalize(100 - rsi_val, 0, 30)
    rsi_score = float(np.clip(rsi_score, 0, 100))

    ret5 = (close.iloc[-1] / close.iloc[-6] - 1) * 100 if len(close) >= 6 else 0
    ret20 = (close.iloc[-1] / close.iloc[-21] - 1) * 100 if len(close) >= 21 else 0
    returns_score = normalize(ret5 + ret20, -10, 20)

    detail.momentum = rsi_score * 0.6 + returns_score * 0.4

    # -- breakout proximity --
    high20 = close.rolling(20).max().iloc[-1]
    high52w = close.rolling(252).max().iloc[-1] if len(close) >= 252 else high20
    dist20 = (last_close / high20 - 1) * 100  # negative = below
    dist52 = (last_close / high52w - 1) * 100

    # Closer to high = higher score
    detail.breakout_proximity = (
        normalize(dist20, -15, 0) * 0.6 + normalize(dist52, -30, 0) * 0.4
    )

    # -- volume trend --
    vol = df["Volume"]
    avg5 = vol.iloc[-5:].mean()
    avg20 = vol.iloc[-20:].mean() if len(vol) >= 20 else avg5
    vol_ratio = avg5 / avg20 if avg20 > 0 else 1
    detail.volume_trend = normalize(vol_ratio, 0.5, 2.0)

    # -- bollinger position --
    mid, upper, lower = ind.bbands(close, 20, 2)
    bb_range = (upper.iloc[-1] - lower.iloc[-1])
    if bb_range > 0:
        bb_pos = (last_close - lower.iloc[-1]) / bb_range
        # Score peaks when price is in upper half but not overextended
        detail.bollinger_position = normalize(bb_pos, 0, 1) if bb_pos <= 1 else normalize(2 - bb_pos, 0, 1)
    else:
        detail.bollinger_position = 50.0

    # -- gap quality --
    # Moderate gaps (0.5-3%) are healthy; extreme gaps are risky
    abs_gap = abs(gap_pct)
    if 0.5 <= abs_gap <= 3.0:
        gap_score = 80 + normalize(abs_gap, 0.5, 3.0) * 0.2
    elif abs_gap < 0.5:
        gap_score = normalize(abs_gap, 0, 0.5) * 0.8
    else:
        gap_score = max(0, 100 - (abs_gap - 3) * 15)
    # Penalise gap-downs for bullish bias
    if gap_pct < 0:
        gap_score *= 0.5
    detail.gap_quality = float(np.clip(gap_score, 0, 100))

    return detail


def _score_live(
    intraday_df: pd.DataFrame,
    current_time: Optional[datetime] = None,
) -> LiveDetail:
    """Score intraday confirmation signals.

    Parameters
    ----------
    intraday_df : DataFrame
        Intraday OHLCV bars (e.g. 1-min or 5-min).
    current_time : datetime, optional
        Evaluation timestamp; defaults to last bar's index.
    """
    detail = LiveDetail()

    if intraday_df.empty or len(intraday_df) < 2:
        return detail

    close = intraday_df["Close"]
    volume = intraday_df["Volume"]
    current_time = current_time or intraday_df.index[-1]

    # -- opening range break --
    # First 15 minutes ~ first 3 bars for 5-min data, 15 bars for 1-min
    n_opening = min(15, len(intraday_df))
    opening_slice = intraday_df.iloc[:n_opening]
    or_high = opening_slice["High"].max()
    or_low = opening_slice["Low"].min()
    last_price = close.iloc[-1]

    if or_high != or_low:
        if last_price > or_high:
            orb_pct = (last_price - or_high) / (or_high - or_low)
            detail.opening_range_break = normalize(orb_pct, 0, 2) * 0.8 + 20
        elif last_price < or_low:
            # Bearish break — could be useful for shorts, score moderately
            detail.opening_range_break = 30.0
        else:
            detail.opening_range_break = normalize(
                (last_price - or_low) / (or_high - or_low), 0, 1
            ) * 0.5

    # -- VWAP position --
    vwap_vals = ind.vwap(intraday_df)
    vwap_last = vwap_vals.iloc[-1]
    if vwap_last > 0:
        vwap_dist_pct = (last_price / vwap_last - 1) * 100
        # Above VWAP is bullish; score 50 at VWAP, 100 at +1%
        detail.vwap_position = normalize(vwap_dist_pct, -1.0, 1.0)

    # -- pullback quality --
    if len(close) > n_opening:
        post_open = close.iloc[n_opening:]
        if len(post_open) >= 3:
            peak = post_open.max()
            trough = post_open.min()
            move = peak - or_high if peak > or_high else 0
            pullback = peak - last_price
            if move > 0:
                retracement = pullback / move
                # 30-60% retracement is ideal
                if 0.3 <= retracement <= 0.6:
                    detail.pullback_quality = 90.0
                elif retracement < 0.3:
                    detail.pullback_quality = normalize(retracement, 0, 0.3) * 0.7 + 30
                else:
                    detail.pullback_quality = max(0, 90 - (retracement - 0.6) * 200)

    # -- time of day factor --
    if hasattr(current_time, "hour"):
        hour = current_time.hour
        minute = current_time.minute
        t = hour + minute / 60.0

        if 9.25 <= t <= 10.5:
            # Opening hour — best
            detail.time_of_day_factor = 90.0
        elif 14.5 <= t <= 15.5:
            # Closing hour — good
            detail.time_of_day_factor = 80.0
        elif 10.5 <= t <= 11.5:
            detail.time_of_day_factor = 65.0
        elif 11.5 <= t <= 13.5:
            # Midday chop — penalty
            detail.time_of_day_factor = 30.0
        else:
            detail.time_of_day_factor = 55.0
    else:
        detail.time_of_day_factor = 50.0

    # -- volume confirmation --
    avg_vol = volume.mean()
    current_vol = volume.iloc[-1]
    if avg_vol > 0:
        vol_ratio = current_vol / avg_vol
        detail.volume_confirmation = normalize(vol_ratio, 0.3, 3.0)

    return detail


def _score_regime(
    regime: str,
    signal_direction: str,
    regime_confidence_pct: float = 50.0,
    regime_days: int = 1,
) -> RegimeDetail:
    """Score how well a signal aligns with the current market regime.

    Parameters
    ----------
    regime : str
        One of 'trending_up', 'trending_down', 'range_bound', 'volatile'.
    signal_direction : str
        'long' or 'short'.
    regime_confidence_pct : float
        0-100 confidence in regime classification.
    regime_days : int
        Number of sessions the regime has persisted.
    """
    detail = RegimeDetail()

    alignment_map = {
        ("trending_up", "long"): 100,
        ("trending_up", "short"): 10,
        ("trending_down", "short"): 100,
        ("trending_down", "long"): 10,
        ("range_bound", "long"): 50,
        ("range_bound", "short"): 50,
        ("volatile", "long"): 35,
        ("volatile", "short"): 35,
    }
    detail.regime_alignment = alignment_map.get(
        (regime.lower(), signal_direction.lower()), 50.0
    )

    detail.regime_confidence = float(np.clip(regime_confidence_pct, 0, 100))

    # Persistence: regimes lasting 5-20 days are most reliable
    detail.regime_persistence = normalize(regime_days, 1, 20)

    return detail


def _score_news(
    weighted_impact: float,
    news_age_hours: float,
    price_confirmed: bool = False,
) -> NewsDetail:
    """Score catalyst / news presence.

    Parameters
    ----------
    weighted_impact : float
        Raw impact score from news ranker (0-100).
    news_age_hours : float
        Hours since the news was published.
    price_confirmed : bool
        Whether price has moved in the direction implied by the news.
    """
    detail = NewsDetail()

    detail.weighted_impact = float(np.clip(weighted_impact, 0, 100))

    # Exponential freshness decay, half-life = 4 hours
    half_life = 4.0
    decay = math.exp(-0.693 * news_age_hours / half_life)  # ln(2) ~ 0.693
    detail.freshness_decay = decay * 100

    detail.price_confirmation_bonus = 100.0 if price_confirmed else 0.0

    return detail


def _score_execution(
    price: float,
    avg_volume: float,
    position_qty: int,
    target_profit_pct: float,
    spread_pct: float = 0.05,
    cost_per_share: float = 0.0,
) -> ExecutionDetail:
    """Score execution feasibility.

    Parameters
    ----------
    price : float
        Current price of the instrument.
    avg_volume : float
        Average daily volume.
    position_qty : int
        Intended position size in shares.
    target_profit_pct : float
        Target profit as a percentage of entry price.
    spread_pct : float
        Estimated bid-ask spread as % of price.
    cost_per_share : float
        Estimated round-trip brokerage + charges per share.
    """
    detail = ExecutionDetail()

    # Spread: lower is better.  0.01% = excellent, 0.20% = poor
    detail.spread_estimate = normalize(0.20 - spread_pct, 0, 0.19) if spread_pct <= 0.20 else 0.0

    # Liquidity: can we fill within 1% of avg volume?
    if avg_volume > 0:
        fill_pct = position_qty / avg_volume * 100
        # <0.5% of avg vol = excellent; >5% = dangerous
        detail.liquidity_score = normalize(5 - fill_pct, 0, 5)
    else:
        detail.liquidity_score = 0.0

    # Cost efficiency: round-trip cost as % of target profit
    if target_profit_pct > 0 and price > 0:
        cost_pct = (cost_per_share / price) * 100
        ratio = cost_pct / target_profit_pct  # fraction of profit eaten by costs
        # <5% excellent, >50% terrible
        detail.cost_efficiency = normalize(50 - ratio * 100, 0, 50)
    else:
        detail.cost_efficiency = 0.0

    return detail


# ── Public API ───────────────────────────────────────────────────────

def score_stock(
    symbol: str,
    daily_df: pd.DataFrame,
    intraday_df: Optional[pd.DataFrame] = None,
    gap_pct: float = 0.0,
    regime: str = "range_bound",
    signal_direction: str = "long",
    regime_confidence_pct: float = 50.0,
    regime_days: int = 1,
    news_impact: float = 0.0,
    news_age_hours: float = 24.0,
    price_confirmed: bool = False,
    position_qty: int = 1,
    target_profit_pct: float = 1.0,
    spread_pct: float = 0.05,
    cost_per_share: float = 0.0,
    timestamp: Optional[datetime] = None,
) -> ScoreBreakdown:
    """Compute a full ScoreBreakdown for a single stock.

    This is the main entry point.  Callers provide the data they have;
    missing intraday data simply leaves the live component at zero.
    """
    ts = timestamp or datetime.utcnow()

    sb = ScoreBreakdown(symbol=symbol, timestamp=ts)
    sb.premarket = _score_premarket(daily_df, gap_pct)

    if intraday_df is not None and not intraday_df.empty:
        sb.live = _score_live(intraday_df, current_time=ts)

    sb.regime = _score_regime(regime, signal_direction, regime_confidence_pct, regime_days)
    sb.news = _score_news(news_impact, news_age_hours, price_confirmed)

    price = daily_df["Close"].iloc[-1]
    avg_vol = daily_df["Volume"].iloc[-20:].mean() if len(daily_df) >= 20 else daily_df["Volume"].mean()
    sb.execution = _score_execution(
        price, avg_vol, position_qty, target_profit_pct, spread_pct, cost_per_share,
    )

    return sb


def confidence_to_position_size(
    final_score: float,
    capital: float,
    max_risk_pct: float = 2.0,
) -> float:
    """Map a 0-100 confidence score to a position size in rupees.

    Logic
    -----
    - Below 40: no position.
    - 40-60: 25% of max risk allocation.
    - 60-75: 50%.
    - 75-85: 75%.
    - 85+:   100%.

    The "max risk allocation" is ``capital * max_risk_pct / 100``.
    """
    max_alloc = capital * max_risk_pct / 100

    if final_score < 40:
        return 0.0
    elif final_score < 60:
        return max_alloc * 0.25
    elif final_score < 75:
        return max_alloc * 0.50
    elif final_score < 85:
        return max_alloc * 0.75
    else:
        return max_alloc
