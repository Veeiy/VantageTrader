#!/usr/bin/env bash
# Background timer guard (P072, 2026-11-20; relative waits added 2026-11-23).
# Usage: timer.sh HH:MM "LABEL"   sleeps until HH:MM Pacific, then prints LABEL
#        timer.sh +9m "LABEL"     sleeps 9 minutes (also +540s), then prints LABEL
# Refuses a wait longer than 115 minutes, because the harness stops a background command at its
# 2 h timeout (the 10:30 PT timer started at 07:33 PT died at 09:33 PT on 2026-11-20). Chain far
# events from a nearer run instead. Every background timer of the trading session uses this
# script, never a raw sleep (four raw sleeps on 2026-11-23, the first day of the rule).
set -euo pipefail
target="${1:?HH:MM or +Nm or +Ns}"; label="${2:-TIMER $1}"
case "$target" in
  +*m) wait=$(( ${target:1:${#target}-2} * 60 )) ;;
  +*s) wait=${target:1:${#target}-2} ;;
  *)   wait=$(( $(TZ=America/Los_Angeles date -d "$target" +%s) - $(date +%s) )) ;;
esac
if [ "$wait" -gt $(( 115 * 60 )) ]; then
  echo "REFUSED: $target is $(( wait / 60 )) minutes away (over 115). Start it from a run nearer the event." >&2
  exit 3
fi
[ "$wait" -gt 0 ] && sleep "$wait"
echo "$label"
