"""
data_loader.py
==============
Historical data loading utilities for the NSE Market Intelligence backtester.

Downloads OHLCV data from Yahoo Finance (yfinance) for NSE-listed equities,
caches results, and provides universe lists (Nifty 50, Nifty 200).
"""
from __future__ import annotations

import logging
import time
from datetime import date, timedelta
from typing import Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Nifty 50 constituents (as of early 2026, subject to periodic rebalancing)
# ---------------------------------------------------------------------------

NIFTY50_SYMBOLS: List[str] = [
    "ADANIENT", "ADANIPORTS", "APOLLOHOSP", "ASIANPAINT", "AXISBANK",
    "BAJAJ-AUTO", "BAJFINANCE", "BAJAJFINSV", "BPCL", "BHARTIARTL",
    "BRITANNIA", "CIPLA", "COALINDIA", "DIVISLAB", "DRREDDY",
    "EICHERMOT", "GRASIM", "HCLTECH", "HDFCBANK", "HDFCLIFE",
    "HEROMOTOCO", "HINDALCO", "HINDUNILVR", "ICICIBANK", "ITC",
    "INDUSINDBK", "INFY", "JSWSTEEL", "KOTAKBANK", "LT",
    "M&M", "MARUTI", "NTPC", "NESTLEIND", "ONGC",
    "POWERGRID", "RELIANCE", "SBILIFE", "SBIN", "SUNPHARMA",
    "TCS", "TATACONSUM", "TATAMOTORS", "TATASTEEL", "TECHM",
    "TITAN", "ULTRACEMCO", "WIPRO", "SHRIRAMFIN", "TRENT",
]

# ---------------------------------------------------------------------------
# Nifty 200 constituents (Nifty 50 + Next 50 + Midcap select)
# ---------------------------------------------------------------------------

NIFTY200_SYMBOLS: List[str] = NIFTY50_SYMBOLS + [
    # Nifty Next 50
    "ABB", "ADANIGREEN", "AMBUJACEM", "ATGL", "BANKBARODA",
    "BEL", "BHEL", "BOSCHLTD", "CANBK", "CHOLAFIN",
    "COLPAL", "DABUR", "DLF", "GAIL", "GODREJCP",
    "HAL", "HAVELLS", "ICICIPRULI", "IDFCFIRSTB", "IGL",
    "INDHOTEL", "IOC", "IRCTC", "IREDA", "JIOFIN",
    "JSWENERGY", "LICI", "LODHA", "LUPIN", "MAZDOCK",
    "MOTHERSON", "NHPC", "NMDC", "NYKAA", "OFSS",
    "PAYTM", "PEL", "PERSISTENT", "PIIND", "PNB",
    "POLYCAB", "SAIL", "SBICARD", "SIEMENS", "SJVN",
    "TORNTPHARM", "TVSMOTOR", "UNIONBANK", "VEDL", "ZOMATO",
    # Midcap select / additional 100
    "AARTIIND", "ACC", "ABCAPITAL", "ABFRL", "AIAENG",
    "ALKEM", "ANGELONE", "ASTRAL", "AUROPHARMA", "BALRAMCHIN",
    "BANDHANBNK", "BATAINDIA", "BERGEPAINT", "BIKAJI", "BIOCON",
    "BSE", "CANFINHOME", "CDSL", "CENTRALBK", "CESC",
    "CHAMBLFERT", "CLEAN", "COCHINSHIP", "CONCOR", "COROMANDEL",
    "CROMPTON", "CUB", "CUMMINSIND", "DEEPAKNTR", "DELHIVERY",
    "DEVYANI", "DIXON", "EMAMILTD", "ENDURANCE", "EQUITASBNK",
    "ESCORTS", "EXIDEIND", "FEDERALBNK", "FLUOROCHEM", "GLENMARK",
    "GLAXO", "GMRAIRPORT", "GNFC", "GRANULES", "GRSE",
    "GSPL", "GUJGASLTD", "HINDCOPPER", "HONAUT", "IDBI",
    "IDEA", "INDIANB", "INDIAMART", "INDUSTOWER", "IPCALAB",
    "IRB", "J&KBANK", "JKCEMENT", "JINDALSTEL", "JSWINFRA",
    "JUBLFOOD", "KALYANKJIL", "KEI", "KPITTECH", "L&TFH",
    "LALPATHLAB", "LAURUSLABS", "LICHSGFIN", "LTTS", "MANAPPURAM",
    "MANYAVAR", "MCX", "METROPOLIS", "MFSL", "MGL",
    "MIDCPNIFTY", "MPHASIS", "MRF", "MUTHOOTFIN", "NAM-INDIA",
    "NATIONALUM", "NAUKRI", "NAVINFLUOR", "OBEROIRLTY", "OIL",
    "PAGEIND", "PGHH", "PHOENIXLTD", "PIDILITIND", "PVR",
    "PVRINOX", "RAILTEL", "RAMCOCEM", "RVNL", "RECLTD",
    "SANOFI", "SCHAEFFLER", "SONACOMS", "STARHEALTH", "SUMICHEM",
    "SUNDARMFIN", "SUPREMEIND", "SYNGENE", "TATACOMM", "TATACHEM",
    "TATAELXSI", "TATAPOWER", "TIINDIA", "TORNTPOWER", "TRIDENT",
    "VOLTAS", "WHIRLPOOL", "YESBANK", "ZEEL", "ZYDUSLIFE",
]


