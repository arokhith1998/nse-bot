"use client";

import {
  TrendingUp,
  TrendingDown,
  Clock,
  AlertTriangle,
  CheckCircle,
  XCircle,
} from "lucide-react";
import { formatCurrency, formatPct, EXIT_ACTION_CONFIG, EXIT_URGENCY_COLOR } from "@/lib/constants";
import type { Trade } from "@/lib/types";

interface TradeCardProps {
  trade: Trade;
}

export default function TradeCard({ trade }: TradeCardProps) {
  const isProfitable = trade.pnl >= 0;
  const exitCfg = trade.exit_signal
    ? EXIT_ACTION_CONFIG[trade.exit_signal.action]
    : null;
  const urgencyColor = trade.exit_signal
    ? EXIT_URGENCY_COLOR[trade.exit_signal.urgency]
    : "";

  return (
    <div className="bg-card border border-line rounded-xl p-4 hover:border-accent/20 transition-colors">
      {/* Header Row */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-ink">
            {trade.symbol}
          </span>
          <span
            className={`inline-flex items-center gap-1 text-[10px] font-bold px-1.5 py-0.5 rounded ${
              trade.bias === "LONG"
                ? "text-green bg-green/10"
                : "text-red bg-red/10"
            }`}
          >
            {trade.bias === "LONG" ? (
              <TrendingUp className="w-2.5 h-2.5" />
            ) : (
              <TrendingDown className="w-2.5 h-2.5" />
            )}
            {trade.bias}
          </span>
          {trade.status === "PARTIAL" && (
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-yellow/10 text-yellow border border-yellow/20">
              Partial
            </span>
          )}
        </div>

        {/* Exit Signal Badge */}
        {exitCfg && trade.exit_signal && (
          <div
            className={`flex items-center gap-1.5 px-2 py-1 rounded-lg text-xs font-semibold ${exitCfg.bg} ${exitCfg.color} ${urgencyColor}`}
          >
            {trade.exit_signal.action === "SELL_NOW" ? (
              <XCircle className="w-3.5 h-3.5" />
            ) : trade.exit_signal.action === "HOLD" ? (
              <CheckCircle className="w-3.5 h-3.5" />
            ) : (
              <AlertTriangle className="w-3.5 h-3.5" />
            )}
            {exitCfg.label}
          </div>
        )}
      </div>

      {/* Price Grid */}
      <div className="grid grid-cols-3 gap-3 mb-3">
        <div>
          <span className="text-[10px] text-mute uppercase tracking-wider">
            Entry
          </span>
          <div className="font-mono text-sm text-ink">
            {formatCurrency(trade.entry_price)}
          </div>
        </div>
        <div>
          <span className="text-[10px] text-mute uppercase tracking-wider">
            Current
          </span>
          <div className="font-mono text-sm text-ink">
            {formatCurrency(trade.current_price)}
          </div>
        </div>
        <div>
          <span className="text-[10px] text-mute uppercase tracking-wider">
            P&L
          </span>
          <div
            className={`font-mono text-sm font-semibold ${isProfitable ? "text-green" : "text-red"}`}
          >
            {formatCurrency(trade.pnl)}
          </div>
          <span
            className={`text-[10px] font-mono ${isProfitable ? "text-green" : "text-red"}`}
          >
            {formatPct(trade.pnl_pct)}
          </span>
        </div>
      </div>

      {/* SL / Target bar */}
      <div className="mb-3">
        <div className="flex justify-between text-[10px] text-mute mb-1">
          <span>SL: {formatCurrency(trade.stop_loss)}</span>
          <span>T: {formatCurrency(trade.target)}</span>
        </div>
        <div className="relative h-1.5 bg-bg rounded-full overflow-hidden">
          {(() => {
            const range = trade.target - trade.stop_loss;
            if (range <= 0) return null;
            const pct = Math.max(
              0,
              Math.min(
                100,
                ((trade.current_price - trade.stop_loss) / range) * 100,
              ),
            );
            return (
              <div
                className={`h-full rounded-full transition-all ${isProfitable ? "bg-green" : "bg-red"}`}
                style={{ width: `${pct}%` }}
              />
            );
          })()}
        </div>
      </div>

      {/* Footer */}
      <div className="flex items-center justify-between text-xs text-mute">
        <div className="flex items-center gap-1.5">
          <Clock className="w-3 h-3" />
          <span>{trade.holding_duration}</span>
        </div>
        <span className="font-mono">Qty: {trade.qty}</span>
      </div>

      {/* Exit Reason */}
      {trade.exit_signal?.reason && (
        <div className="mt-2 pt-2 border-t border-line">
          <p className="text-[11px] text-mute/80 leading-relaxed">
            {trade.exit_signal.reason}
          </p>
        </div>
      )}
    </div>
  );
}
