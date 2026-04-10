// ---------------------------------------------------------------------------
// NSE Market Intelligence - Core TypeScript interfaces
// ---------------------------------------------------------------------------

export interface Pick {
  symbol: string;
  name?: string;
  price: number;
  prev_close?: number;
  day_high?: number;
  day_low?: number;
  day_change_pct?: number;
  entry_zone: string;
  entry?: number;
  stop_loss: number;
  target: number;
  qty: number;
  capital_needed: number;
  fits_budget: boolean;
  score: number;
  strategy: string;
  bias?: "LONG" | "SHORT";
  rsi: number | null;
  stoch_k: number;
  bb_position: number;
  gap_pct: number;
  atr_pct: number;
  vol_ratio: number;
  ret5d_pct: number;
  ret20d_pct: number;
  near_20d_high: boolean;
  news_catalyst: string | null;
  sentiment_score: number;
  cost_roundtrip: number;
  net_profit: number;
  net_loss: number;
  net_rr: number;
  source: string;
  notes?: string[];
}

export interface PicksResponse {
  generated_at: string;
  data_as_of: string;
  trade_for: string;
  universe_size: number;
  scored: number;
  skipped: number;
  weights: Record<string, number>;
  news_count: number;
  top_picks: Pick[];
  stretch_picks: Pick[];
  disclaimer: string;
}

export interface ScoreBreakdown {
  trend: number;
  momentum: number;
  volume: number;
  breakout: number;
  volatility: number;
  liquidity: number;
  news: number;
  stoch?: number;
  bbands?: number;
  gap?: number;
  sentiment?: number;
}

export interface CostAnalysis {
  brokerage: number;
  stt: number;
  exchange_txn: number;
  gst: number;
  sebi: number;
  stamp: number;
  total_roundtrip: number;
}

export type ExitUrgency = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
export type ExitAction = "HOLD" | "PARTIAL_BOOK" | "TRAIL" | "SELL_NOW";

export interface ExitSignal {
  action: ExitAction;
  urgency: ExitUrgency;
  reason: string;
  suggested_exit_price?: number;
}

export interface Trade {
  id: string;
  symbol: string;
  bias: "LONG" | "SHORT";
  entry_price: number;
  current_price: number;
  qty: number;
  stop_loss: number;
  target: number;
  pnl: number;
  pnl_pct: number;
  entry_time: string;
  holding_duration: string;
  exit_signal?: ExitSignal;
  status: "OPEN" | "CLOSED" | "PARTIAL";
}

export interface TradeHistory {
  id: string;
  symbol: string;
  bias: "LONG" | "SHORT";
  entry_price: number;
  exit_price: number;
  qty: number;
  pnl: number;
  pnl_pct: number;
  entry_time: string;
  exit_time: string;
  setup: string;
  result: "WIN" | "LOSS" | "BREAKEVEN";
}

export type RegimeLabel =
  | "RISK_ON"
  | "RISK_OFF"
  | "TRENDING_UP"
  | "TRENDING_DOWN"
  | "RANGE_BOUND"
  | "HIGH_VOL"
  | "EXHAUSTION";

export interface RegimeState {
  label: RegimeLabel;
  description: string;
  nifty_close: number;
  nifty_change_pct: number;
  sensex_close: number;
  sensex_change_pct: number;
  vix: number;
  vix_change_pct: number;
  advance_decline_ratio: number;
  breadth_pct: number;
  sector_leaders: string[];
  sector_laggards: string[];
  scoring_modifier: number;
  reasoning: string;
  timestamp: string;
}

export interface NewsItem {
  symbol: string;
  headline: string;
  source: string;
  count: number;
  sentiment: number;
  published_at?: string;
  url?: string;
}

export interface NewsResponse {
  fetched_at: string;
  items: NewsItem[];
}

export interface PerformanceData {
  total_trades: number;
  win_rate: number;
  avg_profit: number;
  avg_loss: number;
  profit_factor: number;
  sharpe_ratio: number;
  max_drawdown: number;
  total_pnl: number;
  win_rate_by_setup: Record<string, number>;
  avg_rr_achieved: number;
  best_trade: TradeHistory | null;
  worst_trade: TradeHistory | null;
  daily_pnl: Array<{ date: string; pnl: number; cumulative: number }>;
}

export interface FeatureWeight {
  name: string;
  weight: number;
}

export interface PortfolioRisk {
  capital_total: number;
  capital_used: number;
  capital_utilization_pct: number;
  open_positions: number;
  max_positions: number;
  sector_exposure: Record<string, number>;
  portfolio_heat_pct: number;
  risk_per_trade: number;
  max_daily_loss: number;
}

export interface OverviewData {
  regime: RegimeState;
  picks: PicksResponse;
  active_trades: Trade[];
  portfolio_risk: PortfolioRisk;
  recent_news: NewsItem[];
}

export interface Settings {
  capital: number;
  risk_per_trade: number;
  max_positions: number;
  preferred_setups: string[];
  min_score: number;
  auto_refresh_interval: number;
  notifications_enabled: boolean;
  paper_trading: boolean;
}

// ---- Groww Cost Calculator ------------------------------------------------

export interface ChargeLineItem {
  label: string;
  buy_side: number;
  sell_side: number;
  total: number;
}

export interface CostCalcResult {
  buy_price: number;
  sell_price: number;
  quantity: number;
  instrument_type: string;
  buy_value: number;
  sell_value: number;
  brokerage: ChargeLineItem;
  stt: ChargeLineItem;
  exchange_txn: ChargeLineItem;
  gst: ChargeLineItem;
  sebi: ChargeLineItem;
  stamp: ChargeLineItem;
  dp_charge: ChargeLineItem;
  total_charges: number;
  gross_pnl: number;
  net_pnl: number;
  return_pct: number;
  breakeven_sell_price: number;
}

export interface WebSocketMessage {
  type:
    | "price_update"
    | "pick_update"
    | "regime_update"
    | "trade_update"
    | "news_update"
    | "exit_signal";
  data: unknown;
  timestamp: string;
}
