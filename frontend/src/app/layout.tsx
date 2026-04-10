import type { Metadata } from "next";
import "./globals.css";
import LayoutShell from "./layout-shell";

export const metadata: Metadata = {
  title: "NSE Market Intelligence",
  description:
    "AI-powered paper trading intelligence platform for NSE equities",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark">
      <body className="bg-bg text-ink antialiased" suppressHydrationWarning>
        <LayoutShell>{children}</LayoutShell>
      </body>
    </html>
  );
}
