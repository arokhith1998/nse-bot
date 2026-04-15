"use client";

import { useState, useEffect, useCallback } from "react";
import RegimePanel from "@/components/RegimePanel";
import PicksTable from "@/components/PicksTable";
import TradeCard from "@/components/TradeCard";
import NewsPanel from "@/components/NewsPanel";
import RiskGauge from "@/components/RiskGauge";
import GrowwCalculator from "@/components/GrowwCalculator";
import { useRegime } from "@/hooks/useRegime";
import { usePicks } from "@/hooks/usePicks";
import { useTrades } from "@/hooks/useTrades";
import { fetchNews, fetchPortfolioRisk, updateSettings } from "@/lib/api";
import type { NewsItem, PortfolioRisk, FeatureWeight } from "@/lib/types";
import { RefreshCw, IndianRupee } from "lucide-react";
import { formatIST } from "@/lib/constants";

export default function DashboardPage() {
  const { regime, loading: regimeLoading } = useRegime();
  const {
    picks,
    loading: picksLoading,
    refresh: refreshPicks,
    lastUpdated,
  } = usePicks();
  const { trades, loading: tradesLoading } = useTrades();

  const [news, setNews] = useState<NewsItem[]>([]);
  const [newsLoading, setNewsLoading] = useState(true);
  const [risk, setRisk] = useState<PortfolioRisk | null>(null);
  const [riskLoading, setRiskLoading] = useState(true);

  // Capital input state
  const [capital, setCapital] = useState<number>(100000);
  const [capitalInput, setCapitalInput] = useState<string>("100000");
  const [capitalSaving, setCapitalSaving] = useState(false);

  useEffect(() => {
    fetchNews()
      .then((data) => setNews(Array.isArray(data?.items) ? data.items : []))
      .catch(() => setNews([]))
      .finally(() => setNewsLoading(false));

    fetchPortfolioRisk()
      .then(setRisk)
      .catch(() => setRisk(null))
      .finally(() => setRiskLoading(false));
  }, []);

  const handleCapitalSubmit = useCallback(async () => {
    const val = Number(capitalInput);
    if (isNaN(val) || val < 100) return;
    setCapitalSaving(true);
    try {
      await updateSettings({ capital: val });
      setCapital(val);
      // Refresh picks with new capital
      await refreshPicks();
    } catch {
      // silently fail — picks will still show with old capital
    } finally {
      setCapitalSaving(false);
    }
  }, [capitalInput, refreshPicks]);

  const featureWeights: FeatureWeight[] = picks?.weights
    ? Object.entries(picks.weights).map(([name, weight]) => ({ name, weight }))
    : [];

  // Review mode: after 15:15 IST, show review banner
  const [isReviewMode, setIsReviewMode] = useState(false);
  useEffect(() => {
    const checkTime = () => {
      const now = new Date();
      const ist = new Date(now.toLocaleString("en-US", { timeZone: "Asia/Kolkata" }));
      const hours = ist.getHours();
      const mins = ist.getMinutes();
      setIsReviewMode(hours > 15 || (hours === 15 && mins >= 15));
    };
    checkTime();
    const timer = setInterval(checkTime, 60_000);
    return () => clearInterval(timer);
  }, []);

  return (
    <>
      {/* Review Mode Banner (item 22) */}
      {isReviewMode && (
        <div className="bg-yellow/10 border border-yellow/30 rounded-xl p-4 flex items-center gap-3">
          <span className="text-yellow text-lg">&#9201;</span>
          <div>
            <p className="text-sm font-semibold text-yellow">Market Closed — Review Mode</p>
            <p className="text-xs text-mute">
              No new picks. Review today&apos;s outcomes. Fresh picks at 09:15 tomorrow.
            </p>
          </div>
        </div>
      )}

      {/* Capital Advisory (item 15) */}
      {picks?.advisory && (
        <div className="bg-yellow/10 border border-yellow/30 rounded-xl p-3 text-xs text-yellow/90">
          <strong>Advisory:</strong> {picks.advisory}
        </div>
      )}

      {/* Capital input bar */}
      <div className="bg-card border border-line rounded-xl p-4">
        <div className="flex flex-col sm:flex-row items-center gap-3 flex-wrap">
          <div className="flex items-center gap-2 shrink-0">
            <IndianRupee className="w-4 h-4 text-accent" />
            <label className="text-xs font-semibold text-mute uppercase tracking-wider whitespace-nowrap">
              Your Capital
            </label>
          </div>
          <div className="flex items-center gap-2">
            <div className="relative">
              <span className="absolute left-3 top-1/2 -translate-y-1/2 text-xs text-mute">
                INR
              </span>
              <input
                type="number"
                min={100}
                step={1000}
                value={capitalInput}
                onChange={(e) => setCapitalInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") handleCapitalSubmit();
                }}
                className="w-36 pl-10 pr-3 py-1.5 text-sm bg-bg border border-line rounded-lg text-ink focus:border-accent/50 focus:outline-none [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none"
              />
            </div>
            <button
              onClick={handleCapitalSubmit}
              disabled={capitalSaving || picksLoading}
              className="px-3 py-1.5 text-xs font-medium bg-accent/20 text-accent border border-accent/30 rounded-lg hover:bg-accent/30 transition-colors disabled:opacity-50 whitespace-nowrap"
            >
              {capitalSaving ? "Updating..." : "Update Picks"}
            </button>
          </div>
          <span className="text-[10px] text-mute/60 hidden sm:inline">
            Picks scale with capital: 3 for 1K | 5 for 5K | 8 for 50K | 12 for 2L+
          </span>
        </div>
      </div>

      {/* Top info bar */}
      <div className="flex items-center justify-between">
        <div className="text-xs text-mute">
          {picks && (
            <span>
              Candidates: {(picks.candidates_scanned ?? picks.universe_size).toLocaleString()} | Picks:{" "}
              {(picks.top_picks.length + picks.stretch_picks.length).toLocaleString()} | Trade for: {picks.trade_for}
            </span>
          )}
        </div>
        <div className="flex items-center gap-3">
          {lastUpdated && (
            <span className="text-[10px] text-mute/60">
              Updated {formatIST(lastUpdated)}
            </span>
          )}
          <button
            onClick={refreshPicks}
            disabled={picksLoading}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-card-alt border border-line rounded-lg text-mute hover:text-ink hover:border-accent/30 transition-colors disabled:opacity-50"
          >
            <RefreshCw
              className={`w-3 h-3 ${picksLoading ? "animate-spin" : ""}`}
            />
            Refresh
          </button>
        </div>
      </div>

      {/* Regime Panel */}
      <RegimePanel regime={regime} loading={regimeLoading} />

      {/* Picks Table */}
      <PicksTable
        topPicks={picks?.top_picks ?? []}
        stretchPicks={picks?.stretch_picks ?? []}
        weights={picks?.weights}
        advisory={picks?.advisory}
        recommendedPickCount={picks?.recommended_pick_count}
        preMarketWatchlist={picks?.pre_market_watchlist}
        candidatesScanned={picks?.candidates_scanned}
        vetoBreakdown={picks?.veto_breakdown}
        correlatedPairs={picks?.correlated_pairs}
      />

      {/* Main Grid: Trades + News | Risk */}
      <div className="grid grid-cols-12 gap-5">
        <div className="col-span-12 lg:col-span-8 space-y-5">
          {/* Active Trades */}
          <div>
            <h2 className="text-xs font-semibold text-mute uppercase tracking-wider mb-3">
              Active Trades ({trades.length})
            </h2>
            {tradesLoading ? (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                {Array.from({ length: 2 }).map((_, i) => (
                  <div
                    key={i}
                    className="h-40 bg-card border border-line rounded-xl animate-pulse"
                  />
                ))}
              </div>
            ) : trades.length === 0 ? (
              <div className="bg-card border border-line rounded-xl p-8 text-center">
                <p className="text-sm text-mute">No active trades</p>
                <p className="text-xs text-mute/50 mt-1">
                  Trades will appear here when positions are opened
                </p>
              </div>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                {trades.map((trade) => (
                  <TradeCard key={trade.id} trade={trade} />
                ))}
              </div>
            )}
          </div>

          {/* News */}
          <NewsPanel news={news} loading={newsLoading} />
        </div>

        {/* Risk Gauge + Calculator */}
        <div className="col-span-12 lg:col-span-4 space-y-5">
          <RiskGauge risk={risk} loading={riskLoading} />
          <GrowwCalculator />
        </div>
      </div>

      {/* Disclaimer */}
      <div className="bg-red/5 border border-red/20 rounded-xl p-4 text-xs text-red/80 leading-relaxed">
        <strong>PAPER TRADING ONLY -- NOT INVESTMENT ADVICE.</strong>{" "}
        {picks?.disclaimer ??
          "These picks are educational, generated by a rule-based scoring system. SEBI 2023: ~70% of retail intraday traders lose money."}
      </div>
    </>
  );
}
