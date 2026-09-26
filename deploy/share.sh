#!/usr/bin/env bash
# Share the app running on this machine through a temporary public HTTPS link.
#
#   deploy/share.sh
#
# Uses a Cloudflare Quick Tunnel: free, no account, no domain. The link
# (https://<random>.trycloudflare.com) is printed below and stays valid while
# this script runs. Ctrl+C stops sharing. A new run gives a new link.
#
# For testing only: it lasts as long as this machine is on, awake and running
# this script. Anyone with the link reaches the sign-in page, so give every
# tester their own account with a strong password:
#   docker compose exec api python scripts/create_operator.py name@bighammer.ai
set -euo pipefail
cd "$(dirname "$0")/.."

if ! grep -qx 'NEXT_PUBLIC_API_URL=/' .env; then
  echo "The frontend must call the API on its own address for a single link to work."
  echo "Set NEXT_PUBLIC_API_URL=/ in .env, then: docker compose up -d --build frontend"
  exit 1
fi

if ! curl -fsS -o /dev/null http://127.0.0.1:3000/login; then
  echo "The app is not running on this machine. Start it with: docker compose up -d"
  exit 1
fi

if ! command -v cloudflared >/dev/null; then
  echo "Installing cloudflared..."
  brew install cloudflared
fi

echo "Starting the tunnel. Your link is the https://....trycloudflare.com line below."
echo "Keep this window open (and the Mac awake and plugged in). Ctrl+C to stop."
echo

# caffeinate stops the Mac from idle-sleeping while the tunnel is up.
exec caffeinate -i cloudflared tunnel --no-autoupdate --url http://127.0.0.1:3000
