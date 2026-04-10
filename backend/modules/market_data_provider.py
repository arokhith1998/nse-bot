"""
market_data_provider.py
=======================
Pluggable market-data abstraction for the NSE Market Intelligence platform.

Provides a uniform interface for fetching live quotes and historical OHLCV data
from multiple sources (yfinance, nsepython) with TTL-based caching and automatic
fallback via the CompositeProvider.

Usage:
    provider = CompositeProvider()
    q = provider.get_quote("RELIANCE")
    df = provider.get_history("INFY", days=60, interval="1d")
"""
from __future__ import annotations

import time
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

import pandas as pd

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Quote:
    """Snapshot quote for a single instrument."""
    symbol: str
    ltp: float
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    volume: int = 0
    bid: float = 0.0
    ask: float = 0.0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    source: str = "unknown"


# ---------------------------------------------------------------------------
# TTL Cache
# ---------------------------------------------------------------------------

class _TTLCache:
    """Thread-safe TTL cache keyed by arbitrary string."""

    def __init__(self, default_ttl: float = 15.0):
        self._store: Dict[str, tuple[float, object]] = {}
        self._lock = threading.Lock()
        self._default_ttl = default_ttl

    def get(self, key: str) -> Optional[object]:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            ts, val = entry
            if time.monotonic() - ts > self._default_ttl:
                del self._store[key]
                return None
            return val

    def put(self, key: str, value: object, ttl: Optional[float] = None) -> None:
        with self._lock:
            self._store[key] = (time.monotonic(), value)
            # If a custom TTL is provided we store with a tag; the default TTL
            # of the cache instance still governs expiry for simplicity.

    def invalidate(self, key: str) -> None:
        with self._lock:
            self._store.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()


# Per-concern caches
_quote_cache = _TTLCache(default_ttl=15.0)       # 15 s for live quotes
_history_cache = _TTLCache(default_ttl=3600.0)    # 1 hr for daily history
_intraday_cache = _TTLCache(default_ttl=60.0)     # 1 min for intraday bars


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------

class MarketDataProvider(ABC):
    """Abstract interface every data provider must implement."""

    @abstractmethod
    def get_quote(self, symbol: str) -> Optional[Quote]:
        """Return the latest quote for *symbol*, or None on failure."""
        ...

    @abstractmethod
    def get_history(
        self,
        symbol: str,
        days: int = 120,
        interval: str = "1d",
    ) -> Optional[pd.DataFrame]:
        """Return OHLCV DataFrame (columns: Open, High, Low, Close, Volume)."""
        ...

    def get_bulk_quotes(self, symbols: List[str]) -> Dict[str, Quote]:
        """Fetch quotes for many symbols. Default implementation is sequential."""
        result: Dict[str, Quote] = {}
        for sym in symbols:
            q = self.get_quote(sym)
            if q is not None:
                result[sym] = q
        return result

    def get_intraday(
        self,
        symbol: str,
        interval: str = "1m",
    ) -> Optional[pd.DataFrame]:
        """Return intraday OHLCV. Providers may or may not support this."""
        return None


# ---------------------------------------------------------------------------
# YFinance implementation
# ---------------------------------------------------------------------------

class YFinanceProvider(MarketDataProvider):
    """Market data via the ``yfinance`` library (free, delayed)."""

    def __init__(self) -> None:
        try:
            import yfinance  # noqa: F401
            self._yf = yfinance
        except ImportError as exc:
            raise ImportError("yfinance is required: pip install yfinance") from exc

    def _ticker(self, symbol: str):
        """Return a yfinance Ticker for an NSE symbol."""
        suffix = "" if symbol.endswith(".NS") else ".NS"
        return self._yf.Ticker(f"{symbol}{suffix}")

    # -- quote ---------------------------------------------------------------

    def get_quote(self, symbol: str) -> Optional[Quote]:
        cached = _quote_cache.get(f"yf:{symbol}")
        if cached is not None:
            return cached  # type: ignore[return-value]
        try:
            tkr = self._ticker(symbol)
            info = tkr.fast_info
            q = Quote(
                symbol=symbol,
                ltp=float(getattr(info, "last_price", 0) or 0),
                open=float(getattr(info, "open", 0) or 0),
                high=float(getattr(info, "day_high", 0) or 0),
                low=float(getattr(info, "day_low", 0) or 0),
                close=float(getattr(info, "previous_close", 0) or 0),
                volume=int(getattr(info, "last_volume", 0) or 0),
                source="yfinance",
            )
            _quote_cache.put(f"yf:{symbol}", q)
            return q
        except Exception:
            return None

    # -- history -------------------------------------------------------------

    def get_history(
        self,
        symbol: str,
        days: int = 120,
        interval: str = "1d",
    ) -> Optional[pd.DataFrame]:
        cache_key = f"yf_hist:{symbol}:{days}:{interval}"
        cached = _history_cache.get(cache_key)
        if cached is not None:
            return cached  # type: ignore[return-value]
        try:
            df = self._ticker(symbol).history(
                period=f"{days + 30}d",
                interval=interval,
                auto_adjust=False,
            )
            if df is None or df.empty or len(df) < 10:
                return None
            df = df.tail(days).rename(columns=str.title)
            _history_cache.put(cache_key, df)
            return df
        except Exception:
            return None

    # -- intraday ------------------------------------------------------------

    def get_intraday(
        self,
        symbol: str,
        interval: str = "1m",
    ) -> Optional[pd.DataFrame]:
        cache_key = f"yf_intra:{symbol}:{interval}"
        cached = _intraday_cache.get(cache_key)
        if cached is not None:
            return cached  # type: ignore[return-value]
        try:
            df = self._ticker(symbol).history(period="1d", interval=interval)
            if df is None or df.empty:
                return None
            df = df.rename(columns=str.title)
            _intraday_cache.put(cache_key, df)
            return df
        except Exception:
            return None


