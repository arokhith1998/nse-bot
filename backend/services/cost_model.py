"""
Brokerage cost calculators for Indian equity intraday trading.

Supports Groww and Zerodha fee structures.  All monetary values are
in INR.  Charges are as of the 2024-25 SEBI/NSE schedule.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CostBreakdown:
    """Itemised transaction cost for one leg or round trip."""

    brokerage: float
    stt: float              # Securities Transaction Tax
    exchange_txn: float     # NSE transaction charge
    gst: float              # 18% on (brokerage + exchange_txn + SEBI fee)
    sebi: float             # SEBI turnover fee
    stamp: float            # Stamp duty (buy side only)
    total: float

    def __repr__(self) -> str:
        parts = (
            f"brokerage={self.brokerage:.2f}",
            f"stt={self.stt:.2f}",
            f"exchange_txn={self.exchange_txn:.2f}",
            f"gst={self.gst:.2f}",
            f"sebi={self.sebi:.2f}",
            f"stamp={self.stamp:.2f}",
            f"total={self.total:.2f}",
        )
        return f"CostBreakdown({', '.join(parts)})"


@dataclass
class NetRR:
    """Net risk-reward after transaction costs."""

    gross_profit: float
    gross_loss: float
    total_cost: float       # round-trip charges
    net_profit: float       # gross_profit - total_cost
    net_loss: float         # gross_loss + total_cost (more negative)
    gross_rr: float         # |gross_profit / gross_loss|
    net_rr: float           # |net_profit / net_loss|
    cost_as_pct_of_profit: float  # total_cost / gross_profit * 100


# ── Charge rates (equity intraday, NSE) ─────────────────────────────

# STT: 0.025% on sell side turnover (intraday)
_STT_RATE = 0.00025

# NSE transaction charge: 0.00345% per side
_NSE_TXN_RATE = 0.0000345

# SEBI turnover fee: Rs 10 per crore = 0.0001%
_SEBI_RATE = 0.000001

# Stamp duty (buy side only): 0.003% (varies by state; using max)
_STAMP_RATE = 0.00003

# GST: 18% on (brokerage + exchange txn + SEBI)
_GST_RATE = 0.18


def _compute_charges(
    buy_turnover: float,
    sell_turnover: float,
    brokerage: float,
) -> CostBreakdown:
    """Compute all statutory charges given turnover figures and brokerage."""
    total_turnover = buy_turnover + sell_turnover

    stt = sell_turnover * _STT_RATE
    exchange_txn = total_turnover * _NSE_TXN_RATE
    sebi = total_turnover * _SEBI_RATE
    stamp = buy_turnover * _STAMP_RATE

    gst = (brokerage + exchange_txn + sebi) * _GST_RATE

    total = brokerage + stt + exchange_txn + gst + sebi + stamp
    return CostBreakdown(
        brokerage=round(brokerage, 4),
        stt=round(stt, 4),
        exchange_txn=round(exchange_txn, 4),
        gst=round(gst, 4),
        sebi=round(sebi, 4),
        stamp=round(stamp, 4),
        total=round(total, 4),
    )


# ── Groww ────────────────────────────────────────────────────────────

def groww_intraday_cost(price: float, qty: int) -> CostBreakdown:
    """Calculate intraday trading costs for Groww.

    Groww charges Rs 20 per executed order (flat) for intraday equity.
    This function computes the round-trip (buy + sell) cost.

    Parameters
    ----------
    price : float
        Assumed entry price per share.
    qty : int
        Number of shares.
    """
    buy_turnover = price * qty
    sell_turnover = price * qty  # assume exit at same price for cost estimate

    # Groww: flat Rs 20 per executed order, 2 orders for round trip
    brokerage = 40.0

    return _compute_charges(buy_turnover, sell_turnover, brokerage)


# ── Zerodha ──────────────────────────────────────────────────────────

def zerodha_intraday_cost(price: float, qty: int) -> CostBreakdown:
    """Calculate intraday trading costs for Zerodha (Kite).

    Zerodha charges 0.03% or Rs 20 per executed order, whichever is lower.
    This function computes the round-trip (buy + sell) cost.

    Parameters
    ----------
    price : float
        Assumed entry price per share.
    qty : int
        Number of shares.
    """
    buy_turnover = price * qty
    sell_turnover = price * qty

    buy_brokerage = min(20.0, buy_turnover * 0.0003)
    sell_brokerage = min(20.0, sell_turnover * 0.0003)
    brokerage = buy_brokerage + sell_brokerage

    return _compute_charges(buy_turnover, sell_turnover, brokerage)


# ── Net Risk-Reward ──────────────────────────────────────────────────

def calculate_net_rr(
    entry: float,
    stop: float,
    target: float,
    qty: int,
    cost_fn=zerodha_intraday_cost,
) -> NetRR:
    """Calculate net risk-reward after brokerage and charges.

    Parameters
    ----------
    entry : float
        Entry price.
    stop : float
        Stop-loss price.
    target : float
        Target price.
    qty : int
        Position size in shares.
    cost_fn : callable
        One of ``groww_intraday_cost`` or ``zerodha_intraday_cost``.
        Defaults to Zerodha.

    Returns
    -------
    NetRR
        Dataclass with gross/net P&L and risk-reward ratios.
    """
    gross_profit = (target - entry) * qty
    gross_loss = (stop - entry) * qty  # negative for longs where stop < entry

    # Round-trip cost (use average of entry and exit prices for accuracy)
    cost_at_target = cost_fn(price=(entry + target) / 2, qty=qty)
    cost_at_stop = cost_fn(price=(entry + stop) / 2, qty=qty)

    # Use the worse (higher) cost estimate for conservative sizing
    total_cost = max(cost_at_target.total, cost_at_stop.total)

    net_profit = gross_profit - total_cost
    net_loss = gross_loss - total_cost  # costs make the loss worse

    gross_rr = abs(gross_profit / gross_loss) if gross_loss != 0 else float("inf")
    net_rr = abs(net_profit / net_loss) if net_loss != 0 else float("inf")

    cost_pct = (total_cost / gross_profit * 100) if gross_profit > 0 else float("inf")

    return NetRR(
        gross_profit=round(gross_profit, 2),
        gross_loss=round(gross_loss, 2),
        total_cost=round(total_cost, 2),
        net_profit=round(net_profit, 2),
        net_loss=round(net_loss, 2),
        gross_rr=round(gross_rr, 4),
        net_rr=round(net_rr, 4),
        cost_as_pct_of_profit=round(cost_pct, 2),
    )
