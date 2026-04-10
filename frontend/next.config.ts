import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async rewrites() {
    // Only proxy in local dev — in production the frontend calls Railway directly
    if (process.env.NEXT_PUBLIC_API_URL) {
      return [];
    }
    return [
      {
        source: "/api/:path*",
        destination: "http://localhost:8000/api/:path*",
      },
      {
        source: "/ws/:path*",
        destination: "http://localhost:8000/ws/:path*",
      },
    ];
  },
};

export default nextConfig;
