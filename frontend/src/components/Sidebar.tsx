"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  Gauge,
  ArrowLeftRight,
  BarChart2,
  Settings,
  ShieldAlert,
} from "lucide-react";

const NAV_ITEMS = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/regime", label: "Regime", icon: Gauge },
  { href: "/trades", label: "Trades", icon: ArrowLeftRight },
  { href: "/performance", label: "Performance", icon: BarChart2 },
  { href: "/settings", label: "Settings", icon: Settings },
] as const;

export default function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="w-56 h-full bg-card border-r border-line flex flex-col shrink-0">
      {/* Nav Links */}
      <nav className="flex-1 py-4 px-3 space-y-1">
        {NAV_ITEMS.map((item) => {
          const active =
            item.href === "/"
              ? pathname === "/"
              : pathname.startsWith(item.href);
          const Icon = item.icon;

          return (
            <Link
              key={item.href}
              href={item.href}
              className={`
                flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors
                ${
                  active
                    ? "bg-accent/10 text-accent font-medium"
                    : "text-mute hover:text-ink hover:bg-white/[0.03]"
                }
              `}
            >
              <Icon
                className={`w-4.5 h-4.5 ${active ? "text-accent" : "text-mute"}`}
              />
              <span>{item.label}</span>
              {active && (
                <span className="ml-auto w-1.5 h-1.5 rounded-full bg-accent" />
              )}
            </Link>
          );
        })}
      </nav>

      {/* Footer */}
      <div className="p-4 border-t border-line">
        <div className="flex items-center gap-2 text-xs text-mute">
          <ShieldAlert className="w-3.5 h-3.5 text-yellow" />
          <span>Paper Trading Only</span>
        </div>
        <p className="mt-1.5 text-[10px] text-mute/60 leading-tight">
          Not investment advice. SEBI: ~70% of intraday traders lose money.
        </p>
      </div>
    </aside>
  );
}
