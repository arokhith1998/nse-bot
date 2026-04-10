"""
engine.py
=========
Core historical backtesting engine for the NSE Market Intelligence platform.

Replays daily OHLCV bars, applies the same scoring / signal-routing / cost-model
logic used in live trading, simulates intraday fills against daily OHLC, and
produces comprehensive performance analytics.

PAPER TRADING ONLY.  Not investment advice.
"""
from __future__ import annotations

import logging
import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from backend.services import indicators as ind
from backend.services.scoring import score_stock, ScoreBreakdown
from backend.services.cost_model import (
    groww_intraday_cost,
    zerodha_intraday_cost,
    CostBreakdown,
)
from backend.modules.signal_router import SignalRouter, SetupType, RegimeLabel
from backend.backtester.data_loader import (
    load_nifty50_symbols,
    load_nifty200_symbols,
    load_benchmark,
    preload_universe,
    NIFTY50_SYMBOLS,
    NIFTY200_SYMBOLS,
)

logger = logging.getLogger(__name__)

# Default scoring weights (mirrors weights.json defaults)
_DEFAULT_WEIGHTS: Dict[str, float] = {
    "trend": 0.15,
    "momentum": 0.15,
    "volume": 0.10,
    "breakout": 0.15,
    "volatility": 0.10,
    "liquidity": 0.05,
    "news": 0.05,
    "stoch": 0.05,
    "bbands": 0.05,
    "gap": 0.10,
    "sentiment": 0.05,
}

# Risk-free rate for Sharpe / Sortino (annualised, India 10Y benchmark)
_RISK_FREE_ANNUAL = 0.06


# ═══════════════════════════════════════════════════════════════════════
# Dataclasses
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class BacktestConfig:
    """All tuneable parameters for a backtest run."""

    symbols: Any = "nifty50"                # List[str] | "nifty50" | "nifty200" | "full"
    start_date: date = date(2025, 1, 1)
    end_date: date = date(2026, 4, 10)
    capital: float = 100_000.0
    risk_per_trade_pct: float = 1.0
    max_open_positions: int = 6
    slippage_pct: float = 0.05              # 0.05% adverse slippage on entry
    cost_model: str = "groww"               # "groww" | "zerodha"
    top_n: int = 6                          # max picks per day
    use_regime_filter: bool = True
    walk_forward: bool = False              # TODO: expanding-window weight learning
    weights: Optional[Dict[str, float]] = None
    benchmark: str = "^NSEI"                # Yahoo Finance benchmark symbol


@dataclass
class BacktestTrade:
    """Full record of a single simulated trade."""

    symbol: str
    entry_date: str                         # ISO date string
    exit_date: str
    entry_price: float
    exit_price: float
    qty: int
    direction: str = "LONG"
    setup_type: str = ""
    regime_at_entry: str = ""
    gross_pnl: float = 0.0
    net_pnl: float = 0.0
    cost: float = 0.0
    pnl_pct: float = 0.0
    exit_reason: str = ""                   # stop_loss | target1 | target2 | eod_close
    holding_days: int = 1
    max_adverse_excursion_pct: float = 0.0  # worst drawdown during trade
    max_favorable_excursion_pct: float = 0.0  # best unrealised gain
    stop_loss: float = 0.0
    target1: float = 0.0
    target2: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """JSON-serialisable dict."""
        return {k: v for k, v in self.__dict__.items()}


@dataclass
class DailyEquity:
    """Equity curve data point."""

    date: str
    equity_value: float
    drawdown_pct: float = 0.0
    benchmark_value: float = 0.0


@dataclass
class SetupStats:
    """Performance breakdown per setup type."""

    trades: int = 0
    winners: int = 0
    losers: int = 0
    win_rate_pct: float = 0.0
    avg_pnl_pct: float = 0.0
    total_pnl: float = 0.0


@dataclass
class RegimeStats:
    """Performance breakdown per market regime."""

    trades: int = 0
    winners: int = 0
    losers: int = 0
    win_rate_pct: float = 0.0
    avg_pnl_pct: float = 0.0
    total_pnl: float = 0.0


@dataclass
class BacktestSummary:
    """Aggregate performance metrics."""

    total_trades: int = 0
    winners: int = 0
    losers: int = 0
    win_rate_pct: float = 0.0
    avg_win_pct: float = 0.0
    avg_loss_pct: float = 0.0
    profit_factor: float = 0.0
    total_pnl: float = 0.0
    total_pnl_pct: float = 0.0
    max_drawdown_pct: float = 0.0
    max_drawdown_duration_days: int = 0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    calmar_ratio: float = 0.0
    avg_trades_per_day: float = 0.0
    avg_holding_period: str = "1 day"
    best_month: str = ""
    worst_month: str = ""
    benchmark_return_pct: float = 0.0
    alpha_pct: float = 0.0
    beta: float = 0.0
    start_date: str = ""
    end_date: str = ""
    trading_days: int = 0


@dataclass
class BacktestResult:
    """Complete backtest output."""

    trades: List[BacktestTrade] = field(default_factory=list)
    daily_equity: List[DailyEquity] = field(default_factory=list)
    summary: BacktestSummary = field(default_factory=BacktestSummary)
    monthly_returns: Dict[str, float] = field(default_factory=dict)
    setup_breakdown: Dict[str, SetupStats] = field(default_factory=dict)
    regime_breakdown: Dict[str, RegimeStats] = field(default_factory=dict)
    best_trades: List[BacktestTrade] = field(default_factory=list)
    worst_trades: List[BacktestTrade] = field(default_factory=list)
    config: Optional[BacktestConfig] = None


