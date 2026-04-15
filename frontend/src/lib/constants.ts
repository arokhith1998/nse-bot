// ---------------------------------------------------------------------------
// NSE Market Intelligence - Constants
// ---------------------------------------------------------------------------

import type { RegimeLabel, ExitAction, ExitUrgency } from "./types";

// -- Colors -----------------------------------------------------------------

export const COLORS = {
  bg: "#0b1220",
  card: "#131c30",
  cardAlt: "#0c1424",
  accent: "#22d3ee",
  green: "#22c55e",
  red: "#ef4444",
  yellow: "#eab308",
  blue: "#3b82f6",
  mute: "#94a3b8",
  ink: "#e8eefc",
  line: "#1f2a44",
} as const;

export const SCORE_COLORS = {
  high: { bg: "bg-green/20", text: "text-green", border: "border-green/30" },
  medium: {
    bg: "bg-yellow/20",
    text: "text-yellow",
    border: "border-yellow/30",
  },
  low: { bg: "bg-mute/10", text: "text-mute", border: "border-mute/20" },
} as const;

export function scoreColor(score: number) {
  if (score >= 70) return SCORE_COLORS.high;
  if (score >= 55) return SCORE_COLORS.medium;
  return SCORE_COLORS.low;
}

// -- Regime labels ----------------------------------------------------------

export const REGIME_CONFIG: Record<
  RegimeLabel,
  { label: string; color: string; bg: string }
> = {
  RISK_ON: { label: "Risk On", color: "text-green", bg: "bg-green/15" },
  RISK_OFF: { label: "Risk Off", color: "text-red", bg: "bg-red/15" },
  TRENDING_UP: {
    label: "Trending Up",
    color: "text-green",
    bg: "bg-green/15",
  },
  TRENDING_DOWN: {
    label: "Trending Down",
    color: "text-red",
    bg: "bg-red/15",
  },
  RANGE_BOUND: {
    label: "Range Bound",
    color: "text-yellow",
    bg: "bg-yellow/15",
  },
  HIGH_VOL: {
    label: "High Volatility",
    color: "text-red",
    bg: "bg-red/15",
  },
  EXHAUSTION: {
    label: "Exhaustion",
    color: "text-yellow",
    bg: "bg-yellow/15",
  },
  UNKNOWN: {
    label: "Data Pending",
    color: "text-mute",
    bg: "bg-mute/15",
  },
};

// -- Exit action config -----------------------------------------------------

export const EXIT_ACTION_CONFIG: Record<
  ExitAction,
  { label: string; color: string; bg: string }
> = {
  HOLD: { label: "Hold", color: "text-mute", bg: "bg-mute/10" },
  PARTIAL_BOOK: {
    label: "Partial Book",
    color: "text-yellow",
    bg: "bg-yellow/15",
  },
  TRAIL: { label: "Trail Stop", color: "text-accent", bg: "bg-accent/15" },
  SELL_NOW: { label: "Sell Now", color: "text-red", bg: "bg-red/15" },
};

export const EXIT_URGENCY_COLOR: Record<ExitUrgency, string> = {
  LOW: "text-mute",
  MEDIUM: "text-yellow",
  HIGH: "text-red",
  CRITICAL: "text-red animate-pulse",
};

// -- Time zones -------------------------------------------------------------

export const IST_TIMEZONE = "Asia/Kolkata";
export const IST_LOCALE = "en-IN";

export function formatIST(date: Date | string): string {
  const d = typeof date === "string" ? new Date(date) : date;
  return d.toLocaleString(IST_LOCALE, { timeZone: IST_TIMEZONE });
}

export function formatISTTime(date: Date | string): string {
  const d = typeof date === "string" ? new Date(date) : date;
  return d.toLocaleTimeString(IST_LOCALE, {
    timeZone: IST_TIMEZONE,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

// -- Market hours -----------------------------------------------------------

export function isMarketOpen(): boolean {
  const now = new Date();
  const ist = new Date(
    now.toLocaleString("en-US", { timeZone: IST_TIMEZONE }),
  );
  const day = ist.getDay();
  if (day === 0 || day === 6) return false;
  const h = ist.getHours();
  const m = ist.getMinutes();
  const minutes = h * 60 + m;
  // Pre-market 9:00, market 9:15-15:30
  return minutes >= 555 && minutes <= 930;
}

// -- Strategy labels --------------------------------------------------------

export const SETUP_LABELS: Record<string, string> = {
  BREAKOUT: "Breakout",
  MOMENTUM: "Momentum",
  "GAP-AND-GO": "Gap & Go",
  "SWING-INTRADAY": "Swing Intraday",
  "MEAN-REVERSION": "Mean Reversion",
  "PULLBACK-ENTRY": "Pullback Entry",
};

// -- Number formatting ------------------------------------------------------

export function formatCurrency(n: number): string {
  return new Intl.NumberFormat(IST_LOCALE, {
    style: "currency",
    currency: "INR",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(n);
}

export function formatPct(n: number, decimals = 2): string {
  const sign = n > 0 ? "+" : "";
  return `${sign}${n.toFixed(decimals)}%`;
}

export function formatNumber(n: number, decimals = 2): string {
  return n.toFixed(decimals);
}
