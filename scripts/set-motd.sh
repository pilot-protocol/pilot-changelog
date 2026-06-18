#!/usr/bin/env bash
# set-motd.sh — post a message-of-the-day banner, then re-render.
#
# Usage:
#   scripts/set-motd.sh "Your message"             # active today (UTC)
#   scripts/set-motd.sh "Your message" 2026-07-01  # active on a specific UTC day
#
# A motd is just a changelog entry with scope=motd whose `date` is the UTC day
# the banner is active and whose `title` is the banner text shown verbatim by
# pilotctl. Replaces any existing motd entry for that date (one banner/day).
# Re-renders feed-motd.json (the daemon's source). Does not commit.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

MSG="${1:?usage: set-motd.sh \"message\" [YYYY-MM-DD]}"
DATE="${2:-$(date -u +%Y-%m-%d)}"
if ! [[ "$DATE" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
  echo "set-motd: date must be YYYY-MM-DD (got: $DATE)" >&2
  exit 2
fi

# One banner per day: drop any existing motd entry for that date.
rm -f "$ROOT_DIR/entries/${DATE}-motd-"*.md

slug="$(printf '%s' "$MSG" \
  | tr '[:upper:]' '[:lower:]' \
  | LC_ALL=C sed -E 's/[^a-z0-9]+/-/g; s/^-+//; s/-+$//' \
  | cut -c1-40)"
[[ -n "$slug" ]] || slug="banner"

out="$ROOT_DIR/entries/${DATE}-motd-${slug}.md"
printf -- '---\ndate: %s\nscope: motd\nvisibility: public\ntitle: %s\nflagged: false\nlinks: []\nids: []\n---\n\nMessage-of-the-day banner active on %s (UTC). The title above is shown verbatim by pilotctl.\n' \
  "$DATE" "$MSG" "$DATE" > "$out"
echo "wrote $out"

python3 "$ROOT_DIR/scripts/render.py" >/dev/null
echo "rendered feed-motd.json — review the diff, then: git add -A && git commit && git push"
