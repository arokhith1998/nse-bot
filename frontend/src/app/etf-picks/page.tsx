"use client";

import { useState, useEffect, useCallback } from "react";
import { fetchETFPicks } from "@/lib/api";
import type { ETFPicksResponse, ETFPick } from "@/lib/types";
import { RefreshCw, TrendingUp, TrendingDown, AlertTriangle, Info } from "lucide-react";
import { formatIST } from "@/lib/constants";

const CATEGORY_LABELS: Record<string, string> = {
  broad_index: "Broad Index",
  sector: "Sector",
  commodity: "Commodity",
  liquid_bond: "Liquid / Bond",
};

const CATEGORY_COLORS: Record<string, string> = {
  broad_index: "text-blue-400 bg-blue-400/10 border-blue-400/20",
  sector: "text-purple-400 bg-purple-400/10 border-purple-400/20",
  commodity: "text-yellow-400 bg-yellow-400/10 border-yellow-400/20",
  liquid_bond: "text-emerald-400 bg-emerald-400/10 border-emerald-400/20",
};

function ScoreBar({ label, value }: { label: string; value: number }) {
  const pct = Math.min(100, Math.max(0, value));
  const color =
    pct >= 70 ? "bg-green-400" : pct >= 50 ? "bg-yellow-400" : "bg-red-400";
  return (
    <div className="flex items-center gap-2 text-[10px]">
      <span className="text-mute w-20 shrink-0 truncate">{label}</span>
      <div className="flex-1 h-1.5 bg-white/5 rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full ${color}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="text-mute/80 w-8 text-right">{value.toFixed(0)}</span>
    </div>
  );
}

