"""
risk_engine.py
==============
Portfolio-level risk management for the NSE Market Intelligence platform.

Enforces hard limits on position count, sector concentration, portfolio heat,
correlation, and single-stock exposure.  All checks are synchronous and
stateless -- the caller passes in the current portfolio snapshot.

PAPER TRADING ONLY. Not investment advice.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Correlation map (manually maintained for major NSE pairs)
# ---------------------------------------------------------------------------

# Pairs that are highly correlated (same sector, move together).
# Stored as frozensets so lookup is order-independent.
_CORRELATED_PAIRS: List[frozenset] = [
    # Steel
    frozenset({"TATASTEEL", "JSWSTEEL"}),
    frozenset({"TATASTEEL", "SAIL"}),
    frozenset({"JSWSTEEL", "SAIL"}),
    frozenset({"TATASTEEL", "JINDALSTEL"}),
    # Metals (non-ferrous)
    frozenset({"HINDALCO", "VEDL"}),
    frozenset({"HINDALCO", "NATIONALUM"}),
    # Banks (large private)
    frozenset({"HDFCBANK", "ICICIBANK"}),
    frozenset({"HDFCBANK", "KOTAKBANK"}),
    frozenset({"ICICIBANK", "AXISBANK"}),
    # Banks (PSU)
    frozenset({"SBIN", "PNB"}),
    frozenset({"SBIN", "BANKBARODA"}),
    frozenset({"PNB", "CANBK"}),
    frozenset({"BANKBARODA", "CANBK"}),
    # Oil & Gas
    frozenset({"ONGC", "BPCL"}),
    frozenset({"ONGC", "IOC"}),
    frozenset({"BPCL", "IOC"}),
    frozenset({"ONGC", "GAIL"}),
    # IT
    frozenset({"TCS", "INFY"}),
    frozenset({"INFY", "WIPRO"}),
    frozenset({"TCS", "HCLTECH"}),
    frozenset({"WIPRO", "TECHM"}),
    frozenset({"HCLTECH", "TECHM"}),
    # Pharma
    frozenset({"SUNPHARMA", "DRREDDY"}),
    frozenset({"SUNPHARMA", "CIPLA"}),
    frozenset({"DRREDDY", "CIPLA"}),
    # Defence
    frozenset({"HAL", "BEL"}),
    frozenset({"MAZDOCK", "GRSE"}),
    frozenset({"MAZDOCK", "COCHINSHIP"}),
    frozenset({"BDL", "BEL"}),
    # Infrastructure / Rail
    frozenset({"IRFC", "RVNL"}),
    frozenset({"IRFC", "IRCTC"}),
    frozenset({"RAILTEL", "IRCTC"}),
    # Power
    frozenset({"NTPC", "POWERGRID"}),
    frozenset({"NHPC", "SJVN"}),
    # Adani group
    frozenset({"ADANIENT", "ADANIPORTS"}),
]

# Pre-compute a lookup: symbol -> set of correlated symbols
_CORR_LOOKUP: Dict[str, Set[str]] = {}
for _pair in _CORRELATED_PAIRS:
    for _sym in _pair:
        _CORR_LOOKUP.setdefault(_sym, set()).update(_pair - {_sym})


# ---------------------------------------------------------------------------
# Sector map (approximate, for concentration checks)
# ---------------------------------------------------------------------------

_SECTOR_MAP: Dict[str, str] = {
    # Banks
    "HDFCBANK": "BANKING", "ICICIBANK": "BANKING", "KOTAKBANK": "BANKING",
    "AXISBANK": "BANKING", "SBIN": "BANKING", "PNB": "BANKING",
    "BANKBARODA": "BANKING", "CANBK": "BANKING", "IDFCFIRSTB": "BANKING",
    "FEDERALBNK": "BANKING", "YESBANK": "BANKING",
    # IT
    "TCS": "IT", "INFY": "IT", "WIPRO": "IT", "HCLTECH": "IT", "TECHM": "IT",
    # Pharma
    "SUNPHARMA": "PHARMA", "DRREDDY": "PHARMA", "CIPLA": "PHARMA",
    "DIVISLAB": "PHARMA",
    # Metals
    "TATASTEEL": "METALS", "JSWSTEEL": "METALS", "HINDALCO": "METALS",
    "SAIL": "METALS", "VEDL": "METALS", "NMDC": "METALS",
    "JINDALSTEL": "METALS", "NATIONALUM": "METALS",
    # Oil & Gas
    "ONGC": "OIL_GAS", "BPCL": "OIL_GAS", "IOC": "OIL_GAS", "GAIL": "OIL_GAS",
    # Auto
    "MARUTI": "AUTO", "TATAMOTORS": "AUTO", "M&M": "AUTO",
    "BAJAJ-AUTO": "AUTO", "EICHERMOT": "AUTO", "HEROMOTOCO": "AUTO",
    # FMCG
    "HINDUNILVR": "FMCG", "ITC": "FMCG", "NESTLEIND": "FMCG",
    "BRITANNIA": "FMCG",
    # Defence
    "HAL": "DEFENCE", "BEL": "DEFENCE", "BDL": "DEFENCE",
    "MAZDOCK": "DEFENCE", "GRSE": "DEFENCE", "COCHINSHIP": "DEFENCE",
    # Power
    "NTPC": "POWER", "POWERGRID": "POWER", "NHPC": "POWER", "SJVN": "POWER",
    # Infra / Rail
    "LT": "INFRA", "IRFC": "INFRA", "RVNL": "INFRA", "IRCTC": "INFRA",
    "RAILTEL": "INFRA", "NBCC": "INFRA",
    # Telecom
    "BHARTIARTL": "TELECOM", "IDEA": "TELECOM",
    # Financials (non-bank)
    "BAJFINANCE": "NBFC", "BAJAJFINSV": "NBFC", "IREDA": "NBFC",
    # Cement
    "ULTRACEMCO": "CEMENT", "GRASIM": "CEMENT",
    # Real Estate
    "DLF": "REALTY",
    # Conglomerate / Adani
    "ADANIENT": "CONGLOMERATE", "ADANIPORTS": "CONGLOMERATE",
    "RELIANCE": "CONGLOMERATE",
    # Consumer Durables
    "TITAN": "CONSUMER_DURABLES", "ASIANPAINT": "CONSUMER_DURABLES",
    # Energy
    "COALINDIA": "ENERGY", "SUZLON": "ENERGY",
    # Misc
    "BHEL": "CAPITAL_GOODS",
}


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------

@dataclass
class RiskDecision:
    """Outcome of a portfolio-level risk check."""
    allowed: bool
    reason: str
    adjusted_size: Optional[float] = None  # adjusted position_size_pct if capped


@dataclass
class PositionSize:
    """Computed position sizing for a single signal."""
    qty: int
    capital_required: float
    risk_amount: float          # INR at risk (entry - stop) * qty
    pct_of_portfolio: float     # capital_required / total_capital * 100


# ---------------------------------------------------------------------------
# Regime label re-import (avoid circular, keep it local)
# ---------------------------------------------------------------------------

_REDUCED_REGIMES = {"TREND_DOWN", "HIGH_VOL", "HIGH_VOL_EVENT"}


# ---------------------------------------------------------------------------
# RiskEngine
# ---------------------------------------------------------------------------

class RiskEngine:
    """Portfolio risk gatekeeper.

    Parameters
    ----------
    capital : float
        Total paper-trading capital in INR.
    max_open_positions : int
        Hard cap on simultaneous positions (default 6).
    max_sector_concentration_pct : float
        Max percent of capital in any one sector (default 40).
    max_portfolio_heat_pct : float
        Max percent of total capital at risk across all stops (default 6).
    single_stock_max_pct : float
        Max percent of capital in a single stock (default 20).
    """

    def __init__(
        self,
        capital: float = 100_000.0,
        max_open_positions: int = 6,
        max_sector_concentration_pct: float = 40.0,
        max_portfolio_heat_pct: float = 6.0,
        single_stock_max_pct: float = 20.0,
    ) -> None:
        self.capital = capital
        self.max_open_positions = max_open_positions
        self.max_sector_concentration_pct = max_sector_concentration_pct
        self.max_portfolio_heat_pct = max_portfolio_heat_pct
        self.single_stock_max_pct = single_stock_max_pct

    # ------------------------------------------------------------------
    # Primary check
    # ------------------------------------------------------------------

    def check_portfolio_risk(
        self,
        new_signal: Dict[str, Any],
        open_trades: List[Dict[str, Any]],
    ) -> RiskDecision:
        """Run all risk checks against a proposed new signal.

        Parameters
        ----------
        new_signal : dict
            Signal dict (or Signal.to_dict()).  Required keys: ``symbol``,
            ``position_size_pct``, ``invalidation`` (stop), ``entry_zone``,
            ``regime_at_entry``.
        open_trades : list[dict]
            Each element must have at least: ``symbol``, ``entry_price``,
            ``stop_loss``, ``qty``, ``sector`` (optional).

        Returns
        -------
        RiskDecision
        """
        sym = new_signal.get("symbol", "")
        regime = new_signal.get("regime_at_entry", "")

        # ---- 1. Max open positions (regime-aware) -----------------------
        effective_max = self._effective_max_positions(regime)
        if len(open_trades) >= effective_max:
            return RiskDecision(
                allowed=False,
                reason=(
                    f"Max open positions reached ({len(open_trades)}/{effective_max}). "
                    f"Regime={regime}."
                ),
            )

        # ---- 2. Duplicate stock check -----------------------------------
        open_syms = {t.get("symbol", "").upper() for t in open_trades}
        if sym.upper() in open_syms:
            return RiskDecision(
                allowed=False,
                reason=f"Already holding {sym}.",
            )

        # ---- 3. Correlation guard ---------------------------------------
        correlated = _CORR_LOOKUP.get(sym.upper(), set())
        overlap = correlated & open_syms
        if overlap:
            return RiskDecision(
                allowed=False,
                reason=(
                    f"Correlation guard: {sym} is highly correlated with "
                    f"open position(s) {', '.join(overlap)}."
                ),
            )

        # ---- 4. Single-stock max ----------------------------------------
        entry_zone = new_signal.get("entry_zone", [0, 0])
        if isinstance(entry_zone, (list, tuple)) and len(entry_zone) == 2:
            mid_entry = (entry_zone[0] + entry_zone[1]) / 2
        else:
            mid_entry = 0.0

        cost_analysis = new_signal.get("cost_analysis", {})
        cap_required = cost_analysis.get("capital_required", 0.0)
        if cap_required <= 0 and mid_entry > 0:
            # Estimate from position_size_pct
            cap_required = self.capital * new_signal.get("position_size_pct", 0) / 100

        pct_of_portfolio = (cap_required / max(self.capital, 1)) * 100
        if pct_of_portfolio > self.single_stock_max_pct:
            adjusted = self.single_stock_max_pct
            return RiskDecision(
                allowed=True,
                reason=(
                    f"Single-stock cap hit ({pct_of_portfolio:.1f}% > "
                    f"{self.single_stock_max_pct}%). Size reduced to "
                    f"{adjusted:.1f}%."
                ),
                adjusted_size=adjusted,
            )

        # ---- 5. Sector concentration ------------------------------------
        new_sector = _SECTOR_MAP.get(sym.upper(), "OTHER")
        sector_exposure = self._sector_exposure(open_trades)
        current_in_sector = sector_exposure.get(new_sector, 0.0)
        if current_in_sector + pct_of_portfolio > self.max_sector_concentration_pct:
            headroom = max(
                0.0,
                self.max_sector_concentration_pct - current_in_sector,
            )
            if headroom < 5.0:
                return RiskDecision(
                    allowed=False,
                    reason=(
                        f"Sector concentration limit for {new_sector}: "
                        f"already at {current_in_sector:.1f}%, adding "
                        f"{pct_of_portfolio:.1f}% would exceed "
                        f"{self.max_sector_concentration_pct}%."
                    ),
                )
            return RiskDecision(
                allowed=True,
                reason=(
                    f"Sector cap for {new_sector} limits size to "
                    f"{headroom:.1f}% of capital."
                ),
                adjusted_size=headroom,
            )

        # ---- 6. Portfolio heat ------------------------------------------
        current_heat = self._portfolio_heat(open_trades)
        stop_price = float(new_signal.get("invalidation", 0))
        new_risk_pct = 0.0
        if mid_entry > 0 and stop_price > 0:
            risk_per_share = mid_entry - stop_price
            qty_est = int(cap_required / max(mid_entry, 1))
            new_risk_pct = (risk_per_share * qty_est) / max(self.capital, 1) * 100

        total_heat = current_heat + new_risk_pct
        if total_heat > self.max_portfolio_heat_pct:
            headroom_heat = max(
                0.0,
                self.max_portfolio_heat_pct - current_heat,
            )
            if headroom_heat < 0.2:
                return RiskDecision(
                    allowed=False,
                    reason=(
                        f"Portfolio heat limit: current {current_heat:.2f}%, "
                        f"adding {new_risk_pct:.2f}% would exceed "
                        f"{self.max_portfolio_heat_pct}% cap."
                    ),
                )
            # Scale down to fit within heat budget
            scale = headroom_heat / max(new_risk_pct, 0.01)
            adjusted = round(pct_of_portfolio * scale, 2)
            return RiskDecision(
                allowed=True,
                reason=(
                    f"Portfolio heat limits size. Heat headroom: "
                    f"{headroom_heat:.2f}%. Size reduced to {adjusted:.1f}%."
                ),
                adjusted_size=adjusted,
            )

        # ---- All checks passed ------------------------------------------
        return RiskDecision(
            allowed=True,
            reason="All risk checks passed.",
            adjusted_size=pct_of_portfolio,
        )

    # ------------------------------------------------------------------
    # Position sizing
    # ------------------------------------------------------------------

    def calculate_position_size(
        self,
        signal: Dict[str, Any],
        capital: Optional[float] = None,
        open_trades: Optional[List[Dict[str, Any]]] = None,
        risk_per_trade_pct: float = 1.0,
    ) -> PositionSize:
        """Compute qty and capital for a signal, respecting risk limits.

        Parameters
        ----------
        signal : dict
            Must have ``entry_zone`` (list/tuple of two floats) and
            ``invalidation`` (stop price).
        capital : float | None
            Override capital (defaults to self.capital).
        open_trades : list[dict] | None
            Currently open trades (for heat checks).
        risk_per_trade_pct : float
            Percent of capital to risk on this trade.

        Returns
        -------
        PositionSize
        """
        if capital is None:
            capital = self.capital
        if open_trades is None:
            open_trades = []

        entry_zone = signal.get("entry_zone", [0, 0])
        if isinstance(entry_zone, (list, tuple)) and len(entry_zone) == 2:
            entry = (entry_zone[0] + entry_zone[1]) / 2
        else:
            entry = 0.0

        stop = float(signal.get("invalidation", 0))
        risk_per_share = max(entry - stop, 0.01)

        risk_budget = capital * risk_per_trade_pct / 100.0
        qty = max(1, int(risk_budget / risk_per_share))
        cap_required = round(qty * entry, 2)
        risk_amount = round(risk_per_share * qty, 2)
        pct = round(cap_required / max(capital, 1) * 100, 2)

        # Clamp to single-stock max
        if pct > self.single_stock_max_pct:
            qty = max(1, int(capital * self.single_stock_max_pct / 100 / max(entry, 1)))
            cap_required = round(qty * entry, 2)
            risk_amount = round(risk_per_share * qty, 2)
            pct = round(cap_required / max(capital, 1) * 100, 2)

        return PositionSize(
            qty=qty,
            capital_required=cap_required,
            risk_amount=risk_amount,
            pct_of_portfolio=pct,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _effective_max_positions(self, regime: str) -> int:
        """Reduce allowed positions in adverse regimes."""
        if regime in _REDUCED_REGIMES:
            return max(2, self.max_open_positions - 2)
        return self.max_open_positions

    def _sector_exposure(
        self,
        open_trades: List[Dict[str, Any]],
    ) -> Dict[str, float]:
        """Calculate current sector exposure as % of capital.

        Returns
        -------
        dict[str, float]
            Sector name -> percent of total capital currently allocated.
        """
        exposure: Dict[str, float] = {}
        for t in open_trades:
            sym = t.get("symbol", "").upper()
            sector = t.get("sector") or _SECTOR_MAP.get(sym, "OTHER")
            entry = float(t.get("entry_price", 0))
            qty = int(t.get("qty", 0))
            val = entry * qty
            pct = (val / max(self.capital, 1)) * 100
            exposure[sector] = exposure.get(sector, 0.0) + pct
        return exposure

    def _portfolio_heat(self, open_trades: List[Dict[str, Any]]) -> float:
        """Calculate total capital at risk as % of total capital.

        Heat = sum of (entry - stop) * qty for every open trade,
        divided by total capital, * 100.
        """
        total_risk = 0.0
        for t in open_trades:
            entry = float(t.get("entry_price", 0))
            stop = float(t.get("stop_loss", 0))
            qty = int(t.get("qty", 0))
            risk = max(entry - stop, 0) * qty
            total_risk += risk
        return (total_risk / max(self.capital, 1)) * 100
