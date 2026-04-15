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
import type { Pick, PreMarketWatchlistItem } from "@/lib/types";
import { AlertTriangle, Link2 } from "lucide-react";

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
  preMarketWatchlist?: PreMarketWatchlistItem[];
  candidatesScanned?: number;
  vetoBreakdown?: Record<string, number>;
  correlatedPairs?: string[][];
}

// M14: Risk badges derived from pick data
function RiskBadges({ pick }: { pick: Pick }) {
  const badges: { label: string; color: string }[] = [];
  if ((pick.atr_pct ?? 0) < 0.8)
    badges.push({ label: "Low Range", color: "text-amber-400 bg-amber-400/10 border-amber-400/30" });
  if ((pick.atr_pct ?? 0) > 4.5)
    badges.push({ label: "High Vol", color: "text-red bg-red/10 border-red/30" });
  if ((pick.vol_ratio ?? 0) > 5)
    badges.push({ label: "Vol Spike", color: "text-amber-400 bg-amber-400/10 border-amber-400/30" });
  if ((pick.gap_pct ?? 0) > 3)
    badges.push({ label: "Large Gap", color: "text-amber-400 bg-amber-400/10 border-amber-400/30" });
  if ((pick.gap_pct ?? 0) < -2)
    badges.push({ label: "Gap Down", color: "text-red bg-red/10 border-red/30" });
  if (badges.length === 0) return null;
  return (
    <>
      {badges.map((b) => (
        <span
          key={b.label}
          className={`inline-flex items-center gap-0.5 px-1 py-0.5 text-[9px] rounded border font-semibold ${b.color}`}
        >
          <AlertTriangle className="w-2.5 h-2.5" />
          {b.label}
        </span>
      ))}
    </>
  );
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

          {/* M16: Decision surface — price position gauge */}
          <div>
            <div className="flex items-center gap-1.5 mb-2">
              <Target className="w-3 h-3 text-mute" />
              <h4 className="text-[10px] text-mute uppercase tracking-wider font-semibold">
                Price Position
              </h4>
            </div>
            <div className="space-y-2 text-xs">
              {/* Stop ← Price → Target gauge */}
              {(() => {
                const entry = pick.entry ?? pick.price;
                const range = pick.target - pick.stop_loss;
                const pos = range > 0 ? ((pick.price - pick.stop_loss) / range) * 100 : 50;
                const clamped = Math.max(0, Math.min(100, pos));
                return (
                  <div>
                    <div className="flex justify-between text-[9px] text-mute mb-1">
                      <span>SL {pick.stop_loss.toFixed(0)}</span>
                      <span>Entry {entry.toFixed(0)}</span>
                      <span>Tgt {pick.target.toFixed(0)}</span>
                    </div>
                    <div className="relative h-2 bg-bg rounded-full overflow-hidden">
                      <div className="absolute left-0 top-0 h-full bg-gradient-to-r from-red/60 via-yellow/40 to-green/60 w-full" />
                      <div
                        className="absolute top-0 w-1.5 h-full bg-ink rounded-full border border-bg"
                        style={{ left: `${clamped}%`, transform: "translateX(-50%)" }}
                      />
                    </div>
                    <div className="flex justify-between mt-1">
                      <span className="text-mute">Risk: {((entry - pick.stop_loss) / (pick.atr_pct / 100 * pick.price || 1)).toFixed(1)} ATR</span>
                      <span className="text-mute">R:R {(pick.net_rr ?? 0).toFixed(2)}</span>
                    </div>
                  </div>
                );
              })()}
            </div>
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
  correlatedPairs,
}: {
  title: string;
  picks: Pick[];
  weights?: Record<string, number>;
  sortKey: SortKey;
  sortDir: SortDir;
  onSort: (key: SortKey) => void;
  expandedRows: Set<string>;
  toggleRow: (symbol: string) => void;
  correlatedPairs?: string[][];
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
                      <div className="flex items-center gap-2 flex-wrap">
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
                        {/* M14: Risk badges */}
                        <RiskBadges pick={pick} />
                        {/* M15: Correlation warning */}
                        {correlatedPairs?.some(pair => pair.includes(pick.symbol)) && (
                          <span className="inline-flex items-center gap-0.5 px-1 py-0.5 text-[9px] rounded border text-orange-400 bg-orange-400/10 border-orange-400/30 font-semibold">
                            <Link2 className="w-2.5 h-2.5" />
                            Corr: {correlatedPairs.find(pair => pair.includes(pick.symbol))?.filter(s => s !== pick.symbol)?.[0]}
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
  preMarketWatchlist,
  candidatesScanned,
  vetoBreakdown,
  correlatedPairs,
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

      {/* M6: Empty-state card when no picks */}
      {topPicks.length === 0 && stretchPicks.length === 0 && (
        <div className="p-6 rounded-lg bg-card-alt border border-line text-center space-y-3">
          <p className="text-sm font-semibold text-ink">
            No picks today
          </p>
          {candidatesScanned != null && candidatesScanned > 0 && (
            <p className="text-xs text-mute">
              {candidatesScanned} candidates scanned.
              {vetoBreakdown && Object.keys(vetoBreakdown).length > 0 && (
                <> Vetoed by:{" "}
                  {Object.entries(vetoBreakdown)
                    .filter(([, v]) => v > 0)
                    .map(([k, v]) => `${v} ${k.replace("_", " ")}`)
                    .join(" · ")}
                </>
              )}
            </p>
          )}
          <p className="text-xs text-mute/70">
            Recommendation: sit on hands today, or check the{" "}
            <a href="/etf" className="text-accent underline">ETF picks tab</a>.
          </p>
        </div>
      )}

      {/* M3: Pre-market watchlist */}
      {preMarketWatchlist && preMarketWatchlist.length > 0 && (
        <div className="mt-4">
          <div className="flex items-center gap-2 mb-2">
            <Clock className="w-3.5 h-3.5 text-yellow" />
            <h3 className="text-xs font-semibold text-yellow uppercase tracking-wider">
              Pre-market Watchlist — pending 09:15 confirmation
            </h3>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-line">
                  <th className="px-3 py-2 text-left text-[10px] text-mute uppercase">Symbol</th>
                  <th className="px-3 py-2 text-left text-[10px] text-mute uppercase">Score</th>
                  <th className="px-3 py-2 text-left text-[10px] text-mute uppercase">Strategy</th>
                  <th className="px-3 py-2 text-left text-[10px] text-mute uppercase">Entry Zone</th>
                  <th className="px-3 py-2 text-left text-[10px] text-mute uppercase">Stop</th>
                  <th className="px-3 py-2 text-left text-[10px] text-mute uppercase">Target</th>
                </tr>
              </thead>
              <tbody>
                {preMarketWatchlist.map((item) => (
                  <tr key={item.symbol} className="border-b border-line/30 opacity-70">
                    <td className="px-3 py-2 font-semibold text-ink">{item.symbol}</td>
                    <td className="px-3 py-2"><ScoreBadge score={item.score} /></td>
                    <td className="px-3 py-2">
                      <span className="px-1.5 py-0.5 text-[10px] rounded bg-card-alt border border-line text-mute">
                        {item.strategy}
                      </span>
                    </td>
                    <td className="px-3 py-2 font-mono text-ink">{item.entry_zone}</td>
                    <td className="px-3 py-2 font-mono text-red">{item.stop_loss.toFixed(2)}</td>
                    <td className="px-3 py-2 font-mono text-green">{item.target.toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
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
        correlatedPairs={correlatedPairs}
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
          correlatedPairs={correlatedPairs}
        />
      )}
    </div>
  );
}
