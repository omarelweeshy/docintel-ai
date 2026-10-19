import type { NextConfig } from "next";
// A Vercel build without a public API URL is the browser-only portfolio demo (src/demo).
// Docker and local builds keep talking to the FastAPI backend unless this is set explicitly.
const demoMode =
  process.env.NEXT_PUBLIC_DEMO_MODE ??
  (process.env.VERCEL && !process.env.NEXT_PUBLIC_API_URL ? "1" : "0");
const config: NextConfig = {
  output: "standalone",
  env: { NEXT_PUBLIC_DEMO_MODE: demoMode },
  poweredByHeader: false,
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "no-referrer" },
          { key: "X-Frame-Options", value: "DENY" },
        ],
      },
    ];
  },
};
export default config;
