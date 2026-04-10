"""
report.py
=========
Report generation for NSE Market Intelligence backtester.

Produces formatted text reports and JSON-serialisable output for the
dashboard.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from backend.backtester.engine import (
    BacktestResult,
    BacktestSummary,
    BacktestTrade,
    SetupStats,
    RegimeStats,
    DailyEquity,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# Text report
# ═══════════════════════════════════════════════════════════════════════

def generate_text_report(result: BacktestResult) -> str:
    """Generate a nicely formatted text report from backtest results.

    Parameters
    ----------
    result : BacktestResult
        Completed backtest output.

    Returns
    -------
    str
        Multi-line formatted report suitable for console output.
    """
    s = result.summary
    lines: list[str] = []

    def line(text: str = "") -> None:
        lines.append(text)

    def sep(char: str = "-", width: int = 55) -> None:
        lines.append(char * width)

    # Header
    line()
    sep("=")
    line("  NSE BACKTEST REPORT")
    line(f"  Period: {s.start_date} to {s.end_date}")
    line(f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    sep("=")
    line()

    # Performance summary
    line("  PERFORMANCE SUMMARY")
    sep()
    line(f"  Total Trades:          {s.total_trades}")
    line(f"  Winners:               {s.winners}")
    line(f"  Losers:                {s.losers}")
    line(f"  Win Rate:              {s.win_rate_pct:.1f}%")
    line(f"  Avg Win:               {s.avg_win_pct:+.2f}%")
    line(f"  Avg Loss:              {s.avg_loss_pct:+.2f}%")
    line(f"  Profit Factor:         {s.profit_factor:.2f}")
    line()
    line(f"  Total P&L:             Rs {s.total_pnl:+,.2f}  ({s.total_pnl_pct:+.2f}%)")

    if result.config:
        line(f"  Starting Capital:      Rs {result.config.capital:,.0f}")
        final = result.config.capital + s.total_pnl
        line(f"  Final Capital:         Rs {final:,.2f}")

    line()
    line(f"  Max Drawdown:          {s.max_drawdown_pct:.2f}%")
    line(f"  Max DD Duration:       {s.max_drawdown_duration_days} days")
    line(f"  Sharpe Ratio:          {s.sharpe_ratio:.2f}")
    line(f"  Sortino Ratio:         {s.sortino_ratio:.2f}")
    line(f"  Calmar Ratio:          {s.calmar_ratio:.2f}")
    line()
    line(f"  Avg Trades/Day:        {s.avg_trades_per_day:.1f}")
    line(f"  Avg Holding Period:    {s.avg_holding_period}")
    line(f"  Trading Days:          {s.trading_days}")
    line()
    line(f"  Benchmark Return:      {s.benchmark_return_pct:+.2f}%")
    line(f"  Alpha:                 {s.alpha_pct:+.2f}%")
    line(f"  Beta:                  {s.beta:.2f}")
    line()

    if s.best_month:
        line(f"  Best Month:            {s.best_month}")
    if s.worst_month:
        line(f"  Worst Month:           {s.worst_month}")
    line()

    # Monthly returns
    if result.monthly_returns:
        line("  MONTHLY RETURNS")
        sep()
        for month, ret in result.monthly_returns.items():
            bar_len = int(abs(ret) * 5)
            bar_char = "+" if ret >= 0 else "-"
            bar = bar_char * min(bar_len, 40)
            line(f"  {month}:  {ret:+6.2f}%  {bar}")
        line()

    # Top 5 winners
    if result.best_trades:
        line("  TOP 5 WINNERS")
        sep()
        for t in result.best_trades:
            line(
                f"  {t.symbol:12s}  {t.entry_date} -> {t.exit_date}  "
                f"P&L: Rs {t.net_pnl:+8.2f}  ({t.pnl_pct:+.2f}%)  "
                f"[{t.exit_reason}]"
            )
        line()

    # Bottom 5 losers
    if result.worst_trades:
        line("  TOP 5 LOSERS")
        sep()
        for t in result.worst_trades:
            line(
                f"  {t.symbol:12s}  {t.entry_date} -> {t.exit_date}  "
                f"P&L: Rs {t.net_pnl:+8.2f}  ({t.pnl_pct:+.2f}%)  "
                f"[{t.exit_reason}]"
            )
        line()

    # Setup breakdown
    if result.setup_breakdown:
        line("  SETUP BREAKDOWN")
        sep()
        for setup, stats in sorted(
            result.setup_breakdown.items(),
            key=lambda x: x[1].trades,
            reverse=True,
        ):
            line(
                f"  {setup:16s}  {stats.win_rate_pct:5.1f}% win rate, "
                f"{stats.trades:4d} trades, "
                f"avg {stats.avg_pnl_pct:+.2f}%, "
                f"total Rs {stats.total_pnl:+,.2f}"
            )
        line()

    # Regime performance
    if result.regime_breakdown:
        line("  REGIME PERFORMANCE")
        sep()
        for reg, stats in sorted(
            result.regime_breakdown.items(),
            key=lambda x: x[1].trades,
            reverse=True,
        ):
            line(
                f"  {reg:16s}  {stats.win_rate_pct:5.1f}% win rate, "
                f"{stats.trades:4d} trades, "
                f"avg {stats.avg_pnl_pct:+.2f}%"
            )
        line()

    # Exit reason distribution
    if result.trades:
        from collections import Counter
        exit_counts = Counter(t.exit_reason for t in result.trades)
        line("  EXIT REASON DISTRIBUTION")
        sep()
        for reason, count in exit_counts.most_common():
            pct = count / len(result.trades) * 100
            line(f"  {reason:16s}  {count:4d}  ({pct:.1f}%)")
        line()

    sep("=")
    line("  PAPER TRADING ONLY. Not investment advice.")
    sep("=")
    line()

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════
# JSON report
# ═══════════════════════════════════════════════════════════════════════

def generate_json_report(result: BacktestResult) -> dict:
    """Generate a JSON-serialisable report from backtest results.

    Parameters
    ----------
    result : BacktestResult
        Completed backtest output.

    Returns
    -------
    dict
        Full JSON-safe dictionary for dashboard consumption.
    """
    s = result.summary

    report: Dict[str, Any] = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "summary": {
            "total_trades": s.total_trades,
            "winners": s.winners,
            "losers": s.losers,
            "win_rate_pct": s.win_rate_pct,
            "avg_win_pct": s.avg_win_pct,
            "avg_loss_pct": s.avg_loss_pct,
            "profit_factor": s.profit_factor,
            "total_pnl": s.total_pnl,
            "total_pnl_pct": s.total_pnl_pct,
            "max_drawdown_pct": s.max_drawdown_pct,
            "max_drawdown_duration_days": s.max_drawdown_duration_days,
            "sharpe_ratio": s.sharpe_ratio,
            "sortino_ratio": s.sortino_ratio,
            "calmar_ratio": s.calmar_ratio,
            "avg_trades_per_day": s.avg_trades_per_day,
            "avg_holding_period": s.avg_holding_period,
            "best_month": s.best_month,
            "worst_month": s.worst_month,
            "benchmark_return_pct": s.benchmark_return_pct,
            "alpha_pct": s.alpha_pct,
            "beta": s.beta,
            "start_date": s.start_date,
            "end_date": s.end_date,
            "trading_days": s.trading_days,
        },
        "config": None,
        "monthly_returns": result.monthly_returns,
        "trades": [t.to_dict() for t in result.trades],
        "daily_equity": [
            {
                "date": eq.date,
                "equity_value": eq.equity_value,
                "drawdown_pct": eq.drawdown_pct,
                "benchmark_value": eq.benchmark_value,
            }
            for eq in result.daily_equity
        ],
        "setup_breakdown": {
            k: {
                "trades": v.trades,
                "winners": v.winners,
                "losers": v.losers,
                "win_rate_pct": v.win_rate_pct,
                "avg_pnl_pct": v.avg_pnl_pct,
                "total_pnl": v.total_pnl,
            }
            for k, v in result.setup_breakdown.items()
        },
        "regime_breakdown": {
            k: {
                "trades": v.trades,
                "winners": v.winners,
                "losers": v.losers,
                "win_rate_pct": v.win_rate_pct,
                "avg_pnl_pct": v.avg_pnl_pct,
                "total_pnl": v.total_pnl,
            }
            for k, v in result.regime_breakdown.items()
        },
        "best_trades": [t.to_dict() for t in result.best_trades],
        "worst_trades": [t.to_dict() for t in result.worst_trades],
    }

    # Serialise config if present
    if result.config:
        cfg = result.config
        report["config"] = {
            "symbols": cfg.symbols if isinstance(cfg.symbols, str) else "custom",
            "start_date": cfg.start_date.isoformat(),
            "end_date": cfg.end_date.isoformat(),
            "capital": cfg.capital,
            "risk_per_trade_pct": cfg.risk_per_trade_pct,
            "max_open_positions": cfg.max_open_positions,
            "slippage_pct": cfg.slippage_pct,
            "cost_model": cfg.cost_model,
            "top_n": cfg.top_n,
            "use_regime_filter": cfg.use_regime_filter,
            "benchmark": cfg.benchmark,
        }

    return report


# ═══════════════════════════════════════════════════════════════════════
# Save to disk
# ═══════════════════════════════════════════════════════════════════════

def save_report(
    result: BacktestResult,
    output_dir: str | Path = "backend/data/backtest",
    *,
    prefix: str = "",
) -> Dict[str, str]:
    """Save both text and JSON reports to *output_dir*.

    Parameters
    ----------
    result : BacktestResult
        Completed backtest output.
    output_dir : str | Path
        Directory to write reports into.
    prefix : str
        Optional filename prefix (e.g. job ID).

    Returns
    -------
    dict
        Mapping with keys ``text_path`` and ``json_path``.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if prefix:
        base = f"{prefix}_{timestamp}"
    else:
        base = f"backtest_{timestamp}"

    # Text report
    text_path = out / f"{base}.txt"
    text_content = generate_text_report(result)
    text_path.write_text(text_content, encoding="utf-8")
    logger.info("Text report saved: %s", text_path)

    # JSON report
    json_path = out / f"{base}.json"
    json_content = generate_json_report(result)
    json_path.write_text(
        json.dumps(json_content, indent=2, default=str),
        encoding="utf-8",
    )
    logger.info("JSON report saved: %s", json_path)

    return {
        "text_path": str(text_path),
        "json_path": str(json_path),
    }
