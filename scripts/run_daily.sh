#!/usr/bin/env bash
# Runs the daily Pikachu content pipeline and logs output.
set -euo pipefail

BASE_DIR="/home/yoda/wip/pikachu"
LOG_FILE="$BASE_DIR/logs/pikachu_daily.log"

{
  echo "=== $(date '+%Y-%m-%d %H:%M:%S') ==="
  "$BASE_DIR/.venv/bin/python3" "$BASE_DIR/scripts/pikachu_daily.py"
  echo
} >> "$LOG_FILE" 2>&1
