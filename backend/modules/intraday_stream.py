"""
intraday_stream.py
==================
Intraday data manager for the NSE Market Intelligence platform.

Polls live quotes during market hours (9:15-15:30 IST), aggregates them into
1-minute and 5-minute OHLCV bars, computes VWAP and opening range, and
provides time-of-day scoring factors.

Usage:
    from backend.modules.market_data_provider import CompositeProvider
    from backend.modules.intraday_stream import IntraDayManager

    mgr = IntraDayManager(provider=CompositeProvider())
    mgr.start_stream(["RELIANCE", "INFY", "HDFCBANK"])
    bar  = mgr.get_current_bar("RELIANCE")
    vwap = mgr.get_vwap("RELIANCE")
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# IST offset
_IST = timezone(timedelta(hours=5, minutes=30))


# ---------------------------------------------------------------------------
# Time-of-day session taxonomy
# ---------------------------------------------------------------------------

class SessionPhase(Enum):
    """Intraday session phases with associated behaviour."""
    PRE_MARKET       = "pre_market"
    OPENING_RANGE    = "opening_range"      # 09:15 - 09:45
    PRIME_TRADING    = "prime_trading"       # 09:45 - 11:30
    MIDDAY_CHOP      = "midday_chop"        # 11:30 - 13:30
    AFTERNOON_REVIVAL = "afternoon_revival"  # 13:30 - 14:45
    CLOSING_RUSH     = "closing_rush"       # 14:45 - 15:15
    SQUARE_OFF_ONLY  = "square_off_only"    # 15:15 - 15:30
    POST_MARKET      = "post_market"


# Phase boundaries in minutes from midnight IST
_PHASE_BOUNDARIES: List[Tuple[int, int, SessionPhase, float]] = [
    # (start_min, end_min, phase, scoring_factor)
    (555,  585, SessionPhase.OPENING_RANGE,     0.0),   # 09:15 - 09:45
    (585,  690, SessionPhase.PRIME_TRADING,     0.2),   # 09:45 - 11:30
    (690,  810, SessionPhase.MIDDAY_CHOP,      -0.3),   # 11:30 - 13:30
    (810,  885, SessionPhase.AFTERNOON_REVIVAL,  0.1),   # 13:30 - 14:45
    (885,  915, SessionPhase.CLOSING_RUSH,      0.05),  # 14:45 - 15:15
    (915,  930, SessionPhase.SQUARE_OFF_ONLY,  -0.2),   # 15:15 - 15:30
]

# Market hours
_MARKET_OPEN_MIN = 555   # 09:15
_MARKET_CLOSE_MIN = 930  # 15:30


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class OHLCVBar:
    """A single OHLCV bar."""
    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    interval: str = "1m"  # "1m" or "5m"

    def update_with_tick(self, price: float, tick_volume: int) -> None:
        """Update bar with a new tick."""
        self.high = max(self.high, price)
        self.low = min(self.low, price)
        self.close = price
        self.volume += tick_volume


@dataclass
class VWAPState:
    """Running VWAP accumulator."""
    cumulative_tp_volume: float = 0.0   # sum(typical_price * volume)
    cumulative_volume: int = 0

    @property
    def vwap(self) -> float:
        if self.cumulative_volume == 0:
            return 0.0
        return self.cumulative_tp_volume / self.cumulative_volume

    def add_bar(self, bar: OHLCVBar) -> None:
        tp = (bar.high + bar.low + bar.close) / 3.0
        self.cumulative_tp_volume += tp * bar.volume
        self.cumulative_volume += bar.volume


@dataclass
class OpeningRange:
    """High / low of the first 15 minutes (09:15 - 09:30)."""
    high: float = 0.0
    low: float = float("inf")
    complete: bool = False

    def update(self, price: float) -> None:
        self.high = max(self.high, price)
        if price > 0:
            self.low = min(self.low, price)


@dataclass
class SymbolSession:
    """All intraday state for a single symbol during one trading day."""
    symbol: str
    bars_1m: List[OHLCVBar] = field(default_factory=list)
    bars_5m: List[OHLCVBar] = field(default_factory=list)
    vwap_state: VWAPState = field(default_factory=VWAPState)
    opening_range: OpeningRange = field(default_factory=OpeningRange)
    last_price: float = 0.0
    last_volume: int = 0
    _current_1m_bar: Optional[OHLCVBar] = field(default=None, repr=False)
    _current_5m_bar: Optional[OHLCVBar] = field(default=None, repr=False)


# ---------------------------------------------------------------------------
# IntraDayManager
# ---------------------------------------------------------------------------

class IntraDayManager:
    """Polls live quotes and maintains intraday bars, VWAP, and opening range.

    Parameters
    ----------
    provider : MarketDataProvider
        A concrete provider (e.g., CompositeProvider).
    poll_interval : float
        Seconds between polling cycles (default 15).
    """

    def __init__(self, provider=None, poll_interval: float = 15.0) -> None:
        self._provider = provider
        self._poll_interval = poll_interval
        self._sessions: Dict[str, SymbolSession] = {}
        self._symbols: List[str] = []
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    # -- lifecycle -----------------------------------------------------------

    def start_stream(self, symbols: List[str]) -> None:
        """Begin polling quotes for *symbols* in a background thread."""
        if self._running:
            logger.warning("Stream already running; adding symbols")
            with self._lock:
                for s in symbols:
                    if s not in self._symbols:
                        self._symbols.append(s)
                        self._sessions[s] = SymbolSession(symbol=s)
            return

        self._symbols = list(symbols)
        with self._lock:
            for s in symbols:
                self._sessions[s] = SymbolSession(symbol=s)

        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True, name="intraday-poller")
        self._thread.start()
        logger.info("Intraday stream started for %d symbols", len(symbols))

    def stop_stream(self) -> None:
        """Stop the polling thread."""
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=30)
            self._thread = None
        logger.info("Intraday stream stopped")

    # -- queries -------------------------------------------------------------

    def get_current_bar(self, symbol: str, interval: str = "1m") -> Optional[OHLCVBar]:
        """Return the latest (possibly incomplete) bar."""
        with self._lock:
            session = self._sessions.get(symbol)
            if session is None:
                return None
            if interval == "5m":
                return session._current_5m_bar or (session.bars_5m[-1] if session.bars_5m else None)
            return session._current_1m_bar or (session.bars_1m[-1] if session.bars_1m else None)

    def get_vwap(self, symbol: str) -> float:
        """Return current session VWAP for *symbol*."""
        with self._lock:
            session = self._sessions.get(symbol)
            if session is None:
                return 0.0
            return round(session.vwap_state.vwap, 2)

    def get_opening_range(self, symbol: str) -> Tuple[float, float]:
        """Return (high, low) of the first 15 minutes."""
        with self._lock:
            session = self._sessions.get(symbol)
            if session is None:
                return (0.0, 0.0)
            orng = session.opening_range
            low = orng.low if orng.low != float("inf") else 0.0
            return (round(orng.high, 2), round(low, 2))

    def get_bars(self, symbol: str, interval: str = "1m") -> List[OHLCVBar]:
        """Return all completed bars for *symbol* today."""
        with self._lock:
            session = self._sessions.get(symbol)
            if session is None:
                return []
            if interval == "5m":
                return list(session.bars_5m)
            return list(session.bars_1m)

    # -- time-of-day ---------------------------------------------------------

    @staticmethod
    def is_market_open() -> bool:
        """Return True if current IST time is within 9:15-15:30 on a weekday."""
        now = datetime.now(_IST)
        if now.weekday() >= 5:
            return False
        mins = now.hour * 60 + now.minute
        return _MARKET_OPEN_MIN <= mins < _MARKET_CLOSE_MIN

    @staticmethod
    def get_session_phase() -> SessionPhase:
        """Return the current session phase."""
        now = datetime.now(_IST)
        mins = now.hour * 60 + now.minute
        for start, end, phase, _ in _PHASE_BOUNDARIES:
            if start <= mins < end:
                return phase
        if mins < _MARKET_OPEN_MIN:
            return SessionPhase.PRE_MARKET
        return SessionPhase.POST_MARKET

    @staticmethod
    def get_time_of_day_factor() -> float:
        """Return a scoring adjustment based on the current session phase.

        Range: -0.3 (midday chop) to +0.2 (prime trading).
        Returns 0.0 outside market hours.
        """
        now = datetime.now(_IST)
        mins = now.hour * 60 + now.minute
        for start, end, _, factor in _PHASE_BOUNDARIES:
            if start <= mins < end:
                return factor
        return 0.0

    # -- EOD flush -----------------------------------------------------------

    def flush_to_storage(self) -> Dict[str, int]:
        """Flush all in-memory bars to persistent storage (placeholder).

        Returns dict of {symbol: bar_count}.

        TODO: write bars to SQLite / Parquet / InfluxDB
        """
        summary: Dict[str, int] = {}
        with self._lock:
            for sym, session in self._sessions.items():
                count = len(session.bars_1m)
                summary[sym] = count
                logger.info("Flushing %d 1m-bars for %s", count, sym)
                # TODO: actual DB write
            # Reset sessions
            self._sessions.clear()
            for sym in self._symbols:
                self._sessions[sym] = SymbolSession(symbol=sym)
        return summary

    # -- internal poll loop --------------------------------------------------

    def _poll_loop(self) -> None:
        """Background thread: poll quotes every _poll_interval seconds."""
        logger.info("Poll loop started (interval=%.1fs)", self._poll_interval)
        while self._running:
            if not self.is_market_open():
                time.sleep(30)
                continue
            try:
                self._poll_once()
            except Exception:
                logger.exception("Error in poll cycle")
            time.sleep(self._poll_interval)
        logger.info("Poll loop exited")

    def _poll_once(self) -> None:
        """Execute one polling cycle for all tracked symbols."""
        if self._provider is None:
            return

        now = datetime.now(_IST)
        minute_key = now.strftime("%H:%M")
        five_min_key = f"{now.hour}:{(now.minute // 5) * 5:02d}"

        quotes = self._provider.get_bulk_quotes(self._symbols)

        with self._lock:
            for sym, quote in quotes.items():
                session = self._sessions.get(sym)
                if session is None:
                    continue

                price = quote.ltp
                vol = quote.volume
                if price <= 0:
                    continue

                session.last_price = price
                session.last_volume = vol

                # Opening range (first 15 minutes: 09:15 - 09:30)
                mins = now.hour * 60 + now.minute
                if 555 <= mins < 570 and not session.opening_range.complete:
                    session.opening_range.update(price)
                elif mins >= 570:
                    session.opening_range.complete = True

                # 1-minute bar
                self._update_bar(
                    session, price, vol, now, minute_key, "1m",
                )

                # 5-minute bar
                self._update_bar(
                    session, price, vol, now, five_min_key, "5m",
                )

    @staticmethod
    def _update_bar(
        session: SymbolSession,
        price: float,
        volume: int,
        now: datetime,
        bar_key: str,
        interval: str,
    ) -> None:
        """Create or update a bar for the given interval."""
        if interval == "1m":
            current = session._current_1m_bar
            bars = session.bars_1m
        else:
            current = session._current_5m_bar
            bars = session.bars_5m

        if current is None or current.timestamp.strftime(
            "%H:%M" if interval == "1m" else "%H:"
        ) != bar_key[:5] if interval == "5m" else current.timestamp.strftime("%H:%M") != bar_key:
            # Finalize previous bar
            if current is not None:
                bars.append(current)
                session.vwap_state.add_bar(current)

            new_bar = OHLCVBar(
                symbol=session.symbol,
                timestamp=now,
                open=price,
                high=price,
                low=price,
                close=price,
                volume=0,
                interval=interval,
            )
            if interval == "1m":
                session._current_1m_bar = new_bar
            else:
                session._current_5m_bar = new_bar
        else:
            current.update_with_tick(price, 0)
