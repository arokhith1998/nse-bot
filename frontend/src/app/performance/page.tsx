"use client";

import { useState, useEffect } from "react";
import { fetchPerformance } from "@/lib/api";
import PerformanceChart from "@/components/PerformanceChart";
import type { PerformanceData, FeatureWeight } from "@/lib/types";
import { formatCurrency, formatPct } from "@/lib/constants";
import { Brain, Target, TrendingUp, TrendingDown } from "lucide-react";

export default function PerformancePage() {
  const [perf, setPerf] = useState<PerformanceData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchPerformance()
      .then(setPerf)
      .catch(() => setPerf(null))
      .finally(() => setLoading(false));
  }, []);

  const defaultWeights: FeatureWeight[] = [
    { name: "trend", weight: 0.25 },
    { name: "momentum", weight: 0.2 },
    { name: "volume", weight: 0.15 },
    { name: "breakout", weight: 0.15 },
    { name: "volatility", weight: 0.1 },
    { name: "news", weight: 0.1 },
    { name: "liquidity", weight: 0.05 },
  ];

  return (
    <>
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold text-ink">
          Performance & Learning
        </h1>
        <div className="flex items-center gap-1.5 text-xs text-mute">
          <Brain className="w-3.5 h-3.5" />
          <span>Adaptive weight engine</span>
        </div>
      </div>

      <PerformanceChart
        performance={perf}
        weights={defaultWeights}
        loading={loading}
      />

      {/* Best / Worst Trades */}
      {perf && (perf.best_trade || perf.worst_trade) && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
          {perf.best_trade && (
            <div className="bg-card border border-green/20 rounded-xl p-5">
              <div className="flex items-center gap-2 mb-3">
                <TrendingUp className="w-4 h-4 text-green" />
                <h3 className="text-xs font-semibold text-green uppercase tracking-wider">
                  Best Trade
                </h3>
              </div>
              <div className="space-y-2 text-sm">
                <div className="flex justify-between">
                  <span className="text-mute">Symbol</span>
                  <span className="font-semibold text-ink">
                    {perf.best_trade.symbol}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-mute">Setup</span>
                  <span className="text-ink">{perf.best_trade.setup}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-mute">P&L</span>
                  <span className="font-mono font-semibold text-green">
                    {formatCurrency(perf.best_trade.pnl)} (
                    {formatPct(perf.best_trade.pnl_pct)})
                  </span>
                </div>
              </div>
            </div>
          )}

          {perf.worst_trade && (
            <div className="bg-card border border-red/20 rounded-xl p-5">
              <div className="flex items-center gap-2 mb-3">
                <TrendingDown className="w-4 h-4 text-red" />
                <h3 className="text-xs font-semibold text-red uppercase tracking-wider">
                  Worst Trade
                </h3>
              </div>
              <div className="space-y-2 text-sm">
                <div className="flex justify-between">
                  <span className="text-mute">Symbol</span>
                  <span className="font-semibold text-ink">
                    {perf.worst_trade.symbol}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-mute">Setup</span>
                  <span className="text-ink">{perf.worst_trade.setup}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-mute">P&L</span>
                  <span className="font-mono font-semibold text-red">
                    {formatCurrency(perf.worst_trade.pnl)} (
                    {formatPct(perf.worst_trade.pnl_pct)})
                  </span>
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Detailed Metrics */}
      {perf && (
        <div className="bg-card border border-line rounded-xl p-5">
          <div className="flex items-center gap-2 mb-4">
            <Target className="w-4 h-4 text-mute" />
            <h2 className="text-xs font-semibold text-mute uppercase tracking-wider">
              Detailed Metrics
            </h2>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div className="bg-card-alt border border-line rounded-lg p-3">
              <span className="text-[10px] text-mute uppercase tracking-wider">
                Total Trades
              </span>
              <div className="text-lg font-semibold font-mono text-ink mt-0.5">
                {perf.total_trades}
              </div>
            </div>
            <div className="bg-card-alt border border-line rounded-lg p-3">
              <span className="text-[10px] text-mute uppercase tracking-wider">
                Avg Profit
              </span>
              <div className="text-lg font-semibold font-mono text-green mt-0.5">
                {formatCurrency(perf.avg_profit)}
              </div>
            </div>
            <div className="bg-card-alt border border-line rounded-lg p-3">
              <span className="text-[10px] text-mute uppercase tracking-wider">
                Avg Loss
              </span>
              <div className="text-lg font-semibold font-mono text-red mt-0.5">
                {formatCurrency(perf.avg_loss)}
              </div>
            </div>
            <div className="bg-card-alt border border-line rounded-lg p-3">
              <span className="text-[10px] text-mute uppercase tracking-wider">
                Sharpe Ratio
              </span>
              <div
                className={`text-lg font-semibold font-mono mt-0.5 ${
                  perf.sharpe_ratio >= 1
                    ? "text-green"
                    : perf.sharpe_ratio >= 0
                      ? "text-yellow"
                      : "text-red"
                }`}
              >
                {perf.sharpe_ratio.toFixed(2)}
              </div>
            </div>
            <div className="bg-card-alt border border-line rounded-lg p-3">
              <span className="text-[10px] text-mute uppercase tracking-wider">
                Avg R:R Achieved
              </span>
              <div className="text-lg font-semibold font-mono text-accent mt-0.5">
                {perf.avg_rr_achieved.toFixed(2)}
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
