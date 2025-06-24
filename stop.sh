#!/usr/bin/env bash
#
# stop.sh by Rudrashis Gorai
#  - Reads .client.pid, .server.pid, .chrome.pid (if they exist) and kills the processes.
#

set -e

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Helper function: kill a process if its .pid file exists
kill_pidfile() {
  local pidfile="$1"
  if [ -f "$pidfile" ]; then
    local pid
    pid=$(<"$pidfile")
    if ps -p "$pid" > /dev/null 2>&1; then
      echo "🛑 Killing PID $pid"
      kill -9 "$pid" || echo "⚠️  Failed to kill $pid"
    else
      echo "⚠️  PID $pid not running"
    fi
    rm -f "$pidfile"
  fi
}

echo "🛑 Stopping Chrome…"
kill_pidfile "$PROJECT_DIR/.chrome.pid"

echo "🛑 Stopping Python server…"
kill_pidfile "$PROJECT_DIR/.server.pid"

echo "🛑 Stopping http-server (client)…"
kill_pidfile "$PROJECT_DIR/.client.pid"

echo "✅  All processes have been stopped."
