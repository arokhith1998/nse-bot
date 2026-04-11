"use client";

import {
  Activity,
  TrendingUp,
  TrendingDown,
  BarChart3,
  Gauge,
} from "lucide-react";
import { REGIME_CONFIG, formatPct } from "@/lib/constants";
import type { RegimeState } from "@/lib/types";

interface RegimePanelProps {
  regime: RegimeState | null;
  loading?: boolean;
}

export default function RegimePanel({
  regime,
  loading = false,
}: RegimePanelProps) {
  if (loading || !regime) {
    return (
      <div className="bg-card border border-line rounded-xl p-5 animate-pulse">
        <div className="h-4 w-40 bg-line rounded mb-4" />
        <div className="grid grid-cols-4 gap-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="h-20 bg-card-alt rounded-lg" />
          ))}
        </div>
      </div>
    );
  }

  const cfg = REGIME_CONFIG[regime.label] ?? { label: regime.label, color: "text-mute", bg: "bg-mute/15" };
  const vix = regime.vix ?? 0;
  const breadth = regime.breadth_pct ?? 0;
  const niftyClose = regime.nifty_close ?? 0;
  const niftyChangePct = regime.nifty_change_pct ?? 0;
  const sensexClose = regime.sensex_close ?? 0;
  const sensexChangePct = regime.sensex_change_pct ?? 0;
  const advanceDecline = regime.advance_decline_ratio ?? 0;
  const scoringMod = regime.scoring_modifier ?? 0;
  const vixPct = Math.min((vix / 40) * 100, 100);
  const breadthPct = Math.max(0, Math.min(breadth, 100));

  return (
    <div className="bg-card border border-line rounded-xl p-5">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-xs font-semibold text-mute uppercase tracking-wider">
          Market Regime
        </h2>
        <div
          className={`px-3 py-1 rounded-full text-xs font-semibold ${cfg.bg} ${cfg.color}`}
        >
          {cfg.label}
        </div>
      </div>

      {/* KPI Row */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-4">
        {/* Nifty */}
        <div className="bg-card-alt border border-line rounded-lg p-3">
          <div className="flex items-center gap-1.5 mb-1">
            <TrendingUp className="w-3.5 h-3.5 text-mute" />
            <span className="text-[10px] text-mute uppercase tracking-wider">
              Nifty
            </span>
          </div>
          <div className="text-lg font-semibold font-mono text-ink">
            {niftyClose.toLocaleString("en-IN")}
          </div>
          <span
            className={`text-xs font-mono ${niftyChangePct >= 0 ? "text-green" : "text-red"}`}
          >
            {formatPct(niftyChangePct)}
          </span>
        </div>

        {/* Sensex */}
        <div className="bg-card-alt border border-line rounded-lg p-3">
          <div className="flex items-center gap-1.5 mb-1">
            {sensexChangePct >= 0 ? (
              <TrendingUp className="w-3.5 h-3.5 text-green" />
            ) : (
              <TrendingDown className="w-3.5 h-3.5 text-red" />
            )}
            <span className="text-[10px] text-mute uppercase tracking-wider">
              Sensex
            </span>
          </div>
          <div className="text-lg font-semibold font-mono text-ink">
            {sensexClose.toLocaleString("en-IN")}
          </div>
          <span
            className={`text-xs font-mono ${sensexChangePct >= 0 ? "text-green" : "text-red"}`}
          >
            {formatPct(sensexChangePct)}
          </span>
        </div>

        {/* VIX Gauge */}
        <div className="bg-card-alt border border-line rounded-lg p-3">
          <div className="flex items-center gap-1.5 mb-1">
            <Activity className="w-3.5 h-3.5 text-mute" />
            <span className="text-[10px] text-mute uppercase tracking-wider">
              India VIX
            </span>
          </div>
          <div
            className={`text-lg font-semibold font-mono ${
              vix > 20
                ? "text-red"
                : vix > 15
                  ? "text-yellow"
                  : "text-green"
            }`}
          >
            {vix.toFixed(1)}
          </div>
          {/* VIX bar gauge */}
          <div className="mt-1.5 h-1.5 bg-bg rounded-full overflow-hidden">
            <div
              className={`h-full rounded-full transition-all ${
                vix > 20
                  ? "bg-red"
                  : vix > 15
                    ? "bg-yellow"
                    : "bg-green"
              }`}
              style={{ width: `${vixPct}%` }}
            />
          </div>
        </div>

        {/* Breadth */}
        <div className="bg-card-alt border border-line rounded-lg p-3">
          <div className="flex items-center gap-1.5 mb-1">
            <BarChart3 className="w-3.5 h-3.5 text-mute" />
            <span className="text-[10px] text-mute uppercase tracking-wider">
              Breadth
            </span>
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-lg font-semibold font-mono text-ink">
              {breadthPct.toFixed(0)}%
            </span>
            <span className="text-xs text-mute">
              A/D {advanceDecline.toFixed(2)}
            </span>
          </div>
          {/* Breadth bar */}
          <div className="mt-1.5 h-1.5 bg-bg rounded-full overflow-hidden">
            <div
              className={`h-full rounded-full transition-all ${
                breadthPct >= 60
                  ? "bg-green"
                  : breadthPct >= 40
                    ? "bg-yellow"
                    : "bg-red"
              }`}
              style={{ width: `${breadthPct}%` }}
            />
          </div>
        </div>
      </div>

      {/* Scoring Modifier */}
      <div className="flex items-center gap-3 mb-3">
        <Gauge className="w-4 h-4 text-mute" />
        <span className="text-xs text-mute">Scoring Modifier:</span>
        <span
          className={`text-xs font-mono font-semibold ${
            scoringMod > 0
              ? "text-green"
              : scoringMod < 0
                ? "text-red"
                : "text-mute"
          }`}
        >
          {scoringMod > 0 ? "+" : ""}
          {scoringMod}
        </span>
      </div>

      {/* Reasoning */}
      {regime.reasoning && (
        <p className="text-xs text-mute/80 leading-relaxed border-t border-line pt-3">
          {regime.reasoning}
        </p>
      )}

      {/* Sector Leaders / Laggards */}
      {((regime.sector_leaders?.length ?? 0) > 0 ||
        (regime.sector_laggards?.length ?? 0) > 0) && (
        <div className="flex gap-6 mt-3 pt-3 border-t border-line">
          {(regime.sector_leaders?.length ?? 0) > 0 && (
            <div>
              <span className="text-[10px] text-green uppercase tracking-wider font-semibold">
                Leaders
              </span>
              <div className="flex flex-wrap gap-1 mt-1">
                {(regime.sector_leaders ?? []).map((s) => (
                  <span
                    key={s}
                    className="px-2 py-0.5 text-[10px] rounded bg-green/10 text-green border border-green/20"
                  >
                    {s}
                  </span>
                ))}
              </div>
            </div>
          )}
          {(regime.sector_laggards?.length ?? 0) > 0 && (
            <div>
              <span className="text-[10px] text-red uppercase tracking-wider font-semibold">
                Laggards
              </span>
              <div className="flex flex-wrap gap-1 mt-1">
                {(regime.sector_laggards ?? []).map((s) => (
                  <span
                    key={s}
                    className="px-2 py-0.5 text-[10px] rounded bg-red/10 text-red border border-red/20"
                  >
                    {s}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
