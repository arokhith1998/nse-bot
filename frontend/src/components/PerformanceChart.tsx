"use client";

import { useMemo } from "react";
import { BarChart2, Target, TrendingUp } from "lucide-react";
import type { PerformanceData, FeatureWeight } from "@/lib/types";
import { formatCurrency, formatPct } from "@/lib/constants";

interface PerformanceChartProps {
  performance: PerformanceData | null;
  weights: FeatureWeight[];
  loading?: boolean;
}

function KpiCard({
  label,
  value,
  color = "text-ink",
}: {
  label: string;
  value: string;
  color?: string;
}) {
  return (
    <div className="bg-card-alt border border-line rounded-lg p-3">
      <span className="text-[10px] text-mute uppercase tracking-wider">
        {label}
      </span>
      <div className={`text-lg font-semibold font-mono mt-0.5 ${color}`}>
        {value}
      </div>
    </div>
  );
}

function HorizontalBar({
  label,
  value,
  maxValue = 100,
  color = "bg-accent",
}: {
  label: string;
  value: number;
  maxValue?: number;
  color?: string;
}) {
  const pct = Math.max(0, Math.min(100, (value / maxValue) * 100));
  return (
    <div className="flex items-center gap-3">
      <span className="text-xs text-mute w-28 truncate">{label}</span>
      <div className="flex-1 h-2 bg-bg rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full transition-all ${color}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="text-xs font-mono text-ink w-14 text-right">
        {value.toFixed(1)}%
      </span>
    </div>
  );
}

export default function PerformanceChart({
  performance,
  weights,
  loading = false,
}: PerformanceChartProps) {
  const sortedWeights = useMemo(
    () => [...weights].sort((a, b) => b.weight - a.weight),
    [weights],
  );

  if (loading) {
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

  return (
    <div className="bg-card border border-line rounded-xl p-5 space-y-5">
      {/* Header */}
      <div className="flex items-center gap-2">
        <BarChart2 className="w-4 h-4 text-mute" />
        <h2 className="text-xs font-semibold text-mute uppercase tracking-wider">
          Performance Analytics
        </h2>
      </div>

      {/* KPI Grid */}
      {performance && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <KpiCard
            label="Win Rate"
            value={`${(performance.win_rate ?? 0).toFixed(1)}%`}
            color={(performance.win_rate ?? 0) >= 50 ? "text-green" : "text-red"}
          />
          <KpiCard
            label="Profit Factor"
            value={(performance.profit_factor ?? 0).toFixed(2)}
            color={
              (performance.profit_factor ?? 0) >= 1.5 ? "text-green" : "text-yellow"
            }
          />
          <KpiCard
            label="Total P&L"
            value={formatCurrency(performance.total_pnl ?? 0)}
            color={(performance.total_pnl ?? 0) >= 0 ? "text-green" : "text-red"}
          />
          <KpiCard
            label="Max Drawdown"
            value={formatPct(performance.max_drawdown ?? 0)}
            color="text-red"
          />
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        {/* Win Rate by Setup */}
        {performance?.win_rate_by_setup && (
          <div>
            <div className="flex items-center gap-2 mb-3">
              <Target className="w-3.5 h-3.5 text-mute" />
              <h3 className="text-[10px] text-mute uppercase tracking-wider font-semibold">
                Win Rate by Setup
              </h3>
            </div>
            <div className="space-y-2">
              {Object.entries(performance.win_rate_by_setup)
                .sort(([, a], [, b]) => b - a)
                .map(([setup, rate]) => (
                  <HorizontalBar
                    key={setup}
                    label={setup}
                    value={rate}
                    color={
                      rate >= 60
                        ? "bg-green"
                        : rate >= 45
                          ? "bg-yellow"
                          : "bg-red"
                    }
                  />
                ))}
            </div>
          </div>
        )}

        {/* Feature Weights */}
        {sortedWeights.length > 0 && (
          <div>
            <div className="flex items-center gap-2 mb-3">
              <TrendingUp className="w-3.5 h-3.5 text-mute" />
              <h3 className="text-[10px] text-mute uppercase tracking-wider font-semibold">
                Feature Importance
              </h3>
            </div>
            <div className="space-y-2">
              {sortedWeights.map((fw) => (
                <HorizontalBar
                  key={fw.name}
                  label={fw.name}
                  value={fw.weight * 100}
                  maxValue={30}
                  color="bg-accent"
                />
              ))}
            </div>
          </div>
        )}
      </div>

      {/* P&L Curve placeholder */}
      {performance?.daily_pnl && performance.daily_pnl.length > 0 && (
        <div>
          <h3 className="text-[10px] text-mute uppercase tracking-wider font-semibold mb-3">
            Cumulative P&L
          </h3>
          <div className="h-40 bg-card-alt border border-line rounded-lg flex items-end gap-px p-3">
            {(() => {
              const data = performance.daily_pnl;
              const maxAbs = Math.max(
                ...data.map((d) => Math.abs(d.cumulative)),
                1,
              );
              return data.map((d, i) => {
                const h = Math.abs(d.cumulative) / maxAbs;
                const positive = d.cumulative >= 0;
                return (
                  <div
                    key={i}
                    className="flex-1 flex flex-col justify-end"
                    title={`${d.date}: ${formatCurrency(d.cumulative)}`}
                  >
                    <div
                      className={`rounded-sm min-h-[2px] transition-all ${
                        positive ? "bg-green/70" : "bg-red/70"
                      }`}
                      style={{ height: `${h * 100}%` }}
                    />
                  </div>
                );
              });
            })()}
          </div>
          <div className="flex justify-between text-[10px] text-mute/50 mt-1 px-1">
            <span>{performance.daily_pnl[0]?.date}</span>
            <span>
              {performance.daily_pnl[performance.daily_pnl.length - 1]?.date}
            </span>
          </div>
        </div>
      )}
    </div>
  );
}
