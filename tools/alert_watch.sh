#!/usr/bin/env bash
# Hand each new main-page alert of the hosted app to POKESIM_WATCH_ALERT_COMMAND, which reads the
# alert text on stdin. Run it from a timer every few minutes, and from overnight_watch.sh.
# Settings come from the same POKESIM_WATCH_* variables as overnight_watch.sh. HOST has no default.
# A host that cannot be reached, a stopped container or an alerts file that cannot be read is handed
# over as one "app down" alert. While tools/deploy_host.sh holds the deploy lock, the check waits,
# unless the lock is older than 15 minutes.
set -uo pipefail
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
HOST=${POKESIM_WATCH_HOST:?set POKESIM_WATCH_HOST to the SSH host running the app}
CONTAINER=${POKESIM_WATCH_CONTAINER:-pokesim-app-pokesim-1}
APP_DIR=${POKESIM_WATCH_APP_DIR:-/docker/pokesim-app}
LOGS=${POKESIM_WATCH_LOGS:-$HOME/.local/state/pokesim-overnight}
COMMAND=${POKESIM_WATCH_ALERT_COMMAND:-}

problems=$(ssh -o BatchMode=yes -o ConnectTimeout=20 "$HOST" "
  if [ -e $APP_DIR/deploy.lock ] && [ -n \"\$(find $APP_DIR/deploy.lock -mmin -15)\" ]; then echo DEPLOYING; exit 0; fi
  [ \"\$(docker inspect -f '{{.State.Running}}' $CONTAINER 2>/dev/null)\" = true ] || { echo DOWN; exit 0; }
  docker exec $CONTAINER cat /data/watchdog-problems.json 2>/dev/null || echo UNREADABLE") || problems=UNREACHABLE
down() {
  python3 -c 'import json, sys, time
print(json.dumps([{"key": "app-down", "kind": "app_down", "since": time.time(), "message": sys.argv[1]}]))' "$1"
}
case $problems in
  DEPLOYING) echo "-- a deploy is running on $HOST, alerts wait for it"; exit 0 ;;
  DOWN) problems=$(down "The $CONTAINER container on $HOST is not running.") ;;
  UNREADABLE) problems=$(down "The $CONTAINER container on $HOST runs, but its alerts file cannot be read.") ;;
  UNREACHABLE) problems=$(down "$HOST cannot be reached over SSH, so the app cannot be checked.") ;;
esac
if [ -n "$COMMAND" ]; then
  python3 "$HERE/alert_watch.py" "$LOGS/alerts.json" sh -c "$COMMAND" <<<"$problems"
else
  python3 "$HERE/alert_watch.py" "$LOGS/alerts.json" <<<"$problems"
fi
