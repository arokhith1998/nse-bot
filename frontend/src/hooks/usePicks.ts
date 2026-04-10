"use client";

import { useState, useEffect, useCallback } from "react";
import type { PicksResponse, WebSocketMessage } from "@/lib/types";
import { fetchPicks } from "@/lib/api";
import { useWebSocket } from "./useWebSocket";

interface UsePicksReturn {
  picks: PicksResponse | null;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  lastUpdated: Date | null;
  isConnected: boolean;
}

export function usePicks(autoRefreshMs = 60_000): UsePicksReturn {
  const [picks, setPicks] = useState<PicksResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  const { subscribe, isConnected } = useWebSocket();

  const refresh = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await fetchPicks();
      setPicks(data);
      setLastUpdated(new Date());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch picks");
    } finally {
      setLoading(false);
    }
  }, []);

  // Initial fetch
  useEffect(() => {
    refresh();
  }, [refresh]);

  // Auto-refresh on interval
  useEffect(() => {
    if (autoRefreshMs <= 0) return;
    const timer = setInterval(refresh, autoRefreshMs);
    return () => clearInterval(timer);
  }, [autoRefreshMs, refresh]);

  // WebSocket updates
  useEffect(() => {
    const unsub = subscribe("pick_update", (msg: WebSocketMessage) => {
      const data = msg.data as PicksResponse;
      if (data?.top_picks) {
        setPicks(data);
        setLastUpdated(new Date());
      }
    });
    return unsub;
  }, [subscribe]);

  return { picks, loading, error, refresh, lastUpdated, isConnected };
}
