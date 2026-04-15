"use client";

import { useState, useMemo } from "react";
import {
  ChevronDown,
  ChevronRight,
  ArrowUpDown,
  TrendingUp,
  TrendingDown,
  Newspaper,
  ShieldAlert,
  Clock,
  XCircle,
  Target,
} from "lucide-react";
import { scoreColor, formatCurrency, formatNumber } from "@/lib/constants";
import type { Pick } from "@/lib/types";

type SortKey =
  | "score"
  | "symbol"
  | "strategy"
  | "price"
  | "net_rr"
  | "atr_pct"
  | "vol_ratio";
type SortDir = "asc" | "desc";

interface PicksTableProps {
  topPicks: Pick[];
  stretchPicks: Pick[];
  weights?: Record<string, number>;
  advisory?: string | string[] | null;
  recommendedPickCount?: number;
}

function ScoreBadge({ score }: { score: number }) {
  const c = scoreColor(score);
  return (
    <span
      className={`inline-flex items-center justify-center w-12 py-0.5 rounded-full text-xs font-bold ${c.bg} ${c.text} border ${c.border}`}
    >
      {score.toFixed(1)}
    </span>
  );
}

function BiasTag({ bias }: { bias?: string }) {
  const isLong = !bias || bias === "LONG";
  return (
    <span
      className={`inline-flex items-center gap-1 text-xs font-bold ${isLong ? "text-green" : "text-red"}`}
    >
      {isLong ? (
        <TrendingUp className="w-3 h-3" />
      ) : (
        <TrendingDown className="w-3 h-3" />
      )}
      {isLong ? "LONG" : "SHORT"}
    </span>
  );
}

