#!/usr/bin/env bash
# new-entry.sh — create a new changelog entry from the template.
#
# Usage:
#   bash scripts/new-entry.sh "30 open-data networks shipped" \
#       --scope networks --public
#   bash scripts/new-entry.sh "probe band-aid" --scope ops --private
#
# Flags:
#   --scope <name>       protocol | networks | skills | infra | ops | docs
#   --public | --private visibility (default: public)
#   --flagged            mark flagged: true in frontmatter
#   --no-edit            skip opening $EDITOR (useful for scripts/CI)

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

ALLOWED_SCOPES=(protocol networks skills infra ops docs motd)

title=""
scope=""
visibility="public"
flagged="false"
open_editor=1

usage() {
  sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'
  exit "${1:-1}"
}

die() { printf 'new-entry: %s\n' "$*" >&2; exit 1; }

while (($#)); do
  case "$1" in
    --scope) scope="${2:-}"; shift 2 ;;
    --public) visibility="public"; shift ;;
    --private) visibility="private"; shift ;;
    --flagged) flagged="true"; shift ;;
    --no-edit) open_editor=0; shift ;;
    -h|--help) usage 0 ;;
    --*) die "unknown flag: $1" ;;
    *) if [[ -z "$title" ]]; then title="$1"; else die "unexpected arg: $1"; fi; shift ;;
  esac
done

[[ -n "$title" ]] || die "title required (positional arg)"
[[ -n "$scope" ]] || die "--scope required"

ok=0
for s in "${ALLOWED_SCOPES[@]}"; do [[ "$s" == "$scope" ]] && ok=1; done
((ok)) || die "scope must be one of: ${ALLOWED_SCOPES[*]}"

date_str="$(date -u +%Y-%m-%d)"

# Slug: lowercase, replace non-alnum with -, collapse repeats, trim ends, cap at 60.
slug="$(printf '%s' "$title" \
  | tr '[:upper:]' '[:lower:]' \
  | LC_ALL=C sed -E 's/[^a-z0-9]+/-/g; s/^-+//; s/-+$//' \
  | cut -c1-60)"
[[ -n "$slug" ]] || die "could not derive slug from title: $title"

if [[ "$visibility" == "private" ]]; then
  out_dir="$ROOT_DIR/private"
else
  out_dir="$ROOT_DIR/entries"
fi
mkdir -p "$out_dir"

out_path="$out_dir/${date_str}-${slug}.md"
[[ -e "$out_path" ]] && die "entry already exists: $out_path"

template="$ROOT_DIR/templates/entry.md"
[[ -f "$template" ]] || die "missing template: $template"

# Escape title for sed replacement (& and / are special).
title_escaped="$(printf '%s' "$title" | sed -e 's/[\/&]/\\&/g')"

sed \
  -e "s/{{DATE}}/${date_str}/" \
  -e "s/{{SCOPE}}/${scope}/" \
  -e "s/{{VISIBILITY}}/${visibility}/" \
  -e "s/{{TITLE}}/${title_escaped}/" \
  "$template" > "$out_path"

if [[ "$flagged" == "true" ]]; then
  # macOS-friendly in-place sed.
  sed -i.bak 's/^flagged: false$/flagged: true/' "$out_path" && rm -f "${out_path}.bak"
fi

printf 'created %s\n' "$out_path"

if (( open_editor )); then
  "${EDITOR:-vi}" "$out_path"
fi