# ═══════════════════════════════════════════════════════════════════════
# Internal helpers
# ═══════════════════════════════════════════════════════════════════════

def _classify_regime_from_df(nifty_df: pd.DataFrame, idx: int) -> Tuple[str, float]:
    """Classify market regime from Nifty 50 daily data up to bar *idx*.

    Returns (regime_label, confidence).  Uses a simplified version of the
    RegimeEngine decision tree operating on historical bars rather than
    live data.
    """
    if nifty_df is None or nifty_df.empty or idx < 50:
        return RegimeLabel.RANGE_CHOP.value, 0.5

    lookback = nifty_df.iloc[max(0, idx - 99) : idx + 1]
    close = lookback["Close"]
    volume = lookback["Volume"]
    open_ = lookback["Open"]

    if len(close) < 20:
        return RegimeLabel.RANGE_CHOP.value, 0.5

    price = float(close.iloc[-1])
    ema20 = float(close.ewm(span=20, adjust=False).mean().iloc[-1])
    ema50 = float(close.ewm(span=50, adjust=False).mean().iloc[-1])

    avg_vol_20 = float(volume.tail(20).mean()) if len(volume) >= 20 else float(volume.mean())
    vol_ratio = float(volume.iloc[-1]) / max(avg_vol_20, 1)

    gap_pct = 0.0
    if len(close) > 1:
        gap_pct = (float(open_.iloc[-1]) - float(close.iloc[-2])) / max(float(close.iloc[-2]), 1) * 100

    # Simplified decision tree
    if abs(gap_pct) > 1.5:
        return RegimeLabel.HIGH_VOL.value, 0.7
    if vol_ratio < 0.6:
        return RegimeLabel.LOW_VOL.value, 0.6
    if price > ema20 > ema50:
        return RegimeLabel.TREND_UP.value, 0.7
    if price < ema20 < ema50:
        return RegimeLabel.TREND_DOWN.value, 0.7

    return RegimeLabel.RANGE_CHOP.value, 0.5


def _compute_score_breakdown(
    df: pd.DataFrame,
    idx: int,
    weights: Dict[str, float],
) -> Tuple[Dict[str, float], float, float]:
    """Compute a simplified score breakdown from daily OHLCV up to bar *idx*.

    Returns (breakdown_dict, atr_value, last_close).
    """
    lookback = df.iloc[max(0, idx - 249) : idx + 1]
    close = lookback["Close"]
    high = lookback["High"]
    low = lookback["Low"]
    volume = lookback["Volume"]

    if len(close) < 20:
        return {}, 0.0, 0.0

    last_close = float(close.iloc[-1])

    # Trend: EMA alignment
    ema20 = float(close.ewm(span=20, adjust=False).mean().iloc[-1])
    ema50 = float(close.ewm(span=50, adjust=False).mean().iloc[-1])
    trend_score = 0.0
    if last_close > ema20:
        trend_score += 40
    if ema20 > ema50:
        trend_score += 40
    if last_close > ema50:
        trend_score += 20

    # Momentum: RSI
    rsi_s = ind.rsi(close, 14)
    rsi_val = float(rsi_s.iloc[-1]) if not np.isnan(rsi_s.iloc[-1]) else 50.0
    if 40 <= rsi_val <= 70:
        mom_score = 80.0
    elif rsi_val < 40:
        mom_score = max(0, rsi_val * 2)
    else:
        mom_score = max(0, (100 - rsi_val) * 2)

    # Volume
    avg_vol = float(volume.tail(20).mean()) if len(volume) >= 20 else float(volume.mean())
    recent_vol = float(volume.tail(5).mean())
    vol_ratio = recent_vol / max(avg_vol, 1)
    vol_score = min(100, max(0, (vol_ratio - 0.5) / 1.5 * 100))

    # Breakout proximity
    high20 = float(close.rolling(20).max().iloc[-1])
    dist = (last_close / max(high20, 1) - 1) * 100
    breakout_score = max(0, min(100, 100 + dist * 6.67))  # 0% at -15%, 100% at 0%

    # ATR / Volatility
    atr_s = ind.atr(lookback, 14)
    atr_val = float(atr_s.iloc[-1]) if not np.isnan(atr_s.iloc[-1]) else last_close * 0.02
    atr_pct = atr_val / max(last_close, 1) * 100
    # Sweet spot: 1-3% ATR
    if 1.0 <= atr_pct <= 3.0:
        vol_score_bb = 80.0
    elif atr_pct < 1.0:
        vol_score_bb = atr_pct / 1.0 * 60
    else:
        vol_score_bb = max(0, 100 - (atr_pct - 3) * 20)

    # Stochastic
    stoch_k_s = ind.stochastic_k(lookback, 14)
    stoch_val = float(stoch_k_s.iloc[-1]) if not np.isnan(stoch_k_s.iloc[-1]) else 50.0
    stoch_score = stoch_val  # 0-100 naturally

    # Bollinger position
    mid, upper, lower = ind.bbands(close, 20, 2)
    bb_range = float(upper.iloc[-1] - lower.iloc[-1])
    if bb_range > 0:
        bb_pos = (last_close - float(lower.iloc[-1])) / bb_range
        bb_score = min(100, max(0, bb_pos * 100))
    else:
        bb_score = 50.0

    # Gap
    if len(close) >= 2:
        gap = (float(lookback["Open"].iloc[-1]) - float(close.iloc[-2])) / max(float(close.iloc[-2]), 1) * 100
        abs_gap = abs(gap)
        if 0.5 <= abs_gap <= 3.0:
            gap_score = 80.0
        elif abs_gap < 0.5:
            gap_score = abs_gap / 0.5 * 60
        else:
            gap_score = max(0, 100 - (abs_gap - 3) * 20)
        if gap < 0:
            gap_score *= 0.5
    else:
        gap_score = 30.0

    # Liquidity (avg volume in shares * price = turnover proxy)
    turnover = avg_vol * last_close
    # Score higher for more liquid names
    liq_score = min(100, turnover / 1_000_000 * 10)  # 10M turnover = 100

    breakdown = {
        "trend": round(trend_score, 2),
        "momentum": round(mom_score, 2),
        "volume": round(vol_score, 2),
        "breakout": round(breakout_score, 2),
        "volatility": round(vol_score_bb, 2),
        "liquidity": round(liq_score, 2),
        "news": 0.0,       # no news data in backtest
        "stoch": round(stoch_score, 2),
        "bbands": round(bb_score, 2),
        "gap": round(gap_score, 2),
        "sentiment": 50.0,  # neutral default
    }

    return breakdown, atr_val, last_close


