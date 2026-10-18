#!/bin/bash
# Minecraft service entrypoint – called by the Onryo service manager.
# Uses docker compose to bring the stack up/down.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

case "${1:-up}" in
  up)   docker compose up -d ;;
  down) docker compose down  ;;
  *)    docker compose "$@"  ;;
esac
