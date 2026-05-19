/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  // In production nginx handles /api/ and /auth/ proxying.
  // In local development these rewrites forward to ira-api directly.
  async rewrites() {
    if (process.env.NODE_ENV !== "development") return [];
    const api = process.env.IRA_API_INTERNAL_URL || "http://localhost:8000";
    return [
      { source: "/api/:path*",  destination: `${api}/api/:path*` },
      { source: "/auth/:path*", destination: `${api}/auth/:path*` },
      { source: "/health",      destination: `${api}/health` },
    ];
  },
};

module.exports = nextConfig;