function ExpandedRow({
  pick,
  weights,
}: {
  pick: Pick;
  weights?: Record<string, number>;
}) {
  return (
    <tr className="animate-fade-in">
      <td colSpan={10} className="px-4 py-3 bg-card-alt border-b border-line">
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 text-xs">
          {/* Technical Indicators */}
          <div>
            <h4 className="text-[10px] text-mute uppercase tracking-wider mb-2 font-semibold">
              Technical
            </h4>
            <div className="space-y-1">
              <div className="flex justify-between">
                <span className="text-mute">RSI</span>
                <span
                  className={`font-mono ${
                    (pick.rsi ?? 0) > 70
                      ? "text-red"
                      : (pick.rsi ?? 0) < 30
                        ? "text-green"
                        : "text-ink"
                  }`}
                >
                  {pick.rsi?.toFixed(1) ?? "N/A"}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-mute">Stoch %K</span>
                <span className="font-mono text-ink">
                  {(pick.stoch_k ?? 0).toFixed(1)}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-mute">BB Position</span>
                <span className="font-mono text-ink">
                  {(pick.bb_position ?? 0).toFixed(2)}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-mute">Gap %</span>
                <span
                  className={`font-mono ${(pick.gap_pct ?? 0) > 0 ? "text-green" : (pick.gap_pct ?? 0) < 0 ? "text-red" : "text-ink"}`}
                >
                  {(pick.gap_pct ?? 0).toFixed(2)}%
                </span>
              </div>
            </div>
          </div>

          {/* Volume & Momentum */}
          <div>
            <h4 className="text-[10px] text-mute uppercase tracking-wider mb-2 font-semibold">
              Volume & Momentum
            </h4>
            <div className="space-y-1">
              <div className="flex justify-between">
                <span className="text-mute">Vol Ratio</span>
                <span
                  className={`font-mono ${(pick.vol_ratio ?? 0) > 2 ? "text-green" : "text-ink"}`}
                >
                  {(pick.vol_ratio ?? 0).toFixed(2)}x
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-mute">ATR %</span>
                <span className="font-mono text-ink">
                  {(pick.atr_pct ?? 0).toFixed(2)}%
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-mute">5D Return</span>
                <span
                  className={`font-mono ${(pick.ret5d_pct ?? 0) > 0 ? "text-green" : "text-red"}`}
                >
                  {(pick.ret5d_pct ?? 0) > 0 ? "+" : ""}
                  {(pick.ret5d_pct ?? 0).toFixed(2)}%
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-mute">20D Return</span>
                <span
                  className={`font-mono ${(pick.ret20d_pct ?? 0) > 0 ? "text-green" : "text-red"}`}
                >
                  {(pick.ret20d_pct ?? 0) > 0 ? "+" : ""}
                  {(pick.ret20d_pct ?? 0).toFixed(2)}%
                </span>
              </div>
            </div>
          </div>

          {/* Cost Analysis */}
          <div>
            <h4 className="text-[10px] text-mute uppercase tracking-wider mb-2 font-semibold">
              Cost & Risk
            </h4>
            <div className="space-y-1">
              <div className="flex justify-between">
                <span className="text-mute">Cost R/T</span>
                <span className="font-mono text-ink">
                  {formatCurrency(pick.cost_roundtrip)}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-mute">Net Profit</span>
                <span className="font-mono text-green">
                  {formatCurrency(pick.net_profit)}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-mute">Net Loss</span>
                <span className="font-mono text-red">
                  {formatCurrency(pick.net_loss)}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-mute">Capital</span>
                <span className="font-mono text-ink">
                  {formatCurrency(pick.capital_needed)}
                </span>
              </div>
            </div>
          </div>

          {/* Score Breakdown (weights) */}
          <div>
            <h4 className="text-[10px] text-mute uppercase tracking-wider mb-2 font-semibold">
              Feature Weights
            </h4>
            {weights && (
              <div className="space-y-1.5">
                {Object.entries(weights)
                  .sort(([, a], [, b]) => b - a)
                  .map(([key, val]) => (
                    <div key={key} className="flex items-center gap-2">
                      <span className="text-mute w-16 truncate capitalize">
                        {key}
                      </span>
                      <div className="flex-1 h-1.5 bg-bg rounded-full overflow-hidden">
                        <div
                          className="h-full bg-accent rounded-full"
                          style={{ width: `${val * 100 * 4}%` }}
                        />
                      </div>
                      <span className="text-mute font-mono w-10 text-right">
                        {(val * 100).toFixed(1)}%
                      </span>
                    </div>
                  ))}
              </div>
            )}
          </div>
        </div>

        {/* Scale-Out Plan & Invalidation */}
        <div className="mt-3 pt-3 border-t border-line grid grid-cols-1 lg:grid-cols-3 gap-4">
          {/* Scale-out levels */}
          <div>
            <div className="flex items-center gap-1.5 mb-2">
              <Target className="w-3 h-3 text-accent" />
              <h4 className="text-[10px] text-mute uppercase tracking-wider font-semibold">
                Scale-Out Plan
              </h4>
            </div>
            <div className="space-y-1 text-xs">
              <div className="flex justify-between">
                <span className="text-mute">1R — Book 50%</span>
                <span className="font-mono text-green">
                  {formatNumber(pick.scale_out_1 ?? pick.target)}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-mute">1.5R — Book 25%</span>
                <span className="font-mono text-green">
                  {formatNumber(pick.scale_out_2 ?? pick.target)}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-mute">2R+ — Trail 25%</span>
                <span className="font-mono text-accent">
                  {formatNumber(pick.target)}
                </span>
              </div>
            </div>
          </div>

          {/* Invalidation & Time */}
          <div>
            <div className="flex items-center gap-1.5 mb-2">
              <ShieldAlert className="w-3 h-3 text-red" />
              <h4 className="text-[10px] text-mute uppercase tracking-wider font-semibold">
                What Invalidates This
              </h4>
            </div>
            <p className="text-xs text-red/80 font-mono">
              {pick.invalidation ?? `Breaks below ${formatNumber(pick.stop_loss)}`}
            </p>
            {pick.time_validity && (
              <div className="flex items-center gap-1 mt-2 text-xs text-mute">
                <Clock className="w-3 h-3" />
                <span>Valid: {pick.time_validity}</span>
              </div>
            )}
            {pick.ev != null && (
              <div className="flex items-center gap-1 mt-1 text-xs">
                <span className="text-mute">EV:</span>
                <span className={`font-mono font-semibold ${(pick.ev ?? 0) > 0 ? "text-green" : "text-red"}`}>
                  {(pick.ev ?? 0) > 0 ? "+" : ""}{(pick.ev ?? 0).toFixed(0)}
                </span>
              </div>
            )}
          </div>

          {/* Veto / Skip */}
          <div className="flex flex-col justify-center items-end">
            <button
              onClick={(e) => {
                e.stopPropagation();
                fetch(`/api/picks/${pick.symbol}/veto?reason=skip_today`, { method: "POST" })
                  .catch(() => {});
              }}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-red/10 border border-red/20 rounded-lg text-red hover:bg-red/20 transition-colors"
            >
              <XCircle className="w-3.5 h-3.5" />
              Skip Today
            </button>
            <span className="text-[10px] text-mute/50 mt-1">
              Feeds learning engine
            </span>
          </div>
        </div>

        {/* News Catalyst */}
        {pick.news_catalyst && (
          <div className="mt-3 pt-3 border-t border-line flex items-start gap-2">
            <Newspaper className="w-3.5 h-3.5 text-blue mt-0.5 shrink-0" />
            <p className="text-xs text-mute leading-relaxed">
              {pick.news_catalyst}
            </p>
          </div>
        )}

        {/* Notes */}
        {pick.notes && pick.notes.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1.5">
            {pick.notes.map((note, i) => (
              <span
                key={i}
                className="px-2 py-0.5 text-[10px] rounded bg-card border border-line text-mute"
              >
                {note}
              </span>
            ))}
          </div>
        )}
      </td>
    </tr>
  );
}

