#!/usr/bin/env bash
# Nightly watch: runs Core's real-cartridge tests and checks that the hosted
# PokeSim app is up. Writes one log per night and keeps the newest 14.
# Settings come from the environment, with defaults for the owner's machine.
set -uo pipefail
CORE=${POKESIM_WATCH_CORE:-$HOME/Repos/pokesim-core}
ROMS=${POKESIM_WATCH_ROMS:-$HOME/roms/pokemon}
HOST=${POKESIM_WATCH_HOST:-servarr}
CONTAINER=${POKESIM_WATCH_CONTAINER:-pokesim-app-pokesim-1}
LOGS=${POKESIM_WATCH_LOGS:-$HOME/.local/state/pokesim-overnight}
KEEP=${POKESIM_WATCH_KEEP:-14}

mkdir -p "$LOGS"
log=$LOGS/$(date +%F).log
exec >>"$log" 2>&1
echo "== $(date -Is) overnight watch"
failed=()

# Core reads every entry in the ROM folder, so hand it only the cartridge files.
carts=$(mktemp -d)
trap 'rm -rf "$carts"' EXIT
find "$ROMS" -maxdepth 1 -type f -exec ln -s {} "$carts/" \;
echo "-- core real-ROM tests at $(git -C "$CORE" log -1 --format='%h %s')"
if ! (cd "$CORE" && POKESIM_CORE_ROMS=$carts .venv/bin/python -m pytest -q -rs -p no:cacheprovider tests/test_real_roms.py); then
  failed+=(core)
fi

echo "-- app on $HOST"
# The container must report healthy and the app must list adventures.
if ! ssh -o BatchMode=yes -o ConnectTimeout=20 "$HOST" "
  set -e
  docker inspect -f '{{.State.Health.Status}} {{.Config.Image}}' $CONTAINER | tee /dev/stderr | grep -q '^healthy '
  curl -fsS -m 20 -H 'Host: pokesim.tynet.app' -H 'X-Forwarded-Proto: https' localhost:8950/api/v1/adventures
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
