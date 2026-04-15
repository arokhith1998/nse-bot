"""
exit_engine.py
==============
Sell-side decision engine for the NSE Market Intelligence platform.

Evaluates every open trade against a priority-ordered checklist of exit
conditions (stop-loss, targets, VWAP loss, trailing stops, regime reversal,
volume collapse, time-based exits) and emits concrete ExitSignal instructions.

PAPER TRADING ONLY. Not investment advice.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, time as dt_time
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ExitAction(str, Enum):
    """What the system recommends doing with a position."""
    PARTIAL_BOOK = "PARTIAL_BOOK"
    TRAIL_STOP = "TRAIL_STOP"
    SELL_NOW = "SELL_NOW"
    AVOID = "AVOID"
    WATCH_ONLY = "WATCH_ONLY"


class ExitReason(str, Enum):
    """Machine-readable label for WHY we are exiting."""
    STOP_LOSS_HIT = "STOP_LOSS_HIT"
    TARGET1_HIT = "TARGET1_HIT"
    TARGET2_HIT = "TARGET2_HIT"
    VWAP_LOSS = "VWAP_LOSS"
    FAILED_RETEST = "FAILED_RETEST"
    TRAILING_STOP = "TRAILING_STOP"
    REGIME_REVERSAL = "REGIME_REVERSAL"
    VOLUME_COLLAPSE = "VOLUME_COLLAPSE"
    TIME_EXIT_WARNING = "TIME_EXIT_WARNING"
    EOD_FORCED = "EOD_FORCED"


# ---------------------------------------------------------------------------
# ExitSignal dataclass
# ---------------------------------------------------------------------------

@dataclass
class ExitSignal:
    """Concrete exit instruction for a single open position."""

    trade_id: str
    symbol: str

    action: str = ExitAction.WATCH_ONLY.value      # PARTIAL_BOOK / TRAIL_STOP / SELL_NOW / AVOID / WATCH_ONLY
    reason: str = ""                                 # human-readable
    urgency: int = 1                                 # 1 (low) to 5 (immediate)
    exit_price: float = 0.0                          # suggested price to exit at

    # Optional metadata for downstream consumers
    exit_reason_code: str = ""                       # machine-readable ExitReason value
    partial_pct: float = 0.0                         # percent of position to sell (for PARTIAL_BOOK)
    new_stop: float = 0.0                            # updated stop level (for TRAIL_STOP)
    generated_at: str = field(
        default_factory=lambda: datetime.now().isoformat(timespec="seconds"),
    )


# ---------------------------------------------------------------------------
# ExitEngine
# ---------------------------------------------------------------------------

class ExitEngine:
    """Evaluate open trades and emit exit signals.

    Parameters
    ----------
    vwap_loss_threshold_pct : float
        Percentage below VWAP to trigger VWAP_LOSS exit (default 0.3%).
    volume_collapse_ratio : float
        If current volume < this fraction of session average volume,
        flag VOLUME_COLLAPSE (default 0.40).
    time_exit_warn : tuple[int, int]
        IST (hour, minute) after which profitable trades get PARTIAL_BOOK
        and losing trades get SELL_NOW (default 14:45).
    eod_forced : tuple[int, int]
        IST (hour, minute) at which all positions are force-closed
        (default 15:15).
    """

    def __init__(
        self,
        vwap_loss_threshold_pct: float = 0.3,
        volume_collapse_ratio: float = 0.40,
        time_exit_warn: tuple = (14, 45),
        eod_forced: tuple = (15, 15),
    ) -> None:
        self.vwap_loss_threshold_pct = vwap_loss_threshold_pct
        self.volume_collapse_ratio = volume_collapse_ratio
        self.time_exit_warn = dt_time(*time_exit_warn)
        self.eod_forced = dt_time(*eod_forced)

    # ------------------------------------------------------------------
    # Primary evaluation
    # ------------------------------------------------------------------

    def evaluate_exits(
        self,
        open_trades: List[Dict[str, Any]],
        market_data: Dict[str, Dict[str, Any]],
        current_regime: str = "",
        now: Optional[datetime] = None,
    ) -> List[ExitSignal]:
        """Run the full exit checklist on every open trade.

        Parameters
        ----------
        open_trades : list[dict]
            Each trade dict must have:
                - trade_id: str
                - symbol: str
                - entry_price: float
                - stop_loss: float
                - target1: float
                - target2: float
                - qty: int
                - regime_at_entry: str (optional)
                - was_above_vwap: bool (optional, for VWAP_LOSS detection)
                - breakout_level: float (optional, for FAILED_RETEST)
                - trailing_stop: float (optional)
                - atr: float (optional, for trailing stop calc)

        market_data : dict[str, dict]
            Keyed by symbol.  Each value must have:
                - ltp: float (last traded price)
                - vwap: float (optional)
                - volume: int (optional, current session volume)
                - avg_volume: int (optional, average session volume)

        current_regime : str
            Current market regime label.

        now : datetime | None
            Override current time (for testing).

        Returns
        -------
        list[ExitSignal]
            One signal per trade that requires action, sorted by urgency
            descending.
        """
        if now is None:
            now = datetime.now()

        signals: List[ExitSignal] = []

        for trade in open_trades:
            tid = str(trade.get("trade_id", ""))
            sym = trade.get("symbol", "")
            mkt = market_data.get(sym, {})
            ltp = float(mkt.get("ltp", 0))

            if not sym or ltp <= 0:
                continue

            entry = float(trade.get("entry_price", 0))
            sl = float(trade.get("stop_loss", 0))
            t1 = float(trade.get("target1", 0))
            t2 = float(trade.get("target2", 0))
            atr_val = float(trade.get("atr", 0))

            # Run checks in priority order.  First match wins for the
            # primary action, but we may also update trailing stop.
            sig = self._check_all(
                trade_id=tid,
                symbol=sym,
                entry=entry,
                stop_loss=sl,
                target1=t1,
                target2=t2,
                ltp=ltp,
                atr_val=atr_val,
                trade=trade,
                mkt=mkt,
                current_regime=current_regime,
                now=now,
            )
            if sig is not None:
                signals.append(sig)

        # Sort by urgency descending (most urgent first)
        signals.sort(key=lambda s: s.urgency, reverse=True)
        return signals

    # ------------------------------------------------------------------
    # Priority-ordered check chain
    # ------------------------------------------------------------------

    def _check_all(
        self,
        trade_id: str,
        symbol: str,
        entry: float,
        stop_loss: float,
        target1: float,
        target2: float,
        ltp: float,
        atr_val: float,
        trade: Dict[str, Any],
        mkt: Dict[str, Any],
        current_regime: str,
        now: datetime,
    ) -> Optional[ExitSignal]:
        """Run every check in priority order; return the first match."""

        # ---- 1. STOP_LOSS_HIT (urgency 5) ------------------------------
        if stop_loss > 0 and ltp <= stop_loss:
            return ExitSignal(
                trade_id=trade_id,
                symbol=symbol,
                action=ExitAction.SELL_NOW.value,
                reason=f"Stop loss hit. LTP {ltp:.2f} <= SL {stop_loss:.2f}.",
                urgency=5,
                exit_price=ltp,
                exit_reason_code=ExitReason.STOP_LOSS_HIT.value,
            )

        # ---- 10. EOD_FORCED (urgency 5) -- check early so it trumps ---
        if now.time() >= self.eod_forced:
            return ExitSignal(
                trade_id=trade_id,
                symbol=symbol,
                action=ExitAction.SELL_NOW.value,
                reason=(
                    f"End-of-day forced exit at {self.eod_forced.strftime('%H:%M')}. "
                    f"LTP {ltp:.2f}."
                ),
                urgency=5,
                exit_price=ltp,
                exit_reason_code=ExitReason.EOD_FORCED.value,
            )

        # ---- 2. TARGET1_HIT — scale-out 1R: book 50% (urgency 3) --------
        # M9: 3-step scale-out: 50% at T1 (1R), 25% at T2 (1.5R), trail 25%
        t1_already_hit = trade.get("breakeven_moved", False)
        t2_already_hit = trade.get("trail_active", False)

        if target1 > 0 and ltp >= target1 and not t1_already_hit:
            new_stop = max(entry, stop_loss)  # move stop to break-even
            return ExitSignal(
                trade_id=trade_id,
                symbol=symbol,
                action=ExitAction.PARTIAL_BOOK.value,
                reason=(
                    f"Scale-out 1R hit! LTP {ltp:.2f} >= T1 {target1:.2f}. "
                    f"Book 50%, move stop to breakeven {new_stop:.2f}."
                ),
                urgency=3,
                exit_price=ltp,
                exit_reason_code=ExitReason.TARGET1_HIT.value,
                partial_pct=50.0,
                new_stop=new_stop,
            )

        # ---- 3. TARGET2_HIT — scale-out 1.5R: book 25% (urgency 3) ----
        if target2 > 0 and ltp >= target2 and t1_already_hit and not t2_already_hit:
            # Book 25% of original qty, activate trail for remaining 25%
            vwap = float(mkt.get("vwap", 0))
            trail_stop = max(entry, vwap if vwap > 0 else entry)
            return ExitSignal(
                trade_id=trade_id,
                symbol=symbol,
                action=ExitAction.PARTIAL_BOOK.value,
                reason=(
                    f"Scale-out 1.5R hit! LTP {ltp:.2f} >= T2 {target2:.2f}. "
                    f"Book 25%, trail remaining 25% with stop at {trail_stop:.2f}."
                ),
                urgency=3,
                exit_price=ltp,
                exit_reason_code=ExitReason.TARGET2_HIT.value,
                partial_pct=25.0,
                new_stop=trail_stop,
            )

        # ---- 3b. Beyond 2R — full exit if price hits 2R+ and T2 done --
        if target2 > 0 and t2_already_hit:
            two_r = entry + 2 * (target1 - entry)  # 2R level
            if ltp >= two_r:
                return ExitSignal(
                    trade_id=trade_id,
                    symbol=symbol,
                    action=ExitAction.SELL_NOW.value,
                    reason=f"2R+ reached! LTP {ltp:.2f} >= 2R {two_r:.2f}. Close remaining.",
                    urgency=4,
                    exit_price=ltp,
                    exit_reason_code=ExitReason.TARGET2_HIT.value,
                )

        # ---- 4. VWAP_LOSS (urgency 4) ----------------------------------
        vwap = float(mkt.get("vwap", 0))
        was_above_vwap = trade.get("was_above_vwap", False)
        if vwap > 0 and was_above_vwap:
            pct_below = ((vwap - ltp) / vwap) * 100
            if pct_below > self.vwap_loss_threshold_pct:
                return ExitSignal(
                    trade_id=trade_id,
                    symbol=symbol,
                    action=ExitAction.SELL_NOW.value,
                    reason=(
                        f"VWAP loss. Was above VWAP, now {pct_below:.2f}% below "
                        f"(VWAP={vwap:.2f}, LTP={ltp:.2f})."
                    ),
                    urgency=4,
                    exit_price=ltp,
                    exit_reason_code=ExitReason.VWAP_LOSS.value,
                )

        # ---- 5. FAILED_RETEST (urgency 3) ------------------------------
        breakout_level = float(trade.get("breakout_level", 0))
        if breakout_level > 0 and entry > breakout_level and ltp < breakout_level:
            return ExitSignal(
                trade_id=trade_id,
                symbol=symbol,
                action=ExitAction.SELL_NOW.value,
                reason=(
                    f"Failed retest. Broke above {breakout_level:.2f}, "
                    f"now back below at {ltp:.2f}."
                ),
                urgency=3,
                exit_price=ltp,
                exit_reason_code=ExitReason.FAILED_RETEST.value,
            )

        # ---- 6. TRAILING_STOP (urgency 3) ------------------------------
        trailing_stop = float(trade.get("trailing_stop", 0))
        if trailing_stop > 0 and ltp <= trailing_stop:
            return ExitSignal(
                trade_id=trade_id,
                symbol=symbol,
                action=ExitAction.SELL_NOW.value,
                reason=(
                    f"Trailing stop hit. LTP {ltp:.2f} <= trail {trailing_stop:.2f}."
                ),
                urgency=3,
                exit_price=ltp,
                exit_reason_code=ExitReason.TRAILING_STOP.value,
            )

        # If trailing stop not hit but can be tightened, emit TRAIL_STOP
        if atr_val > 0 and trailing_stop > 0:
            new_trail = self.update_trailing_stop(trade, ltp, atr_val)
            if new_trail > trailing_stop:
                return ExitSignal(
                    trade_id=trade_id,
                    symbol=symbol,
                    action=ExitAction.TRAIL_STOP.value,
                    reason=(
                        f"Tighten trailing stop from {trailing_stop:.2f} "
                        f"to {new_trail:.2f} (ATR-based)."
                    ),
                    urgency=2,
                    exit_price=0.0,
                    exit_reason_code=ExitReason.TRAILING_STOP.value,
                    new_stop=new_trail,
                )

        # ---- 7. REGIME_REVERSAL (urgency 3) -----------------------------
        regime_at_entry = trade.get("regime_at_entry", "")
        if regime_at_entry and current_regime:
            if self._regime_turned_adverse(regime_at_entry, current_regime):
                return ExitSignal(
                    trade_id=trade_id,
                    symbol=symbol,
                    action=ExitAction.SELL_NOW.value,
                    reason=(
                        f"Regime reversal. Entry regime was {regime_at_entry}, "
                        f"now {current_regime}."
                    ),
                    urgency=3,
                    exit_price=ltp,
                    exit_reason_code=ExitReason.REGIME_REVERSAL.value,
                )

        # ---- 8. VOLUME_COLLAPSE (urgency 2) ----------------------------
        cur_vol = int(mkt.get("volume", 0))
        avg_vol = int(mkt.get("avg_volume", 0))
        if avg_vol > 0 and cur_vol > 0:
            vol_ratio = cur_vol / avg_vol
            if vol_ratio < self.volume_collapse_ratio:
                return ExitSignal(
                    trade_id=trade_id,
                    symbol=symbol,
                    action=ExitAction.WATCH_ONLY.value,
                    reason=(
                        f"Volume collapse. Current vol is {vol_ratio:.0%} of "
                        f"session average. Tighten stop and watch."
                    ),
                    urgency=2,
                    exit_price=0.0,
                    exit_reason_code=ExitReason.VOLUME_COLLAPSE.value,
                    new_stop=self._tighten_stop_for_vol_collapse(
                        stop_loss, entry, ltp,
                    ),
                )

        # ---- 9. TIME_EXIT_WARNING (urgency 3) --------------------------
        if now.time() >= self.time_exit_warn:
            is_profitable = ltp > entry
            if is_profitable:
                return ExitSignal(
                    trade_id=trade_id,
                    symbol=symbol,
                    action=ExitAction.PARTIAL_BOOK.value,
                    reason=(
                        f"Late session ({now.strftime('%H:%M')}). "
                        f"Profitable at {ltp:.2f} (entry {entry:.2f}). "
                        f"Book partial profits."
                    ),
                    urgency=3,
                    exit_price=ltp,
                    exit_reason_code=ExitReason.TIME_EXIT_WARNING.value,
                    partial_pct=50.0,
                )
            else:
                return ExitSignal(
                    trade_id=trade_id,
                    symbol=symbol,
                    action=ExitAction.SELL_NOW.value,
                    reason=(
                        f"Late session ({now.strftime('%H:%M')}). "
                        f"Losing at {ltp:.2f} (entry {entry:.2f}). "
                        f"Exit before close."
                    ),
                    urgency=3,
                    exit_price=ltp,
                    exit_reason_code=ExitReason.TIME_EXIT_WARNING.value,
                )

        # No exit signal needed
        return None

    # ------------------------------------------------------------------
    # Trailing stop logic
    # ------------------------------------------------------------------

    def update_trailing_stop(
        self,
        trade: Dict[str, Any],
        current_price: float,
        atr: float,
    ) -> float:
        """Calculate an updated trailing stop level.

        Logic:
        - Default trail: 1x ATR below the current price.
        - If price has moved past T1, tighten to 0.5x ATR.
        - The new stop is always max(old_stop, computed_stop) -- it never
          moves down.

        Parameters
        ----------
        trade : dict
            Must have ``trailing_stop``, ``entry_price``, ``target1``.
        current_price : float
            Latest traded price.
        atr : float
            Current ATR value.

        Returns
        -------
        float
            New trailing stop level (rounded to 2 decimals).
        """
        old_stop = float(trade.get("trailing_stop", 0))
        entry = float(trade.get("entry_price", 0))
        t1 = float(trade.get("target1", 0))

        if atr <= 0:
            return old_stop

        # Tighten multiplier after T1
        if t1 > 0 and current_price >= t1:
            mult = 0.5
        else:
            mult = 1.0

        computed = round(current_price - mult * atr, 2)

        # Never let stop go below entry once in profit
        if current_price > entry:
            computed = max(computed, entry)

        # Never move stop down
        return max(old_stop, computed)

    # ------------------------------------------------------------------
    # Human-readable status card
    # ------------------------------------------------------------------

    @staticmethod
    def get_exit_summary(trade: Dict[str, Any], ltp: float = 0.0) -> str:
        """Generate a concise human-readable status card for a trade.

        Parameters
        ----------
        trade : dict
            Trade dict with standard keys.
        ltp : float
            Current last-traded price.

        Returns
        -------
        str
            Multi-line status card.
        """
        sym = trade.get("symbol", "???")
        entry = float(trade.get("entry_price", 0))
        sl = float(trade.get("stop_loss", 0))
        t1 = float(trade.get("target1", 0))
        t2 = float(trade.get("target2", 0))
        trail = float(trade.get("trailing_stop", 0))
        qty = int(trade.get("qty", 0))

        pnl = (ltp - entry) * qty if ltp > 0 and entry > 0 else 0.0
        pnl_pct = ((ltp - entry) / entry * 100) if entry > 0 and ltp > 0 else 0.0
        status_emoji = "PROFIT" if pnl >= 0 else "LOSS"

        # Distance to targets / stop
        dist_sl = ((ltp - sl) / ltp * 100) if ltp > 0 and sl > 0 else 0.0
        dist_t1 = ((t1 - ltp) / ltp * 100) if ltp > 0 and t1 > 0 else 0.0

        lines = [
            f"=== {sym} Status Card ===",
            f"  Entry:   {entry:.2f}  |  LTP: {ltp:.2f}",
            f"  SL:      {sl:.2f}  |  Trail: {trail:.2f}" if trail > 0 else f"  SL:      {sl:.2f}",
            f"  T1:      {t1:.2f}  |  T2: {t2:.2f}",
            f"  Qty:     {qty}",
            f"  P&L:     {pnl:+.2f} INR ({pnl_pct:+.2f}%)  [{status_emoji}]",
            f"  Dist SL: {dist_sl:.2f}%  |  Dist T1: {dist_t1:.2f}%",
            "========================",
        ]
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _regime_turned_adverse(entry_regime: str, current_regime: str) -> bool:
        """Return True if the regime change is unfavourable for a LONG position.

        Adverse transitions:
        - TREND_UP -> TREND_DOWN
        - TREND_UP -> HIGH_VOL_EVENT
        - Any -> HIGH_VOL_EVENT (except if entered during HIGH_VOL_EVENT)
        """
        if entry_regime == current_regime:
            return False

        adverse_transitions = {
            ("TREND_UP", "TREND_DOWN"),
            ("TREND_UP", "HIGH_VOL_EVENT"),
            ("TREND_UP", "HIGH_VOL"),
            ("RANGE_CHOP", "TREND_DOWN"),
            ("RANGE_CHOP", "HIGH_VOL_EVENT"),
            ("LOW_VOL", "HIGH_VOL_EVENT"),
            ("LOW_VOL", "TREND_DOWN"),
        }
        return (entry_regime, current_regime) in adverse_transitions

    @staticmethod
    def _tighten_stop_for_vol_collapse(
        stop_loss: float,
        entry: float,
        ltp: float,
    ) -> float:
        """Move the stop closer when volume collapses.

        Shift the stop to the midpoint between the current stop and entry
        (if still in loss) or to 50% of the unrealised profit (if profitable).
        """
        if ltp > entry:
            # Lock in half the unrealised gain
            return round(entry + (ltp - entry) * 0.5, 2)
        else:
            # Tighten toward entry to reduce loss
            return round((stop_loss + entry) / 2, 2)
