import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Self-contained server bundle for the Docker image (Vercel manages its own output).
  ...(process.env.VERCEL ? {} : { output: "standalone" as const }),
};

export default nextConfig;
