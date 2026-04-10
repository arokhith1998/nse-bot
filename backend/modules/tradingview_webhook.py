"""
NSE Market Intelligence Platform - TradingView Webhook Processing
=================================================================
Parses raw TradingView webhook payloads, normalises them into internal
Signal dicts, and validates symbols against the trading universe.

PineScript Alert Template (TODO)
---------------------------------
Paste this into TradingView's "Alert Message" field::

    {
        "ticker": "{{ticker}}",
        "action": "{{strategy.order.action}}",
        "price": {{close}},
        "strategy": "{{strategy.order.comment}}",
        "interval": "{{interval}}",
        "time": "{{time}}",
        "exchange": "{{exchange}}",
        "volume": {{volume}},
        "open": {{open}},
        "high": {{high}},
        "low": {{low}},
        "close": {{close}},
        "message": "{{strategy.order.alert_message}}",
        "secret": "YOUR_WEBHOOK_SECRET_HERE"
    }
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Known NSE exchange prefixes that TradingView may prepend to tickers.
_EXCHANGE_PREFIXES = ("NSE:", "BSE:", "MCX:", "NFO:")

# Default ATR-based stop/target percentages when no levels are provided.
_DEFAULT_STOP_PCT = 2.0   # 2% below entry for long
_DEFAULT_T1_PCT = 3.0     # 3% above entry for long
_DEFAULT_T2_PCT = 5.0     # 5% above entry for long


# =====================================================================
# TVAlert dataclass
# =====================================================================

@dataclass
class TVAlert:
    """Parsed representation of a TradingView webhook alert."""
    ticker: str
    exchange: str
    action: str          # buy | sell | close
    price: float
    strategy: str
    interval: Optional[str] = None
    time: Optional[str] = None
    message: Optional[str] = None
    volume: Optional[float] = None
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    close: Optional[float] = None
    raw: Dict[str, Any] = field(default_factory=dict)


# =====================================================================
# Parse
# =====================================================================

def parse_tv_alert(payload: Dict[str, Any]) -> TVAlert:
    """Parse a raw TradingView webhook JSON dict into a TVAlert.

    Parameters
    ----------
    payload : dict
        The deserialized JSON body from the webhook POST.

    Returns
    -------
    TVAlert

    Raises
    ------
    ValueError
        If required fields (ticker, action, price) are missing or invalid.
    """
    ticker_raw = payload.get("ticker", "").strip()
    if not ticker_raw:
        raise ValueError("Missing required field: 'ticker'")

    action = payload.get("action", "").strip().lower()
    if action not in ("buy", "sell", "close"):
        raise ValueError(f"Invalid action '{action}'. Expected one of: buy, sell, close")

    try:
        price = float(payload["price"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"Missing or invalid 'price': {exc}")
    if price <= 0:
        raise ValueError(f"Price must be positive, got {price}")

    # Strip exchange prefix from ticker
    exchange = payload.get("exchange", "NSE") or "NSE"
    symbol = ticker_raw
    for prefix in _EXCHANGE_PREFIXES:
        if symbol.upper().startswith(prefix):
            exchange = prefix.rstrip(":")
            symbol = symbol[len(prefix):]
            break

    symbol = symbol.strip().upper()
    if not symbol:
        raise ValueError("Ticker is empty after stripping exchange prefix.")

    return TVAlert(
        ticker=symbol,
        exchange=exchange.upper(),
        action=action,
        price=price,
        strategy=payload.get("strategy", "TradingView Alert") or "TradingView Alert",
        interval=payload.get("interval"),
        time=payload.get("time"),
        message=payload.get("message"),
        volume=_safe_float(payload.get("volume")),
        open=_safe_float(payload.get("open")),
        high=_safe_float(payload.get("high")),
        low=_safe_float(payload.get("low")),
        close=_safe_float(payload.get("close")),
        raw=payload,
    )


# =====================================================================
# Normalise to internal Signal dict
# =====================================================================

def normalize_to_signal(
    tv_alert: TVAlert,
    regime: Optional[str] = None,
) -> Dict[str, Any]:
    """Convert a parsed TVAlert into a dict suitable for creating a Signal ORM.

    Parameters
    ----------
    tv_alert : TVAlert
        The parsed TradingView alert.
    regime : str, optional
        Current market regime label (e.g. 'risk_on', 'choppy').

    Returns
    -------
    dict
        Fields matching the Signal model constructor kwargs.
    """
    direction = "long" if tv_alert.action == "buy" else "short"
    price = tv_alert.price

    # Compute default entry zone, stop-loss, and targets
    if direction == "long":
        entry_zone_low = round(price * 0.998, 2)    # 0.2% below
        entry_zone_high = round(price * 1.002, 2)    # 0.2% above
        stop_loss = round(price * (1 - _DEFAULT_STOP_PCT / 100), 2)
        target1 = round(price * (1 + _DEFAULT_T1_PCT / 100), 2)
        target2 = round(price * (1 + _DEFAULT_T2_PCT / 100), 2)
    else:
        entry_zone_low = round(price * 0.998, 2)
        entry_zone_high = round(price * 1.002, 2)
        stop_loss = round(price * (1 + _DEFAULT_STOP_PCT / 100), 2)
        target1 = round(price * (1 - _DEFAULT_T1_PCT / 100), 2)
        target2 = round(price * (1 - _DEFAULT_T2_PCT / 100), 2)

    # Build explanation string
    explanation_parts = [
        f"TradingView {tv_alert.strategy} alert: {tv_alert.action.upper()} {tv_alert.ticker} @ {price}",
    ]
    if tv_alert.interval:
        explanation_parts.append(f"Interval: {tv_alert.interval}")
    if tv_alert.message:
        explanation_parts.append(f"Message: {tv_alert.message}")
    if regime:
        explanation_parts.append(f"Regime at entry: {regime}")

    # Base score for TradingView signals (neutral; no ML scoring yet).
    # Adjust slightly based on regime confidence if available.
    base_score = 50.0
    confidence = 0.5

    return {
        "symbol": tv_alert.ticker,
        "instrument_type": "stock",
        "direction": direction,
        "score": base_score,
        "strategy": tv_alert.strategy,
        "regime_at_entry": regime,
        "source": "tradingview",
        "entry_zone_low": entry_zone_low,
        "entry_zone_high": entry_zone_high,
        "stop_loss": stop_loss,
        "target1": target1,
        "target2": target2,
        "confidence": confidence,
        "position_size_pct": 0.0,
        "explanation": " | ".join(explanation_parts),
    }


# =====================================================================
# Validation helpers
# =====================================================================

def validate_symbol_in_universe(symbol: str, known_symbols: List[str]) -> bool:
    """Check whether *symbol* exists in the trading universe.

    Parameters
    ----------
    symbol : str
        Cleaned uppercase symbol (e.g. 'RELIANCE').
    known_symbols : list[str]
        Symbols currently in the universe table.

    Returns
    -------
    bool
    """
    return symbol in known_symbols


# =====================================================================
# Internal helpers
# =====================================================================

def _safe_float(val: Any) -> Optional[float]:
    """Convert to float or return None."""
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None
