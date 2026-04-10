"use client";

import { useState, useEffect } from "react";
import {
  Activity,
  Clock,
  TrendingUp,
  Wifi,
  WifiOff,
  BarChart3,
} from "lucide-react";
import { isMarketOpen, formatISTTime, REGIME_CONFIG } from "@/lib/constants";
import type { RegimeLabel } from "@/lib/types";

interface HeaderProps {
  regime?: {
    label: RegimeLabel;
    vix: number;
    nifty_close: number;
    nifty_change_pct: number;
  } | null;
  isConnected?: boolean;
}

export default function Header({ regime, isConnected = false }: HeaderProps) {
  const [time, setTime] = useState<string>("");
  const [marketOpen, setMarketOpen] = useState(false);

  useEffect(() => {
    const tick = () => {
      setTime(formatISTTime(new Date()));
      setMarketOpen(isMarketOpen());
    };
    tick();
    const timer = setInterval(tick, 1000);
    return () => clearInterval(timer);
  }, []);

  const regimeCfg = regime?.label
    ? REGIME_CONFIG[regime.label]
    : null;

  return (
    <header className="h-14 border-b border-line bg-card flex items-center justify-between px-5 shrink-0">
      {/* Left: Logo + Title */}
      <div className="flex items-center gap-3">
        <div className="w-8 h-8 rounded-lg bg-accent/15 flex items-center justify-center">
          <BarChart3 className="w-5 h-5 text-accent" />
        </div>
        <h1 className="text-base font-semibold text-ink tracking-tight">
          NSE Market Intelligence
        </h1>
      </div>

      {/* Right: Status Indicators */}
      <div className="flex items-center gap-4 text-sm">
        {/* Market Status */}
        <div className="flex items-center gap-1.5">
          <span
            className={`w-2 h-2 rounded-full ${marketOpen ? "bg-green animate-pulse-slow" : "bg-mute/50"}`}
          />
          <span className={marketOpen ? "text-green" : "text-mute"}>
            {marketOpen ? "Market Open" : "Market Closed"}
          </span>
        </div>

        {/* Regime Badge */}
        {regimeCfg && (
          <div
            className={`px-2.5 py-0.5 rounded-full text-xs font-medium ${regimeCfg.bg} ${regimeCfg.color}`}
          >
            {regimeCfg.label}
          </div>
        )}

        {/* Nifty */}
        {regime && (
          <div className="flex items-center gap-1.5 text-xs">
            <TrendingUp className="w-3.5 h-3.5 text-mute" />
            <span className="text-ink font-mono">
              {regime.nifty_close.toLocaleString("en-IN")}
            </span>
            <span
              className={
                regime.nifty_change_pct >= 0 ? "text-green" : "text-red"
              }
            >
              {regime.nifty_change_pct >= 0 ? "+" : ""}
              {regime.nifty_change_pct.toFixed(2)}%
            </span>
          </div>
        )}

        {/* VIX */}
        {regime && (
          <div className="flex items-center gap-1.5 text-xs">
            <Activity className="w-3.5 h-3.5 text-mute" />
            <span className="text-mute">VIX</span>
            <span
              className={`font-mono ${
                regime.vix > 20
                  ? "text-red"
                  : regime.vix > 15
                    ? "text-yellow"
                    : "text-green"
              }`}
            >
              {regime.vix.toFixed(1)}
            </span>
          </div>
        )}

        {/* WS Status */}
        <div className="flex items-center gap-1">
          {isConnected ? (
            <Wifi className="w-3.5 h-3.5 text-green" />
          ) : (
            <WifiOff className="w-3.5 h-3.5 text-mute" />
          )}
        </div>

        {/* IST Clock */}
        <div className="flex items-center gap-1.5 text-xs text-mute font-mono">
          <Clock className="w-3.5 h-3.5" />
          <span>{time}</span>
          <span className="text-[10px] opacity-60">IST</span>
        </div>
      </div>
    </header>
  );
}
