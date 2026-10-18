#!/bin/bash
# example-script/run.sh
# Replace this with your actual script logic.
# Runs indefinitely (loop) to stay alive as a systemd service.
# For one-shot jobs, just exit 0 and set Type=oneshot in the generated unit.

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SETTINGS="${SCRIPT_DIR}/settings.yaml"

# Read a simple setting using grep (no yaml parser needed for basic scripts)
INTERVAL=$(grep '^interval:' "$SETTINGS" 2>/dev/null | awk '{print $2}' || echo 30)

echo "[example-script] Starting. Interval=${INTERVAL}s"

while true; do
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] example-script heartbeat"
  sleep "$INTERVAL"
done
