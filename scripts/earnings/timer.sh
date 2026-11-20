#!/usr/bin/env bash
# Background timer guard (P072, 2026-11-20). Usage: timer.sh HH:MM "LABEL"
# Sleeps until HH:MM Pacific and prints LABEL. Refuses a wait longer than 115 minutes, because
# the harness stops a background command at its 2 h timeout (the 10:30 PT timer started at
# 07:33 PT died at 09:33 PT on 2026-11-20). Chain far events from a nearer run instead.
set -euo pipefail
target="${1:?HH:MM}"; label="${2:-TIMER $1 PT}"
now=$(date +%s); at=$(TZ=America/Los_Angeles date -d "$target" +%s)
wait=$(( at - now ))
if [ "$wait" -gt $(( 115 * 60 )) ]; then
  echo "REFUSED: $target PT is $(( wait / 60 )) minutes away (over 115). Start it from a run nearer the event." >&2
  exit 3
fi
[ "$wait" -gt 0 ] && sleep "$wait"
echo "$label"
