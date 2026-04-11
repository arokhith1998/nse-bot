"use client";

import { useState, useEffect } from "react";
import { fetchRegimeHistory } from "@/lib/api";
import { useRegime } from "@/hooks/useRegime";
import RegimePanel from "@/components/RegimePanel";
import { REGIME_CONFIG, formatIST, formatPct } from "@/lib/constants";
import type { RegimeState } from "@/lib/types";
import { History, Calendar } from "lucide-react";

export default function RegimePage() {
  const { regime, loading: currentLoading } = useRegime();
  const [history, setHistory] = useState<RegimeState[]>([]);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [days, setDays] = useState(30);

  useEffect(() => {
    setHistoryLoading(true);
    fetchRegimeHistory(days)
      .then((data) => setHistory(Array.isArray(data?.history) ? data.history : []))
      .catch(() => setHistory([]))
      .finally(() => setHistoryLoading(false));
  }, [days]);

  return (
    <>
      <div className="flex items-center gap-2 mb-1">
        <h1 className="text-lg font-semibold text-ink">Market Regime</h1>
      </div>

      <RegimePanel regime={regime} loading={currentLoading} />

      {/* History */}
      <div className="bg-card border border-line rounded-xl p-5">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <History className="w-4 h-4 text-mute" />
            <h2 className="text-xs font-semibold text-mute uppercase tracking-wider">
              Regime History
            </h2>
          </div>
          <div className="flex items-center gap-2">
            <Calendar className="w-3.5 h-3.5 text-mute" />
            <select
              value={days}
              onChange={(e) => setDays(Number(e.target.value))}
              className="text-xs bg-card-alt border border-line rounded-lg px-2 py-1 text-ink focus:outline-none focus:border-accent/40"
            >
              <option value={7}>7 days</option>
              <option value={14}>14 days</option>
              <option value={30}>30 days</option>
              <option value={60}>60 days</option>
              <option value={90}>90 days</option>
            </select>
          </div>
        </div>

        {historyLoading ? (
          <div className="space-y-2">
            {Array.from({ length: 5 }).map((_, i) => (
              <div
                key={i}
                className="h-12 bg-card-alt rounded-lg animate-pulse"
              />
            ))}
          </div>
        ) : history.length === 0 ? (
          <p className="text-sm text-mute text-center py-8">
            No regime history available
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b border-line">
                  <th className="px-3 py-2 text-left text-[10px] text-mute uppercase tracking-wider">
                    Date
                  </th>
                  <th className="px-3 py-2 text-left text-[10px] text-mute uppercase tracking-wider">
                    Regime
                  </th>
                  <th className="px-3 py-2 text-right text-[10px] text-mute uppercase tracking-wider">
                    Nifty
                  </th>
                  <th className="px-3 py-2 text-right text-[10px] text-mute uppercase tracking-wider">
                    Change
                  </th>
                  <th className="px-3 py-2 text-right text-[10px] text-mute uppercase tracking-wider">
                    VIX
                  </th>
                  <th className="px-3 py-2 text-right text-[10px] text-mute uppercase tracking-wider">
                    Breadth
                  </th>
                  <th className="px-3 py-2 text-right text-[10px] text-mute uppercase tracking-wider">
                    Modifier
                  </th>
                </tr>
              </thead>
              <tbody>
                {history.map((r, i) => {
                  const cfg = REGIME_CONFIG[r.label] ?? { label: r.label, color: "text-mute", bg: "bg-mute/15" };
                  const vix = r.vix ?? 0;
                  const niftyClose = r.nifty_close ?? 0;
                  const niftyChangePct = r.nifty_change_pct ?? 0;
                  const breadthPct = r.breadth_pct ?? 0;
                  const scoringMod = r.scoring_modifier ?? 0;
                  return (
                    <tr
                      key={i}
                      className="border-b border-line/30 hover:bg-white/[0.02]"
                    >
                      <td className="px-3 py-2 text-xs text-mute font-mono">
                        {formatIST(r.timestamp)}
                      </td>
                      <td className="px-3 py-2">
                        <span
                          className={`px-2 py-0.5 rounded-full text-[10px] font-semibold ${cfg.bg} ${cfg.color}`}
                        >
                          {cfg.label}
                        </span>
                      </td>
                      <td className="px-3 py-2 text-xs font-mono text-ink text-right">
                        {niftyClose.toLocaleString("en-IN")}
                      </td>
                      <td
                        className={`px-3 py-2 text-xs font-mono text-right ${
                          niftyChangePct >= 0 ? "text-green" : "text-red"
                        }`}
                      >
                        {formatPct(niftyChangePct)}
                      </td>
                      <td
                        className={`px-3 py-2 text-xs font-mono text-right ${
                          vix > 20
                            ? "text-red"
                            : vix > 15
                              ? "text-yellow"
                              : "text-green"
                        }`}
                      >
                        {vix.toFixed(1)}
                      </td>
                      <td className="px-3 py-2 text-xs font-mono text-ink text-right">
                        {breadthPct.toFixed(0)}%
                      </td>
                      <td
                        className={`px-3 py-2 text-xs font-mono text-right ${
                          scoringMod > 0
                            ? "text-green"
                            : scoringMod < 0
                              ? "text-red"
                              : "text-mute"
                        }`}
                      >
                        {scoringMod > 0 ? "+" : ""}
                        {scoringMod}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  );
}
