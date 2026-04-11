"""
Simulator API
=============
Endpoints for the "What If" trade simulator.

Given a symbol, capital, and entry details, calculates:
  - Net P&L at day close
  - Net P&L at day high
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(tags=["simulator"])


class SimulatorRequest(BaseModel):
    symbol: str = Field(..., description="Stock or ETF symbol")
    capital: float = Field(100000, ge=100, description="Available capital in INR")
    instrument_type: str = Field("stock", description="'stock' or 'etf'")


class SimulatorResult(BaseModel):
    symbol: str
    name: str
    instrument_type: str
    prev_close: float
    day_open: float
    day_high: float
    day_low: float
    day_close: float
    entry_price: float
    qty: int
    invested: float
    # At day close
    close_value: float
    close_pnl: float
    close_pnl_pct: float
    close_charges: float
    close_net_pnl: float
    # At day high
    high_value: float
    high_pnl: float
    high_pnl_pct: float
    high_charges: float
    high_net_pnl: float
    # Metadata
    volume: int
    avg_volume: int
    data_available: bool
    notes: List[str]


@router.get("/api/simulator/symbols")
async def get_simulator_symbols(
    type: str = Query("all", description="'stock', 'etf', or 'all'"),
) -> Dict[str, Any]:
    """Return list of available symbols for the simulator dropdown."""
    symbols: List[Dict[str, str]] = []

    if type in ("stock", "all"):
        try:
            from backend.modules.etf_universe import fetch_nse_equity_universe
            equities = fetch_nse_equity_universe()
            for sym in sorted(equities):
                symbols.append({
                    "symbol": sym,
                    "name": sym,  # We don't have full names for all equities
                    "type": "stock",
                })
        except Exception as exc:
            logger.warning("Failed to fetch equity universe: %s", exc)

    if type in ("etf", "all"):
        try:
            from backend.modules.etf_universe import ETF_UNIVERSE
            for cat, etfs in ETF_UNIVERSE.items():
                for etf in etfs:
                    symbols.append({
                        "symbol": etf["symbol"],
                        "name": etf["name"],
                        "type": "etf",
                    })
        except Exception as exc:
            logger.warning("Failed to fetch ETF universe: %s", exc)

    return {"symbols": symbols, "count": len(symbols)}


@router.post("/api/simulator/simulate")
async def simulate_trade(req: SimulatorRequest) -> Dict[str, Any]:
    """Simulate a trade: what if you bought at previous day's close?

    Uses the previous trading day's close as entry price, and shows
    P&L at the current/latest day's close and day high.
    """
    from backend.modules.market_data_provider import CompositeProvider

    provider = CompositeProvider()
    symbol = req.symbol.upper()
    capital = req.capital
    notes: List[str] = []

    # Determine name
    name = symbol
    if req.instrument_type == "etf":
        try:
            from backend.modules.etf_universe import ETF_UNIVERSE
            for cat, etfs in ETF_UNIVERSE.items():
                for etf in etfs:
                    if etf["symbol"] == symbol:
                        name = etf["name"]
                        break
        except Exception:
            pass

    # Get historical data (last 5 days to find prev trading day)
    hist = provider.get_history(symbol, days=10, interval="1d")
    if hist is None or len(hist) < 2:
        return {
            "symbol": symbol,
            "name": name,
            "instrument_type": req.instrument_type,
            "prev_close": 0, "day_open": 0, "day_high": 0,
            "day_low": 0, "day_close": 0,
            "entry_price": 0, "qty": 0, "invested": 0,
            "close_value": 0, "close_pnl": 0, "close_pnl_pct": 0,
            "close_charges": 0, "close_net_pnl": 0,
            "high_value": 0, "high_pnl": 0, "high_pnl_pct": 0,
            "high_charges": 0, "high_net_pnl": 0,
            "volume": 0, "avg_volume": 0,
            "data_available": False,
            "notes": ["No historical data available for this symbol."],
        }

    # Previous trading day = second-to-last row
    # Current/latest day = last row
    prev_day = hist.iloc[-2]
    curr_day = hist.iloc[-1]

    prev_close = float(prev_day.get("Close", 0))
    day_open = float(curr_day.get("Open", 0))
    day_high = float(curr_day.get("High", 0))
    day_low = float(curr_day.get("Low", 0))
    day_close = float(curr_day.get("Close", 0))
    volume = int(curr_day.get("Volume", 0))

    # Average volume
    avg_vol = int(hist["Volume"].mean()) if "Volume" in hist.columns else 0

    # Entry = previous day's close
    entry_price = prev_close
    if entry_price <= 0:
        return {
            "symbol": symbol, "name": name,
            "instrument_type": req.instrument_type,
            "prev_close": 0, "day_open": 0, "day_high": 0,
            "day_low": 0, "day_close": 0,
            "entry_price": 0, "qty": 0, "invested": 0,
            "close_value": 0, "close_pnl": 0, "close_pnl_pct": 0,
            "close_charges": 0, "close_net_pnl": 0,
            "high_value": 0, "high_pnl": 0, "high_pnl_pct": 0,
            "high_charges": 0, "high_net_pnl": 0,
            "volume": 0, "avg_volume": 0,
            "data_available": False,
            "notes": ["Invalid price data for this symbol."],
        }

    # Quantity: how many shares can you buy with capital
    qty = max(1, int(capital / entry_price))
    invested = round(entry_price * qty, 2)

    # Charges (Groww flat fee model)
    def calc_charges(buy_price: float, sell_price: float, quantity: int) -> float:
        buy_val = buy_price * quantity
        sell_val = sell_price * quantity
        brokerage = 40  # Rs 20 each side
        stt = sell_val * 0.00025  # 0.025% on sell side for intraday
        exchange_txn = (buy_val + sell_val) * 0.0000345
        gst = (brokerage + exchange_txn) * 0.18
        sebi = (buy_val + sell_val) * 0.000001
        stamp = buy_val * 0.00003
        return round(brokerage + stt + exchange_txn + gst + sebi + stamp, 2)

    # P&L at close
    close_value = round(day_close * qty, 2)
    close_gross = round((day_close - entry_price) * qty, 2)
    close_charges = calc_charges(entry_price, day_close, qty)
    close_net = round(close_gross - close_charges, 2)
    close_pct = round((close_gross / invested) * 100, 2) if invested > 0 else 0

    # P&L at day high
    high_value = round(day_high * qty, 2)
    high_gross = round((day_high - entry_price) * qty, 2)
    high_charges = calc_charges(entry_price, day_high, qty)
    high_net = round(high_gross - high_charges, 2)
    high_pct = round((high_gross / invested) * 100, 2) if invested > 0 else 0

    # Notes
    if day_close > entry_price:
        notes.append(f"Stock gained {((day_close/entry_price - 1)*100):.2f}% from prev close")
    elif day_close < entry_price:
        notes.append(f"Stock fell {((1 - day_close/entry_price)*100):.2f}% from prev close")
    else:
        notes.append("Stock closed flat relative to prev close")

    if day_high > entry_price * 1.02:
        notes.append(f"Intraday high was {((day_high/entry_price - 1)*100):.2f}% above entry")

    gap_pct = ((day_open - entry_price) / entry_price) * 100 if entry_price > 0 else 0
    if abs(gap_pct) > 0.5:
        direction = "up" if gap_pct > 0 else "down"
        notes.append(f"Gap {direction} of {abs(gap_pct):.2f}% at open")

    return {
        "symbol": symbol,
        "name": name,
        "instrument_type": req.instrument_type,
        "prev_close": round(prev_close, 2),
        "day_open": round(day_open, 2),
        "day_high": round(day_high, 2),
        "day_low": round(day_low, 2),
        "day_close": round(day_close, 2),
        "entry_price": round(entry_price, 2),
        "qty": qty,
        "invested": invested,
        "close_value": close_value,
        "close_pnl": close_gross,
        "close_pnl_pct": close_pct,
        "close_charges": close_charges,
        "close_net_pnl": close_net,
        "high_value": high_value,
        "high_pnl": high_gross,
        "high_pnl_pct": high_pct,
        "high_charges": high_charges,
        "high_net_pnl": high_net,
        "volume": volume,
        "avg_volume": avg_vol,
        "data_available": True,
        "notes": notes,
    }