function PicksSection({
  title,
  picks,
  weights,
  sortKey,
  sortDir,
  onSort,
  expandedRows,
  toggleRow,
}: {
  title: string;
  picks: Pick[];
  weights?: Record<string, number>;
  sortKey: SortKey;
  sortDir: SortDir;
  onSort: (key: SortKey) => void;
  expandedRows: Set<string>;
  toggleRow: (symbol: string) => void;
}) {
  const sorted = useMemo(() => {
    const copy = [...picks];
    copy.sort((a, b) => {
      const aVal = a[sortKey] ?? 0;
      const bVal = b[sortKey] ?? 0;
      if (typeof aVal === "string" && typeof bVal === "string") {
        return sortDir === "asc"
          ? aVal.localeCompare(bVal)
          : bVal.localeCompare(aVal);
      }
      return sortDir === "asc"
        ? (aVal as number) - (bVal as number)
        : (bVal as number) - (aVal as number);
    });
    return copy;
  }, [picks, sortKey, sortDir]);

  const SortHeader = ({
    label,
    field,
    className = "",
  }: {
    label: string;
    field: SortKey;
    className?: string;
  }) => (
    <th
      className={`px-3 py-2.5 text-left text-[10px] text-mute uppercase tracking-wider font-semibold cursor-pointer hover:text-ink select-none ${className}`}
      onClick={() => onSort(field)}
    >
      <span className="inline-flex items-center gap-1">
        {label}
        <ArrowUpDown
          className={`w-3 h-3 ${sortKey === field ? "text-accent" : "text-mute/30"}`}
        />
      </span>
    </th>
  );

  return (
    <div className="mt-4 first:mt-0">
      <h3 className="text-xs font-semibold text-mute uppercase tracking-wider mb-2">
        {title}
      </h3>
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead>
            <tr className="border-b border-line">
              <th className="w-8" />
              <SortHeader label="Score" field="score" />
              <SortHeader label="Symbol" field="symbol" />
              <th className="px-3 py-2.5 text-left text-[10px] text-mute uppercase tracking-wider font-semibold">
                Bias
              </th>
              <SortHeader label="Setup" field="strategy" />
              <th className="px-3 py-2.5 text-left text-[10px] text-mute uppercase tracking-wider font-semibold">
                Entry Zone
              </th>
              <th className="px-3 py-2.5 text-left text-[10px] text-mute uppercase tracking-wider font-semibold">
                Stop
              </th>
              <th className="px-3 py-2.5 text-left text-[10px] text-mute uppercase tracking-wider font-semibold">
                Target
              </th>
              <th className="px-3 py-2.5 text-right text-[10px] text-mute uppercase tracking-wider font-semibold">
                Qty
              </th>
              <SortHeader label="R:R" field="net_rr" className="text-right" />
            </tr>
          </thead>
          <tbody>
            {sorted.map((pick) => {
              const expanded = expandedRows.has(pick.symbol);
              return (
                <>
                  <tr
                    key={pick.symbol}
                    className="border-b border-line/50 hover:bg-white/[0.02] cursor-pointer transition-colors"
                    onClick={() => toggleRow(pick.symbol)}
                  >
                    <td className="pl-3 py-2.5">
                      {expanded ? (
                        <ChevronDown className="w-3.5 h-3.5 text-accent" />
                      ) : (
                        <ChevronRight className="w-3.5 h-3.5 text-mute" />
                      )}
                    </td>
                    <td className="px-3 py-2.5">
                      <ScoreBadge score={pick.score} />
                    </td>
                    <td className="px-3 py-2.5">
                      <div className="flex items-center gap-2">
                        <span className="font-semibold text-sm text-ink">
                          {pick.symbol}
                        </span>
                        {pick.news_catalyst && (
                          <Newspaper className="w-3 h-3 text-blue" />
                        )}
                        {pick.near_20d_high && (
                          <span className="text-[9px] px-1 py-0.5 rounded bg-accent/10 text-accent border border-accent/20">
                            20D Hi
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="px-3 py-2.5">
                      <BiasTag bias={pick.bias} />
                    </td>
                    <td className="px-3 py-2.5">
                      <div className="flex flex-wrap gap-1">
                        {(pick.strategy ?? "").split("/").map((s) => (
                          <span
                            key={s}
                            className="px-1.5 py-0.5 text-[10px] rounded bg-card-alt border border-line text-mute"
                          >
                            {s}
                          </span>
                        ))}
                      </div>
                    </td>
                    <td className="px-3 py-2.5 font-mono text-xs text-ink">
                      {pick.entry_zone}
                    </td>
                    <td className="px-3 py-2.5 font-mono text-xs text-red">
                      {formatNumber(pick.stop_loss)}
                    </td>
                    <td className="px-3 py-2.5 font-mono text-xs text-green">
                      {formatNumber(pick.target)}
                    </td>
                    <td className="px-3 py-2.5 font-mono text-xs text-ink text-right">
                      {pick.qty}
                    </td>
                    <td className="px-3 py-2.5 font-mono text-xs text-right font-semibold text-accent">
                      {(pick.net_rr ?? 0).toFixed(2)}
                    </td>
                  </tr>
                  {expanded && (
                    <ExpandedRow
                      key={`${pick.symbol}-expanded`}
                      pick={pick}
                      weights={weights}
                    />
                  )}
                </>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function PicksTable({
  topPicks,
  stretchPicks,
  weights,
  advisory,
  recommendedPickCount,
}: PicksTableProps) {
  const [sortKey, setSortKey] = useState<SortKey>("score");
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const [expandedRows, setExpandedRows] = useState<Set<string>>(new Set());

  const handleSort = (key: SortKey) => {
    if (key === sortKey) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("desc");
    }
  };

  const toggleRow = (symbol: string) => {
    setExpandedRows((prev) => {
      const next = new Set(prev);
      if (next.has(symbol)) next.delete(symbol);
      else next.add(symbol);
      return next;
    });
  };

  return (
    <div className="bg-card border border-line rounded-xl p-5">
      <div className="flex items-center justify-between mb-2">
        <h2 className="text-xs font-semibold text-mute uppercase tracking-wider">
          Picks
        </h2>
        <span className="text-[10px] text-mute">
          {topPicks.length + stretchPicks.length} total
        </span>
      </div>

      {advisory && (
        <div className="mb-4 p-3 rounded-lg bg-yellow-500/10 border border-yellow-500/30">
          <p className="text-[10px] font-semibold text-yellow-400 uppercase tracking-wider mb-1.5">
            Advisory
          </p>
          <ul className="space-y-1">
            {(Array.isArray(advisory) ? advisory : [advisory]).map((line, i) => (
              <li key={i} className="text-xs text-mute leading-relaxed">
                {line}
              </li>
            ))}
          </ul>
        </div>
      )}

      <PicksSection
        title={`Top Picks (${topPicks.length})`}
        picks={topPicks}
        weights={weights}
        sortKey={sortKey}
        sortDir={sortDir}
        onSort={handleSort}
        expandedRows={expandedRows}
        toggleRow={toggleRow}
      />

      {stretchPicks.length > 0 && (
        <PicksSection
          title={`Stretch Picks (${stretchPicks.length})`}
          picks={stretchPicks}
          weights={weights}
          sortKey={sortKey}
          sortDir={sortDir}
          onSort={handleSort}
          expandedRows={expandedRows}
          toggleRow={toggleRow}
        />
      )}
    </div>
  );
}
