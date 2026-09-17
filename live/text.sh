#!/bin/sh
# live-e-ink: paint one line of text on the Kindle (partial refresh, no flash).
# Usage: text.sh <col> <row> <text...>
# Rows/cols are eips character cells (~row 3 top margin, ~row 33 near bottom).
set -e
KINDLE="${KINDLE_HOST:?set KINDLE_HOST to the Kindle Tailscale IP or hostname}"
COL="$1"; ROW="$2"; shift 2 || { echo "usage: text.sh <col> <row> <text...>" >&2; exit 1; }
TEXT="$*"
# eips has no '--' end-of-options: leading '-' in text is parsed as an option.
case "$TEXT" in -*) TEXT=" $TEXT" ;; esac
ssh "root@${KINDLE}" "eips $COL $ROW \"$(printf '%s' "$TEXT" | sed 's/"/\\\\"/g')\"" 2>/dev/null
