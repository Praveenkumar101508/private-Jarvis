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
  async headers() {
    return [
      {
        source: "/manifest.json",
        headers: [
          { key: "Content-Type", value: "application/manifest+json" },
          { key: "Cache-Control", value: "public, max-age=86400" },
        ],
      },
      {
        // Tell browsers this app can be installed (required for PWA prompt)
        source: "/(.*)",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "no-referrer" },
          { key: "X-Frame-Options", value: "DENY" },
          // CSP kept permissive enough that the Next.js PWA still loads: Next
          // injects inline hydration scripts and inline styles, and the service
          // worker needs blob: workers. connect-src 'self' covers the same-origin
          // /api and /auth calls (nginx proxies them in prod). nginx may also set
          // these headers at the edge in production.
          {
            key: "Content-Security-Policy",
            value: [
              "default-src 'self'",
              "script-src 'self' 'unsafe-inline' 'unsafe-eval'",
              "style-src 'self' 'unsafe-inline'",
              "img-src 'self' data: blob:",
              "font-src 'self' data:",
              "connect-src 'self'",
              "manifest-src 'self'",
              "worker-src 'self' blob:",
              "object-src 'none'",
              "base-uri 'self'",
              "frame-ancestors 'none'",
            ].join("; "),
          },
        ],
      },
    ];
  },
};

module.exports = nextConfig;
