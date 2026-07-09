#!/usr/bin/env bash
# Daily sync: pull remote changes, then commit and push any local changes.
set -euo pipefail

REPO_DIR="/home/yoda/wip/pikachu"
LOG_FILE="$REPO_DIR/.daily-sync.log"

cd "$REPO_DIR"

{
  echo "=== $(date '+%Y-%m-%d %H:%M:%S') ==="

  git pull --rebase origin main

  git add -A

  if ! git diff --cached --quiet; then
    git commit -m "Daily sync: $(date '+%Y-%m-%d')"
    git push origin main
    echo "Pushed changes."
  else
    echo "Nothing to commit."
  fi

  echo
} >> "$LOG_FILE" 2>&1
