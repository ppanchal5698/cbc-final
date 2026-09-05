import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Emits a self-contained server under .next/standalone so the runtime image
  // carries neither the source tree nor the full node_modules.
  output: "standalone",
  // Bid-set PDFs routinely exceed 10 MB; match the API upload cap (200 MB default).
  experimental: {
    proxyClientMaxBodySize: "200mb",
  },
};

export default nextConfig;
