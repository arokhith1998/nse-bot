"use client";

import { useState } from "react";
import { calculateGrowwCost } from "@/lib/api";
import type { CostCalcResult, ChargeLineItem } from "@/lib/types";
import { Calculator, TrendingUp, TrendingDown, Minus } from "lucide-react";

function ChargeRow({ item }: { item: ChargeLineItem }) {
  return (
    <tr className="border-b border-line/30 text-xs">
      <td className="py-1.5 text-mute">{item.label}</td>
      <td className="py-1.5 text-right tabular-nums">
        {item.buy_side > 0 ? `₹${item.buy_side.toFixed(2)}` : "-"}
      </td>
      <td className="py-1.5 text-right tabular-nums">
        {item.sell_side > 0 ? `₹${item.sell_side.toFixed(2)}` : "-"}
      </td>
      <td className="py-1.5 text-right tabular-nums font-medium">
        ₹{item.total.toFixed(2)}
      </td>
    </tr>
  );
}

export default function GrowwCalculator() {
  const [instrumentType, setInstrumentType] = useState<"stock" | "etf">(
    "stock"
  );
  const [buyPrice, setBuyPrice] = useState("");
  const [sellPrice, setSellPrice] = useState("");
  const [quantity, setQuantity] = useState("");
  const [result, setResult] = useState<CostCalcResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const canCalculate =
    buyPrice && sellPrice && quantity && Number(quantity) > 0;

  async function handleCalculate() {
    if (!canCalculate) return;
    setLoading(true);
    setError("");
    try {
      const res = await calculateGrowwCost({
        instrument_type: instrumentType,
        buy_price: Number(buyPrice),
        sell_price: Number(sellPrice),
        quantity: Number(quantity),
      });
      setResult(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Calculation failed");
      setResult(null);
    } finally {
      setLoading(false);
    }
  }

  function handleReset() {
    setBuyPrice("");
    setSellPrice("");
    setQuantity("");
    setResult(null);
    setError("");
  }

  const pnlColor = result
    ? result.net_pnl > 0
      ? "text-green"
      : result.net_pnl < 0
        ? "text-red"
        : "text-mute"
    : "";

  const PnlIcon = result
    ? result.net_pnl > 0
      ? TrendingUp
      : result.net_pnl < 0
        ? TrendingDown
        : Minus
    : Minus;

  return (
    <div className="bg-card border border-line rounded-xl overflow-hidden">
      {/* Header */}
      <div className="px-4 py-3 border-b border-line flex items-center gap-2">
        <Calculator className="w-4 h-4 text-accent" />
        <h3 className="text-sm font-semibold text-ink">
          Groww Brokerage Calculator
        </h3>
        <span className="text-[10px] text-mute ml-auto">
          Equity Intraday (MIS)
        </span>
      </div>

      <div className="p-4 space-y-4">
        {/* Inputs */}
        <div className="grid grid-cols-2 gap-3">
          {/* Instrument Type */}
          <div className="col-span-2">
            <label className="text-[10px] text-mute uppercase tracking-wider mb-1 block">
              Instrument
            </label>
            <div className="flex gap-2">
              <button
                onClick={() => setInstrumentType("stock")}
                className={`flex-1 py-1.5 text-xs rounded-lg border transition-colors ${
                  instrumentType === "stock"
                    ? "bg-accent/10 border-accent/40 text-accent"
                    : "bg-card-alt border-line text-mute hover:text-ink"
                }`}
              >
                Stock
              </button>
              <button
                onClick={() => setInstrumentType("etf")}
                className={`flex-1 py-1.5 text-xs rounded-lg border transition-colors ${
                  instrumentType === "etf"
                    ? "bg-accent/10 border-accent/40 text-accent"
                    : "bg-card-alt border-line text-mute hover:text-ink"
                }`}
              >
                ETF
              </button>
            </div>
          </div>

          {/* Buy Price */}
          <div>
            <label className="text-[10px] text-mute uppercase tracking-wider mb-1 block">
              Buy Price (₹)
            </label>
            <input
              type="number"
              step="0.05"
              min="0"
              value={buyPrice}
              onChange={(e) => setBuyPrice(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleCalculate()}
              placeholder="e.g. 983.25"
              className="w-full bg-bg border border-line rounded-lg px-3 py-2 text-sm text-ink placeholder:text-mute/40 focus:outline-none focus:border-accent/50 tabular-nums"
            />
          </div>

          {/* Sell Price */}
          <div>
            <label className="text-[10px] text-mute uppercase tracking-wider mb-1 block">
              Sell Price (₹)
            </label>
            <input
              type="number"
              step="0.05"
              min="0"
              value={sellPrice}
              onChange={(e) => setSellPrice(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleCalculate()}
              placeholder="e.g. 1015.00"
              className="w-full bg-bg border border-line rounded-lg px-3 py-2 text-sm text-ink placeholder:text-mute/40 focus:outline-none focus:border-accent/50 tabular-nums"
            />
          </div>

          {/* Quantity */}
          <div className="col-span-2">
            <label className="text-[10px] text-mute uppercase tracking-wider mb-1 block">
              Quantity
            </label>
            <input
              type="number"
              step="1"
              min="1"
              value={quantity}
              onChange={(e) => setQuantity(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleCalculate()}
              placeholder="e.g. 10"
              className="w-full bg-bg border border-line rounded-lg px-3 py-2 text-sm text-ink placeholder:text-mute/40 focus:outline-none focus:border-accent/50 tabular-nums"
            />
          </div>
        </div>

        {/* Buttons */}
        <div className="flex gap-2">
          <button
            onClick={handleCalculate}
            disabled={!canCalculate || loading}
            className="flex-1 py-2 text-sm font-medium bg-accent/90 text-bg rounded-lg hover:bg-accent transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {loading ? "Calculating..." : "Calculate"}
          </button>
          <button
            onClick={handleReset}
            className="px-4 py-2 text-sm text-mute border border-line rounded-lg hover:text-ink hover:border-accent/30 transition-colors"
          >
            Reset
          </button>
        </div>

        {error && (
          <p className="text-xs text-red bg-red/5 border border-red/20 rounded-lg p-2">
            {error}
          </p>
        )}

        {/* Results */}
        {result && (
          <div className="space-y-3 pt-1">
            {/* Net P&L Hero */}
            <div
              className={`rounded-xl p-4 text-center ${
                result.net_pnl > 0
                  ? "bg-green/5 border border-green/20"
                  : result.net_pnl < 0
                    ? "bg-red/5 border border-red/20"
                    : "bg-card-alt border border-line"
              }`}
            >
              <div className="text-[10px] text-mute uppercase tracking-wider mb-1">
                Net Profit / Loss
              </div>
              <div className={`text-2xl font-bold tabular-nums ${pnlColor}`}>
                <PnlIcon className="w-5 h-5 inline mr-1 -mt-1" />
                ₹{Math.abs(result.net_pnl).toFixed(2)}
              </div>
              <div className={`text-xs mt-1 ${pnlColor}`}>
                {result.return_pct >= 0 ? "+" : ""}
                {result.return_pct.toFixed(2)}% return on invested
              </div>
            </div>

            {/* Summary Row */}
            <div className="grid grid-cols-3 gap-2 text-center">
              <div className="bg-card-alt rounded-lg p-2">
                <div className="text-[10px] text-mute">Buy Value</div>
                <div className="text-xs font-medium tabular-nums">
                  ₹{result.buy_value.toLocaleString("en-IN")}
                </div>
              </div>
              <div className="bg-card-alt rounded-lg p-2">
                <div className="text-[10px] text-mute">Sell Value</div>
                <div className="text-xs font-medium tabular-nums">
                  ₹{result.sell_value.toLocaleString("en-IN")}
                </div>
              </div>
              <div className="bg-card-alt rounded-lg p-2">
                <div className="text-[10px] text-mute">Total Charges</div>
                <div className="text-xs font-medium text-yellow tabular-nums">
                  ₹{result.total_charges.toFixed(2)}
                </div>
              </div>
            </div>

            {/* Charge Breakdown Table */}
            <div>
              <div className="text-[10px] text-mute uppercase tracking-wider mb-2">
                Charge Breakdown
              </div>
              <table className="w-full">
                <thead>
                  <tr className="border-b border-line text-[10px] text-mute uppercase">
                    <th className="py-1 text-left">Charge</th>
                    <th className="py-1 text-right">Buy</th>
                    <th className="py-1 text-right">Sell</th>
                    <th className="py-1 text-right">Total</th>
                  </tr>
                </thead>
                <tbody>
                  <ChargeRow item={result.brokerage} />
                  <ChargeRow item={result.stt} />
                  <ChargeRow item={result.exchange_txn} />
                  <ChargeRow item={result.gst} />
                  <ChargeRow item={result.sebi} />
                  <ChargeRow item={result.stamp} />
                  <ChargeRow item={result.dp_charge} />
                </tbody>
                <tfoot>
                  <tr className="text-xs font-semibold">
                    <td className="pt-2">Total</td>
                    <td className="pt-2 text-right" colSpan={2}></td>
                    <td className="pt-2 text-right text-yellow tabular-nums">
                      ₹{result.total_charges.toFixed(2)}
                    </td>
                  </tr>
                </tfoot>
              </table>
            </div>

            {/* Breakeven */}
            <div className="bg-card-alt rounded-lg p-3 flex items-center justify-between">
              <span className="text-xs text-mute">
                Breakeven sell price (to cover all charges)
              </span>
              <span className="text-sm font-semibold text-accent tabular-nums">
                ₹{result.breakeven_sell_price.toFixed(2)}
              </span>
            </div>

            {/* Gross vs Net */}
            <div className="grid grid-cols-2 gap-2 text-xs">
              <div className="bg-card-alt rounded-lg p-2 flex justify-between">
                <span className="text-mute">Gross P&L</span>
                <span
                  className={`font-medium tabular-nums ${result.gross_pnl >= 0 ? "text-green" : "text-red"}`}
                >
                  {result.gross_pnl >= 0 ? "+" : ""}₹
                  {result.gross_pnl.toFixed(2)}
                </span>
              </div>
              <div className="bg-card-alt rounded-lg p-2 flex justify-between">
                <span className="text-mute">Charges eat</span>
                <span className="font-medium text-yellow tabular-nums">
                  {result.gross_pnl > 0
                    ? `${((result.total_charges / result.gross_pnl) * 100).toFixed(1)}%`
                    : "N/A"}
                </span>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