# ---------------------------------------------------------------------------
# NSEPython implementation
# ---------------------------------------------------------------------------

class NSEPythonProvider(MarketDataProvider):
    """Live NSE quotes via ``nsepython``."""

    def __init__(self) -> None:
        try:
            from nsepython import nse_eq  # noqa: F401
            self._nse_eq = nse_eq
        except ImportError as exc:
            raise ImportError("nsepython is required: pip install nsepython") from exc

    def get_quote(self, symbol: str) -> Optional[Quote]:
        cached = _quote_cache.get(f"nse:{symbol}")
        if cached is not None:
            return cached  # type: ignore[return-value]
        try:
            data = self._nse_eq(symbol)
            pi = data.get("priceInfo", {})
            q = Quote(
                symbol=symbol,
                ltp=float(pi.get("lastPrice", 0)),
                open=float(pi.get("open", 0)),
                high=float(pi.get("intraDayHighLow", {}).get("max", 0)),
                low=float(pi.get("intraDayHighLow", {}).get("min", 0)),
                close=float(pi.get("previousClose", 0)),
                volume=int(data.get("securityWiseDP", {}).get("quantityTraded", 0)),
                source="nsepython",
            )
            _quote_cache.put(f"nse:{symbol}", q)
            return q
        except Exception:
            return None

    def get_history(
        self,
        symbol: str,
        days: int = 120,
        interval: str = "1d",
    ) -> Optional[pd.DataFrame]:
        # nsepython does not provide convenient historical OHLCV.
        return None


# ---------------------------------------------------------------------------
# Composite (fallback chain)
# ---------------------------------------------------------------------------

class CompositeProvider(MarketDataProvider):
    """Try NSEPython for live quotes first, fall back to yfinance.

    History is always served from yfinance (nsepython lacks this).
    """

    def __init__(self) -> None:
        self._providers: List[MarketDataProvider] = []
        try:
            self._providers.append(NSEPythonProvider())
        except ImportError:
            pass
        try:
            self._providers.append(YFinanceProvider())
        except ImportError:
            pass
        if not self._providers:
            raise RuntimeError(
                "No market-data provider available. "
                "Install at least one of: yfinance, nsepython"
            )
        # Dedicated yfinance instance for history / intraday
        self._yf_provider: Optional[YFinanceProvider] = None
        for p in self._providers:
            if isinstance(p, YFinanceProvider):
                self._yf_provider = p
                break

    # -- quote ---------------------------------------------------------------

    def get_quote(self, symbol: str) -> Optional[Quote]:
        for provider in self._providers:
            q = provider.get_quote(symbol)
            if q is not None and q.ltp > 0:
                return q
        return None

    # -- history (always yfinance) -------------------------------------------

    def get_history(
        self,
        symbol: str,
        days: int = 120,
        interval: str = "1d",
    ) -> Optional[pd.DataFrame]:
        if self._yf_provider is not None:
            return self._yf_provider.get_history(symbol, days, interval)
        # Fallback: try each provider
        for p in self._providers:
            df = p.get_history(symbol, days, interval)
            if df is not None:
                return df
        return None

    # -- bulk quotes ---------------------------------------------------------

    def get_bulk_quotes(self, symbols: List[str]) -> Dict[str, Quote]:
        result: Dict[str, Quote] = {}
        for sym in symbols:
            q = self.get_quote(sym)
            if q is not None:
                result[sym] = q
        return result

    # -- intraday ------------------------------------------------------------

    def get_intraday(
        self,
        symbol: str,
        interval: str = "1m",
    ) -> Optional[pd.DataFrame]:
        if self._yf_provider is not None:
            return self._yf_provider.get_intraday(symbol, interval)
        return None


# ---------------------------------------------------------------------------
# TODO: Additional provider stubs
# ---------------------------------------------------------------------------

# TODO: ZerodhaKiteProvider(MarketDataProvider)
#   - Uses kiteconnect SDK
#   - Real-time WebSocket streaming for quotes
#   - Historical data via instruments API
#   - Requires API key + access token (daily login flow)

# TODO: AngelSmartAPIProvider(MarketDataProvider)
#   - Uses smartapi-python SDK
#   - REST quotes + WebSocket streaming
#   - Historical candle data via /getCandleData

# TODO: DhanAPIProvider(MarketDataProvider)
#   - Uses dhanhq SDK
#   - REST + WebSocket for live data
#   - Intraday and historical OHLCV via /charts/intraday, /charts/historical
