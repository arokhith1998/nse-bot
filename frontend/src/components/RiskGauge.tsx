"use client";

import { ShieldAlert, PieChart, Flame } from "lucide-react";
import { formatCurrency, formatPct } from "@/lib/constants";
import type { PortfolioRisk } from "@/lib/types";

interface RiskGaugeProps {
  risk: PortfolioRisk | null;
  loading?: boolean;
}

function MeterBar({
  value,
  max,
  label,
  thresholds = [50, 80],
}: {
  value: number;
  max: number;
  label: string;
  thresholds?: [number, number];
}) {
  const pct = Math.max(0, Math.min(100, (value / max) * 100));
  const color =
    pct >= thresholds[1]
      ? "bg-red"
      : pct >= thresholds[0]
        ? "bg-yellow"
        : "bg-green";

  return (
    <div>
      <div className="flex justify-between text-xs mb-1">
        <span className="text-mute">{label}</span>
        <span className="font-mono text-ink">{pct.toFixed(0)}%</span>
      </div>
      <div className="h-2 bg-bg rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full transition-all ${color}`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

export default function RiskGauge({ risk, loading = false }: RiskGaugeProps) {
  if (loading || !risk) {
    return (
      <div className="bg-card border border-line rounded-xl p-5 animate-pulse">
        <div className="h-4 w-32 bg-line rounded mb-4" />
        <div className="space-y-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="h-8 bg-card-alt rounded" />
          ))}
        </div>
      </div>
    );
  }

  const heatColor =
    risk.portfolio_heat_pct > 6
      ? "text-red"
      : risk.portfolio_heat_pct > 3
        ? "text-yellow"
        : "text-green";

  return (
    <div className="bg-card border border-line rounded-xl p-5">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <ShieldAlert className="w-4 h-4 text-mute" />
          <h2 className="text-xs font-semibold text-mute uppercase tracking-wider">
            Portfolio Risk
          </h2>
        </div>
        <div className="flex items-center gap-1.5">
          <Flame className={`w-4 h-4 ${heatColor}`} />
          <span className={`text-sm font-semibold font-mono ${heatColor}`}>
            {formatPct(risk.portfolio_heat_pct)}
          </span>
          <span className="text-[10px] text-mute">heat</span>
        </div>
      </div>

      {/* Capital Utilization */}
      <MeterBar
        value={risk.capital_used}
        max={risk.capital_total}
        label={`Capital: ${formatCurrency(risk.capital_used)} / ${formatCurrency(risk.capital_total)}`}
      />

      {/* Positions */}
      <div className="mt-3">
        <MeterBar
          value={risk.open_positions}
          max={risk.max_positions}
          label={`Positions: ${risk.open_positions} / ${risk.max_positions}`}
          thresholds={[60, 90]}
        />
      </div>

      {/* Sector Concentration */}
      {Object.keys(risk.sector_exposure).length > 0 && (
        <div className="mt-4">
          <div className="flex items-center gap-2 mb-2">
            <PieChart className="w-3.5 h-3.5 text-mute" />
            <span className="text-[10px] text-mute uppercase tracking-wider font-semibold">
              Sector Exposure
            </span>
          </div>
          <div className="space-y-2">
            {Object.entries(risk.sector_exposure)
              .sort(([, a], [, b]) => b - a)
              .slice(0, 6)
              .map(([sector, pct]) => (
                <div key={sector} className="flex items-center gap-2">
                  <span className="text-xs text-mute w-24 truncate">
                    {sector}
                  </span>
                  <div className="flex-1 h-1.5 bg-bg rounded-full overflow-hidden">
                    <div
                      className={`h-full rounded-full ${
                        pct > 40
                          ? "bg-red"
                          : pct > 25
                            ? "bg-yellow"
                            : "bg-accent"
                      }`}
                      style={{ width: `${Math.min(pct, 100)}%` }}
                    />
                  </div>
                  <span className="text-xs font-mono text-ink w-10 text-right">
                    {pct.toFixed(0)}%
                  </span>
                </div>
              ))}
          </div>
        </div>
      )}

      {/* Risk Per Trade */}
      <div className="mt-4 pt-3 border-t border-line flex justify-between text-xs">
        <span className="text-mute">Risk per trade</span>
        <span className="font-mono text-ink">
          {formatCurrency(risk.risk_per_trade)}
        </span>
      </div>
      <div className="flex justify-between text-xs mt-1">
        <span className="text-mute">Max daily loss</span>
        <span className="font-mono text-red">
          {formatCurrency(risk.max_daily_loss)}
        </span>
      </div>
    </div>
  );
}