def load_history(
    symbol: str,
    start_date: date,
    end_date: date,
    *,
    buffer_days: int = 300,
) -> pd.DataFrame:
    """Download daily OHLCV history for a single NSE symbol.

    Adds a lookback buffer before ``start_date`` so indicators (e.g. 200-EMA)
    have sufficient warm-up data.

    Parameters
    ----------
    symbol : str
        NSE symbol (without ``.NS`` suffix).
    start_date : date
        Backtest start date.
    end_date : date
        Backtest end date.
    buffer_days : int
        Extra calendar days prepended for indicator warm-up (default 300).

    Returns
    -------
    pd.DataFrame
        OHLCV DataFrame with a DatetimeIndex and columns:
        Open, High, Low, Close, Volume.
    """
    import yfinance as yf

    ticker = f"{symbol}.NS"
    fetch_start = start_date - timedelta(days=buffer_days)

    try:
        df = yf.download(
            ticker,
            start=fetch_start.isoformat(),
            end=(end_date + timedelta(days=1)).isoformat(),
            progress=False,
            auto_adjust=False,
        )
    except Exception as exc:
        logger.warning("Failed to download %s: %s", ticker, exc)
        return pd.DataFrame()

    if df is None or df.empty:
        logger.warning("No data returned for %s", ticker)
        return pd.DataFrame()

    # Handle multi-level columns from yfinance
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    # Ensure standard column names
    col_map = {c: c.title() for c in df.columns}
    df = df.rename(columns=col_map)

    required = {"Open", "High", "Low", "Close", "Volume"}
    if not required.issubset(set(df.columns)):
        logger.warning("Missing columns for %s: have %s", symbol, list(df.columns))
        return pd.DataFrame()

    df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
    df.dropna(subset=["Close"], inplace=True)

    return df


def load_benchmark(
    start_date: date,
    end_date: date,
    symbol: str = "^NSEI",
    buffer_days: int = 300,
) -> pd.DataFrame:
    """Download benchmark index data (default: Nifty 50).

    Parameters
    ----------
    start_date : date
        Backtest start date.
    end_date : date
        Backtest end date.
    symbol : str
        Yahoo Finance ticker for the benchmark (default ``^NSEI``).
    buffer_days : int
        Lookback buffer for indicator warm-up.

    Returns
    -------
    pd.DataFrame
        OHLCV DataFrame.
    """
    import yfinance as yf

    fetch_start = start_date - timedelta(days=buffer_days)

    try:
        df = yf.download(
            symbol,
            start=fetch_start.isoformat(),
            end=(end_date + timedelta(days=1)).isoformat(),
            progress=False,
            auto_adjust=False,
        )
    except Exception as exc:
        logger.warning("Failed to download benchmark %s: %s", symbol, exc)
        return pd.DataFrame()

    if df is None or df.empty:
        return pd.DataFrame()

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    col_map = {c: c.title() for c in df.columns}
    df = df.rename(columns=col_map)

    required = {"Open", "High", "Low", "Close", "Volume"}
    if not required.issubset(set(df.columns)):
        return pd.DataFrame()

    df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
    df.dropna(subset=["Close"], inplace=True)

    return df


# ---------------------------------------------------------------------------
# Full NSE Universe (from EQUITY_L.csv)
# ---------------------------------------------------------------------------

_EQUITY_L_CACHE: Optional[List[str]] = None
_EQUITY_L_CACHE_TIME: float = 0


