"use client";

import Header from "@/components/Header";
import Sidebar from "@/components/Sidebar";
import { useRegime } from "@/hooks/useRegime";
import { useWebSocket } from "@/hooks/useWebSocket";

export default function LayoutShell({
  children,
}: {
  children: React.ReactNode;
}) {
  const { regime } = useRegime();
  const { isConnected } = useWebSocket();

  const headerRegime = regime
    ? {
        label: regime.label,
        vix: regime.vix,
        nifty_close: regime.nifty_close,
        nifty_change_pct: regime.nifty_change_pct,
      }
    : null;

  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar />
      <div className="flex-1 flex flex-col overflow-hidden">
        <Header regime={headerRegime} isConnected={isConnected} />
        <main className="flex-1 overflow-y-auto p-5 space-y-5">
          {children}
        </main>
      </div>
    </div>
  );
}
