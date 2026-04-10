"use client";

import { useState, useEffect, useCallback } from "react";
import type { Trade, WebSocketMessage } from "@/lib/types";
import { fetchActiveTrades } from "@/lib/api";
import { useWebSocket } from "./useWebSocket";

interface UseTradesReturn {
  trades: Trade[];
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

export function useTrades(autoRefreshMs = 30_000): UseTradesReturn {
  const [trades, setTrades] = useState<Trade[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const { subscribe } = useWebSocket();

  const refresh = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await fetchActiveTrades();
      setTrades(Array.isArray(data) ? data : []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch trades");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    if (autoRefreshMs <= 0) return;
    const timer = setInterval(refresh, autoRefreshMs);
    return () => clearInterval(timer);
  }, [autoRefreshMs, refresh]);

  useEffect(() => {
    const unsub = subscribe("trade_update", (msg: WebSocketMessage) => {
      const data = msg.data as Trade;
      if (data?.id) {
        setTrades((prev) => {
          const idx = prev.findIndex((t) => t.id === data.id);
          if (idx >= 0) {
            const copy = [...prev];
            copy[idx] = data;
            return copy;
          }
          return [data, ...prev];
        });
      }
    });
    return unsub;
  }, [subscribe]);

  return { trades, loading, error, refresh };
}
