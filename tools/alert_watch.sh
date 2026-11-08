#!/usr/bin/env bash
# Hand each new main-page alert of the hosted app to POKESIM_WATCH_ALERT_COMMAND, which reads the
# alert text on stdin. Run it from a timer every few minutes, and from overnight_watch.sh.
# Settings come from the same POKESIM_WATCH_* variables as overnight_watch.sh. HOST has no default.
set -uo pipefail
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
HOST=${POKESIM_WATCH_HOST:?set POKESIM_WATCH_HOST to the SSH host running the app}
CONTAINER=${POKESIM_WATCH_CONTAINER:-pokesim-app-pokesim-1}
LOGS=${POKESIM_WATCH_LOGS:-$HOME/.local/state/pokesim-overnight}
COMMAND=${POKESIM_WATCH_ALERT_COMMAND:-}

problems=$(ssh -o BatchMode=yes -o ConnectTimeout=20 "$HOST" \
  "docker exec $CONTAINER sh -c 'cat /data/watchdog-problems.json 2>/dev/null || echo []'") || {
  echo "-- could not read the alerts on $HOST"
  exit 1
}
if [ -n "$COMMAND" ]; then
  python3 "$HERE/alert_watch.py" "$LOGS/alerts.json" sh -c "$COMMAND" <<<"$problems"
else
  python3 "$HERE/alert_watch.py" "$LOGS/alerts.json" <<<"$problems"
fi
