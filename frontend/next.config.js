/** @type {import('next').NextConfig} */
// Divergence from gc-website, which uses `output: 'export'` to Cloudflare Pages.
// This app needs a server: it runs behind auth and talks to the API per request.
const nextConfig = {
  output: 'standalone',
  reactStrictMode: true,
}

module.exports = nextConfig
