"use client";

import { useState, useMemo } from "react";
import { Newspaper, TrendingUp, TrendingDown, Minus, Search } from "lucide-react";
import type { NewsItem } from "@/lib/types";

interface NewsPanelProps {
  news: NewsItem[];
  loading?: boolean;
}

function SentimentBadge({ sentiment }: { sentiment: number }) {
  if (sentiment > 0) {
    return (
      <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-semibold bg-green/10 text-green border border-green/20">
        <TrendingUp className="w-2.5 h-2.5" />
        +{sentiment.toFixed(1)}
      </span>
    );
  }
  if (sentiment < 0) {
    return (
      <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-semibold bg-red/10 text-red border border-red/20">
        <TrendingDown className="w-2.5 h-2.5" />
        {sentiment.toFixed(1)}
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-semibold bg-mute/10 text-mute border border-mute/20">
      <Minus className="w-2.5 h-2.5" />
      Neutral
    </span>
  );
}

function ImpactBar({ sentiment }: { sentiment: number }) {
  const abs = Math.min(Math.abs(sentiment), 3);
  const pct = (abs / 3) * 100;
  const color = sentiment > 0 ? "bg-green" : sentiment < 0 ? "bg-red" : "bg-mute";

  return (
    <div className="w-16 h-1.5 bg-bg rounded-full overflow-hidden">
      <div
        className={`h-full rounded-full ${color}`}
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}

export default function NewsPanel({ news, loading = false }: NewsPanelProps) {
  const [filter, setFilter] = useState("");

  const filtered = useMemo(() => {
    if (!filter) return news;
    const q = filter.toUpperCase();
    return news.filter(
      (item) =>
        (item.symbol ?? "").includes(q) ||
        (item.headline ?? "").toLowerCase().includes(filter.toLowerCase()),
    );
  }, [news, filter]);

  if (loading) {
    return (
      <div className="bg-card border border-line rounded-xl p-5 animate-pulse">
        <div className="h-4 w-32 bg-line rounded mb-4" />
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="h-12 bg-card-alt rounded-lg mb-2" />
        ))}
      </div>
    );
  }

  return (
    <div className="bg-card border border-line rounded-xl p-5">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Newspaper className="w-4 h-4 text-mute" />
          <h2 className="text-xs font-semibold text-mute uppercase tracking-wider">
            News & Catalysts
          </h2>
          <span className="text-[10px] text-mute/60">{news.length} items</span>
        </div>

        {/* Filter */}
        <div className="relative">
          <Search className="absolute left-2 top-1/2 -translate-y-1/2 w-3 h-3 text-mute" />
          <input
            type="text"
            placeholder="Filter by symbol..."
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            className="pl-6 pr-3 py-1 text-xs bg-card-alt border border-line rounded-lg text-ink placeholder-mute/40 focus:outline-none focus:border-accent/40 w-36"
          />
        </div>
      </div>

      <div className="space-y-1.5 max-h-80 overflow-y-auto scrollbar-thin">
        {filtered.length === 0 && (
          <p className="text-xs text-mute/60 py-4 text-center">
            No news items found
          </p>
        )}
        {filtered.map((item, i) => (
          <div
            key={`${item.symbol}-${i}`}
            className="flex items-start gap-3 p-2.5 rounded-lg hover:bg-white/[0.02] transition-colors"
          >
            {/* Symbol tag */}
            <span className="shrink-0 px-2 py-0.5 text-[10px] rounded bg-blue/10 text-blue border border-blue/20 font-semibold">
              {item.symbol}
            </span>

            {/* Content */}
            <div className="flex-1 min-w-0">
              <p className="text-xs text-ink/90 leading-relaxed line-clamp-2">
                {(item.headline ?? "").replace(/<[^>]*>/g, "").substring(0, 200)}
              </p>
              <div className="flex items-center gap-2 mt-1">
                <span className="text-[10px] text-mute">{item.source}</span>
                {item.count > 1 && (
                  <span className="text-[10px] text-mute/60">
                    x{item.count} mentions
                  </span>
                )}
              </div>
            </div>

            {/* Sentiment + Impact */}
            <div className="flex flex-col items-end gap-1 shrink-0">
              <SentimentBadge sentiment={item.sentiment} />
              <ImpactBar sentiment={item.sentiment} />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
