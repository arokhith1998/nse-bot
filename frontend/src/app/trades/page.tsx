"use client";

import { useState, useEffect, useMemo } from "react";
import { fetchTradeHistory } from "@/lib/api";
import { useTrades } from "@/hooks/useTrades";
import TradeCard from "@/components/TradeCard";
import type { TradeHistory } from "@/lib/types";
import { formatCurrency, formatPct } from "@/lib/constants";
import {
  ArrowLeftRight,
  Search,
  Filter,
  CheckCircle,
  XCircle,
  Minus,
} from "lucide-react";

export default function TradesPage() {
  const { trades: activeTrades, loading: activeLoading } = useTrades();
  const [history, setHistory] = useState<TradeHistory[]>([]);
  const [historyLoading, setHistoryLoading] = useState(true);

  const [symbolFilter, setSymbolFilter] = useState("");
  const [resultFilter, setResultFilter] = useState<string>("");
  const [setupFilter, setSetupFilter] = useState<string>("");

  useEffect(() => {
    fetchTradeHistory({ limit: 100 })
      .then((data) => setHistory(Array.isArray(data) ? data : []))
      .catch(() => setHistory([]))
      .finally(() => setHistoryLoading(false));
  }, []);

  const filtered = useMemo(() => {
    return history.filter((t) => {
      if (symbolFilter && !t.symbol.includes(symbolFilter.toUpperCase()))
        return false;
      if (resultFilter && t.result !== resultFilter) return false;
      if (setupFilter && !t.setup.includes(setupFilter)) return false;
      return true;
    });
  }, [history, symbolFilter, resultFilter, setupFilter]);

  const stats = useMemo(() => {
    if (filtered.length === 0) return null;
    const wins = filtered.filter((t) => t.result === "WIN").length;
    const totalPnl = filtered.reduce((s, t) => s + t.pnl, 0);
    return {
      total: filtered.length,
      wins,
      losses: filtered.filter((t) => t.result === "LOSS").length,
      winRate: (wins / filtered.length) * 100,
      totalPnl,
    };
  }, [filtered]);

  const setups = useMemo(
    () => [...new Set(history.map((t) => t.setup))].sort(),
    [history],
  );

  return (
    <>
      <h1 className="text-lg font-semibold text-ink">Trades</h1>

      {/* Active Trades */}
      <div>
        <h2 className="text-xs font-semibold text-mute uppercase tracking-wider mb-3">
          Active Positions ({activeTrades.length})
        </h2>
        {activeLoading ? (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {Array.from({ length: 3 }).map((_, i) => (
              <div
                key={i}
                className="h-40 bg-card border border-line rounded-xl animate-pulse"
              />
            ))}
          </div>
        ) : activeTrades.length === 0 ? (
          <div className="bg-card border border-line rounded-xl p-6 text-center">
            <p className="text-sm text-mute">No active positions</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {activeTrades.map((trade) => (
              <TradeCard key={trade.id} trade={trade} />
            ))}
          </div>
        )}
      </div>

      {/* Trade History */}
      <div className="bg-card border border-line rounded-xl p-5">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <ArrowLeftRight className="w-4 h-4 text-mute" />
            <h2 className="text-xs font-semibold text-mute uppercase tracking-wider">
              Trade History
            </h2>
          </div>
          {stats && (
            <div className="flex items-center gap-4 text-xs">
              <span className="text-mute">{stats.total} trades</span>
              <span className="text-green">{stats.wins}W</span>
              <span className="text-red">{stats.losses}L</span>
              <span
                className={`font-mono font-semibold ${stats.totalPnl >= 0 ? "text-green" : "text-red"}`}
              >
                {formatCurrency(stats.totalPnl)}
              </span>
              <span
                className={`font-mono ${stats.winRate >= 50 ? "text-green" : "text-red"}`}
              >
                {stats.winRate.toFixed(1)}% WR
              </span>
            </div>
          )}
        </div>

        {/* Filters */}
        <div className="flex items-center gap-3 mb-4">
          <div className="relative flex-1 max-w-xs">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3 h-3 text-mute" />
            <input
              type="text"
              placeholder="Filter by symbol..."
              value={symbolFilter}
              onChange={(e) => setSymbolFilter(e.target.value)}
              className="w-full pl-7 pr-3 py-1.5 text-xs bg-card-alt border border-line rounded-lg text-ink placeholder-mute/40 focus:outline-none focus:border-accent/40"
            />
          </div>
          <div className="flex items-center gap-1.5">
            <Filter className="w-3 h-3 text-mute" />
            <select
              value={resultFilter}
              onChange={(e) => setResultFilter(e.target.value)}
              className="text-xs bg-card-alt border border-line rounded-lg px-2 py-1.5 text-ink focus:outline-none focus:border-accent/40"
            >
              <option value="">All Results</option>
              <option value="WIN">Wins</option>
              <option value="LOSS">Losses</option>
              <option value="BREAKEVEN">Breakeven</option>
            </select>
          </div>
          <select
            value={setupFilter}
            onChange={(e) => setSetupFilter(e.target.value)}
            className="text-xs bg-card-alt border border-line rounded-lg px-2 py-1.5 text-ink focus:outline-none focus:border-accent/40"
          >
            <option value="">All Setups</option>
            {setups.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </div>

        {/* Table */}
        {historyLoading ? (
          <div className="space-y-2">
            {Array.from({ length: 5 }).map((_, i) => (
              <div
                key={i}
                className="h-10 bg-card-alt rounded animate-pulse"
              />
            ))}
          </div>
        ) : filtered.length === 0 ? (
          <p className="text-sm text-mute text-center py-8">
            No trade history found
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b border-line">
                  {[
                    "Result",
                    "Symbol",
                    "Bias",
                    "Setup",
                    "Entry",
                    "Exit",
                    "Qty",
                    "P&L",
                    "P&L %",
                    "Entry Time",
                    "Exit Time",
                  ].map((h) => (
                    <th
                      key={h}
                      className="px-3 py-2 text-left text-[10px] text-mute uppercase tracking-wider"
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filtered.map((t) => (
                  <tr
                    key={t.id}
                    className="border-b border-line/30 hover:bg-white/[0.02]"
                  >
                    <td className="px-3 py-2">
                      {t.result === "WIN" ? (
                        <CheckCircle className="w-4 h-4 text-green" />
                      ) : t.result === "LOSS" ? (
                        <XCircle className="w-4 h-4 text-red" />
                      ) : (
                        <Minus className="w-4 h-4 text-mute" />
                      )}
                    </td>
                    <td className="px-3 py-2 text-sm font-semibold text-ink">
                      {t.symbol}
                    </td>
                    <td
                      className={`px-3 py-2 text-xs font-bold ${t.bias === "LONG" ? "text-green" : "text-red"}`}
                    >
                      {t.bias}
                    </td>
                    <td className="px-3 py-2">
                      <span className="px-1.5 py-0.5 text-[10px] rounded bg-card-alt border border-line text-mute">
                        {t.setup}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-xs font-mono text-ink">
                      {formatCurrency(t.entry_price)}
                    </td>
                    <td className="px-3 py-2 text-xs font-mono text-ink">
                      {formatCurrency(t.exit_price)}
                    </td>
                    <td className="px-3 py-2 text-xs font-mono text-ink">
                      {t.qty}
                    </td>
                    <td
                      className={`px-3 py-2 text-xs font-mono font-semibold ${t.pnl >= 0 ? "text-green" : "text-red"}`}
                    >
                      {formatCurrency(t.pnl)}
                    </td>
                    <td
                      className={`px-3 py-2 text-xs font-mono ${t.pnl_pct >= 0 ? "text-green" : "text-red"}`}
                    >
                      {formatPct(t.pnl_pct)}
                    </td>
                    <td className="px-3 py-2 text-[10px] text-mute font-mono">
                      {t.entry_time}
                    </td>
                    <td className="px-3 py-2 text-[10px] text-mute font-mono">
                      {t.exit_time}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  );
}
