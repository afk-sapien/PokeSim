#!/usr/bin/env bash
# Nightly watch: runs Core's real-cartridge tests, runs PokeSim's suite with the
# private saves CI lacks, checks that the hosted PokeSim app is up, and checks that
# Gen 2 adventures go back to quality hunts once training runs out. Writes one log
# per night and keeps the newest 14.
# Settings come from POKESIM_WATCH_* environment variables. HOST and SITE have no default.
set -uo pipefail
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
CORE=${POKESIM_WATCH_CORE:-$HOME/.local/share/pokesim-overnight/pokesim-core}
CORE_REPO=${POKESIM_WATCH_CORE_REPO:-https://github.com/afk-sapien/pokesim-core.git}
POKESIM=${POKESIM_WATCH_POKESIM:-$HOME/.local/share/pokesim-overnight/pokesim}
POKESIM_REPO=${POKESIM_WATCH_POKESIM_REPO:-https://github.com/afk-sapien/PokeSim.git}
ROMS=${POKESIM_WATCH_ROMS:-$HOME/roms/pokemon}
# Private PokeSim data: stuck scenarios and the other saves CI skips without.
DATA=${POKESIM_WATCH_DATA:-$HOME/Repos/pokesim/data}
# Save states plus a shortcuts.json manifest for Core's shortcut test on real cartridges.
SHORTCUTS=${POKESIM_CORE_SHORTCUT_STATES:-$HOME/roms/pokemon/shortcut-states}
# The SSH host that runs the app and the site name its proxy answers to.
HOST=${POKESIM_WATCH_HOST:?set POKESIM_WATCH_HOST to the SSH host running the app}
SITE=${POKESIM_WATCH_SITE:?set POKESIM_WATCH_SITE to the app site name}
PORT=${POKESIM_WATCH_PORT:-8950}
CONTAINER=${POKESIM_WATCH_CONTAINER:-pokesim-app-pokesim-1}
LOGS=${POKESIM_WATCH_LOGS:-$HOME/.local/state/pokesim-overnight}
KEEP=${POKESIM_WATCH_KEEP:-14}
# The tests wait for the heavy lock of tools/load_gate.sh, so they never overlap a replay batch.
GATE=${POKESIM_LOAD_GATE:-$HOME/.local/state/pokesim-load}
# One wait covers both test steps. 20 minutes leaves about 10 for the tests inside
# the unit's 30-minute start timeout.
GATE_WAIT=${POKESIM_WATCH_GATE_WAIT:-1200}

mkdir -p "$LOGS"
log=$LOGS/$(date +%F).log
exec >>"$log" 2>&1
echo "== $(date -Is) overnight watch"
failed=()

# Both test steps hold the heavy lock and every test slot of tools/load_gate.sh,
# so they never overlap a replay batch or an agent's tests.
mkdir -p "$GATE"
echo "-- waiting up to ${GATE_WAIT}s for the load gate"
exec 9>"$GATE/heavy"
if ! flock -w "$GATE_WAIT" 9; then
  echo "-- load gate stayed busy for ${GATE_WAIT}s"
  failed+=(core pokesim)
else
  slots=()
  for i in 1 2 3; do
    exec {fd}>"$GATE/slot$i"
    flock "$fd"
    slots+=("$fd")
  done

  # The watch keeps its own Core clone at origin/main, apart from any working checkout.
  [ -d "$CORE/.git" ] || git clone -q "$CORE_REPO" "$CORE"
  if git -C "$CORE" fetch -q origin && git -C "$CORE" reset -q --hard origin/main && git -C "$CORE" clean -qfdx -e .venv; then
    echo "-- core real-ROM tests at $(git -C "$CORE" log -1 --format='%h %s')"
    # Without the states the shortcut test skips quietly, so the watch fails instead.
    if [ ! -f "$SHORTCUTS/shortcuts.json" ]; then
      echo "-- no shortcut states: $SHORTCUTS/shortcuts.json is missing"
      failed+=(core)
    else
      out=$(cd "$CORE" && POKESIM_CORE_ROMS=$ROMS POKESIM_CORE_SHORTCUT_STATES=$SHORTCUTS \
        nice -n 10 uv run -q --locked --extra dev --extra emulator pytest -q -rs -p no:cacheprovider tests/test_real_roms.py 2>&1)
      rc=$?
      echo "$out"
      if [ "$rc" -ne 0 ]; then
        failed+=(core)
      elif grep -q 'POKESIM_CORE_SHORTCUT_STATES to run' <<<"$out"; then
        echo "-- the shortcut test skipped although $SHORTCUTS is set"
        failed+=(core)
      fi
    fi
  else
    echo "-- could not update the Core clone"
    failed+=(core)
  fi

  # PokeSim's whole suite with every private input, so a test CI skips for lack
  # of private saves cannot hide a regression for more than a night. The clone
  # keeps its generated Gen II data between nights.
  [ -d "$POKESIM/.git" ] || git clone -q "$POKESIM_REPO" "$POKESIM"
  if git -C "$POKESIM" fetch -q origin && git -C "$POKESIM" reset -q --hard origin/main \
      && git -C "$POKESIM" clean -qfdx -e .venv -e .release-local; then
    echo "-- pokesim private-save tests at $(git -C "$POKESIM" log -1 --format='%h %s')"
    # Without the scenarios the private tests skip quietly, so the watch fails instead.
    if [ ! -d "$DATA/scenarios" ]; then
      echo "-- no private scenarios: $DATA/scenarios is missing"
      failed+=(pokesim)
    else
      out=$(cd "$POKESIM" && {
        [ -d .release-local/gen2-data/gen2 ] \
          || nice -n 10 uv run -q --locked python tools/prepare_gen2_test_data.py .release-local/gen2-data
      } && DATA_DIR=$DATA GEN2_DATA_DIR=$POKESIM/.release-local/gen2-data GEN2_CARTRIDGE_DIR=$ROMS \
        ROM_PATH=$ROMS/red.gb BLUE_ROM_PATH=$ROMS/blue.gb YELLOW_ROM_PATH=$ROMS/yellow.gb \
        POKESIM_SCENARIO_TESTS=1 POKESIM_SCENARIOS=$DATA/scenarios \
        nice -n 10 uv run -q --locked --extra dev pytest -q -rf -p no:cacheprovider --ignore=tests/browser -n 6 2>&1)
      rc=$?
      # Only the failures and the summary line, since the suite prints a dot per test.
      grep -E '^(FAILED|ERROR)|^E  |[0-9]+ (passed|failed|errors?)\b' <<<"$out" | tail -40
      [ "$rc" -ne 0 ] && failed+=(pokesim)
    fi
  else
    echo "-- could not update the PokeSim clone"
    failed+=(pokesim)
  fi
  for fd in "${slots[@]}"; do
    exec {fd}>&-
  done
fi
# Free the gate before the app check, which needs no machine time.
exec 9>&-

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

echo "-- Gen 2 quality hunts on $HOST"
# A Gold, Silver or Crystal adventure with no trainee left must start a better-DV hunt within 6 game
# hours. The state file keeps the game hour at which each one was first seen without a trainee.
if ! ssh -o BatchMode=yes -o ConnectTimeout=20 "$HOST" "docker exec -i $CONTAINER python - collect $SITE" \
    <"$HERE/quality_hunt_watch.py" | python3 "$HERE/quality_hunt_watch.py" judge "$LOGS/quality-hunts.json"; then
  failed+=(quality)
fi

ls -1t "$LOGS"/*.log | tail -n +$((KEEP + 1)) | xargs -r rm --
if [ ${#failed[@]} -gt 0 ]; then
  echo "== FAILED: ${failed[*]}"
  exit 1
fi
echo "== passed"
