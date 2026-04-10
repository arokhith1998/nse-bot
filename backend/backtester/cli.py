"""
cli.py
======
Command-line interface for the NSE Market Intelligence backtester.

Usage::

    python -m backend.backtester.cli \\
        --start 2025-01-01 \\
        --end 2026-04-10 \\
        --universe nifty50 \\
        --capital 100000

Run ``python -m backend.backtester.cli --help`` for full option list.
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime
from pathlib import Path

from backend.backtester.engine import BacktestConfig, BacktestEngine
from backend.backtester.report import generate_text_report, save_report

logger = logging.getLogger(__name__)


def _parse_date(s: str) -> date:
    """Parse a YYYY-MM-DD string into a ``date`` object."""
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        raise argparse.ArgumentTypeError(f"Invalid date format: '{s}'. Use YYYY-MM-DD.")


def _build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="nse-backtest",
        description="NSE Market Intelligence -- Historical Backtester",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python -m backend.backtester.cli --start 2025-01-01 --end 2026-04-10\n"
            "  python -m backend.backtester.cli --universe RELIANCE,TCS,INFY --capital 200000\n"
            "  python -m backend.backtester.cli --universe nifty200 --risk 2.0 --cost-model zerodha\n"
        ),
    )

    parser.add_argument(
        "--start",
        type=_parse_date,
        default=date(2025, 1, 1),
        help="Backtest start date (YYYY-MM-DD). Default: 2025-01-01",
    )
    parser.add_argument(
        "--end",
        type=_parse_date,
        default=date.today(),
        help="Backtest end date (YYYY-MM-DD). Default: today",
    )
    parser.add_argument(
        "--universe",
        type=str,
        default="nifty50",
        help=(
            "Symbol universe. Options: nifty50, nifty200, full, "
            "or comma-separated symbols (e.g. RELIANCE,TCS,INFY). "
            "Default: nifty50"
        ),
    )
    parser.add_argument(
        "--capital",
        type=float,
        default=100_000.0,
        help="Starting capital in INR. Default: 100000",
    )
    parser.add_argument(
        "--risk",
        type=float,
        default=1.0,
        help="Risk per trade as percent of capital. Default: 1.0",
    )
    parser.add_argument(
        "--max-positions",
        type=int,
        default=6,
        help="Maximum concurrent open positions. Default: 6",
    )
    parser.add_argument(
        "--slippage",
        type=float,
        default=0.05,
        help="Slippage percent (adverse, on entry). Default: 0.05",
    )
    parser.add_argument(
        "--cost-model",
        type=str,
        choices=["groww", "zerodha"],
        default="groww",
        help="Brokerage cost model. Default: groww",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=6,
        help="Maximum picks per day. Default: 6",
    )
    parser.add_argument(
        "--no-regime-filter",
        action="store_true",
        help="Disable regime-based signal filtering.",
    )
    parser.add_argument(
        "--benchmark",
        type=str,
        default="^NSEI",
        help="Benchmark symbol (Yahoo Finance). Default: ^NSEI",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="backend/data/backtest",
        help="Output directory for reports. Default: backend/data/backtest",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Minimal output (suppress progress, only print summary).",
    )

    return parser


def _progress_bar(pct: int, msg: str) -> None:
    """Print a simple inline progress bar to stderr."""
    bar_len = 30
    filled = int(bar_len * pct / 100)
    bar = "#" * filled + "-" * (bar_len - filled)
    sys.stderr.write(f"\r  [{bar}] {pct:3d}%  {msg:40s}")
    sys.stderr.flush()
    if pct >= 100:
        sys.stderr.write("\n")


def main(argv: list[str] | None = None) -> None:
    """CLI entry point."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    # Configure logging
    log_level = logging.WARNING if args.quiet else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        force=True,
    )

    # Resolve symbols
    universe_spec = args.universe
    if "," in universe_spec:
        symbols = [s.strip().upper() for s in universe_spec.split(",") if s.strip()]
    else:
        symbols = universe_spec

    # Build config
    config = BacktestConfig(
        symbols=symbols,
        start_date=args.start,
        end_date=args.end,
        capital=args.capital,
        risk_per_trade_pct=args.risk,
        max_open_positions=args.max_positions,
        slippage_pct=args.slippage,
        cost_model=args.cost_model,
        top_n=args.top_n,
        use_regime_filter=not args.no_regime_filter,
        benchmark=args.benchmark,
    )

    # Print header
    if not args.quiet:
        print()
        print("=" * 55)
        print("  NSE Market Intelligence -- Backtester")
        print("=" * 55)
        print(f"  Universe:    {args.universe}")
        print(f"  Period:      {args.start} to {args.end}")
        print(f"  Capital:     Rs {args.capital:,.0f}")
        print(f"  Risk/Trade:  {args.risk}%")
        print(f"  Max Pos:     {args.max_positions}")
        print(f"  Cost Model:  {args.cost_model}")
        print(f"  Benchmark:   {args.benchmark}")
        print("=" * 55)
        print()

    # Run backtest
    engine = BacktestEngine(config)
    if not args.quiet:
        engine.on_progress = _progress_bar

    result = engine.run()

    # Print report
    report_text = generate_text_report(result)
    print(report_text)

    # Save reports
    paths = save_report(result, output_dir=args.output)
    if not args.quiet:
        print(f"  Reports saved to:")
        print(f"    Text: {paths['text_path']}")
        print(f"    JSON: {paths['json_path']}")
        print()


if __name__ == "__main__":
    main()
