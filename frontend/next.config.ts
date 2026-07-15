import type { NextConfig } from "next";

const apiProxyTarget = (process.env.API_PROXY_TARGET || "http://127.0.0.1:5061").replace(/\/$/, "");
const publicApiUrl = process.env.NEXT_PUBLIC_API_URL || "/api/v1";
let apiOrigin = "'self'";
try {
  apiOrigin = new URL(publicApiUrl).origin;
} catch {
  // URL relativa usa a propria origem.
}

const contentSecurityPolicy = [
  "default-src 'self'",
  "base-uri 'self'",
  "frame-ancestors 'none'",
  "form-action 'self'",
  "object-src 'none'",
  "img-src 'self' data: blob:",
  "font-src 'self' data:",
  "style-src 'self' 'unsafe-inline'",
  // Next.js em exportacao estatica injeta bootstrap inline; nonce exige middleware dinamico.
  "script-src 'self' 'unsafe-inline'",
  `connect-src 'self' ${apiOrigin}`,
].join("; ");

const nextConfig: NextConfig = {
  async headers() {
    return [{
      source: "/:path*",
      headers: [
        { key: "Content-Security-Policy", value: contentSecurityPolicy },
        { key: "Referrer-Policy", value: "no-referrer" },
        { key: "X-Content-Type-Options", value: "nosniff" },
        { key: "X-Frame-Options", value: "DENY" },
      ],
    }];
  },
  async rewrites() {
    return [
      {
        source: "/api/v1/:path*",
        destination: `${apiProxyTarget}/api/v1/:path*`,
      },
    ];
  },
};

export default nextConfig;
