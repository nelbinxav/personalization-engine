#!/bin/bash
# Supervisor for the LinkedIn browser service (the `linkedin` compose service).
#
# Normally it just runs the MCP server. When the app's Settings page asks to
# connect an account, the api container drops a `login-requested` file in the
# shared /control volume; this script then stops the server, runs the image's
# own login browser (reachable at 127.0.0.1:6080 on the host), publishes the
# sign-in link back through /control, and starts the server again afterwards.
# The LinkedIn password is typed into LinkedIn's own page in that browser; it
# never passes through the app.
CONTROL=/control
SERVER_ARGS=(--transport streamable-http --host 0.0.0.0 --port 8080 --path /mcp)

note() { echo "$1" > "$CONTROL/login-state" 2>/dev/null || true; }

# A browser that was killed (container stopped mid-sign-in) leaves Chromium's
# lock files behind, and the next start refuses the profile as "in use". Only
# called when nothing in this container is using the profile.
clear_stale_locks() { rm -f /home/pwuser/.linkedin-mcp/profile/Singleton* 2>/dev/null || true; }

run_login() {
  rm -f "$CONTROL/login-requested" "$CONTROL/login-url" 2>/dev/null
  clear_stale_locks
  note starting
  linkedin-mcp-entrypoint python -m linkedin_mcp_server --login --login-viewer 2>&1 |
    while IFS= read -r line; do
      echo "$line"
      case "$line" in
        http://127.0.0.1:6080*) echo "$line" > "$CONTROL/login-url"; note waiting ;;
      esac
    done
  local status=${PIPESTATUS[0]}
  rm -f "$CONTROL/login-url" 2>/dev/null
  if [ "$status" -eq 0 ]; then note signed-in; else note failed; fi
}

clear_stale_locks
child=""
trap '[ -n "$child" ] && kill -TERM "$child" 2>/dev/null; exit 143' TERM INT

while true; do
  if [ -f "$CONTROL/login-requested" ]; then
    run_login
    continue
  fi
  linkedin-mcp-entrypoint python -m linkedin_mcp_server "${SERVER_ARGS[@]}" &
  child=$!
  while kill -0 "$child" 2>/dev/null; do
    if [ -f "$CONTROL/login-requested" ]; then
      kill -TERM "$child" 2>/dev/null
      wait "$child" 2>/dev/null
      break
    fi
    sleep 2
  done
  child=""
  sleep 1
done
