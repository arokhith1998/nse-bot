"use client";

import { useEffect, useRef, useCallback, useState } from "react";
import type { WebSocketMessage } from "@/lib/types";

type Subscriber = (msg: WebSocketMessage) => void;

interface UseWebSocketOptions {
  url?: string;
  reconnectInterval?: number;
  maxReconnectAttempts?: number;
}

interface UseWebSocketReturn {
  lastMessage: WebSocketMessage | null;
  isConnected: boolean;
  reconnectCount: number;
  subscribe: (type: WebSocketMessage["type"], cb: Subscriber) => () => void;
  send: (data: unknown) => void;
}

export function useWebSocket(
  options: UseWebSocketOptions = {},
): UseWebSocketReturn {
  const {
    url = process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8000/ws/live",
    reconnectInterval = 3000,
    maxReconnectAttempts = 20,
  } = options;

  const wsRef = useRef<WebSocket | null>(null);
  const subscribersRef = useRef<Map<string, Set<Subscriber>>>(new Map());
  const reconnectCountRef = useRef(0);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const [lastMessage, setLastMessage] = useState<WebSocketMessage | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [reconnectCount, setReconnectCount] = useState(0);

  const dispatch = useCallback((msg: WebSocketMessage) => {
    setLastMessage(msg);
    const subs = subscribersRef.current.get(msg.type);
    if (subs) {
      subs.forEach((cb) => {
        try {
          cb(msg);
        } catch (err) {
          console.error("[WS] subscriber error:", err);
        }
      });
    }
    // Also fire wildcard subscribers
    const wildcard = subscribersRef.current.get("*");
    if (wildcard) {
      wildcard.forEach((cb) => {
        try {
          cb(msg);
        } catch (err) {
          console.error("[WS] wildcard subscriber error:", err);
        }
      });
    }
  }, []);

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    try {
      const ws = new WebSocket(url);

      ws.onopen = () => {
        console.log("[WS] Connected to", url);
        setIsConnected(true);
        reconnectCountRef.current = 0;
        setReconnectCount(0);
      };

      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data) as WebSocketMessage;
          dispatch(msg);
        } catch {
          console.warn("[WS] Failed to parse message:", event.data);
        }
      };

      ws.onclose = (event) => {
        console.log("[WS] Disconnected:", event.code, event.reason);
        setIsConnected(false);
        wsRef.current = null;

        if (reconnectCountRef.current < maxReconnectAttempts) {
          const delay =
            reconnectInterval *
            Math.min(Math.pow(1.5, reconnectCountRef.current), 10);
          console.log(
            `[WS] Reconnecting in ${Math.round(delay)}ms (attempt ${reconnectCountRef.current + 1})`,
          );
          reconnectTimerRef.current = setTimeout(() => {
            reconnectCountRef.current += 1;
            setReconnectCount(reconnectCountRef.current);
            connect();
          }, delay);
        }
      };

      ws.onerror = () => {
        // Suppress – onclose handles reconnect logic
      };

      wsRef.current = ws;
    } catch (err) {
      console.error("[WS] Connection failed:", err);
    }
  }, [url, reconnectInterval, maxReconnectAttempts, dispatch]);

  useEffect(() => {
    connect();

    return () => {
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current);
      }
      if (wsRef.current) {
        wsRef.current.close(1000, "Component unmounted");
        wsRef.current = null;
      }
    };
  }, [connect]);

  const subscribe = useCallback(
    (type: WebSocketMessage["type"] | "*", cb: Subscriber) => {
      const key = type as string;
      if (!subscribersRef.current.has(key)) {
        subscribersRef.current.set(key, new Set());
      }
      subscribersRef.current.get(key)!.add(cb);

      return () => {
        subscribersRef.current.get(key)?.delete(cb);
      };
    },
    [],
  );

  const send = useCallback((data: unknown) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(data));
    } else {
      console.warn("[WS] Cannot send, not connected");
    }
  }, []);

  return { lastMessage, isConnected, reconnectCount, subscribe, send };
}
