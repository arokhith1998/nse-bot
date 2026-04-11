"""
signal_router.py
================
Central signal routing hub for the NSE Market Intelligence platform.

Aggregates scores from multiple sub-systems (technical scoring, regime engine,
news ranker, intraday timing) into a unified Signal dataclass, applies risk
filters, and returns ranked actionable signals.

Also normalises incoming TradingView webhook alerts into the same Signal format
so every downstream consumer speaks a single language.

PAPER TRADING ONLY. Not investment advice.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field, asdict
from datetime import datetime, time as dt_time
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class Bias(str, Enum):
    """Trade direction.  Cash-market only -- no SHORT."""
    LONG = "LONG"
    AVOID = "AVOID"


class SetupType(str, Enum):
    BREAKOUT = "BREAKOUT"
    MOMENTUM = "MOMENTUM"
    GAP_AND_GO = "GAP_AND_GO"
    VWAP_RECLAIM = "VWAP_RECLAIM"
    PULLBACK = "PULLBACK"
    REVERSAL = "REVERSAL"
    SWING = "SWING"


class RegimeLabel(str, Enum):
    """Market regime labels used across the platform."""
    TREND_UP = "TREND_UP"
    TREND_DOWN = "TREND_DOWN"
    RANGE_CHOP = "RANGE_CHOP"
    HIGH_VOL = "HIGH_VOL"
    HIGH_VOL_EVENT = "HIGH_VOL_EVENT"
    LOW_VOL = "LOW_VOL"


# ---------------------------------------------------------------------------
# Signal dataclass
# ---------------------------------------------------------------------------

@dataclass
class Signal:
    """Fully-qualified trade signal with all decision metadata.

    Every field the dashboard, risk engine, or exit engine could ever need
    lives here so downstream consumers never have to re-derive anything.
    """

    # ---- Identity ----------------------------------------------------------
    symbol: str
    instrument_type: str = "EQ"                   # EQ, ETF, FUT, etc.

    # ---- Direction & Setup -------------------------------------------------
    bias: str = Bias.LONG.value                    # "LONG" | "AVOID"
    setup_type: str = SetupType.SWING.value

    # ---- Price Levels ------------------------------------------------------
    entry_zone: Tuple[float, float] = (0.0, 0.0)  # (low, high)
    invalidation: float = 0.0                      # thesis-breaking price
    target1: float = 0.0
    target2: float = 0.0

    # ---- Exit Rules --------------------------------------------------------
    trailing_exit_rule: str = ""
    do_not_enter_after: str = "14:30"              # IST HH:MM
    best_exit_window: str = "14:00 - 15:00"        # IST HH:MM - HH:MM

    # ---- Scores & Sizing ---------------------------------------------------
    confidence_score: float = 0.0                  # 0-100
    position_size_pct: float = 0.0                 # 0-100% of capital

    # ---- Explanatory -------------------------------------------------------
    explanation: str = ""
    score_breakdown: Dict[str, float] = field(default_factory=dict)
    regime_at_entry: str = ""
    news_catalyst: Optional[str] = None

    # ---- Cost Analysis -----------------------------------------------------
    cost_analysis: Dict[str, float] = field(default_factory=dict)
    # Expected keys: round_trip_cost, net_rr

    # ---- Metadata ----------------------------------------------------------
    generated_at: str = field(
        default_factory=lambda: datetime.now().isoformat(timespec="seconds"),
    )

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a plain dict (JSON-safe with minor coercion)."""
        d = asdict(self)
        d["entry_zone"] = list(d["entry_zone"])
        return d


# ---------------------------------------------------------------------------
# Groww cost model (carried over from generate_picks.py)
# ---------------------------------------------------------------------------

def _groww_roundtrip_cost(price: float, qty: int) -> float:
    """Estimate intraday (MIS) round-trip cost on Groww."""
    turnover_buy = price * qty
    turnover_sell = price * qty
    brok = min(20, 0.0003 * turnover_buy) + min(20, 0.0003 * turnover_sell)
    stt = 0.00025 * turnover_sell
    exch = 0.0000345 * (turnover_buy + turnover_sell)
    gst = 0.18 * (brok + exch)
    sebi = 0.000001 * (turnover_buy + turnover_sell)
    stamp = 0.00003 * turnover_buy
    return round(brok + stt + exch + gst + sebi + stamp, 2)


# ---------------------------------------------------------------------------
# Time-of-day factor
# ---------------------------------------------------------------------------