def load_full_nse_universe(cache_ttl_hours: int = 168) -> List[str]:
    """Fetch the full NSE equity universe from EQUITY_L.csv.

    Results are cached for ``cache_ttl_hours`` (default 7 days).
    Falls back to NIFTY200_SYMBOLS if the fetch fails.
    """
    global _EQUITY_L_CACHE, _EQUITY_L_CACHE_TIME
    if _EQUITY_L_CACHE and (time.time() - _EQUITY_L_CACHE_TIME) < cache_ttl_hours * 3600:
        return _EQUITY_L_CACHE

    try:
        import requests
        r = requests.get(
            "https://archives.nseindia.com/content/equities/EQUITY_L.csv",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=20,
        )
        if r.status_code == 200:
            syms = [
                ln.split(",")[0].strip()
                for ln in r.text.splitlines()[1:]
                if ln.strip()
            ]
            syms = [s for s in syms if s and s != "SYMBOL"]
            _EQUITY_L_CACHE = syms
            _EQUITY_L_CACHE_TIME = time.time()
            logger.info("Loaded %d symbols from EQUITY_L.csv", len(syms))
            return syms
    except Exception as exc:
        logger.warning("EQUITY_L.csv fetch failed: %s", exc)

    logger.info("Falling back to NIFTY200 (%d symbols)", len(NIFTY200_SYMBOLS))
    return list(NIFTY200_SYMBOLS)


def build_watchlist(
    min_avg_volume: int = 50_000,
    min_price: float = 10.0,
    max_price: float = 50_000.0,
    min_turnover: float = 10_000_000,
) -> List[str]:
    """Build a filtered watchlist from the full NSE universe.

    Applies liquidity and price filters. Downloads a quick 5-day history
    per symbol to check volume. Returns 200-400 symbols that pass filters.
    This is designed to run weekly (Sunday evening).
    """
    import yfinance as yf

    full = load_full_nse_universe()
    logger.info("Building watchlist from %d symbols...", len(full))

    watchlist = []
    BATCH = 40

    for i in range(0, len(full), BATCH):
        batch = full[i:i + BATCH]
        tickers_str = " ".join(f"{s}.NS" for s in batch)
        try:
            data = yf.download(
                tickers_str, period="5d", group_by="ticker",
                progress=False, threads=True,
            )
            if data is None or data.empty:
                continue

            for sym in batch:
                try:
                    ticker = f"{sym}.NS"
                    if len(batch) == 1:
                        df = data
                    else:
                        if ticker not in data.columns.get_level_values(0):
                            continue
                        df = data[ticker].dropna()

                    if df.empty or len(df) < 2:
                        continue

                    close = float(df["Close"].iloc[-1])
                    vol = float(df["Volume"].mean())

                    if close < min_price or close > max_price:
                        continue
                    if vol < min_avg_volume:
                        continue
                    if vol * close < min_turnover:
                        continue

                    watchlist.append(sym)
                except Exception:
                    continue

            # Rate limiting
            time.sleep(0.5)
        except Exception:
            continue

        if (i // BATCH + 1) % 10 == 0:
            logger.info(
                "Watchlist progress: %d/%d batches, %d symbols passed",
                i // BATCH + 1, (len(full) + BATCH - 1) // BATCH, len(watchlist),
            )

    logger.info("Watchlist built: %d symbols from %d universe", len(watchlist), len(full))
    return watchlist


def load_nifty50_symbols() -> List[str]:
    """Return the hardcoded Nifty 50 constituent list."""
    return list(NIFTY50_SYMBOLS)


def load_nifty200_symbols() -> List[str]:
    """Return the hardcoded Nifty 200 constituent list."""
    return list(NIFTY200_SYMBOLS)


def preload_universe(
    symbols: List[str],
    start_date: date,
    end_date: date,
    buffer_days: int = 300,
) -> Dict[str, pd.DataFrame]:
    """Batch-download OHLCV data for an entire universe.

    Downloads all symbols sequentially with progress logging.  Symbols that
    fail to download are silently skipped.

    Parameters
    ----------
    symbols : list[str]
        NSE symbols (without ``.NS``).
    start_date : date
        Backtest start date.
    end_date : date
        Backtest end date.
    buffer_days : int
        Lookback buffer days.

    Returns
    -------
    dict[str, pd.DataFrame]
        Mapping of symbol -> OHLCV DataFrame.
    """
    universe: Dict[str, pd.DataFrame] = {}
    total = len(symbols)

    for i, sym in enumerate(symbols, 1):
        if i % 10 == 0 or i == total:
            logger.info("Downloading %d/%d: %s ...", i, total, sym)

        df = load_history(sym, start_date, end_date, buffer_days=buffer_days)
        if not df.empty:
            universe[sym] = df
        else:
            logger.debug("Skipped %s (no data)", sym)

    logger.info(
        "Preloaded %d/%d symbols successfully.",
        len(universe),
        total,
    )
    return universe
