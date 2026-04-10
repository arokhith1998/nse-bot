"""
Technical indicator library for NSE Market Intelligence.

All functions operate on pandas Series or DataFrames and return
pandas Series or scalar floats.  No external dependencies beyond
pandas and numpy.

DataFrame inputs are expected to have columns:
    Open, High, Low, Close, Volume  (title-case)
"""

from __future__ import annotations

import numpy as np
import pandas as pd


# ── Trend ────────────────────────────────────────────────────────────

def ema(series: pd.Series, period: int) -> pd.Series:
    """Exponential Moving Average.

    Uses the standard span-based smoothing factor: alpha = 2 / (period + 1).
    The first *period* values use an expanding window so the output length
    matches the input length.
    """
    return series.ewm(span=period, adjust=False).mean()


def sma(series: pd.Series, period: int) -> pd.Series:
    """Simple Moving Average.

    Returns NaN for the first (period - 1) bars.
    """
    return series.rolling(window=period).mean()


# ── Momentum ─────────────────────────────────────────────────────────

def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Relative Strength Index (Wilder smoothing).

    Returns a Series on a 0-100 scale.
    """
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def stochastic_k(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Stochastic %K (fast).

    %K = (Close - Lowest Low) / (Highest High - Lowest Low) * 100
    """
    low_min = df["Low"].rolling(window=period).min()
    high_max = df["High"].rolling(window=period).max()
    denom = (high_max - low_min).replace(0, np.nan)
    return ((df["Close"] - low_min) / denom) * 100


def stochastic_d(df: pd.DataFrame, k_period: int = 14, d_period: int = 3) -> pd.Series:
    """Stochastic %D — SMA of %K."""
    k = stochastic_k(df, period=k_period)
    return sma(k, d_period)


# ── Volatility ───────────────────────────────────────────────────────

def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range (Wilder smoothing)."""
    high = df["High"]
    low = df["Low"]
    prev_close = df["Close"].shift(1)

    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)

    return tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()


def bbands(
    series: pd.Series,
    period: int = 20,
    num_std: float = 2,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Bollinger Bands.

    Returns (middle, upper, lower).
    """
    middle = sma(series, period)
    std = series.rolling(window=period).std()
    upper = middle + num_std * std
    lower = middle - num_std * std
    return middle, upper, lower


def supertrend(
    df: pd.DataFrame,
    period: int = 10,
    multiplier: float = 3,
) -> pd.Series:
    """Supertrend indicator.

    Returns a Series whose value is the supertrend level.  When the close
    is above the supertrend the trend is bullish; when below, bearish.
    """
    atr_vals = atr(df, period)
    hl2 = (df["High"] + df["Low"]) / 2

    upper_band = hl2 + multiplier * atr_vals
    lower_band = hl2 - multiplier * atr_vals

    close = df["Close"]
    st = pd.Series(np.nan, index=df.index, dtype=float)
    direction = pd.Series(1, index=df.index, dtype=int)  # 1 = up, -1 = down

    final_upper = upper_band.copy()
    final_lower = lower_band.copy()

    for i in range(1, len(df)):
        # Carry forward tighter bands
        if lower_band.iat[i] > final_lower.iat[i - 1] or close.iat[i - 1] < final_lower.iat[i - 1]:
            final_lower.iat[i] = lower_band.iat[i]
        else:
            final_lower.iat[i] = final_lower.iat[i - 1]

        if upper_band.iat[i] < final_upper.iat[i - 1] or close.iat[i - 1] > final_upper.iat[i - 1]:
            final_upper.iat[i] = upper_band.iat[i]
        else:
            final_upper.iat[i] = final_upper.iat[i - 1]

        # Determine direction
        if direction.iat[i - 1] == 1:
            if close.iat[i] < final_lower.iat[i]:
                direction.iat[i] = -1
            else:
                direction.iat[i] = 1
        else:
            if close.iat[i] > final_upper.iat[i]:
                direction.iat[i] = 1
            else:
                direction.iat[i] = -1

        st.iat[i] = final_lower.iat[i] if direction.iat[i] == 1 else final_upper.iat[i]

    return st


# ── MACD ─────────────────────────────────────────────────────────────

def macd(
    series: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Moving Average Convergence Divergence.

    Returns (macd_line, signal_line, histogram).
    """
    fast_ema = ema(series, fast)
    slow_ema = ema(series, slow)
    macd_line = fast_ema - slow_ema
    signal_line = ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


# ── Volume ───────────────────────────────────────────────────────────

def vwap(df: pd.DataFrame) -> pd.Series:
    """Volume Weighted Average Price (intraday cumulative).

    Assumes the DataFrame covers a single trading session.
    """
    typical_price = (df["High"] + df["Low"] + df["Close"]) / 3
    cum_tp_vol = (typical_price * df["Volume"]).cumsum()
    cum_vol = df["Volume"].cumsum().replace(0, np.nan)
    return cum_tp_vol / cum_vol


def obv(df: pd.DataFrame) -> pd.Series:
    """On Balance Volume.

    Cumulative volume where up-closes add and down-closes subtract.
    """
    direction = np.sign(df["Close"].diff()).fillna(0)
    return (direction * df["Volume"]).cumsum()


# ── Directional ──────────────────────────────────────────────────────

def adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average Directional Index.

    Returns a Series on a 0-100 scale indicating trend strength.
    """
    high = df["High"]
    low = df["Low"]
    close = df["Close"]

    plus_dm = high.diff().clip(lower=0)
    minus_dm = (-low.diff()).clip(lower=0)

    # Zero out whichever DM is smaller
    both = pd.DataFrame({"plus": plus_dm, "minus": minus_dm})
    plus_dm = both["plus"].where(both["plus"] > both["minus"], 0)
    minus_dm = both["minus"].where(both["minus"] > both["plus"], 0)

    atr_vals = atr(df, period)

    smooth_plus = plus_dm.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    smooth_minus = minus_dm.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()

    plus_di = 100 * smooth_plus / atr_vals.replace(0, np.nan)
    minus_di = 100 * smooth_minus / atr_vals.replace(0, np.nan)

    dx = (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan) * 100
    return dx.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
