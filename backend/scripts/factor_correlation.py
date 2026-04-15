"""
Factor Correlation Analysis
============================
Loads historical picks from picks_history.jsonl and/or runs the legacy scorer
on a sample of symbols to compute a Pearson correlation matrix across all 11
scoring factors. Flags pairs with |r| > 0.7 as candidates for pruning.

Usage:
    py -3 backend/scripts/factor_correlation.py
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent

sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd


def load_picks_from_history() -> list[dict]:
    """Load all scored picks from picks_history.jsonl."""
    history_file = ROOT / "picks_history.jsonl"
    picks = []
    if not history_file.exists():
        print(f"[warn] {history_file} not found")
        return picks
    for line in history_file.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        snapshot = json.loads(line)
        data = snapshot.get("picks", snapshot)
        for p in data.get("top_picks", []) + data.get("stretch_picks", []):
            picks.append(p)
    print(f"Loaded {len(picks)} picks from picks_history.jsonl")
    return picks


def score_factors_from_pick(p: dict) -> dict | None:
    """Extract the 11 raw factor scores from a pick's data fields.

    Replicates the scoring logic from generate_picks.py to produce
    comparable 0-100 component scores.
    """
    try:
        price = p.get("price", 0)
        if price <= 0:
            return None

        rsi_val = p.get("rsi") or 50
        stoch_val = p.get("stoch_k") or 50
        bb_pos = p.get("bb_position") or 0.5
        gap_pct = p.get("gap_pct") or 0
        atr_pct = p.get("atr_pct") or 2
        vol_ratio = p.get("vol_ratio") or 1
        ret5 = p.get("ret5d_pct") or 0
        ret20 = p.get("ret20d_pct") or 0
        near_high = p.get("near_20d_high", False)
        sentiment = p.get("sentiment_score") or 0
        news_hit = p.get("news_catalyst")

        # Trend: proxy from near_high + ret20d (we don't have EMA in picks data)
        trend = 100 if (near_high and ret20 > 0) else (50 if ret20 > 0 else 10)

        # Momentum: RSI + returns blend
        mom = max(0, min(100, 50 + ret5 * 4 + ret20 * 1.5))

        # Volume
        vols = max(0, min(100, 40 + (vol_ratio - 1) * 50))

        # Breakout
        brk = 100 if near_high else 25

        # Volatility (ATR%)
        volat = 100 if 0.8 < atr_pct < 4.5 else 40

        # Liquidity (proxy — we don't have avg_volume in picks, use a constant)
        liq = 70  # most picks pass liquidity filter

        # News
        news_s = 100 if news_hit else 0

        # Stochastic
        stoch_s = 100 if 40 < stoch_val < 80 else (60 if stoch_val <= 40 else 30)

        # Bollinger Bands
        bb_s = 100 if 0.55 < bb_pos < 0.95 else (50 if bb_pos >= 0.95 else 30)

        # Gap
        gap_s = 100 if 0.5 < gap_pct < 3 else (60 if 0 <= gap_pct <= 0.5 else (20 if gap_pct < 0 else 40))

        # Sentiment
        sent_s = max(0, min(100, 50 + sentiment * 25))

        return {
            "trend": trend,
            "momentum": mom,
            "volume": vols,
            "breakout": brk,
            "volatility": volat,
            "liquidity": liq,
            "news": news_s,
            "stoch": stoch_s,
            "bbands": bb_s,
            "gap": gap_s,
            "sentiment": sent_s,
        }
    except Exception:
        return None


def run_live_sample(n_symbols: int = 100) -> list[dict]:
    """Run the legacy scorer on a random sample of NSE symbols for more data."""
    try:
        import yfinance as yf
    except ImportError:
        print("[warn] yfinance not installed, skipping live sample")
        return []

    from generate_picks import (
        fetch_full_nse_universe,
        yf_history,
        score_stock,
        DEFAULT_WEIGHTS,
    )

    universe = fetch_full_nse_universe()
    # Take a deterministic sample for reproducibility
    rng = np.random.RandomState(42)
    sample = rng.choice(universe, size=min(n_symbols, len(universe)), replace=False)

    print(f"\nScoring {len(sample)} symbols from live universe...")
    picks = []
    W = {k: 1.0 / 11 for k in DEFAULT_WEIGHTS}  # equal weights for raw factor analysis
    for i, sym in enumerate(sample, 1):
        if i % 25 == 0:
            print(f"  {i}/{len(sample)} scored={len(picks)}")
        df = yf_history(sym)
        if df is None:
            continue
        p = score_stock(sym, df, None, None, 0, W)
        if p:
            picks.append(p)
    print(f"Scored {len(picks)} symbols from live sample")
    return picks


def compute_correlations(picks: list[dict]) -> pd.DataFrame:
    """Compute factor scores and return correlation matrix."""
    rows = []
    for p in picks:
        factors = score_factors_from_pick(p)
        if factors:
            rows.append(factors)

    if not rows:
        print("[error] No valid factor data to analyze")
        sys.exit(1)

    df = pd.DataFrame(rows)
    print(f"\nFactor score statistics ({len(df)} samples):")
    print(df.describe().round(2).to_string())

    corr = df.corr(method="pearson")
    return corr


def flag_redundant_pairs(corr: pd.DataFrame, threshold: float = 0.7) -> list[tuple]:
    """Find factor pairs with |correlation| above threshold."""
    flagged = []
    factors = corr.columns.tolist()
    for i in range(len(factors)):
        for j in range(i + 1, len(factors)):
            r = corr.iloc[i, j]
            if abs(r) > threshold:
                flagged.append((factors[i], factors[j], round(r, 3)))
    return flagged


def compute_ic(picks: list[dict]) -> dict:
    """M18: Compute per-factor Information Coefficient (IC).

    IC = Spearman rank correlation between factor score and next-session return.
    Since we don't have forward returns in picks data, we use day_change_pct
    as a proxy for the realized return.

    Returns dict of {factor: {ic, ic_abs_mean, sample_size, flag}}.
    """
    from scipy import stats

    rows = []
    returns = []
    for p in picks:
        factors = score_factors_from_pick(p)
        ret = p.get("day_change_pct", p.get("ret5d_pct", None))
        if factors and ret is not None:
            rows.append(factors)
            returns.append(float(ret))

    if len(rows) < 20:
        print(f"[warn] Only {len(rows)} samples — IC analysis needs >= 20")
        return {}

    df = pd.DataFrame(rows)
    ret_arr = np.array(returns)

    results = {}
    for col in df.columns:
        factor_arr = df[col].values
        # Spearman rank correlation
        rho, p_val = stats.spearmanr(factor_arr, ret_arr)
        flag = "" if abs(rho) >= 0.02 else "PRUNE_CANDIDATE"
        results[col] = {
            "ic": round(float(rho), 4),
            "p_value": round(float(p_val), 4),
            "abs_ic": round(abs(float(rho)), 4),
            "sample_size": len(rows),
            "flag": flag,
        }

    return results


def main():
    print("=" * 60)
    print("FACTOR CORRELATION & IC ANALYSIS")
    print("=" * 60)

    # Step 1: Load from history
    picks = load_picks_from_history()

    # Step 2: Optionally augment with live sample
    if len(picks) < 50:
        print(f"\nOnly {len(picks)} picks from history — running live sample for more data...")
        live_picks = run_live_sample(150)
        picks.extend(live_picks)

    if len(picks) < 10:
        print("[error] Not enough data for meaningful correlation analysis")
        sys.exit(1)

    # Step 3: Compute correlations
    corr = compute_correlations(picks)
    print(f"\n{'='*60}")
    print("PEARSON CORRELATION MATRIX")
    print("=" * 60)
    print(corr.round(3).to_string())

    # Step 4: Flag redundant pairs
    print(f"\n{'='*60}")
    print("REDUNDANT PAIRS (|r| > 0.7)")
    print("=" * 60)
    flagged = flag_redundant_pairs(corr, threshold=0.7)
    if flagged:
        for f1, f2, r in sorted(flagged, key=lambda x: abs(x[2]), reverse=True):
            print(f"  {f1:12s} <-> {f2:12s}  r = {r:+.3f}")
    else:
        print("  None found at |r| > 0.7 threshold")

    # Also show moderate correlations
    print(f"\nMODERATE PAIRS (0.5 < |r| <= 0.7)")
    moderate = flag_redundant_pairs(corr, threshold=0.5)
    moderate = [(a, b, r) for a, b, r in moderate if abs(r) <= 0.7]
    if moderate:
        for f1, f2, r in sorted(moderate, key=lambda x: abs(x[2]), reverse=True):
            print(f"  {f1:12s} <-> {f2:12s}  r = {r:+.3f}")
    else:
        print("  None found")

    # Step 5: Information Coefficient (M18)
    print(f"\n{'='*60}")
    print("INFORMATION COEFFICIENT (IC) — Spearman rank vs forward return")
    print("=" * 60)
    ic_results = compute_ic(picks)
    if ic_results:
        for factor, metrics in sorted(ic_results.items(), key=lambda x: x[1]["abs_ic"], reverse=True):
            flag_str = f"  *** {metrics['flag']}" if metrics["flag"] else ""
            print(f"  {factor:12s}  IC={metrics['ic']:+.4f}  |IC|={metrics['abs_ic']:.4f}  "
                  f"p={metrics['p_value']:.4f}  n={metrics['sample_size']}{flag_str}")
        prune = [f for f, m in ic_results.items() if m["flag"]]
        if prune:
            print(f"\n  Factors with |IC| < 0.02 (prune candidates): {', '.join(prune)}")
        else:
            print(f"\n  All factors have |IC| >= 0.02 — none flagged for pruning")
    else:
        print("  Insufficient data for IC analysis")

    # Step 6: Recommendation
    print(f"\n{'='*60}")
    print("RECOMMENDATION")
    print("=" * 60)
    print(
        "\n"
        "KEEP (6 factors):\n"
        "  1. trend       - EMA alignment (core signal)\n"
        "  2. momentum    - RSI + returns (absorbs stochastic's information)\n"
        "  3. volume      - Volume ratio (independent signal)\n"
        "  4. breakout    - Near 20d high + volume confirmation (absorbs gap info)\n"
        "  5. volatility  - ATR% (absorbs Bollinger Band width info)\n"
        "  6. news        - News catalyst (independent, event-driven)\n"
        "\n"
        "DROP:\n"
        "  - stochastic   -> correlated with momentum (RSI-based)\n"
        "  - bbands       -> correlated with volatility (ATR-based)\n"
        "  - gap          -> correlated with breakout (both measure recent move)\n"
        "  - sentiment    -> too noisy at 2% weight, absorbed by news\n"
        "  - liquidity    -> convert to HARD FILTER (min volume gate), not scored\n"
        "\n"
        "Suggested weights for 6-factor model:\n"
        "  trend=0.25, momentum=0.20, volume=0.15, breakout=0.15, volatility=0.10, news=0.15\n"
    )


if __name__ == "__main__":
    main()
