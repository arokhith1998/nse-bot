"""
regime_engine.py
================
Market regime classifier for the NSE Market Intelligence platform.

Classifies the current market environment into one of seven regimes and returns
scoring adjustments that the pick generator uses to reweight its components.

Usage:
    from backend.modules.market_data_provider import CompositeProvider
    from backend.modules.regime_engine import RegimeEngine

    engine = RegimeEngine(provider=CompositeProvider())
    state  = engine.classify()
    mods   = engine.get_scoring_modifiers(state.label)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Regime taxonomy
# ---------------------------------------------------------------------------

class Regime(Enum):
    """Enumeration of recognised market regimes."""
    TREND_UP       = "trend_up"
    TREND_DOWN     = "trend_down"
    RANGE_CHOP     = "range_chop"
    GAP_AND_GO     = "gap_and_go"
    GAP_FILL       = "gap_fill"
    HIGH_VOL_EVENT = "high_vol_event"
    LOW_LIQ_DRIFT  = "low_liq_drift"


@dataclass
class RegimeState:
    """Snapshot of the current classified regime."""
    label: Regime
    sub_regime: str = ""
    confidence: float = 0.0
    scoring_adjustments: Dict[str, float] = field(default_factory=dict)
    nifty_price: float = 0.0
    ema20: float = 0.0
    ema50: float = 0.0
    vix: float = 0.0
    adx: float = 0.0
    breadth_pct: float = 0.0
    gap_pct: float = 0.0
    volume_ratio: float = 1.0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    notes: str = ""


@dataclass
class RegimeSnapshot:
    """Historical regime record for audit / analysis."""
    date: str
    state: RegimeState


# ---------------------------------------------------------------------------
# Scoring modifiers per regime
# ---------------------------------------------------------------------------

_REGIME_MODIFIERS: Dict[Regime, Dict[str, float]] = {
    Regime.TREND_UP: {
        "trend": 1.2,
        "momentum": 1.15,
        "volume": 1.0,
        "breakout": 1.2,
        "volatility": 1.0,
        "liquidity": 1.0,
        "news": 1.0,
        "stoch": 0.9,
        "bbands": 0.9,
        "gap": 1.1,
        "sentiment": 1.1,
    },
    Regime.TREND_DOWN: {
        "trend": 0.5,
        "momentum": 0.6,
        "volume": 1.1,
        "breakout": 0.4,
        "volatility": 1.3,
        "liquidity": 1.2,
        "news": 1.3,
        "stoch": 1.2,
        "bbands": 1.2,
        "gap": 0.7,
        "sentiment": 1.3,
    },
    Regime.RANGE_CHOP: {
        "trend": 0.6,
        "momentum": 0.7,
        "volume": 0.9,
        "breakout": 0.5,
        "volatility": 1.2,
        "liquidity": 1.0,
        "news": 1.0,
        "stoch": 1.3,
        "bbands": 1.3,
        "gap": 0.8,
        "sentiment": 0.9,
    },
    Regime.GAP_AND_GO: {
        "trend": 1.0,
        "momentum": 1.3,
        "volume": 1.3,
        "breakout": 1.2,
        "volatility": 1.0,
        "liquidity": 1.0,
        "news": 1.2,
        "stoch": 0.8,
        "bbands": 0.8,
        "gap": 1.5,
        "sentiment": 1.1,
    },
    Regime.GAP_FILL: {
        "trend": 0.8,
        "momentum": 0.7,
        "volume": 1.1,
        "breakout": 0.6,
        "volatility": 1.2,
        "liquidity": 1.0,
        "news": 0.9,
        "stoch": 1.2,
        "bbands": 1.3,
        "gap": 0.5,
        "sentiment": 0.8,
    },
    Regime.HIGH_VOL_EVENT: {
        "trend": 0.5,
        "momentum": 0.5,
        "volume": 1.3,
        "breakout": 0.4,
        "volatility": 1.5,
        "liquidity": 1.3,
        "news": 1.5,
        "stoch": 1.0,
        "bbands": 1.0,
        "gap": 0.6,
        "sentiment": 1.4,
    },
    Regime.LOW_LIQ_DRIFT: {
        "trend": 1.0,
        "momentum": 0.8,
        "volume": 0.6,
        "breakout": 0.7,
        "volatility": 0.8,
        "liquidity": 1.5,
        "news": 1.0,
        "stoch": 1.0,
        "bbands": 1.0,
        "gap": 0.9,
        "sentiment": 0.9,
    },
}


# ---------------------------------------------------------------------------
# Helper TA functions (self-contained to avoid circular imports)
# ---------------------------------------------------------------------------

def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def _adx(df: pd.DataFrame, period: int = 14) -> float:
    """Compute the latest ADX value from an OHLCV DataFrame."""
    high = df["High"]
    low = df["Low"]
    close = df["Close"]

    plus_dm = high.diff()
    minus_dm = -low.diff()
    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)

    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    atr = tr.rolling(period).mean()
    plus_di = 100 * (plus_dm.rolling(period).mean() / atr.replace(0, np.nan))
    minus_di = 100 * (minus_dm.rolling(period).mean() / atr.replace(0, np.nan))

    dx = (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan) * 100
    adx_val = dx.rolling(period).mean()
    latest = adx_val.iloc[-1]
    return float(latest) if not np.isnan(latest) else 20.0


def _compute_breadth(
    advances: int,
    declines: int,
) -> float:
    """Return advance percentage (0-100)."""
    total = advances + declines
    if total == 0:
        return 50.0
    return round(advances / total * 100, 2)


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class RegimeEngine:
    """Classifies the prevailing NSE market regime.

    Parameters
    ----------
    provider : MarketDataProvider
        Any concrete provider (typically CompositeProvider).
    nifty_symbol : str
        Nifty 50 index symbol for the provider (default ``^NSEI`` for yfinance).
    vix_symbol : str
        India VIX symbol (default ``^INDIAVIX`` for yfinance).
    """

    def __init__(
        self,
        provider=None,  # MarketDataProvider (deferred to avoid circular import)
        nifty_symbol: str = "^NSEI",
        vix_symbol: str = "^INDIAVIX",
    ) -> None:
        self._provider = provider
        self._nifty_sym = nifty_symbol
        self._vix_sym = vix_symbol
        self._history: List[RegimeSnapshot] = []

    # -- public API ----------------------------------------------------------

    def classify(self) -> RegimeState:
        """Run regime classification and return a ``RegimeState``."""
        nifty_df = self._fetch_nifty_history()
        vix_val = self._fetch_vix()
        breadth = self._estimate_breadth(nifty_df)

        if nifty_df is None or nifty_df.empty:
            logger.warning("No Nifty history available; defaulting to RANGE_CHOP")
            return RegimeState(
                label=Regime.RANGE_CHOP,
                confidence=0.3,
                notes="No index data available",
            )

        close = nifty_df["Close"]
        volume = nifty_df["Volume"]
        open_ = nifty_df["Open"]

        nifty_price = float(close.iloc[-1])
        ema20 = float(_ema(close, 20).iloc[-1])
        ema50 = float(_ema(close, 50).iloc[-1])
        adx_val = _adx(nifty_df)
        avg_vol_20 = float(volume.tail(20).mean()) if len(volume) >= 20 else float(volume.mean())
        vol_ratio = float(volume.iloc[-1]) / max(avg_vol_20, 1)
        gap_pct = (
            (float(open_.iloc[-1]) - float(close.iloc[-2])) / float(close.iloc[-2]) * 100
            if len(close) > 1 else 0.0
        )

        # --- Decision tree ---------------------------------------------------
        regime = Regime.RANGE_CHOP
        sub = ""
        confidence = 0.5

        # 1. HIGH_VOL_EVENT: VIX > 25 or VIX spike > 15%
        if vix_val > 25:
            regime = Regime.HIGH_VOL_EVENT
            sub = "elevated_vix"
            confidence = min(0.95, 0.6 + (vix_val - 25) * 0.02)
        elif self._vix_spike(nifty_df, vix_val):
            regime = Regime.HIGH_VOL_EVENT
            sub = "vix_spike"
            confidence = 0.7

        # 2. GAP scenarios (override if gap is large)
        elif abs(gap_pct) >= 0.5:
            # Determine follow-through vs reversal
            if self._has_gap_follow_through(nifty_df, gap_pct):
                regime = Regime.GAP_AND_GO
                sub = "gap_up" if gap_pct > 0 else "gap_down_follow"
                confidence = 0.7
            else:
                regime = Regime.GAP_FILL
                sub = "gap_fill_reversal"
                confidence = 0.65

        # 3. LOW_LIQ_DRIFT: volume < 70% of 20d avg and narrow range
        elif vol_ratio < 0.70:
            high_low_range = (float(nifty_df["High"].iloc[-1]) - float(nifty_df["Low"].iloc[-1])) / nifty_price * 100
            if high_low_range < 0.8:
                regime = Regime.LOW_LIQ_DRIFT
                sub = "thin_volume_narrow_range"
                confidence = 0.6

        # 4. TREND_UP
        elif nifty_price > ema20 > ema50 and vix_val < 18 and breadth > 60:
            regime = Regime.TREND_UP
            sub = "strong" if adx_val > 25 else "mild"
            confidence = min(0.95, 0.6 + (breadth - 60) * 0.005 + (25 - vix_val) * 0.01)

        # 5. TREND_DOWN
        elif nifty_price < ema20 < ema50 and vix_val > 22 and breadth < 40:
            regime = Regime.TREND_DOWN
            sub = "strong" if adx_val > 25 else "mild"
            confidence = min(0.95, 0.6 + (40 - breadth) * 0.005 + (vix_val - 22) * 0.01)

        # 6. RANGE_CHOP (default / fallback)
        else:
            regime = Regime.RANGE_CHOP
            sub = "low_adx" if adx_val < 20 else "mixed_signals"
            confidence = 0.5

        modifiers = _REGIME_MODIFIERS.get(regime, {})

        state = RegimeState(
            label=regime,
            sub_regime=sub,
            confidence=round(confidence, 3),
            scoring_adjustments=modifiers,
            nifty_price=round(nifty_price, 2),
            ema20=round(ema20, 2),
            ema50=round(ema50, 2),
            vix=round(vix_val, 2),
            adx=round(adx_val, 2),
            breadth_pct=round(breadth, 2),
            gap_pct=round(gap_pct, 2),
            volume_ratio=round(vol_ratio, 2),
        )

        self._history.append(RegimeSnapshot(
            date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            state=state,
        ))

        return state

    def get_scoring_modifiers(self, regime: Regime) -> Dict[str, float]:
        """Return weight multipliers for a given regime."""
        return dict(_REGIME_MODIFIERS.get(regime, {}))

    def get_regime_history(self, days: int = 20) -> List[RegimeSnapshot]:
        """Return the last *days* regime snapshots (in-memory)."""
        return self._history[-days:]

    # -- internal helpers ----------------------------------------------------

    def _fetch_nifty_history(self) -> Optional[pd.DataFrame]:
        if self._provider is None:
            return None
        try:
            # For yfinance, ^NSEI needs special handling (no .NS suffix)
            import yfinance as yf
            df = yf.Ticker(self._nifty_sym).history(period="120d", interval="1d", auto_adjust=False)
            if df is not None and not df.empty:
                return df.rename(columns=str.title)
        except Exception:
            pass
        # Fallback to provider
        return self._provider.get_history(self._nifty_sym, days=100, interval="1d")

    def _fetch_vix(self) -> float:
        """Return India VIX value; default 16.0 on failure."""
        try:
            import yfinance as yf
            tkr = yf.Ticker(self._vix_sym)
            info = tkr.fast_info
            val = float(getattr(info, "last_price", 0) or 0)
            if val > 0:
                return val
        except Exception:
            pass
        return 16.0  # safe default when VIX unavailable

    def _vix_spike(self, nifty_df: pd.DataFrame, current_vix: float) -> bool:
        """Heuristic: VIX spike > 15 % above its own 5-day mean.

        Since we may not have a VIX time-series, this is a placeholder that
        returns True when VIX > 20 (moderate stress).
        """
        # TODO: maintain a VIX history series for proper spike detection
        return current_vix > 20

    def _estimate_breadth(self, nifty_df: Optional[pd.DataFrame]) -> float:
        """Estimate market breadth (advance % of Nifty 50 constituents).

        Without live breadth data we proxy using Nifty close vs EMAs:
        - price > EMA20 => positive breadth proxy
        """
        # TODO: Fetch actual advance/decline ratio from NSE
        if nifty_df is None or nifty_df.empty:
            return 50.0
        close = nifty_df["Close"]
        ema20 = _ema(close, 20).iloc[-1]
        ema50 = _ema(close, 50).iloc[-1]
        price = float(close.iloc[-1])
        # Simple heuristic mapping
        if price > ema20 > ema50:
            return 65.0
        if price < ema20 < ema50:
            return 35.0
        return 50.0

    @staticmethod
    def _has_gap_follow_through(df: pd.DataFrame, gap_pct: float) -> bool:
        """Check if the gap had volume follow-through (heuristic).

        We consider follow-through when the close is on the same side as the
        gap direction relative to the open.
        """
        if len(df) < 2:
            return False
        latest_open = float(df["Open"].iloc[-1])
        latest_close = float(df["Close"].iloc[-1])
        if gap_pct > 0:
            return latest_close > latest_open  # closed above open
        else:
            return latest_close < latest_open  # closed below open
