// ---------------------------------------------------------------------------
// NSE Market Intelligence - Typed API client
// ---------------------------------------------------------------------------

import type {
  PicksResponse,
  Trade,
  TradeHistory,
  RegimeState,
  PerformanceData,
  NewsResponse,
  OverviewData,
  PortfolioRisk,
  Settings,
} from "./types";

const BASE = process.env.NEXT_PUBLIC_API_URL
  ? `${process.env.NEXT_PUBLIC_API_URL}/api`
  : "/api";

async function fetchJSON<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    throw new Error(`API ${res.status}: ${res.statusText} — ${path}`);
  }
  return res.json() as Promise<T>;
}

// ---- Picks ----------------------------------------------------------------

export function fetchPicks(): Promise<PicksResponse> {
  return fetchJSON<PicksResponse>("/picks");
}

export function fetchPicksHistory(
  days?: number,
): Promise<{ snapshots: PicksResponse[] }> {
  const q = days ? `?days=${days}` : "";
  return fetchJSON(`/picks/history${q}`);
}

// ---- Trades ---------------------------------------------------------------

export function fetchActiveTrades(): Promise<Trade[]> {
  return fetchJSON<Trade[]>("/trades/active");
}

export function fetchTradeHistory(params?: {
  from?: string;
  to?: string;
  symbol?: string;
  setup?: string;
  result?: string;
  limit?: number;
}): Promise<TradeHistory[]> {
  const q = new URLSearchParams();
  if (params) {
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined) q.set(k, String(v));
    });
  }
  const qs = q.toString();
  return fetchJSON<TradeHistory[]>(`/trades/history${qs ? `?${qs}` : ""}`);
}

// ---- Regime ---------------------------------------------------------------

export function fetchRegime(): Promise<RegimeState> {
  return fetchJSON<RegimeState>("/regime");
}

export function fetchRegimeHistory(
  days?: number,
): Promise<{ history: RegimeState[] }> {
  const q = days ? `?days=${days}` : "";
  return fetchJSON(`/regime/history${q}`);
}

// ---- Performance ----------------------------------------------------------

export function fetchPerformance(): Promise<PerformanceData> {
  return fetchJSON<PerformanceData>("/performance");
}

// ---- News -----------------------------------------------------------------

export function fetchNews(symbol?: string): Promise<NewsResponse> {
  const q = symbol ? `?symbol=${symbol}` : "";
  return fetchJSON<NewsResponse>(`/news${q}`);
}

// ---- Portfolio Risk -------------------------------------------------------

export function fetchPortfolioRisk(): Promise<PortfolioRisk> {
  return fetchJSON<PortfolioRisk>("/portfolio/risk");
}

// ---- Overview (composite) -------------------------------------------------

export function fetchOverview(): Promise<OverviewData> {
  return fetchJSON<OverviewData>("/overview");
}

// ---- Settings -------------------------------------------------------------

export function fetchSettings(): Promise<Settings> {
  return fetchJSON<Settings>("/settings");
}

export function updateSettings(
  patch: Partial<Settings>,
): Promise<Settings> {
  return fetchJSON<Settings>("/settings", {
    method: "PUT",
    body: JSON.stringify(patch),
  });
}

// ---- ETF Picks ------------------------------------------------------------

import type { ETFPicksResponse, SimulatorResult, SimulatorSymbol } from "./types";

export function fetchETFPicks(): Promise<ETFPicksResponse> {
  return fetchJSON<ETFPicksResponse>("/etf-picks");
}

// ---- Simulator ------------------------------------------------------------

export function fetchSimulatorSymbols(
  type: "stock" | "etf" | "all" = "all",
): Promise<{ symbols: SimulatorSymbol[]; count: number }> {
  return fetchJSON(`/simulator/symbols?type=${type}`);
}

export function simulateTrade(params: {
  symbol: string;
  capital: number;
  instrument_type: string;
}): Promise<SimulatorResult> {
  return fetchJSON<SimulatorResult>("/simulator/simulate", {
    method: "POST",
    body: JSON.stringify(params),
  });
}

// ---- Groww Cost Calculator ------------------------------------------------

import type { CostCalcResult } from "./types";

export function calculateGrowwCost(params: {
  instrument_type: string;
  buy_price: number;
  sell_price: number;
  quantity: number;
}): Promise<CostCalcResult> {
  return fetchJSON<CostCalcResult>("/calculator/groww", {
    method: "POST",
    body: JSON.stringify(params),
  });
}
