/** @type {import('next').NextConfig} */
// Divergence from gc-website, which uses `output: 'export'` to Cloudflare Pages.
// This app needs a server: it runs behind auth and talks to the API per request.

// Where the Next server itself reaches the API (container to container).
// Only used in same-origin mode, i.e. NEXT_PUBLIC_API_URL=/ : the browser
// calls /api/v1/* on this server and it is forwarded here, so the whole app
// lives at one address (one tunnel, no CORS, cookies on a single host).
const API_INTERNAL_URL = (process.env.API_INTERNAL_URL || 'http://api:8000').replace(/\/$/, '')

const nextConfig = {
  output: 'standalone',
  reactStrictMode: true,
  async rewrites() {
    return [{ source: '/api/v1/:path*', destination: `${API_INTERNAL_URL}/api/v1/:path*` }]
  },
  experimental: {
    // The default 30s would cut off a prompt preview (three Claude calls).
    proxyTimeout: 5 * 60 * 1000,
    // CSV uploads go up to 25MB.
    proxyClientMaxBodySize: '30mb',
  },
}

module.exports = nextConfig
