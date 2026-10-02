#!/usr/bin/env bash
# Keep the engine and its permanent Cloudflare link running on this Mac.
#
# Run by a LaunchAgent at login and restarted if it ever exits, so the link
# works whenever the Mac is on and signed in. It does three things, in order:
#   1. starts Docker (Colima) if it is not already running
#   2. starts the stack; containers that are already up are left alone
#   3. runs the Cloudflare tunnel described in ~/.cloudflared/config.yml,
#      holding the Mac awake while it runs
#
# Closing the lid still puts a MacBook to sleep unless it is on power with an
# external display; nothing a script does changes that.
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

if ! docker info >/dev/null 2>&1; then
  echo "$(date) starting Docker (Colima)"
  colima start
fi

# COMPOSE_PROFILES in .env decides whether the LinkedIn service comes up too.
docker compose up -d

echo "$(date) starting the tunnel"
# caffeinate -i: no idle sleep while the tunnel is up, on battery as well.
exec caffeinate -i cloudflared tunnel --no-autoupdate run
