#!/usr/bin/env bash
# clear-motd.sh — remove a message-of-the-day banner, then re-render.
#
# Usage:
#   scripts/clear-motd.sh             # clear today's (UTC) banner
#   scripts/clear-motd.sh 2026-07-01  # clear a specific UTC day
#   scripts/clear-motd.sh --all       # remove every motd entry
#
# Re-renders feed-motd.json. The daemon self-clears the banner within one poll
# interval once today's motd entry is gone. Does not commit.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

ARG="${1:-$(date -u +%Y-%m-%d)}"
if [[ "$ARG" == "--all" ]]; then
  rm -f "$ROOT_DIR"/entries/*-motd-*.md
  echo "removed all motd entries"
elif [[ "$ARG" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
  rm -f "$ROOT_DIR/entries/${ARG}-motd-"*.md
  echo "removed motd entries for $ARG"
else
  echo "clear-motd: argument must be YYYY-MM-DD or --all (got: $ARG)" >&2
  exit 2
fi

python3 "$ROOT_DIR/scripts/render.py" >/dev/null
echo "rendered feed-motd.json — review the diff, then: git add -A && git commit && git push"
