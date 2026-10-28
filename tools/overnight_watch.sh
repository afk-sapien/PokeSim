#!/usr/bin/env bash
# Nightly watch: runs Core's real-cartridge tests and checks that the hosted
# PokeSim app is up. Writes one log per night and keeps the newest 14.
# Settings come from POKESIM_WATCH_* environment variables. HOST and SITE have no default.
set -uo pipefail
CORE=${POKESIM_WATCH_CORE:-$HOME/.local/share/pokesim-overnight/pokesim-core}
CORE_REPO=${POKESIM_WATCH_CORE_REPO:-https://github.com/afk-sapien/pokesim-core.git}
ROMS=${POKESIM_WATCH_ROMS:-$HOME/roms/pokemon}
# The SSH host that runs the app and the site name its proxy answers to.
HOST=${POKESIM_WATCH_HOST:?set POKESIM_WATCH_HOST to the SSH host running the app}
SITE=${POKESIM_WATCH_SITE:?set POKESIM_WATCH_SITE to the app site name}
PORT=${POKESIM_WATCH_PORT:-8950}
CONTAINER=${POKESIM_WATCH_CONTAINER:-pokesim-app-pokesim-1}
LOGS=${POKESIM_WATCH_LOGS:-$HOME/.local/state/pokesim-overnight}
KEEP=${POKESIM_WATCH_KEEP:-14}
# The tests wait for the heavy lock of tools/load_gate.sh, so they never overlap a replay batch.
GATE=${POKESIM_LOAD_GATE:-$HOME/.local/state/pokesim-load}
# 25 minutes, so the wait fits inside the unit's 30-minute start timeout.
GATE_WAIT=${POKESIM_WATCH_GATE_WAIT:-1500}

mkdir -p "$LOGS"
log=$LOGS/$(date +%F).log
exec >>"$log" 2>&1
echo "== $(date -Is) overnight watch"
failed=()

# The watch keeps its own Core clone at origin/main, apart from any working checkout.
[ -d "$CORE/.git" ] || git clone -q "$CORE_REPO" "$CORE"
if git -C "$CORE" fetch -q origin && git -C "$CORE" reset -q --hard origin/main && git -C "$CORE" clean -qfdx -e .venv; then
  echo "-- core real-ROM tests at $(git -C "$CORE" log -1 --format='%h %s')"
  mkdir -p "$GATE"
  echo "-- waiting up to ${GATE_WAIT}s for the load gate"
  (cd "$CORE" && POKESIM_CORE_ROMS=$ROMS flock -w "$GATE_WAIT" -E 75 "$GATE/heavy" \
    nice -n 10 uv run -q --locked --extra dev --extra emulator pytest -q -rs -p no:cacheprovider tests/test_real_roms.py)
  rc=$?
  if [ "$rc" -eq 75 ]; then
    echo "-- load gate stayed busy for ${GATE_WAIT}s"
    failed+=(core)
  elif [ "$rc" -ne 0 ]; then
    failed+=(core)
  fi
else
  echo "-- could not update the Core clone"
  failed+=(core)
fi

echo "-- app on $HOST"
# The container must report healthy and the app must list adventures.
if ! ssh -o BatchMode=yes -o ConnectTimeout=20 "$HOST" "
  set -e
  docker inspect -f '{{.State.Health.Status}} {{.Config.Image}}' $CONTAINER | tee /dev/stderr | grep -q '^healthy '
  curl -fsS -m 20 -H 'Host: $SITE' -H 'X-Forwarded-Proto: https' localhost:$PORT/api/v1/adventures
" | python3 -c '
import json, sys
data = json.load(sys.stdin)
adventures = data.get("adventures", data)
running = sum((a.get("status") or a.get("state")) == "running" for a in adventures)
print(len(adventures), "adventures,", running, "running")
'; then
  failed+=(app)
fi

ls -1t "$LOGS"/*.log | tail -n +$((KEEP + 1)) | xargs -r rm --
if [ ${#failed[@]} -gt 0 ]; then
  echo "== FAILED: ${failed[*]}"
  exit 1
fi
echo "== passed"
