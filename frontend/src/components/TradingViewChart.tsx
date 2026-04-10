"use client";

import { useState, useRef, useEffect } from "react";
import { Search, Maximize2, Minimize2 } from "lucide-react";

interface TradingViewChartProps {
  defaultSymbol?: string;
  height?: number;
}

const POPULAR_SYMBOLS = [
  "NSE:NIFTY",
  "NSE:BANKNIFTY",
  "NSE:RELIANCE",
  "NSE:TCS",
  "NSE:HDFCBANK",
  "NSE:INFY",
  "NSE:ICICIBANK",
  "NSE:SBIN",
];

export default function TradingViewChart({
  defaultSymbol = "NSE:NIFTY",
  height = 500,
}: TradingViewChartProps) {
  const [symbol, setSymbol] = useState(defaultSymbol);
  const [inputValue, setInputValue] = useState(defaultSymbol);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const handleSymbolChange = () => {
    const formatted = inputValue.toUpperCase();
    const s = formatted.includes(":") ? formatted : `NSE:${formatted}`;
    setSymbol(s);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") {
      handleSymbolChange();
    }
  };

  const toggleFullscreen = () => {
    setIsFullscreen((prev) => !prev);
  };

  // Build TradingView widget URL
  const widgetUrl = `https://s.tradingview.com/widgetembed/?frameElementId=tradingview_widget&symbol=${encodeURIComponent(symbol)}&interval=D&hidesidetoolbar=0&symboledit=1&saveimage=1&toolbarbg=0b1220&studies=[]&theme=dark&style=1&timezone=Asia%2FKolkata&withdateranges=1&showpopupbutton=0&studies_overrides={}&overrides={}&enabled_features=[]&disabled_features=[]&showVolume=true&locale=en&utm_source=localhost&utm_medium=widget_new&utm_campaign=chart`;

  return (
    <div
      ref={containerRef}
      className={`bg-card border border-line rounded-xl overflow-hidden ${
        isFullscreen
          ? "fixed inset-0 z-50 rounded-none border-0"
          : ""
      }`}
    >
      {/* Toolbar */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-line bg-card">
        <div className="flex items-center gap-3">
          {/* Symbol Input */}
          <div className="relative">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-mute" />
            <input
              type="text"
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              onKeyDown={handleKeyDown}
              onBlur={handleSymbolChange}
              placeholder="Symbol (e.g. NSE:RELIANCE)"
              className="pl-8 pr-3 py-1.5 text-xs bg-card-alt border border-line rounded-lg text-ink placeholder-mute/40 focus:outline-none focus:border-accent/40 w-52 font-mono"
            />
          </div>

          {/* Quick Symbols */}
          <div className="hidden md:flex items-center gap-1">
            {POPULAR_SYMBOLS.slice(0, 6).map((sym) => (
              <button
                key={sym}
                onClick={() => {
                  setSymbol(sym);
                  setInputValue(sym);
                }}
                className={`px-2 py-1 text-[10px] rounded transition-colors ${
                  symbol === sym
                    ? "bg-accent/15 text-accent border border-accent/30"
                    : "text-mute hover:text-ink hover:bg-white/[0.03] border border-transparent"
                }`}
              >
                {sym.replace("NSE:", "")}
              </button>
            ))}
          </div>
        </div>

        {/* Fullscreen Toggle */}
        <button
          onClick={toggleFullscreen}
          className="p-1.5 rounded-lg text-mute hover:text-ink hover:bg-white/[0.05] transition-colors"
          title={isFullscreen ? "Exit fullscreen" : "Fullscreen"}
        >
          {isFullscreen ? (
            <Minimize2 className="w-4 h-4" />
          ) : (
            <Maximize2 className="w-4 h-4" />
          )}
        </button>
      </div>

      {/* Chart iframe */}
      <div
        style={{ height: isFullscreen ? "calc(100vh - 48px)" : `${height}px` }}
      >
        <iframe
          key={symbol}
          src={widgetUrl}
          className="w-full h-full border-0"
          allow="autoplay; fullscreen"
          sandbox="allow-scripts allow-same-origin allow-popups"
          title={`TradingView Chart - ${symbol}`}
        />
      </div>
    </div>
  );
}