function ETFPickCard({ pick }: { pick: ETFPick }) {
  const [expanded, setExpanded] = useState(false);
  const scoreColor =
    pick.score >= 70
      ? "text-green-400"
      : pick.score >= 50
        ? "text-yellow-400"
        : "text-red-400";
  const catStyle = CATEGORY_COLORS[pick.category] || CATEGORY_COLORS.broad_index;

  return (
    <div className="bg-card border border-line rounded-xl p-4 hover:border-accent/30 transition-colors">
      <div className="flex items-start justify-between mb-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <span className="text-sm font-semibold text-ink">{pick.symbol}</span>
            <span className={`text-[10px] px-1.5 py-0.5 rounded border ${catStyle}`}>
              {CATEGORY_LABELS[pick.category] || pick.category}
            </span>
          </div>
          <p className="text-[11px] text-mute truncate">{pick.name}</p>
        </div>
        <div className="text-right shrink-0 ml-3">
          <span className={`text-lg font-bold ${scoreColor}`}>
            {pick.score.toFixed(0)}
          </span>
          <p className="text-[10px] text-mute">score</p>
        </div>
      </div>

      {/* Price info */}
      <div className="grid grid-cols-3 gap-3 text-xs mb-3">
        <div>
          <span className="text-mute/70 block text-[10px]">LTP</span>
          <span className="text-ink font-medium">{pick.ltp.toFixed(2)}</span>
        </div>
        <div>
          <span className="text-mute/70 block text-[10px]">NAV</span>
          <span className="text-ink font-medium">{pick.nav.toFixed(2)}</span>
        </div>
        <div>
          <span className="text-mute/70 block text-[10px]">Discount</span>
          <span
            className={`font-medium ${pick.nav_discount_pct > 0 ? "text-green-400" : pick.nav_discount_pct < -0.2 ? "text-red-400" : "text-mute"}`}
          >
            {pick.nav_discount_pct > 0 ? "+" : ""}
            {pick.nav_discount_pct.toFixed(2)}%
          </span>
        </div>
      </div>

      {/* Trade levels */}
      <div className="grid grid-cols-4 gap-2 text-xs mb-3">
        <div>
          <span className="text-mute/70 block text-[10px]">Entry</span>
          <span className="text-ink">{pick.entry.toFixed(2)}</span>
        </div>
        <div>
          <span className="text-mute/70 block text-[10px]">Stop</span>
          <span className="text-red-400">{pick.stop_loss.toFixed(2)}</span>
        </div>
        <div>
          <span className="text-mute/70 block text-[10px]">Target</span>
          <span className="text-green-400">{pick.target.toFixed(2)}</span>
        </div>
        <div>
          <span className="text-mute/70 block text-[10px]">R:R</span>
          <span className="text-ink">{pick.net_rr.toFixed(1)}</span>
        </div>
      </div>

      {/* Qty & Capital */}
      <div className="flex items-center justify-between text-xs mb-3">
        <div className="flex items-center gap-3">
          <span className="text-mute">
            Qty: <span className="text-ink font-medium">{pick.qty}</span>
          </span>
          <span className="text-mute">
            Capital:{" "}
            <span className={`font-medium ${pick.fits_budget ? "text-ink" : "text-red-400"}`}>
              Rs {pick.capital_needed.toLocaleString()}
            </span>
          </span>
        </div>
        <span className="text-mute/60 text-[10px]">
          Spread: {(pick.spread_pct * 100).toFixed(2)}%
        </span>
      </div>

      {/* Expand for breakdown */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="text-[10px] text-accent hover:underline"
      >
        {expanded ? "Hide breakdown" : "Show score breakdown"}
      </button>

      {expanded && (
        <div className="mt-3 space-y-1.5 border-t border-line/50 pt-3">
          <ScoreBar label="NAV Disc." value={pick.breakdown.nav_discount} />
          <ScoreBar label="Spread/Liq" value={pick.breakdown.spread_liquidity} />
          <ScoreBar label="Regime" value={pick.breakdown.regime_alignment} />
          <ScoreBar label="FII/DII" value={pick.breakdown.fii_dii_flow} />
          <ScoreBar label="Time" value={pick.breakdown.time_of_day} />
        </div>
      )}

      {/* Notes */}
      {pick.notes.length > 0 && (
        <div className="mt-3 space-y-1">
          {pick.notes.map((note, i) => (
            <p key={i} className="text-[10px] text-mute/70 flex items-start gap-1">
              <Info className="w-3 h-3 shrink-0 mt-0.5" />
              {note}
            </p>
          ))}
        </div>
      )}
    </div>
  );
}

export default function ETFPicksPage() {
  const [data, setData] = useState<ETFPicksResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetchETFPicks();
      setData(res);
      setLastUpdated(new Date());
    } catch {
      // keep stale data
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold text-ink">ETF Picks</h1>
          <p className="text-xs text-mute mt-0.5">
            5-factor scoring: NAV discount, spread, regime, flows, time-of-day
          </p>
        </div>
        <div className="flex items-center gap-3">
          {lastUpdated && (
            <span className="text-[10px] text-mute/60">
              Updated {formatIST(lastUpdated)}
            </span>
          )}
          <button
            onClick={refresh}
            disabled={loading}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-card-alt border border-line rounded-lg text-mute hover:text-ink hover:border-accent/30 transition-colors disabled:opacity-50"
          >
            <RefreshCw className={`w-3 h-3 ${loading ? "animate-spin" : ""}`} />
            Refresh
          </button>
        </div>
      </div>

      {/* Info bar */}
      {data && (
        <div className="flex items-center justify-between text-xs text-mute">
          <span>
            Universe: {data.universe_size} ETFs | Scored: {data.scored} | Regime:{" "}
            <span className="text-accent font-medium">{data.regime}</span>
          </span>
          <span className="text-[10px] text-mute/60">
            {data.trade_for}
          </span>
        </div>
      )}

      {/* Advisory */}
      {data?.advisory && data.advisory.length > 0 && (
        <div className="bg-yellow-500/5 border border-yellow-500/20 rounded-xl p-4">
          <div className="flex items-center gap-2 mb-2">
            <AlertTriangle className="w-4 h-4 text-yellow-400" />
            <span className="text-xs font-semibold text-yellow-400">Advisory</span>
          </div>
          <ul className="space-y-1">
            {data.advisory.map((line, i) => (
              <li key={i} className="text-xs text-yellow-400/80 flex items-start gap-2">
                <span className="text-yellow-400/40 mt-0.5">--</span>
                {line}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Loading skeleton */}
      {loading && !data && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {Array.from({ length: 6 }).map((_, i) => (
            <div
              key={i}
              className="h-52 bg-card border border-line rounded-xl animate-pulse"
            />
          ))}
        </div>
      )}

      {/* Top picks */}
      {data && data.top_picks.length > 0 && (
        <div>
          <h2 className="text-xs font-semibold text-mute uppercase tracking-wider mb-3 flex items-center gap-2">
            <TrendingUp className="w-3.5 h-3.5 text-green-400" />
            Top ETF Picks ({data.top_picks.length})
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {data.top_picks.map((pick) => (
              <ETFPickCard key={pick.symbol} pick={pick} />
            ))}
          </div>
        </div>
      )}

      {/* Stretch picks */}
      {data && data.stretch_picks.length > 0 && (
        <div>
          <h2 className="text-xs font-semibold text-mute uppercase tracking-wider mb-3 flex items-center gap-2">
            <TrendingDown className="w-3.5 h-3.5 text-mute/50" />
            Stretch Picks ({data.stretch_picks.length})
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {data.stretch_picks.map((pick) => (
              <ETFPickCard key={pick.symbol} pick={pick} />
            ))}
          </div>
        </div>
      )}

      {/* No picks */}
      {data && data.top_picks.length === 0 && !loading && (
        <div className="bg-card border border-line rounded-xl p-8 text-center">
          <p className="text-sm text-mute">No ETF picks available</p>
          <p className="text-xs text-mute/50 mt-1">
            ETF scoring requires market data. Try refreshing during market hours.
          </p>
        </div>
      )}

      {/* Weights */}
      {data?.weights && (
        <div className="bg-card border border-line rounded-xl p-4">
          <h3 className="text-xs font-semibold text-mute uppercase tracking-wider mb-3">
            ETF Scoring Weights
          </h3>
          <div className="grid grid-cols-5 gap-3">
            {Object.entries(data.weights).map(([name, weight]) => (
              <div key={name} className="text-center">
                <div className="text-lg font-bold text-accent">
                  {(weight * 100).toFixed(0)}%
                </div>
                <div className="text-[10px] text-mute capitalize">
                  {name.replace(/_/g, " ")}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Disclaimer */}
      <div className="bg-red-500/5 border border-red-500/20 rounded-xl p-4 text-xs text-red-400/80 leading-relaxed">
        <strong>PAPER TRADING ONLY.</strong>{" "}
        {data?.disclaimer ??
          "ETF picks are educational, generated by a 5-factor scoring model. Always verify with your broker's data."}
      </div>
    </div>
  );
}