# ═══════════════════════════════════════════════════════════════════════
# BacktestEngine
# ═══════════════════════════════════════════════════════════════════════

class BacktestEngine:
    """Historical backtesting engine.

    Replays daily bars for the configured universe, generates signals using
    the same scoring pipeline as live trading, simulates fills with slippage,
    and tracks all trades with full P&L including transaction costs.

    Usage
    -----
    >>> from backend.backtester.engine import BacktestEngine, BacktestConfig
    >>> config = BacktestConfig(symbols="nifty50", start_date=date(2025, 1, 1))
    >>> engine = BacktestEngine(config)
    >>> result = engine.run()
    """

    def __init__(self, config: BacktestConfig) -> None:
        self.config = config
        self.weights = config.weights or dict(_DEFAULT_WEIGHTS)

        # Select cost function
        if config.cost_model.lower() == "zerodha":
            self._cost_fn = zerodha_intraday_cost
        else:
            self._cost_fn = groww_intraday_cost

        # Internal state
        self._universe: Dict[str, pd.DataFrame] = {}
        self._benchmark_df: pd.DataFrame = pd.DataFrame()
        self._trades: List[BacktestTrade] = []
        self._daily_equity: List[DailyEquity] = []
        self._cash: float = config.capital
        self._open_positions: List[Dict[str, Any]] = []

        # Progress callback (set externally for API/CLI progress reporting)
        self.on_progress: Optional[Any] = None

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def run(
        self,
        symbols: Optional[List[str]] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> BacktestResult:
        """Execute the full backtest and return results.

        Parameters
        ----------
        symbols : list[str], optional
            Override symbols from config.
        start_date : date, optional
            Override start date from config.
        end_date : date, optional
            Override end date from config.

        Returns
        -------
        BacktestResult
        """
        cfg = self.config
        start = start_date or cfg.start_date
        end = end_date or cfg.end_date
        sym_spec = symbols or cfg.symbols

        # Resolve symbol universe
        symbol_list = self._resolve_symbols(sym_spec)
        if not symbol_list:
            logger.error("No symbols to backtest.")
            return BacktestResult(config=cfg)

        logger.info(
            "Starting backtest: %d symbols, %s to %s, capital=%.0f",
            len(symbol_list), start, end, cfg.capital,
        )

        # Load data
        logger.info("Downloading universe data ...")
        self._universe = preload_universe(symbol_list, start, end)
        logger.info("Downloading benchmark data (%s) ...", cfg.benchmark)
        self._benchmark_df = load_benchmark(start, end, symbol=cfg.benchmark)

        if not self._universe:
            logger.error("No data loaded. Aborting backtest.")
            return BacktestResult(config=cfg)

        # Determine trading calendar from Nifty/benchmark
        trading_dates = self._build_trading_calendar(start, end)
        if not trading_dates:
            logger.error("No trading dates found in the date range.")
            return BacktestResult(config=cfg)

        logger.info("Simulating %d trading days ...", len(trading_dates))

        # Reset state
        self._cash = cfg.capital
        self._open_positions = []
        self._trades = []
        self._daily_equity = []

        # Signal router
        router = SignalRouter(
            weights=self.weights,
            capital=cfg.capital,
            risk_per_trade_pct=cfg.risk_per_trade_pct,
            atr_sl_mult=1.0,
            rr=2.0,
            top_n=cfg.top_n,
        )

        peak_equity = cfg.capital

        # ---- Day-by-day simulation ------------------------------------
        for day_idx, trade_date in enumerate(trading_dates):
            # Progress reporting
            if self.on_progress and day_idx % 10 == 0:
                pct = int(day_idx / len(trading_dates) * 100)
                self.on_progress(pct, f"Day {day_idx + 1}/{len(trading_dates)}")

            # 1. Classify regime from Nifty data
            regime_label, regime_conf = self._get_regime_for_date(trade_date)

            # 2. Close any open positions using today's OHLC
            self._simulate_exits(trade_date, regime_label)

            # 3. Score universe and generate new signals (if capacity)
            if len(self._open_positions) < cfg.max_open_positions:
                new_signals = self._generate_daily_signals(
                    trade_date, router, regime_label,
                )
                # 4. Simulate entries at today's open (next bar after signal)
                self._simulate_entries(trade_date, new_signals, regime_label)

            # 5. Record equity curve
            equity = self._compute_equity(trade_date)
            peak_equity = max(peak_equity, equity)
            dd_pct = (peak_equity - equity) / max(peak_equity, 1) * 100

            bm_val = self._benchmark_value_at(trade_date)
            self._daily_equity.append(DailyEquity(
                date=trade_date.isoformat(),
                equity_value=round(equity, 2),
                drawdown_pct=round(dd_pct, 4),
                benchmark_value=round(bm_val, 2),
            ))

        # Force-close remaining positions at last date
        if self._open_positions and trading_dates:
            self._force_close_all(trading_dates[-1])

        # Progress done
        if self.on_progress:
            self.on_progress(100, "Complete")

        # ---- Compile results ------------------------------------------
        result = self._compile_results(cfg, trading_dates)
        return result

    # ------------------------------------------------------------------
    # Symbol resolution
    # ------------------------------------------------------------------

    def _resolve_symbols(self, sym_spec: Any) -> List[str]:
        """Resolve symbol specification to a concrete list."""
        if isinstance(sym_spec, list):
            return sym_spec
        if isinstance(sym_spec, str):
            lower = sym_spec.lower()
            if lower == "nifty50":
                return load_nifty50_symbols()
            if lower == "nifty200":
                return load_nifty200_symbols()
            if lower == "full":
                return load_nifty200_symbols()
            # Treat as comma-separated
            return [s.strip().upper() for s in sym_spec.split(",") if s.strip()]
        return []

    # ------------------------------------------------------------------
    # Trading calendar
    # ------------------------------------------------------------------

    def _build_trading_calendar(self, start: date, end: date) -> List[date]:
        """Build a list of valid trading dates from the benchmark data."""
        if not self._benchmark_df.empty:
            dates = [d.date() if hasattr(d, 'date') else d for d in self._benchmark_df.index]
            return [d for d in dates if start <= d <= end]

        # Fallback: use any symbol's data
        for sym, df in self._universe.items():
            if not df.empty:
                dates = [d.date() if hasattr(d, 'date') else d for d in df.index]
                return [d for d in dates if start <= d <= end]
        return []

    # ------------------------------------------------------------------
    # Regime
    # ------------------------------------------------------------------

    def _get_regime_for_date(self, trade_date: date) -> Tuple[str, float]:
        """Classify regime from Nifty data up to *trade_date*."""
        if self._benchmark_df.empty:
            return RegimeLabel.RANGE_CHOP.value, 0.5

        # Find the index position for this date
        bm_dates = [d.date() if hasattr(d, 'date') else d for d in self._benchmark_df.index]
        matching = [i for i, d in enumerate(bm_dates) if d <= trade_date]
        if not matching:
            return RegimeLabel.RANGE_CHOP.value, 0.5

        idx = matching[-1]
        return _classify_regime_from_df(self._benchmark_df, idx)

    # ------------------------------------------------------------------
    # Signal generation
    # ------------------------------------------------------------------

    def _generate_daily_signals(
        self,
        trade_date: date,
        router: SignalRouter,
        regime: str,
    ) -> List[Dict[str, Any]]:
        """Score all symbols and return top-N signal dicts for *trade_date*.

        Each returned dict has keys: symbol, price, atr, score_breakdown,
        stop_loss, target1, target2, setup_type, qty.
        """
        cfg = self.config
        candidates: List[Dict[str, Any]] = []

        # Symbols already held
        held_symbols = {p["symbol"] for p in self._open_positions}

        for sym, df in self._universe.items():
            if sym in held_symbols:
                continue

            # Find bar index for trade_date
            df_dates = [d.date() if hasattr(d, 'date') else d for d in df.index]
            matching = [i for i, d in enumerate(df_dates) if d <= trade_date]
            if not matching:
                continue
            idx = matching[-1]

            # Need at least 50 bars for indicators
            if idx < 50:
                continue

            # Must have data ON this date (or at most 1 day prior)
            actual_date = df_dates[idx]
            if (trade_date - actual_date).days > 3:
                continue

            breakdown, atr_val, last_close = _compute_score_breakdown(df, idx, self.weights)
            if not breakdown or last_close <= 0 or atr_val <= 0:
                continue

            candidates.append({
                "symbol": sym,
                "price": last_close,
                "atr": atr_val,
                "score_breakdown": breakdown,
                "df_idx": idx,
            })

        if not candidates:
            return []

        # Use SignalRouter to score and rank
        signals = router.generate_signals(
            universe=candidates,
            regime=regime,
            news=None,
            now=datetime(trade_date.year, trade_date.month, trade_date.day, 9, 15),
        )

        # Convert Signal objects to dicts for entry simulation
        result = []
        for sig in signals:
            if sig.bias == "AVOID":
                continue

            # Regime filter
            if cfg.use_regime_filter and regime in (
                RegimeLabel.TREND_DOWN.value,
                RegimeLabel.HIGH_VOL.value,
            ):
                if sig.confidence_score < 70:
                    continue

            price = sig.entry_zone[1]  # upper end of entry zone
            stop = sig.invalidation
            t1 = sig.target1
            t2 = sig.target2

            if stop <= 0 or price <= 0:
                continue

            # Position sizing via risk budget
            risk_per_share = max(price - stop, 0.01)
            risk_budget = self._cash * cfg.risk_per_trade_pct / 100.0
            qty = max(1, int(risk_budget / risk_per_share))

            # Cap at 20% of current cash
            max_capital = self._cash * 0.20
            qty = min(qty, max(1, int(max_capital / price)))

            # Ensure we have enough cash
            required = qty * price
            if required > self._cash:
                qty = max(1, int(self._cash / price))
                if qty * price > self._cash:
                    continue

            result.append({
                "symbol": sig.symbol,
                "price": price,
                "stop_loss": stop,
                "target1": t1,
                "target2": t2,
                "setup_type": sig.setup_type,
                "qty": qty,
                "confidence": sig.confidence_score,
            })

        return result

    # ------------------------------------------------------------------
    # Entry simulation
    # ------------------------------------------------------------------

    def _simulate_entries(
        self,
        trade_date: date,
        signals: List[Dict[str, Any]],
        regime: str,
    ) -> None:
        """Simulate entries for new signals on *trade_date*.

        Entry is at today's Open + slippage (simulating next-bar-open entry
        after previous day's signal).  We use the *trade_date*'s Open price.
        """
        cfg = self.config

        for sig in signals:
            if len(self._open_positions) >= cfg.max_open_positions:
                break

            sym = sig["symbol"]
            df = self._universe.get(sym)
            if df is None or df.empty:
                continue

            # Find today's bar
            df_dates = [d.date() if hasattr(d, 'date') else d for d in df.index]
            matching = [i for i, d in enumerate(df_dates) if d == trade_date]
            if not matching:
                # Try next available bar
                matching = [i for i, d in enumerate(df_dates) if d >= trade_date]
                if not matching:
                    continue
            idx = matching[0]

            open_price = float(df.iloc[idx]["Open"])
            if open_price <= 0:
                continue

            # Apply slippage (adverse = buy higher)
            entry_price = round(open_price * (1 + cfg.slippage_pct / 100), 2)

            qty = sig["qty"]
            capital_needed = entry_price * qty
            if capital_needed > self._cash:
                qty = max(1, int(self._cash / entry_price))
                capital_needed = entry_price * qty
                if capital_needed > self._cash:
                    continue

            # Deduct cash
            self._cash -= capital_needed

            # Re-compute levels relative to actual entry
            atr_val = sig.get("atr", entry_price * 0.02)
            if atr_val <= 0:
                # Recompute from data
                lookback = df.iloc[max(0, idx - 19) : idx + 1]
                atr_s = ind.atr(lookback, 14)
                atr_val = float(atr_s.iloc[-1]) if len(atr_s) > 0 and not np.isnan(atr_s.iloc[-1]) else entry_price * 0.02

            stop = sig["stop_loss"]
            t1 = sig["target1"]
            t2 = sig["target2"]

            # Ensure stop is below entry
            if stop >= entry_price:
                stop = round(entry_price - atr_val, 2)
            # Ensure targets above entry
            if t1 <= entry_price:
                t1 = round(entry_price + 2 * atr_val, 2)
            if t2 <= t1:
                t2 = round(entry_price + 3 * atr_val, 2)

            self._open_positions.append({
                "symbol": sym,
                "entry_date": trade_date.isoformat(),
                "entry_price": entry_price,
                "qty": qty,
                "stop_loss": stop,
                "target1": t1,
                "target2": t2,
                "setup_type": sig.get("setup_type", "SWING"),
                "regime_at_entry": regime,
                "remaining_qty": qty,
                "t1_hit": False,
                "peak_price": entry_price,
                "trough_price": entry_price,
            })

    # ------------------------------------------------------------------
    # Exit simulation
    # ------------------------------------------------------------------

    def _simulate_exits(self, trade_date: date, regime: str) -> None:
        """Simulate intraday exits for all open positions using daily OHLC.

        Exit priority:
        1. Stop loss: Low <= stop  ->  exit at stop
        2. Target 2: High >= T2   ->  full exit at T2
        3. Target 1: High >= T1   ->  partial book 50%
        4. EOD: close at day's Close

        For intraday simulation with daily bars, we use a pessimistic ordering:
        check stop first (assume low happens before high if both are breached).
        """
        closed_positions: List[Dict[str, Any]] = []

        for pos in self._open_positions:
            sym = pos["symbol"]
            df = self._universe.get(sym)
            if df is None or df.empty:
                continue

            df_dates = [d.date() if hasattr(d, 'date') else d for d in df.index]
            matching = [i for i, d in enumerate(df_dates) if d == trade_date]
            if not matching:
                continue
            idx = matching[0]

            bar = df.iloc[idx]
            bar_open = float(bar["Open"])
            bar_high = float(bar["High"])
            bar_low = float(bar["Low"])
            bar_close = float(bar["Close"])

            entry_price = pos["entry_price"]
            stop = pos["stop_loss"]
            t1 = pos["target1"]
            t2 = pos["target2"]
            qty = pos["remaining_qty"]

            # Track excursions
            pos["peak_price"] = max(pos["peak_price"], bar_high)
            pos["trough_price"] = min(pos["trough_price"], bar_low)

            mae_pct = (entry_price - pos["trough_price"]) / max(entry_price, 1) * 100
            mfe_pct = (pos["peak_price"] - entry_price) / max(entry_price, 1) * 100

            entry_date = pos["entry_date"]
            hold_days = (trade_date - date.fromisoformat(entry_date)).days
            hold_days = max(hold_days, 1)

            # 1. Stop loss check
            if bar_low <= stop:
                exit_price = stop
                cost_bd = self._cost_fn(price=(entry_price + exit_price) / 2, qty=qty)
                gross_pnl = (exit_price - entry_price) * qty
                net_pnl = gross_pnl - cost_bd.total

                self._trades.append(BacktestTrade(
                    symbol=sym,
                    entry_date=entry_date,
                    exit_date=trade_date.isoformat(),
                    entry_price=entry_price,
                    exit_price=exit_price,
                    qty=qty,
                    setup_type=pos["setup_type"],
                    regime_at_entry=pos["regime_at_entry"],
                    gross_pnl=round(gross_pnl, 2),
                    net_pnl=round(net_pnl, 2),
                    cost=round(cost_bd.total, 2),
                    pnl_pct=round((exit_price / entry_price - 1) * 100, 4),
                    exit_reason="stop_loss",
                    holding_days=hold_days,
                    max_adverse_excursion_pct=round(mae_pct, 4),
                    max_favorable_excursion_pct=round(mfe_pct, 4),
                    stop_loss=stop,
                    target1=t1,
                    target2=t2,
                ))
                self._cash += exit_price * qty
                closed_positions.append(pos)
                continue

            # 2. Target 2 check (full exit)
            if bar_high >= t2:
                exit_price = t2
                cost_bd = self._cost_fn(price=(entry_price + exit_price) / 2, qty=qty)
                gross_pnl = (exit_price - entry_price) * qty
                net_pnl = gross_pnl - cost_bd.total

                self._trades.append(BacktestTrade(
                    symbol=sym,
                    entry_date=entry_date,
                    exit_date=trade_date.isoformat(),
                    entry_price=entry_price,
                    exit_price=exit_price,
                    qty=qty,
                    setup_type=pos["setup_type"],
                    regime_at_entry=pos["regime_at_entry"],
                    gross_pnl=round(gross_pnl, 2),
                    net_pnl=round(net_pnl, 2),
                    cost=round(cost_bd.total, 2),
                    pnl_pct=round((exit_price / entry_price - 1) * 100, 4),
                    exit_reason="target2",
                    holding_days=hold_days,
                    max_adverse_excursion_pct=round(mae_pct, 4),
                    max_favorable_excursion_pct=round(mfe_pct, 4),
                    stop_loss=stop,
                    target1=t1,
                    target2=t2,
                ))
                self._cash += exit_price * qty
                closed_positions.append(pos)
                continue

            # 3. Target 1 check (partial book 50%)
            if not pos["t1_hit"] and bar_high >= t1:
                partial_qty = qty // 2
                if partial_qty > 0:
                    exit_price = t1
                    cost_bd = self._cost_fn(price=(entry_price + exit_price) / 2, qty=partial_qty)
                    gross_pnl = (exit_price - entry_price) * partial_qty
                    net_pnl = gross_pnl - cost_bd.total

                    self._trades.append(BacktestTrade(
                        symbol=sym,
                        entry_date=entry_date,
                        exit_date=trade_date.isoformat(),
                        entry_price=entry_price,
                        exit_price=exit_price,
                        qty=partial_qty,
                        setup_type=pos["setup_type"],
                        regime_at_entry=pos["regime_at_entry"],
                        gross_pnl=round(gross_pnl, 2),
                        net_pnl=round(net_pnl, 2),
                        cost=round(cost_bd.total, 2),
                        pnl_pct=round((exit_price / entry_price - 1) * 100, 4),
                        exit_reason="target1",
                        holding_days=hold_days,
                        max_adverse_excursion_pct=round(mae_pct, 4),
                        max_favorable_excursion_pct=round(mfe_pct, 4),
                        stop_loss=stop,
                        target1=t1,
                        target2=t2,
                    ))
                    self._cash += exit_price * partial_qty
                    pos["remaining_qty"] -= partial_qty
                    pos["t1_hit"] = True
                    # Move stop to breakeven
                    pos["stop_loss"] = entry_price

            # 4. EOD close for intraday-style (all trades are day trades)
            remaining = pos["remaining_qty"]
            if remaining > 0:
                exit_price = bar_close
                cost_bd = self._cost_fn(price=(entry_price + exit_price) / 2, qty=remaining)
                gross_pnl = (exit_price - entry_price) * remaining
                net_pnl = gross_pnl - cost_bd.total

                reason = "eod_close"
                if pos["t1_hit"]:
                    reason = "eod_close"  # remainder after T1 partial

                self._trades.append(BacktestTrade(
                    symbol=sym,
                    entry_date=entry_date,
                    exit_date=trade_date.isoformat(),
                    entry_price=entry_price,
                    exit_price=exit_price,
                    qty=remaining,
                    setup_type=pos["setup_type"],
                    regime_at_entry=pos["regime_at_entry"],
                    gross_pnl=round(gross_pnl, 2),
                    net_pnl=round(net_pnl, 2),
                    cost=round(cost_bd.total, 2),
                    pnl_pct=round((exit_price / entry_price - 1) * 100, 4),
                    exit_reason=reason,
                    holding_days=hold_days,
                    max_adverse_excursion_pct=round(mae_pct, 4),
                    max_favorable_excursion_pct=round(mfe_pct, 4),
                    stop_loss=stop,
                    target1=t1,
                    target2=t2,
                ))
                self._cash += exit_price * remaining
                closed_positions.append(pos)

        # Remove closed positions
        for p in closed_positions:
            if p in self._open_positions:
                self._open_positions.remove(p)

    def _force_close_all(self, trade_date: date) -> None:
        """Force-close all remaining positions at the last trading date's close."""
        for pos in list(self._open_positions):
            sym = pos["symbol"]
            df = self._universe.get(sym)
            if df is None or df.empty:
                continue

            df_dates = [d.date() if hasattr(d, 'date') else d for d in df.index]
            matching = [i for i, d in enumerate(df_dates) if d <= trade_date]
            if not matching:
                continue

            idx = matching[-1]
            exit_price = float(df.iloc[idx]["Close"])
            entry_price = pos["entry_price"]
            qty = pos["remaining_qty"]

            if qty <= 0:
                continue

            hold_days = max(1, (trade_date - date.fromisoformat(pos["entry_date"])).days)
            mae_pct = (entry_price - pos["trough_price"]) / max(entry_price, 1) * 100
            mfe_pct = (pos["peak_price"] - entry_price) / max(entry_price, 1) * 100

            cost_bd = self._cost_fn(price=(entry_price + exit_price) / 2, qty=qty)
            gross_pnl = (exit_price - entry_price) * qty
            net_pnl = gross_pnl - cost_bd.total

            self._trades.append(BacktestTrade(
                symbol=sym,
                entry_date=pos["entry_date"],
                exit_date=trade_date.isoformat(),
                entry_price=entry_price,
                exit_price=exit_price,
                qty=qty,
                setup_type=pos["setup_type"],
                regime_at_entry=pos["regime_at_entry"],
                gross_pnl=round(gross_pnl, 2),
                net_pnl=round(net_pnl, 2),
                cost=round(cost_bd.total, 2),
                pnl_pct=round((exit_price / entry_price - 1) * 100, 4),
                exit_reason="eod_close",
                holding_days=hold_days,
                max_adverse_excursion_pct=round(mae_pct, 4),
                max_favorable_excursion_pct=round(mfe_pct, 4),
                stop_loss=pos["stop_loss"],
                target1=pos["target1"],
                target2=pos["target2"],
            ))
            self._cash += exit_price * qty

        self._open_positions.clear()

    # ------------------------------------------------------------------
    # Equity tracking
    # ------------------------------------------------------------------

    def _compute_equity(self, trade_date: date) -> float:
        """Compute total equity = cash + mark-to-market of open positions."""
        equity = self._cash
        for pos in self._open_positions:
            sym = pos["symbol"]
            df = self._universe.get(sym)
            if df is None or df.empty:
                continue
            df_dates = [d.date() if hasattr(d, 'date') else d for d in df.index]
            matching = [i for i, d in enumerate(df_dates) if d <= trade_date]
            if matching:
                mtm_price = float(df.iloc[matching[-1]]["Close"])
                equity += mtm_price * pos["remaining_qty"]
        return equity

    def _benchmark_value_at(self, trade_date: date) -> float:
        """Get benchmark close value at *trade_date*."""
        if self._benchmark_df.empty:
            return 0.0
        bm_dates = [d.date() if hasattr(d, 'date') else d for d in self._benchmark_df.index]
        matching = [i for i, d in enumerate(bm_dates) if d <= trade_date]
        if matching:
            return float(self._benchmark_df.iloc[matching[-1]]["Close"])
        return 0.0

    # ------------------------------------------------------------------
    # Results compilation
    # ------------------------------------------------------------------

    def _compile_results(
        self,
        cfg: BacktestConfig,
        trading_dates: List[date],
    ) -> BacktestResult:
        """Compile all trades and equity data into a BacktestResult."""
        trades = self._trades
        daily_eq = self._daily_equity

        result = BacktestResult(
            trades=trades,
            daily_equity=daily_eq,
            config=cfg,
        )

        # -- Summary --
        summary = BacktestSummary()
        summary.total_trades = len(trades)
        summary.start_date = cfg.start_date.isoformat()
        summary.end_date = cfg.end_date.isoformat()
        summary.trading_days = len(trading_dates)

        if not trades:
            result.summary = summary
            return result

        winners = [t for t in trades if t.net_pnl > 0]
        losers = [t for t in trades if t.net_pnl <= 0]
        summary.winners = len(winners)
        summary.losers = len(losers)
        summary.win_rate_pct = round(len(winners) / len(trades) * 100, 2)

        if winners:
            summary.avg_win_pct = round(sum(t.pnl_pct for t in winners) / len(winners), 4)
        if losers:
            summary.avg_loss_pct = round(sum(t.pnl_pct for t in losers) / len(losers), 4)

        gross_profit = sum(t.net_pnl for t in winners) if winners else 0
        gross_loss = abs(sum(t.net_pnl for t in losers)) if losers else 0
        summary.profit_factor = round(gross_profit / max(gross_loss, 0.01), 4)

        summary.total_pnl = round(sum(t.net_pnl for t in trades), 2)
        summary.total_pnl_pct = round(summary.total_pnl / max(cfg.capital, 1) * 100, 4)

        summary.avg_trades_per_day = round(len(trades) / max(len(trading_dates), 1), 2)

        avg_hold = sum(t.holding_days for t in trades) / len(trades)
        summary.avg_holding_period = f"{avg_hold:.1f} days"

        # Drawdown
        if daily_eq:
            max_dd = max(eq.drawdown_pct for eq in daily_eq)
            summary.max_drawdown_pct = round(max_dd, 4)

            # Max drawdown duration
            max_dd_dur = 0
            current_dur = 0
            for eq in daily_eq:
                if eq.drawdown_pct > 0.01:
                    current_dur += 1
                    max_dd_dur = max(max_dd_dur, current_dur)
                else:
                    current_dur = 0
            summary.max_drawdown_duration_days = max_dd_dur

        # Sharpe, Sortino, Calmar
        if len(daily_eq) > 1:
            equity_values = [eq.equity_value for eq in daily_eq]
            daily_returns = []
            for i in range(1, len(equity_values)):
                prev = equity_values[i - 1]
                if prev > 0:
                    daily_returns.append(equity_values[i] / prev - 1)

            if daily_returns:
                daily_rf = _RISK_FREE_ANNUAL / 252
                excess = [r - daily_rf for r in daily_returns]
                mean_excess = np.mean(excess)
                std_ret = np.std(daily_returns, ddof=1)
                if std_ret > 0:
                    summary.sharpe_ratio = round(
                        mean_excess / std_ret * math.sqrt(252), 4
                    )

                # Sortino (downside deviation)
                downside = [r for r in excess if r < 0]
                if downside:
                    downside_std = np.std(downside, ddof=1)
                    if downside_std > 0:
                        summary.sortino_ratio = round(
                            mean_excess / downside_std * math.sqrt(252), 4
                        )

                # Calmar
                if summary.max_drawdown_pct > 0:
                    ann_return = summary.total_pnl_pct / max(len(trading_dates) / 252, 0.01)
                    summary.calmar_ratio = round(
                        ann_return / summary.max_drawdown_pct, 4
                    )

                # Beta vs benchmark
                if daily_eq[0].benchmark_value > 0:
                    bm_returns = []
                    for i in range(1, len(daily_eq)):
                        prev_bm = daily_eq[i - 1].benchmark_value
                        if prev_bm > 0:
                            bm_returns.append(daily_eq[i].benchmark_value / prev_bm - 1)
                        else:
                            bm_returns.append(0.0)

                    if len(bm_returns) == len(daily_returns) and len(bm_returns) > 1:
                        cov = np.cov(daily_returns, bm_returns)
                        if cov.shape == (2, 2) and cov[1, 1] > 0:
                            summary.beta = round(float(cov[0, 1] / cov[1, 1]), 4)

        # Benchmark return
        if daily_eq and daily_eq[0].benchmark_value > 0 and daily_eq[-1].benchmark_value > 0:
            summary.benchmark_return_pct = round(
                (daily_eq[-1].benchmark_value / daily_eq[0].benchmark_value - 1) * 100, 4
            )
        summary.alpha_pct = round(summary.total_pnl_pct - summary.benchmark_return_pct, 4)

        # Monthly returns
        monthly: Dict[str, float] = defaultdict(float)
        for t in trades:
            month_key = t.exit_date[:7]  # YYYY-MM
            monthly[month_key] += t.net_pnl

        monthly_pct = {}
        for k in sorted(monthly.keys()):
            monthly_pct[k] = round(monthly[k] / max(cfg.capital, 1) * 100, 4)
        result.monthly_returns = monthly_pct

        if monthly_pct:
            best_k = max(monthly_pct, key=monthly_pct.get)
            worst_k = min(monthly_pct, key=monthly_pct.get)
            summary.best_month = f"{best_k}: {monthly_pct[best_k]:+.2f}%"
            summary.worst_month = f"{worst_k}: {monthly_pct[worst_k]:+.2f}%"

        result.summary = summary

        # Setup breakdown
        setup_groups: Dict[str, List[BacktestTrade]] = defaultdict(list)
        for t in trades:
            setup_groups[t.setup_type or "UNKNOWN"].append(t)

        for setup, group in setup_groups.items():
            w = [t for t in group if t.net_pnl > 0]
            result.setup_breakdown[setup] = SetupStats(
                trades=len(group),
                winners=len(w),
                losers=len(group) - len(w),
                win_rate_pct=round(len(w) / len(group) * 100, 2) if group else 0,
                avg_pnl_pct=round(sum(t.pnl_pct for t in group) / len(group), 4),
                total_pnl=round(sum(t.net_pnl for t in group), 2),
            )

        # Regime breakdown
        regime_groups: Dict[str, List[BacktestTrade]] = defaultdict(list)
        for t in trades:
            regime_groups[t.regime_at_entry or "UNKNOWN"].append(t)

        for reg, group in regime_groups.items():
            w = [t for t in group if t.net_pnl > 0]
            result.regime_breakdown[reg] = RegimeStats(
                trades=len(group),
                winners=len(w),
                losers=len(group) - len(w),
                win_rate_pct=round(len(w) / len(group) * 100, 2) if group else 0,
                avg_pnl_pct=round(sum(t.pnl_pct for t in group) / len(group), 4),
                total_pnl=round(sum(t.net_pnl for t in group), 2),
            )

        # Best / worst trades
        sorted_by_pnl = sorted(trades, key=lambda t: t.net_pnl, reverse=True)
        result.best_trades = sorted_by_pnl[:5]
        result.worst_trades = sorted_by_pnl[-5:][::-1]  # worst first

        return result