def _time_of_day_factor(now: Optional[datetime] = None) -> float:
    """Return a multiplier (0.5 - 1.0) based on IST time of day.

    Best entries are in the first 90 minutes (09:15 - 10:45) and during
    the post-lunch push (13:00 - 14:00).  After 14:30 the factor tapers
    aggressively because there is insufficient runway for intraday trades.
    """
    if now is None:
        now = datetime.now()
    t = now.time()

    if t < dt_time(9, 15):
        return 0.5          # pre-market, no entries
    elif t <= dt_time(10, 45):
        return 1.0          # opening drive -- best window
    elif t <= dt_time(12, 0):
        return 0.85         # mid-morning, okay
    elif t <= dt_time(13, 0):
        return 0.70         # lunch chop
    elif t <= dt_time(14, 0):
        return 0.90         # post-lunch push
    elif t <= dt_time(14, 30):
        return 0.65         # taper zone
    else:
        return 0.50         # late session, avoid new entries


# ---------------------------------------------------------------------------
# Setup-type classifier
# ---------------------------------------------------------------------------

def _classify_setup(score_breakdown: Dict[str, float]) -> str:
    """Heuristically pick the best SetupType label from sub-scores."""
    brk = score_breakdown.get("breakout", 0)
    mom = score_breakdown.get("momentum", 0)
    trend = score_breakdown.get("trend", 0)
    vol = score_breakdown.get("volume", 0)

    if brk >= 80:
        return SetupType.BREAKOUT.value
    if mom >= 75 and brk >= 50:
        return SetupType.MOMENTUM.value
    if brk >= 60 and vol >= 70:
        return SetupType.GAP_AND_GO.value
    if trend >= 60 and mom < 40:
        return SetupType.PULLBACK.value
    if trend < 30 and mom >= 60:
        return SetupType.REVERSAL.value
    return SetupType.SWING.value


# ---------------------------------------------------------------------------
# Explanation builder
# ---------------------------------------------------------------------------

def _build_explanation(
    symbol: str,
    setup_type: str,
    score_breakdown: Dict[str, float],
    regime: str,
    news_catalyst: Optional[str],
) -> str:
    """Generate a 2-3 sentence human-readable justification for the signal."""
    parts: List[str] = []

    top_features = sorted(score_breakdown.items(), key=lambda x: x[1], reverse=True)[:3]
    feature_str = ", ".join(f"{k} ({v:.0f})" for k, v in top_features)
    parts.append(
        f"{symbol} shows a {setup_type.replace('_', ' ').title()} setup "
        f"with strongest signals from {feature_str}."
    )

    if regime:
        parts.append(f"Current market regime is {regime}.")

    if news_catalyst:
        parts.append(f"News catalyst: {news_catalyst}.")

    return " ".join(parts)


# ---------------------------------------------------------------------------
# SignalRouter
# ---------------------------------------------------------------------------

