"""
etf_universe.py
===============
Universe management for NSE equities and ETFs.

Provides functions to fetch the full NSE equity list, maintain a curated ETF
universe with per-category scoring adjustments, and build InstrumentProfile
records used by the scoring engine.

Usage:
    from backend.modules.etf_universe import (
        fetch_nse_equity_universe,
        fetch_etf_universe,
        get_instrument_profile,
        refresh_universe,
    )

    equities = fetch_nse_equity_universe()
    etfs     = fetch_etf_universe()
    profile  = get_instrument_profile("NIFTYBEES")
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums & data classes
# ---------------------------------------------------------------------------

class InstrumentType(Enum):
    EQUITY = "equity"
    ETF = "etf"
    INDEX = "index"


class ETFCategory(Enum):
    BROAD_INDEX = "broad_index"
    SECTOR = "sector"
    COMMODITY = "commodity"
    LIQUID_BOND = "liquid_bond"


@dataclass
class InstrumentProfile:
    """Rich metadata for a tradeable instrument."""
    symbol: str
    name: str = ""
    instrument_type: InstrumentType = InstrumentType.EQUITY
    category: Optional[ETFCategory] = None
    sector: str = ""
    index_membership: List[str] = field(default_factory=list)
    scoring_adjustments: Dict[str, float] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Hardcoded ETF universe (NSE)
# ---------------------------------------------------------------------------

ETF_UNIVERSE: Dict[ETFCategory, List[Dict[str, str]]] = {
    ETFCategory.BROAD_INDEX: [
        {"symbol": "NIFTYBEES", "name": "Nippon India Nifty 50 BeES"},
        {"symbol": "JUNIORBEES", "name": "Nippon India Nifty Next 50 Junior BeES"},
        {"symbol": "BANKBEES", "name": "Nippon India Bank BeES"},
        {"symbol": "SETFNIFTY", "name": "SBI Nifty 50 ETF"},
        {"symbol": "SETFNIF50", "name": "SBI Nifty 50 ETF (alt)"},
        {"symbol": "ICICIN50", "name": "ICICI Pru Nifty 50 ETF"},
        {"symbol": "UTINIFTETF", "name": "UTI Nifty 50 ETF"},
        {"symbol": "MOM50", "name": "Motilal Oswal Nifty 50 ETF"},
        {"symbol": "MIDCAPETF", "name": "Nippon India Nifty Midcap 150 ETF"},
        {"symbol": "NEXT50", "name": "ICICI Pru Nifty Next 50 ETF"},
        {"symbol": "MOM100", "name": "Motilal Oswal Midcap 100 ETF"},
        {"symbol": "NIFTY1", "name": "Kotak Nifty ETF"},
        {"symbol": "LOWVOL1", "name": "ICICI Pru Nifty Low Vol 30 ETF"},
        {"symbol": "NV20", "name": "ICICI Pru NV20 ETF"},
    ],
    ETFCategory.SECTOR: [
        {"symbol": "ITBEES", "name": "Nippon India IT ETF"},
        {"symbol": "PSUBNKBEES", "name": "Nippon India PSU Bank BeES"},
        {"symbol": "INFRAES", "name": "Nippon India Infra ETF"},
        {"symbol": "SETFNN50", "name": "SBI Nifty Next 50 ETF"},
        {"symbol": "PHARMABEES", "name": "Nippon India Pharma ETF"},
        {"symbol": "COMMOETF", "name": "Nippon India Commodities ETF"},
        {"symbol": "DIVOPPBEES", "name": "Nippon India Dividend Opp ETF"},
        {"symbol": "CONSUMETF", "name": "Nippon India Consumption ETF"},
        {"symbol": "AUTOBEES", "name": "Nippon India Auto ETF"},
        {"symbol": "FINIETF", "name": "Nippon India Financial Services ETF"},
        {"symbol": "HEALTHIETF", "name": "Nippon India Healthcare ETF"},
        {"symbol": "PVTBANIETF", "name": "Nippon India Private Bank ETF"},
        {"symbol": "ENERGY", "name": "Nippon India Energy ETF"},
        {"symbol": "METALIETF", "name": "Nippon India Metal ETF"},
    ],
    ETFCategory.COMMODITY: [
        {"symbol": "GOLDBEES", "name": "Nippon India Gold BeES"},
        {"symbol": "GOLDIETF", "name": "ICICI Pru Gold ETF"},
        {"symbol": "SETFGOLD", "name": "SBI Gold ETF"},
        {"symbol": "GOLDETF", "name": "UTI Gold ETF"},
        {"symbol": "AXISGOLD", "name": "Axis Gold ETF"},
        {"symbol": "HDFCGOLD", "name": "HDFC Gold ETF"},
        {"symbol": "KOTAKGOLD", "name": "Kotak Gold ETF"},
        {"symbol": "SILVERBEES", "name": "Nippon India Silver ETF"},
        {"symbol": "SILVERIETF", "name": "ICICI Pru Silver ETF"},
    ],
    ETFCategory.LIQUID_BOND: [
        {"symbol": "LIQUIDBEES", "name": "Nippon India Liquid BeES"},
        {"symbol": "LIQUIDETF", "name": "ICICI Pru Liquid ETF"},
        {"symbol": "LICNETFN50", "name": "LIC Nifty 50 ETF"},
        {"symbol": "LIQUIDCASE", "name": "DSP Liquid ETF"},
        {"symbol": "GILT5YBEES", "name": "Nippon India Gilt 5Y ETF"},
        {"symbol": "NETFGILT5Y", "name": "Nippon India Gilt 5Y (alt)"},
        {"symbol": "ICICIB22", "name": "ICICI Pru Bharat 22 ETF"},
        {"symbol": "CPSEETF", "name": "CPSE ETF"},
    ],
}

# Per-category scoring adjustments
# These multiply the base weight for each scoring component.
_CATEGORY_SCORING: Dict[ETFCategory, Dict[str, float]] = {
    ETFCategory.BROAD_INDEX: {
        "trend": 1.2,
        "momentum": 1.0,
        "volume": 0.8,
        "breakout": 1.0,
        "volatility": 0.8,
        "news": 0.6,        # less stock-specific news
    },
    ETFCategory.SECTOR: {
        "trend": 1.1,
        "momentum": 1.2,
        "volume": 1.0,
        "breakout": 1.1,
        "volatility": 1.0,
        "news": 1.2,         # sector rotation themes
    },
    ETFCategory.COMMODITY: {
        "trend": 1.3,
        "momentum": 1.3,
        "volume": 0.7,
        "breakout": 1.2,
        "volatility": 1.1,
        "news": 1.3,         # global macro / commodity news matters
    },
    ETFCategory.LIQUID_BOND: {
        "trend": 0.5,
        "momentum": 0.3,
        "volume": 0.3,
        "breakout": 0.2,
        "volatility": 0.3,   # near-zero vol is fine
        "news": 0.4,
    },
}


# ---------------------------------------------------------------------------
# Module-level cache for universe
# ---------------------------------------------------------------------------

_equity_universe_cache: Optional[List[str]] = None
_instrument_profiles: Dict[str, InstrumentProfile] = {}


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------

def fetch_nse_equity_universe() -> List[str]:
    """Download the full NSE equity symbol list from EQUITY_L.csv.

    Falls back to a curated 70-symbol list on failure.
    """
    global _equity_universe_cache
    if _equity_universe_cache is not None:
        return list(_equity_universe_cache)

    try:
        import requests
        r = requests.get(
            "https://archives.nseindia.com/content/equities/EQUITY_L.csv",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=20,
        )
        if r.status_code == 200:
            lines = r.text.splitlines()
            syms = [ln.split(",")[0].strip() for ln in lines[1:] if ln.strip()]
            syms = [s for s in syms if s]
            logger.info("Loaded %d symbols from EQUITY_L.csv", len(syms))
            _equity_universe_cache = syms
            return list(syms)
    except Exception as exc:
        logger.warning("EQUITY_L.csv fetch failed: %s", exc)

    # Fallback curated list (Nifty 50 + popular mid/small caps)
    fallback = [
        "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "SBIN", "ITC", "LT",
        "HINDUNILVR", "BHARTIARTL", "KOTAKBANK", "AXISBANK", "BAJFINANCE", "MARUTI",
        "ONGC", "COALINDIA", "NTPC", "POWERGRID", "TATAMOTORS", "TATASTEEL",
        "JSWSTEEL", "HINDALCO", "WIPRO", "HCLTECH", "TECHM", "SUNPHARMA",
        "DRREDDY", "CIPLA", "DIVISLAB", "BAJAJFINSV", "ADANIENT", "ADANIPORTS",
        "TITAN", "NESTLEIND", "BRITANNIA", "ASIANPAINT", "ULTRACEMCO", "GRASIM",
        "EICHERMOT", "HEROMOTOCO", "M&M", "BAJAJ-AUTO", "BPCL", "IOC", "GAIL",
        "PNB", "BANKBARODA", "CANBK", "IDFCFIRSTB", "FEDERALBNK", "IDEA",
        "YESBANK", "SUZLON", "BHEL", "HAL", "BEL", "MAZDOCK", "BDL", "GRSE",
        "COCHINSHIP", "IRFC", "RVNL", "NHPC", "SJVN", "IREDA", "NBCC",
        "RAILTEL", "IRCTC", "NMDC", "SAIL", "VEDL", "DLF",
    ]
    logger.info("Using fallback equity universe (%d symbols)", len(fallback))
    _equity_universe_cache = fallback
    return list(fallback)


def fetch_etf_universe() -> Dict[ETFCategory, List[Dict[str, str]]]:
    """Return the curated ETF universe grouped by category."""
    return {cat: list(etfs) for cat, etfs in ETF_UNIVERSE.items()}


def get_all_etf_symbols() -> List[str]:
    """Flat list of every known ETF symbol."""
    symbols: List[str] = []
    for etfs in ETF_UNIVERSE.values():
        symbols.extend(e["symbol"] for e in etfs)
    return symbols


def get_category_scoring(category: ETFCategory) -> Dict[str, float]:
    """Return scoring adjustments for an ETF category."""
    return dict(_CATEGORY_SCORING.get(category, {}))


def get_instrument_profile(symbol: str) -> InstrumentProfile:
    """Build or return cached InstrumentProfile for *symbol*."""
    if symbol in _instrument_profiles:
        return _instrument_profiles[symbol]

    # Check if symbol is an ETF
    for cat, etfs in ETF_UNIVERSE.items():
        for etf in etfs:
            if etf["symbol"] == symbol:
                profile = InstrumentProfile(
                    symbol=symbol,
                    name=etf["name"],
                    instrument_type=InstrumentType.ETF,
                    category=cat,
                    scoring_adjustments=get_category_scoring(cat),
                )
                _instrument_profiles[symbol] = profile
                return profile

    # Default equity profile
    profile = InstrumentProfile(
        symbol=symbol,
        instrument_type=InstrumentType.EQUITY,
    )
    _instrument_profiles[symbol] = profile
    return profile


def refresh_universe() -> Dict[str, int]:
    """Re-fetch universes and rebuild profile cache.

    Returns a summary dict with counts.
    """
    global _equity_universe_cache
    _equity_universe_cache = None  # force re-fetch
    _instrument_profiles.clear()

    equities = fetch_nse_equity_universe()
    etf_symbols = get_all_etf_symbols()

    # Pre-populate profiles for ETFs
    for sym in etf_symbols:
        get_instrument_profile(sym)

    # TODO: persist universe to SQLite / JSON cache for offline use
    # TODO: fetch sectoral index constituents to populate index_membership
    # TODO: map equities to sectors using EQUITY_L.csv ISIN codes

    summary = {
        "equities": len(equities),
        "etfs": len(etf_symbols),
        "profiles_cached": len(_instrument_profiles),
    }
    logger.info("Universe refreshed: %s", summary)
    return summary
