#!/usr/bin/env bash
# Nightly watch: runs Core's real-cartridge tests, runs PokeSim's suite with the
# private saves CI lacks at the commit the local dev instance runs, checks that the hosted
# app is up, and checks that the dev instance's Gen 2 adventures go back to quality hunts
# once training runs out. The hosted app gets the health check alone.
# Writes one log per night and keeps the newest 14.
# Settings come from POKESIM_WATCH_* environment variables. HOST has no default.
# The systemd units in deploy/systemd run it from the watch's own PokeSim clone, which it
# moves to origin/main first. The whole script is one function, so bash has read all of it
# before the clone changes under it.
set -uo pipefail
main() {
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
CORE=${POKESIM_WATCH_CORE:-$HOME/.local/share/pokesim-overnight/pokesim-core}
CORE_REPO=${POKESIM_WATCH_CORE_REPO:-https://github.com/afk-sapien/pokesim-core.git}
POKESIM=${POKESIM_WATCH_POKESIM:-$HOME/.local/share/pokesim-overnight/pokesim}
# A worktree of that clone at the commit the dev instance runs, where the private-save tests run.
DEPLOYED=${POKESIM_WATCH_DEPLOYED:-$HOME/.local/share/pokesim-overnight/pokesim-deployed}
POKESIM_REPO=${POKESIM_WATCH_POKESIM_REPO:-https://github.com/afk-sapien/PokeSim.git}
ROMS=${POKESIM_WATCH_ROMS:-$HOME/roms/pokemon}
# Private PokeSim data: stuck scenarios and the other saves CI skips without.
DATA=${POKESIM_WATCH_DATA:-$HOME/Repos/pokesim/data}
# Save states plus a shortcuts.json manifest for Core's shortcut test on real cartridges.
SHORTCUTS=${POKESIM_CORE_SHORTCUT_STATES:-$HOME/roms/pokemon/shortcut-states}
# The SSH host that runs the app. Its health check reads it through docker there, so it needs no login.
HOST=${POKESIM_WATCH_HOST:?set POKESIM_WATCH_HOST to the SSH host running the app}
CONTAINER=${POKESIM_WATCH_CONTAINER:-pokesim-app-pokesim-1}
# The systemd user unit of the dev instance, an app on this machine. Its process names the commit,
# the Python and the data folder, so the tests and the quality hunts follow it after each rebuild.
DEV_UNIT=${POKESIM_WATCH_DEV_UNIT:-pokesim-local-sims}
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

# The watch's clone moves to origin/main, and the tests run at the commit the dev instance runs.
[ -d "$POKESIM/.git" ] || git clone -q "$POKESIM_REPO" "$POKESIM"
if ! { git -C "$POKESIM" fetch -q origin && git -C "$POKESIM" reset -q --hard origin/main \
    && git -C "$POKESIM" clean -qfdx -e .venv; }; then
  echo "-- could not update the PokeSim clone"
  failed+=(pokesim)
fi
# The dev instance runs `<python> <env>/bin/pokesim app --data-dir <folder> ...` from its code folder,
# with POKESIM_REVISION and GEN2_DATA_DIR in its environment.
dev_python='' dev_data='' dev_code='' dev_revision='' dev_gen2=''
dev_pid=$(systemctl --user show -p MainPID --value "$DEV_UNIT" 2>/dev/null)
if [ "${dev_pid:-0}" -gt 0 ] 2>/dev/null && [ -r "/proc/$dev_pid/environ" ]; then
  mapfile -d '' -t dev_args <"/proc/$dev_pid/cmdline"
  dev_python=${dev_args[0]}
  for i in "${!dev_args[@]}"; do
    case ${dev_args[$i]} in
      --data-dir) dev_data=${dev_args[$((i + 1))]:-} ;;
      --data-dir=*) dev_data=${dev_args[$i]#--data-dir=} ;;
    esac
  done
  dev_code=$(readlink "/proc/$dev_pid/cwd")
  dev_revision=$(tr '\0' '\n' <"/proc/$dev_pid/environ" | sed -n 's/^POKESIM_REVISION=//p')
  dev_gen2=$(tr '\0' '\n' <"/proc/$dev_pid/environ" | sed -n 's/^GEN2_DATA_DIR=//p')
else
  echo "-- the dev instance $DEV_UNIT is not running"
fi
revision=$dev_revision
if ! git -C "$POKESIM" cat-file -e "${revision:-none}^{commit}" 2>/dev/null; then
  echo "-- the dev instance names no known commit (${revision:-none}), so the tests run at origin/main"
  revision=$(git -C "$POKESIM" rev-parse origin/main)
fi

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
  for i in 1 2 3 4 5; do
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
  # of private saves cannot hide a regression for more than a night. The worktree
  # keeps its generated Gen II data between nights.
  [ -d "$DEPLOYED/.git" ] || [ -f "$DEPLOYED/.git" ] || git -C "$POKESIM" worktree add -q --detach "$DEPLOYED" "$revision"
  if git -C "$DEPLOYED" checkout -q --detach "$revision" && git -C "$DEPLOYED" reset -q --hard \
      && git -C "$DEPLOYED" clean -qfdx -e .venv -e .release-local; then
    echo "-- pokesim private-save tests at the dev instance's $(git -C "$DEPLOYED" log -1 --format='%h %s')"
    # Without the scenarios the private tests skip quietly, so the watch fails instead.
    if [ ! -d "$DATA/scenarios" ]; then
      echo "-- no private scenarios: $DATA/scenarios is missing"
      failed+=(pokesim)
    else
      out=$(cd "$DEPLOYED" && {
        [ -d .release-local/gen2-data/gen2 ] \
          || nice -n 10 uv run -q --locked python tools/prepare_gen2_test_data.py .release-local/gen2-data
      } && DATA_DIR=$DATA GEN2_DATA_DIR=$DEPLOYED/.release-local/gen2-data GEN2_CARTRIDGE_DIR=$ROMS \
        ROM_PATH=$ROMS/red.gb BLUE_ROM_PATH=$ROMS/blue.gb YELLOW_ROM_PATH=$ROMS/yellow.gb \
        POKESIM_SCENARIO_TESTS=1 POKESIM_SCENARIOS=$DATA/scenarios \
        nice -n 10 uv run -q --locked --extra dev pytest -q -rf -p no:cacheprovider --ignore=tests/browser -n 10 2>&1)
      rc=$?
      # Only the failures and the summary line, since the suite prints a dot per test.
      grep -E '^(FAILED|ERROR)|^E  |[0-9]+ (passed|failed|errors?)\b' <<<"$out" | tail -40
      [ "$rc" -ne 0 ] && failed+=(pokesim)
    fi
  else
    echo "-- could not check out $revision for the tests"
    failed+=(pokesim)
  fi
  for fd in "${slots[@]}"; do
    exec {fd}>&-
  done
fi
# Free the gate before the app check, which needs no machine time.
exec 9>&-

echo "-- app on $HOST"
# The container must report healthy and pass the smoke check inside it, which needs no login.
if ! ssh -o BatchMode=yes -o ConnectTimeout=20 "$HOST" "
  set -e
  docker inspect -f '{{.State.Health.Status}} {{.Config.Image}}' $CONTAINER | tee /dev/stderr | grep -q '^healthy '
  docker exec $CONTAINER pokesim smoke --data-dir /data
"; then
  failed+=(app)
fi

echo "-- Gen 2 quality hunts on the dev instance"
# A Gold, Silver or Crystal adventure with no trainee left must start a better-DV hunt within 6 game
# hours. The state file keeps the game hour at which each one was first seen without a trainee.
# It reads the adventures' files in the dev instance's data folder with the dev instance's own Python,
# never the site. The hosted app's main-page alerts stay with the pokesim-alerts timer.
if [ -z "$dev_data" ] || [ -z "$dev_code" ]; then
  echo "-- the dev instance $DEV_UNIT names no data folder, so no quality hunt was read"
  failed+=(quality)
elif ! (cd "$dev_code" && env DATA_DIR="$dev_data" ${dev_gen2:+GEN2_DATA_DIR="$dev_gen2"} \
      nice -n 10 "$dev_python" - collect) <"$HERE/quality_hunt_watch.py" \
    | python3 "$HERE/quality_hunt_watch.py" judge "$LOGS/quality-hunts-dev.json"; then
  failed+=(quality)
fi

ls -1t "$LOGS"/*.log | tail -n +$((KEEP + 1)) | xargs -r rm --
if [ ${#failed[@]} -gt 0 ]; then
  echo "== FAILED: ${failed[*]}"
  exit 1
fi
echo "== passed"
}
main "$@"
exit
