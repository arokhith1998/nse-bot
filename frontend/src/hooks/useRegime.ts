"use client";

import { useState, useEffect, useCallback } from "react";
import type { RegimeState, WebSocketMessage } from "@/lib/types";
import { fetchRegime } from "@/lib/api";
import { useWebSocket } from "./useWebSocket";

interface UseRegimeReturn {
  regime: RegimeState | null;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

export function useRegime(): UseRegimeReturn {
  const [regime, setRegime] = useState<RegimeState | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const { subscribe } = useWebSocket();

  const refresh = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await fetchRegime();
      setRegime(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch regime");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    const unsub = subscribe("regime_update", (msg: WebSocketMessage) => {
      const data = msg.data as RegimeState;
      if (data?.label) {
        setRegime(data);
      }
    });
    return unsub;
  }, [subscribe]);

  return { regime, loading, error, refresh };
}
