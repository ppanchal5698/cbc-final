import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Emits a self-contained server under .next/standalone so the runtime image
  // carries neither the source tree nor the full node_modules.
  output: "standalone",
  // Bid-set PDFs routinely exceed 10 MB; match the API upload cap (200 MB default).
  experimental: {
    proxyClientMaxBodySize: "200mb",
  },
  // These were Settings tabs before they became pages of their own; old links and
  // bookmarks still land.
  async redirects() {
    return [
      { source: "/settings/pricing", destination: "/pricing", permanent: true },
      { source: "/settings/reference", destination: "/reference-data", permanent: true },
      { source: "/settings/users", destination: "/users", permanent: true },
    ];
  },
};

export default nextConfig;
