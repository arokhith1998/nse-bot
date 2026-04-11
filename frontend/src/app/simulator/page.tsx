"use client";

import { useState, useEffect, useCallback, useMemo } from "react";
import { fetchSimulatorSymbols, simulateTrade } from "@/lib/api";
import type { SimulatorSymbol, SimulatorResult } from "@/lib/types";
import {
  Calculator,
  IndianRupee,
  TrendingUp,
  TrendingDown,
  Search,
  Info,
  ArrowRight,
  RefreshCw,
} from "lucide-react";

function PnLCard({
  title,
  subtitle,
  grossPnl,
  charges,
  netPnl,
  pnlPct,
  value,
}: {
  title: string;
  subtitle: string;
  grossPnl: number;
  charges: number;
  netPnl: number;
  pnlPct: number;
  value: number;
}) {
  const isPositive = netPnl > 0;
  const color = isPositive ? "text-green-400" : netPnl < 0 ? "text-red-400" : "text-mute";
  const bgColor = isPositive
    ? "bg-green-400/5 border-green-400/20"
    : netPnl < 0
      ? "bg-red-400/5 border-red-400/20"
      : "bg-card border-line";

  return (
    <div className={`rounded-xl p-5 border ${bgColor}`}>
      <div className="flex items-center gap-2 mb-1">
        {isPositive ? (
          <TrendingUp className="w-4 h-4 text-green-400" />
        ) : (
          <TrendingDown className="w-4 h-4 text-red-400" />
        )}
        <h3 className="text-xs font-semibold text-ink">{title}</h3>
      </div>
      <p className="text-[10px] text-mute mb-4">{subtitle}</p>

      <div className={`text-2xl font-bold ${color} mb-1`}>
        {netPnl >= 0 ? "+" : ""}Rs {netPnl.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
      </div>
      <div className={`text-sm font-medium ${color} mb-4`}>
        {pnlPct >= 0 ? "+" : ""}{pnlPct.toFixed(2)}%
      </div>

      <div className="space-y-1.5 text-xs">
        <div className="flex justify-between">
          <span className="text-mute">Gross P&L</span>
          <span className={grossPnl >= 0 ? "text-green-400" : "text-red-400"}>
            {grossPnl >= 0 ? "+" : ""}Rs {grossPnl.toFixed(2)}
          </span>
        </div>
        <div className="flex justify-between">
          <span className="text-mute">Charges</span>
          <span className="text-red-400">-Rs {charges.toFixed(2)}</span>
        </div>
        <div className="flex justify-between border-t border-line/50 pt-1.5">
          <span className="text-mute font-medium">Exit Value</span>
          <span className="text-ink">Rs {value.toLocaleString(undefined, { minimumFractionDigits: 2 })}</span>
        </div>
      </div>
    </div>
  );
}

export default function SimulatorPage() {
  const [symbols, setSymbols] = useState<SimulatorSymbol[]>([]);
  const [filterType, setFilterType] = useState<"all" | "stock" | "etf">("all");
  const [search, setSearch] = useState("");
  const [selectedSymbol, setSelectedSymbol] = useState<SimulatorSymbol | null>(null);
  const [capital, setCapital] = useState("100000");
  const [result, setResult] = useState<SimulatorResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [symbolsLoading, setSymbolsLoading] = useState(true);
  const [dropdownOpen, setDropdownOpen] = useState(false);

  // Load symbols
  useEffect(() => {
    setSymbolsLoading(true);
    fetchSimulatorSymbols("all")
      .then((data) => setSymbols(data.symbols || []))
      .catch(() => setSymbols([]))
      .finally(() => setSymbolsLoading(false));
  }, []);

  // Filtered symbols
  const filtered = useMemo(() => {
    let list = symbols;
    if (filterType !== "all") {
      list = list.filter((s) => s.type === filterType);
    }
    if (search.trim()) {
      const q = search.trim().toLowerCase();
      list = list.filter(
        (s) =>
          s.symbol.toLowerCase().includes(q) ||
          s.name.toLowerCase().includes(q),
      );
    }
    return list.slice(0, 50); // limit dropdown size
  }, [symbols, filterType, search]);

  const handleSimulate = useCallback(async () => {
    if (!selectedSymbol) return;
    const cap = Number(capital);
    if (isNaN(cap) || cap < 100) return;

    setLoading(true);
    try {
      const res = await simulateTrade({
        symbol: selectedSymbol.symbol,
        capital: cap,
        instrument_type: selectedSymbol.type,
      });
      setResult(res);
    } catch {
      setResult(null);
    } finally {
      setLoading(false);
    }
  }, [selectedSymbol, capital]);

  return (
    <div className="space-y-5 max-w-4xl">
      {/* Header */}
      <div>
        <h1 className="text-lg font-semibold text-ink flex items-center gap-2">
          <Calculator className="w-5 h-5 text-accent" />
          Trade Simulator
        </h1>
        <p className="text-xs text-mute mt-0.5">
          What if you had invested yesterday? See your P&L at today&apos;s close and
          day high.
        </p>
      </div>

      {/* Input section */}
      <div className="bg-card border border-line rounded-xl p-5 space-y-4">
        {/* Filter toggle */}
        <div className="flex items-center gap-2">
          <span className="text-xs text-mute font-medium">Show:</span>
          {(["all", "stock", "etf"] as const).map((t) => (
            <button
              key={t}
              onClick={() => {
                setFilterType(t);
                setSelectedSymbol(null);
                setResult(null);
              }}
              className={`px-3 py-1 text-xs rounded-lg border transition-colors ${
                filterType === t
                  ? "bg-accent/20 text-accent border-accent/30"
                  : "bg-card-alt text-mute border-line hover:border-accent/20"
              }`}
            >
              {t === "all" ? "All" : t === "stock" ? "Stocks" : "ETFs"}
            </button>
          ))}
        </div>

        {/* Symbol selector */}
        <div className="relative">
          <div className="flex items-center gap-2">
            <Search className="w-4 h-4 text-mute" />
            <input
              type="text"
              placeholder={
                symbolsLoading
                  ? "Loading symbols..."
                  : "Search stock or ETF symbol..."
              }
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                setDropdownOpen(true);
              }}
              onFocus={() => setDropdownOpen(true)}
              className="flex-1 px-3 py-2 text-sm bg-bg border border-line rounded-lg text-ink placeholder:text-mute/50 focus:border-accent/50 focus:outline-none"
            />
          </div>

          {dropdownOpen && filtered.length > 0 && (
            <div className="absolute z-20 mt-1 w-full max-h-60 overflow-y-auto bg-card border border-line rounded-xl shadow-xl">
              {filtered.map((sym) => (
                <button
                  key={`${sym.type}-${sym.symbol}`}
                  onClick={() => {
                    setSelectedSymbol(sym);
                    setSearch(sym.symbol);
                    setDropdownOpen(false);
                    setResult(null);
                  }}
                  className="w-full flex items-center justify-between px-4 py-2.5 text-left hover:bg-white/[0.03] transition-colors border-b border-line/30 last:border-0"
                >
                  <div className="flex items-center gap-3">
                    <span className="text-sm font-medium text-ink">
                      {sym.symbol}
                    </span>
                    <span className="text-xs text-mute truncate max-w-[200px]">
                      {sym.name !== sym.symbol ? sym.name : ""}
                    </span>
                  </div>
                  <span
                    className={`text-[10px] px-1.5 py-0.5 rounded border ${
                      sym.type === "etf"
                        ? "text-purple-400 bg-purple-400/10 border-purple-400/20"
                        : "text-blue-400 bg-blue-400/10 border-blue-400/20"
                    }`}
                  >
                    {sym.type.toUpperCase()}
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Selected symbol badge */}
        {selectedSymbol && (
          <div className="flex items-center gap-2 text-xs">
            <span className="text-mute">Selected:</span>
            <span className="px-2 py-1 bg-accent/10 text-accent rounded-lg font-medium">
              {selectedSymbol.symbol}
            </span>
            <span className="text-mute/60">
              {selectedSymbol.name !== selectedSymbol.symbol
                ? selectedSymbol.name
                : ""}
            </span>
            <span
              className={`text-[10px] px-1.5 py-0.5 rounded border ${
                selectedSymbol.type === "etf"
                  ? "text-purple-400 bg-purple-400/10 border-purple-400/20"
                  : "text-blue-400 bg-blue-400/10 border-blue-400/20"
              }`}
            >
              {selectedSymbol.type.toUpperCase()}
            </span>
          </div>
        )}

        {/* Capital input + simulate button */}
        <div className="flex items-center gap-3">
          <div className="relative">
            <span className="absolute left-3 top-1/2 -translate-y-1/2 text-xs text-mute">
              <IndianRupee className="w-3.5 h-3.5" />
            </span>
            <input
              type="number"
              min={100}
              step={1000}
              value={capital}
              onChange={(e) => setCapital(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") handleSimulate();
              }}
              placeholder="Capital"
              className="w-40 pl-8 pr-3 py-2 text-sm bg-bg border border-line rounded-lg text-ink focus:border-accent/50 focus:outline-none [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none"
            />
          </div>
          <button
            onClick={handleSimulate}
            disabled={!selectedSymbol || loading}
            className="flex items-center gap-2 px-4 py-2 text-sm font-medium bg-accent/20 text-accent border border-accent/30 rounded-lg hover:bg-accent/30 transition-colors disabled:opacity-50"
          >
            {loading ? (
              <RefreshCw className="w-3.5 h-3.5 animate-spin" />
            ) : (
              <ArrowRight className="w-3.5 h-3.5" />
            )}
            {loading ? "Simulating..." : "Simulate"}
          </button>
        </div>
      </div>

      {/* Results */}
      {result && result.data_available && (
        <>
          {/* Trade summary */}
          <div className="bg-card border border-line rounded-xl p-5">
            <h2 className="text-xs font-semibold text-mute uppercase tracking-wider mb-4">
              Trade Summary
            </h2>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 text-xs">
              <div>
                <span className="text-mute/70 block text-[10px]">Entry (Prev Close)</span>
                <span className="text-ink font-medium text-sm">
                  Rs {result.entry_price.toFixed(2)}
                </span>
              </div>
              <div>
                <span className="text-mute/70 block text-[10px]">Quantity</span>
                <span className="text-ink font-medium text-sm">{result.qty}</span>
              </div>
              <div>
                <span className="text-mute/70 block text-[10px]">Invested</span>
                <span className="text-ink font-medium text-sm">
                  Rs {result.invested.toLocaleString()}
                </span>
              </div>
              <div>
                <span className="text-mute/70 block text-[10px]">Day Open</span>
                <span className="text-ink font-medium text-sm">
                  Rs {result.day_open.toFixed(2)}
                </span>
              </div>
            </div>

            {/* Price bar */}
            <div className="mt-4 pt-4 border-t border-line/50">
              <div className="flex justify-between text-[10px] text-mute mb-1">
                <span>Day Low: Rs {result.day_low.toFixed(2)}</span>
                <span>Day High: Rs {result.day_high.toFixed(2)}</span>
              </div>
              <div className="h-2 bg-white/5 rounded-full overflow-hidden relative">
                {/* Close position indicator */}
                {result.day_high > result.day_low && (
                  <div
                    className="absolute h-full bg-accent/40 rounded-full"
                    style={{
                      left: `${Math.max(0, ((result.day_close - result.day_low) / (result.day_high - result.day_low)) * 100 - 1)}%`,
                      width: "3px",
                    }}
                  />
                )}
                <div className="h-full bg-gradient-to-r from-red-400/30 via-yellow-400/30 to-green-400/30 rounded-full" />
              </div>
              <div className="text-center text-[10px] text-mute mt-1">
                Close: Rs {result.day_close.toFixed(2)}
              </div>
            </div>
          </div>

          {/* P&L Cards */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <PnLCard
              title="P&L at Day Close"
              subtitle="If you sold at closing price"
              grossPnl={result.close_pnl}
              charges={result.close_charges}
              netPnl={result.close_net_pnl}
              pnlPct={result.close_pnl_pct}
              value={result.close_value}
            />
            <PnLCard
              title="P&L at Day High"
              subtitle="Best case - if you sold at day's highest"
              grossPnl={result.high_pnl}
              charges={result.high_charges}
              netPnl={result.high_net_pnl}
              pnlPct={result.high_pnl_pct}
              value={result.high_value}
            />
          </div>

          {/* Notes */}
          {result.notes.length > 0 && (
            <div className="bg-card border border-line rounded-xl p-4">
              <h3 className="text-xs font-semibold text-mute uppercase tracking-wider mb-2">
                Analysis
              </h3>
              <ul className="space-y-1">
                {result.notes.map((note, i) => (
                  <li
                    key={i}
                    className="text-xs text-mute flex items-start gap-2"
                  >
                    <Info className="w-3 h-3 text-accent shrink-0 mt-0.5" />
                    {note}
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div className="text-[10px] text-mute/50 text-center">
            Volume: {result.volume.toLocaleString()} | Avg Volume:{" "}
            {result.avg_volume.toLocaleString()} | Charges include brokerage
            (Rs 20/side), STT, exchange fees, GST, SEBI, stamp duty
          </div>
        </>
      )}

      {/* No data */}
      {result && !result.data_available && (
        <div className="bg-card border border-line rounded-xl p-8 text-center">
          <p className="text-sm text-mute">No data available</p>
          <p className="text-xs text-mute/50 mt-1">
            {result.notes?.[0] || "Could not fetch price data for this symbol."}
          </p>
        </div>
      )}

      {/* Explanation */}
      {!result && (
        <div className="bg-card border border-line rounded-xl p-5">
          <h3 className="text-xs font-semibold text-mute uppercase tracking-wider mb-3">
            How It Works
          </h3>
          <div className="space-y-2 text-xs text-mute">
            <p>
              <strong className="text-ink">1.</strong> Select a stock or ETF from
              the dropdown above.
            </p>
            <p>
              <strong className="text-ink">2.</strong> Enter your available
              capital (how much you&apos;d invest).
            </p>
            <p>
              <strong className="text-ink">3.</strong> The simulator calculates:
              if you bought at <strong className="text-ink">yesterday&apos;s closing
              price</strong> with the maximum shares your capital allows...
            </p>
            <p className="pl-4">
              -- What would your <strong className="text-green-400">Net P&L</strong>{" "}
              be at today&apos;s close?
            </p>
            <p className="pl-4">
              -- What would your <strong className="text-green-400">Net P&L</strong>{" "}
              be if you sold at today&apos;s high?
            </p>
            <p className="text-mute/60 mt-2">
              All charges (brokerage, STT, exchange fees, GST, SEBI, stamp duty)
              are included in the Net P&L calculation.
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