class SignalRouter:
    """Central hub that produces ranked, risk-checked signals.

    Parameters
    ----------
    weights : dict
        Component weights (trend, momentum, volume, breakout, ...).
        Loaded from ``weights.json`` at startup.
    capital : float
        Total paper-trading capital in INR.
    risk_per_trade_pct : float
        Max capital risked per trade (percent).
    atr_sl_mult : float
        ATR multiplier for stop-loss calculation.
    rr : float
        Minimum reward-to-risk ratio.
    top_n : int
        Maximum number of signals to return.
    """

    def __init__(
        self,
        weights: Dict[str, float],
        capital: float = 100_000.0,
        risk_per_trade_pct: float = 1.0,
        atr_sl_mult: float = 1.0,
        rr: float = 2.0,
        top_n: int = 6,
    ) -> None:
        self.weights = weights
        self.capital = capital
        self.risk_per_trade_pct = risk_per_trade_pct
        self.atr_sl_mult = atr_sl_mult
        self.rr = rr
        self.top_n = top_n

    # ------------------------------------------------------------------
    # Core signal generation
    # ------------------------------------------------------------------

    def generate_signals(
        self,
        universe: List[Dict[str, Any]],
        regime: str = RegimeLabel.RANGE_CHOP.value,
        news: Optional[Dict[str, Any]] = None,
        now: Optional[datetime] = None,
        risk_engine: Optional[Any] = None,
        open_trades: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Signal]:
        """Score every symbol in *universe* and return the top-N actionable signals.

        Parameters
        ----------
        universe : list[dict]
            Each dict must contain at least:
              - ``symbol``: str
              - ``score_breakdown``: dict of component scores (trend, momentum, ...)
              - ``price``: float (current / last traded price)
              - ``atr``: float
              - optional: ``instrument_type``, ``sector``
        regime : str
            Current market regime label from regime_engine.
        news : dict | None
            News map ``{SYMBOL: headline, ...}`` from news_ranker.
        now : datetime | None
            Override for the current timestamp (useful for back-testing).
        risk_engine : RiskEngine | None
            If provided, each signal is checked against portfolio risk limits.
        open_trades : list[dict] | None
            Currently open positions, forwarded to risk_engine.

        Returns
        -------
        list[Signal]
            Sorted by ``confidence_score`` descending, filtered and risk-checked.
        """
        if news is None:
            news = {}
        if open_trades is None:
            open_trades = []

        tod_factor = _time_of_day_factor(now)
        regime_mod = self._regime_modifier(regime)

        signals: List[Signal] = []

        for item in universe:
            sym = item.get("symbol", "")
            if not sym:
                continue

            raw_breakdown = item.get("score_breakdown", {})
            price = item.get("price", 0.0)
            atr_val = item.get("atr", 0.0)

            if price <= 0 or atr_val <= 0:
                continue

            # ---- Weighted base score ------------------------------------
            base_score = sum(
                self.weights.get(k, 0) * v
                for k, v in raw_breakdown.items()
            )

            # ---- News boost (add up to +15 if there is a catalyst) ------
            news_headline = news.get(sym.upper())
            news_boost = 15.0 if news_headline else 0.0

            # ---- Composite confidence -----------------------------------
            confidence = (base_score + news_boost) * regime_mod * tod_factor
            confidence = max(0.0, min(100.0, confidence))

            # ---- Regime gate --------------------------------------------
            if confidence < 40:
                continue
            if regime == RegimeLabel.HIGH_VOL_EVENT.value and confidence < 70:
                continue

            # ---- Bias ---------------------------------------------------
            bias = Bias.LONG.value if confidence >= 50 else Bias.AVOID.value

            # ---- Price levels -------------------------------------------
            sl = round(price - self.atr_sl_mult * atr_val, 2)
            tgt1 = round(price + self.rr * self.atr_sl_mult * atr_val, 2)
            tgt2 = round(price + (self.rr + 1.0) * self.atr_sl_mult * atr_val, 2)
            entry_low = round(price * 0.998, 2)
            entry_high = round(price * 1.004, 2)

            # ---- Position sizing ----------------------------------------
            risk_per_share = max(price - sl, 0.01)
            risk_budget = self.capital * self.risk_per_trade_pct / 100.0
            qty = max(1, int(risk_budget / risk_per_share))
            cap_required = qty * price
            pct_of_capital = round(cap_required / max(self.capital, 1) * 100, 2)

            # ---- Cost analysis ------------------------------------------
            rt_cost = _groww_roundtrip_cost(price, qty)
            gross_profit = (tgt1 - price) * qty
            gross_loss = (price - sl) * qty
            net_profit = round(gross_profit - rt_cost, 2)
            net_loss = round(gross_loss + rt_cost, 2)
            net_rr = round(net_profit / max(net_loss, 0.01), 2)

            # Skip if costs eat the edge
            if rt_cost > 0.25 * max(gross_profit, 0.01):
                continue

            # ---- Setup classification -----------------------------------
            setup = _classify_setup(raw_breakdown)

            # ---- Trailing exit rule text --------------------------------
            trailing_rule = (
                f"Trail stop at {self.atr_sl_mult}x ATR below swing highs. "
                f"After T1 hit, move stop to entry (break-even). "
                f"After T2 proximity (within 0.5 ATR), use 0.5x ATR trail."
            )

            # ---- Build Signal -------------------------------------------
            sig = Signal(
                symbol=sym,
                instrument_type=item.get("instrument_type", "EQ"),
                bias=bias,
                setup_type=setup,
                entry_zone=(entry_low, entry_high),
                invalidation=sl,
                target1=tgt1,
                target2=tgt2,
                trailing_exit_rule=trailing_rule,
                confidence_score=round(confidence, 1),
                position_size_pct=round(min(pct_of_capital, 100.0), 2),
                do_not_enter_after=self._cutoff_time(setup),
                best_exit_window=self._best_exit_window(setup),
                explanation=_build_explanation(
                    sym, setup, raw_breakdown, regime, news_headline,
                ),
                score_breakdown=raw_breakdown,
                regime_at_entry=regime,
                news_catalyst=news_headline,
                cost_analysis={
                    "round_trip_cost": rt_cost,
                    "net_rr": net_rr,
                    "net_profit_t1": net_profit,
                    "net_loss": net_loss,
                    "qty": qty,
                    "capital_required": round(cap_required, 2),
                },
            )
            signals.append(sig)

        # ---- Sort by confidence descending ------------------------------
        signals.sort(key=lambda s: s.confidence_score, reverse=True)

        # ---- Apply risk-engine portfolio checks -------------------------
        if risk_engine is not None:
            checked: List[Signal] = []
            for sig in signals:
                decision = risk_engine.check_portfolio_risk(
                    sig.to_dict(), open_trades,
                )
                if decision.allowed:
                    if decision.adjusted_size is not None:
                        sig.position_size_pct = round(decision.adjusted_size, 2)
                    checked.append(sig)
                else:
                    logger.info(
                        "Signal %s blocked by risk engine: %s",
                        sig.symbol, decision.reason,
                    )
            signals = checked

        return signals[: self.top_n]

    # ------------------------------------------------------------------
    # Webhook normalisation
    # ------------------------------------------------------------------

    def route_webhook_signal(self, webhook_data: Dict[str, Any]) -> Signal:
        """Normalise a TradingView-style webhook alert into our Signal format.

        Expected webhook payload keys (all optional with defaults):
            ticker, exchange, close, interval, volume, action, strategy,
            entry, stop, target, message

        Returns
        -------
        Signal
            A partially-filled Signal.  The caller can enrich it further
            with live market data before acting on it.
        """
        sym = (
            webhook_data.get("ticker", "")
            or webhook_data.get("symbol", "")
        ).upper().replace(".NS", "")

        price = float(webhook_data.get("close", 0) or webhook_data.get("price", 0) or 0)
        entry_raw = webhook_data.get("entry", price)
        stop_raw = float(webhook_data.get("stop", 0) or webhook_data.get("stop_loss", 0) or 0)
        target_raw = float(webhook_data.get("target", 0) or webhook_data.get("target1", 0) or 0)

        action = str(webhook_data.get("action", "buy")).upper()
        bias = Bias.LONG.value if action in ("BUY", "LONG") else Bias.AVOID.value

        strategy_raw = str(webhook_data.get("strategy", "SWING")).upper()
        try:
            setup = SetupType(strategy_raw).value
        except ValueError:
            setup = SetupType.SWING.value

        entry_price = float(entry_raw) if entry_raw else price
        entry_zone = (
            round(entry_price * 0.998, 2),
            round(entry_price * 1.004, 2),
        )

        message = webhook_data.get("message", "") or ""

        return Signal(
            symbol=sym,
            instrument_type="EQ",
            bias=bias,
            setup_type=setup,
            entry_zone=entry_zone,
            invalidation=stop_raw,
            target1=target_raw,
            target2=round(target_raw * 1.5, 2) if target_raw else 0.0,
            trailing_exit_rule="Webhook signal -- apply default ATR trail.",
            confidence_score=60.0,       # default; enrich later with full scoring
            position_size_pct=0.0,       # must be computed by risk_engine
            explanation=f"Webhook alert: {message}" if message else "External webhook signal.",
            score_breakdown={},
            regime_at_entry="",
            news_catalyst=None,
            cost_analysis={},
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _regime_modifier(regime: str) -> float:
        """Return a confidence multiplier based on the current regime.

        Bullish regimes amplify scores; choppy/volatile regimes dampen them.
        """
        modifiers = {
            RegimeLabel.TREND_UP.value: 1.10,
            RegimeLabel.TREND_DOWN.value: 0.70,
            RegimeLabel.RANGE_CHOP.value: 0.85,
            RegimeLabel.HIGH_VOL.value: 0.75,
            RegimeLabel.HIGH_VOL_EVENT.value: 0.60,
            RegimeLabel.LOW_VOL.value: 0.90,
        }
        return modifiers.get(regime, 1.0)

    @staticmethod
    def _cutoff_time(setup_type: str) -> str:
        """Return the latest safe entry time for a given setup."""
        cutoffs = {
            SetupType.BREAKOUT.value: "14:00",
            SetupType.MOMENTUM.value: "13:30",
            SetupType.GAP_AND_GO.value: "10:30",
            SetupType.VWAP_RECLAIM.value: "14:00",
            SetupType.PULLBACK.value: "14:30",
            SetupType.REVERSAL.value: "13:00",
            SetupType.SWING.value: "14:30",
        }
        return cutoffs.get(setup_type, "14:30")

    @staticmethod
    def _best_exit_window(setup_type: str) -> str:
        """Return the ideal exit window for a given setup."""
        windows = {
            SetupType.BREAKOUT.value: "14:00 - 15:15",
            SetupType.MOMENTUM.value: "13:30 - 15:00",
            SetupType.GAP_AND_GO.value: "10:00 - 11:30",
            SetupType.VWAP_RECLAIM.value: "14:00 - 15:15",
            SetupType.PULLBACK.value: "14:00 - 15:15",
            SetupType.REVERSAL.value: "13:00 - 15:00",
            SetupType.SWING.value: "14:30 - 15:15",
        }
        return windows.get(setup_type, "14:00 - 15:15")
