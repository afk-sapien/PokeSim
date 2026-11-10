#!/usr/bin/env bash
# Local nightly run: the whole suite on a fresh origin/main, with the private scenario replays and the
# slow tests on. Usage:
#   bash tools/nightly_tests.sh install   write the systemd user units. It enables nothing.
#   bash tools/nightly_tests.sh run       update the nightly clone and run the suite in it
# The run uses its own clone, apart from any working checkout, and takes the heavy lock of
# tools/load_gate.sh, so it never runs beside a replay batch or an agent's tests.
# Each run writes <date>.txt and <date>.log to the results folder and keeps the newest 30 of each.
# The first line of the .txt file is the verdict, one of:
#   nightly <date> <sha7>: <N> passed, only the known <K> failed
#   nightly <date> <sha7>: <N> passed, none failed
#   nightly <date> <sha7>: NEW FAILURES <test ids>
# A known failure is a scenario replay named in known-failures.txt in the scenarios folder, the same
# baseline tools/preflight.py reads.
# Private settings come from the file POKESIM_NIGHTLY_ENV names, by default operations/nightly.env in
# the data folder of the checkout that runs install:
#   POKESIM_NIGHTLY_ROMS        red.gb, blue.gb, yellow.gb and the Gen II cartridges
#   POKESIM_NIGHTLY_DATA        the private data folder
#   POKESIM_NIGHTLY_SCENARIOS   the stuck scenarios, by default the scenarios folder in the data folder
# The whole script is one function, so bash has read all of it before the clone changes under it.
set -uo pipefail
main() {
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
ROOT=$(dirname "$HERE")
ENV_FILE=${POKESIM_NIGHTLY_ENV:-${DATA_DIR:-$ROOT/data}/operations/nightly.env}
if [ -f "$ENV_FILE" ]; then
  set -a
  . "$ENV_FILE"
  set +a
fi
CLONE=${POKESIM_NIGHTLY_CLONE:-${XDG_DATA_HOME:-$HOME/.local/share}/pokesim-nightly/pokesim}
REPO=${POKESIM_NIGHTLY_REPO:-https://github.com/afk-sapien/PokeSim.git}
BRANCH=${POKESIM_NIGHTLY_BRANCH:-main}
RESULTS=${POKESIM_NIGHTLY_RESULTS:-${XDG_STATE_HOME:-$HOME/.local/state}/pokesim-nightly}
KEEP=${POKESIM_NIGHTLY_KEEP:-30}
UNITS=${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user
DAY=${POKESIM_NIGHTLY_DAY:-$(date +%F)}
txt=$RESULTS/$DAY.txt
log=$RESULTS/$DAY.log

# A run that cannot finish still writes a verdict, so a broken night never looks like a quiet one.
broke() {
  local sha
  sha=$(git -C "$1" rev-parse --short=7 HEAD 2>/dev/null || echo unknown)
  echo "-- $2"
  printf 'nightly %s %s: NEW FAILURES (the run broke: %s)\nlog: %s\n' "$DAY" "$sha" "$2" "$log" >"$txt"
  exit 1
}

case ${1:-} in
  install)
    uv=$(command -v uv) || { echo "nightly: uv is not on PATH" >&2; exit 1; }
    # Any slice name reports loaded, so look for the unit file that holds the caps.
    if [ -z "$(systemctl --user show -p FragmentPath --value pokesim-tests.slice 2>/dev/null)" ]; then
      echo "nightly: install the slices first with sh tools/local_sims.sh install" >&2
      exit 1
    fi
    [ -f "$ENV_FILE" ] || echo "nightly: write POKESIM_NIGHTLY_ROMS and POKESIM_NIGHTLY_DATA to $ENV_FILE before the first night" >&2
    [ -d "$CLONE/.git" ] || git clone -q "$REPO" "$CLONE" || exit 1
    mkdir -p "$UNITS"
    cat >"$UNITS/pokesim-nightly.service" <<EOF
[Unit]
Description=PokeSim local nightly tests: the full suite on origin/main with the replays and the slow tests
After=network-online.target

[Service]
Type=oneshot
Slice=pokesim-tests.slice
Nice=10
Environment="PATH=$(dirname "$uv"):/usr/local/bin:/usr/bin:/bin"
Environment="POKESIM_NIGHTLY_ENV=$ENV_FILE"
Environment="POKESIM_NIGHTLY_CLONE=$CLONE"
Environment="POKESIM_NIGHTLY_RESULTS=$RESULTS"
# The service already runs in the tests slice, so the load gate starts no scope of its own and a stop
# or a timeout ends every test process.
Environment=POKESIM_LOAD_GATE_SLICE=
ExecStart=/bin/bash "$CLONE/tools/nightly_tests.sh" run
TimeoutStartSec=4h
EOF
    cat >"$UNITS/pokesim-nightly.timer" <<EOF
[Unit]
Description=Run the PokeSim local nightly tests at 02:00

[Timer]
OnCalendar=*-*-* 02:00:00
# A night the machine was off is skipped, so a late start never lands on the day's work.
Persistent=false

[Install]
WantedBy=timers.target
EOF
    echo "nightly: wrote pokesim-nightly.service and pokesim-nightly.timer to $UNITS"
    echo "nightly: enable it with systemctl --user daemon-reload && systemctl --user enable --now pokesim-nightly.timer"
    echo "nightly: each run writes $RESULTS/<date>.txt"
    ;;
  run)
    mkdir -p "$RESULTS"
    # One nightly run at a time. The suite step inherits the lock.
    exec 8>"$RESULTS/.lock"
    flock -n 8 || { echo "nightly: another run is under way" >&2; exit 1; }
    exec >"$log" 2>&1
    echo "== $(date -Is) nightly tests on origin/$BRANCH"
    [ -d "$CLONE/.git" ] || git clone -q "$REPO" "$CLONE" || broke "$CLONE" "could not clone $REPO"
    if ! { git -C "$CLONE" fetch -q origin && git -C "$CLONE" reset -q --hard "origin/$BRANCH" \
        && git -C "$CLONE" clean -qfdx -e .venv -e .release-local; }; then
      broke "$CLONE" "could not move the clone to origin/$BRANCH"
    fi
    [ -f "$CLONE/tools/nightly_tests.sh" ] || broke "$CLONE" "origin/$BRANCH has no tools/nightly_tests.sh"
    # The suite step runs from the updated clone, so tonight's run follows tonight's main.
    export POKESIM_NIGHTLY_ENV=$ENV_FILE POKESIM_NIGHTLY_RESULTS=$RESULTS POKESIM_NIGHTLY_DAY=$DAY
    exec bash "$CLONE/tools/nightly_tests.sh" suite
    ;;
  suite)
    mkdir -p "$RESULTS"
    exec >>"$log" 2>&1
    cd "$ROOT" || broke "$ROOT" "could not enter $ROOT"
    sha=$(git rev-parse --short=7 HEAD)
    echo "-- suite at $(git log -1 --format='%h %s')"
    ROMS=${POKESIM_NIGHTLY_ROMS:-}
    DATA=${POKESIM_NIGHTLY_DATA:-}
    SCENARIOS=${POKESIM_NIGHTLY_SCENARIOS:-${DATA:+$DATA/scenarios}}
    # Without these the private tests skip quietly, so the run refuses instead.
    [ -n "$ROMS" ] && [ -f "$ROMS/red.gb" ] || broke "$ROOT" "no ROM folder: set POKESIM_NIGHTLY_ROMS in $ENV_FILE"
    [ -n "$DATA" ] && [ -d "$DATA" ] || broke "$ROOT" "no data folder: set POKESIM_NIGHTLY_DATA in $ENV_FILE"
    [ -n "$SCENARIOS" ] && [ -d "$SCENARIOS" ] || broke "$ROOT" "no scenarios folder at ${SCENARIOS:-(unset)}"
    if [ ! -d .release-local/gen2-data/gen2 ]; then
      uv run -q --locked python tools/prepare_gen2_test_data.py .release-local/gen2-data \
        || broke "$ROOT" "could not prepare the Gen II data"
    fi
    export DATA_DIR=$DATA GEN2_DATA_DIR=$ROOT/.release-local/gen2-data GEN2_CARTRIDGE_DIR=$ROMS \
      ROM_PATH=$ROMS/red.gb BLUE_ROM_PATH=$ROMS/blue.gb YELLOW_ROM_PATH=$ROMS/yellow.gb \
      POKESIM_SCENARIO_TESTS=1 POKESIM_SCENARIOS=$SCENARIOS POKESIM_SLOW_TESTS=1
    out=$(mktemp)
    # The outer limit covers the wait for the heavy lock, and the inner one the tests alone.
    timeout 3h sh tools/load_gate.sh heavy timeout 2h \
      uv run -q --locked --extra dev pytest -q -rfE -p no:cacheprovider --ignore=tests/browser -n 10 2>&1 | tee "$out"
    rc=${PIPESTATUS[0]}
    summary=$(grep -E '^(=+ )?[0-9]+ (passed|failed|errors?|skipped|deselected|xfailed|xpassed|warnings?)\b.* in [0-9.]+s' "$out" | tail -1)
    mapfile -t bad < <(awk '/short test summary info/ {s = 1; next} s && /^(FAILED|ERROR) [^ ]/' "$out" \
      | sed -E 's/^(FAILED|ERROR) //; s/ - .*$//' | sort -u)
    rm -f "$out"
    case $rc in
      0 | 1) ;;
      124) broke "$ROOT" "the run passed its time limit" ;;
      *) broke "$ROOT" "pytest exited with $rc" ;;
    esac
    [ -n "$summary" ] || broke "$ROOT" "pytest printed no summary"
    [ "$rc" -eq 0 ] || [ ${#bad[@]} -gt 0 ] || broke "$ROOT" "pytest failed but named no test"
    known=()
    baseline=$SCENARIOS/known-failures.txt
    if [ -f "$baseline" ]; then
      mapfile -t known < <(sed -E 's/#.*//; s/^[[:space:]]+//; s/[[:space:]]+$//' "$baseline" | grep -v '^$')
    else
      echo "-- no known-failures.txt in the scenarios folder, so every failure counts as new"
    fi
    replay='tests/test_scenarios.py::test_the_player_gets_going_again['
    new=() seen=()
    for id in "${bad[@]}"; do
      name=''
      case $id in "$replay"*']') name=${id#"$replay"} && name=${name%]} ;; esac
      if [ -n "$name" ] && printf '%s\n' "${known[@]}" | grep -qxF -- "$name"; then
        seen+=("$name")
      else
        new+=("$id")
      fi
    done
    quiet=()
    for name in "${known[@]}"; do
      printf '%s\n' "${seen[@]}" | grep -qxF -- "$name" || quiet+=("$name")
    done
    passed=$(grep -oE '[0-9]+ passed' <<<"$summary" | grep -oE '[0-9]+' || echo 0)
    if [ ${#new[@]} -gt 0 ]; then
      verdict="NEW FAILURES ${new[*]}"
    elif [ ${#seen[@]} -gt 0 ]; then
      verdict="$passed passed, only the known ${#seen[@]} failed"
    else
      verdict="$passed passed, none failed"
    fi
    {
      echo "nightly $DAY $sha: $verdict"
      [ ${#quiet[@]} -eq 0 ] || echo "known failures that did not fail: ${quiet[*]}"
      echo "log: $log"
      echo "$summary"
      [ ${#bad[@]} -eq 0 ] || printf 'failed: %s\n' "${bad[@]}"
    } >"$txt"
    cat "$txt"
    for kind in txt log; do
      ls -1t "$RESULTS"/[0-9]*."$kind" 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm --
    done
    [ ${#new[@]} -eq 0 ]
    ;;
  *)
    echo "usage: bash tools/nightly_tests.sh install | run" >&2
    exit 2
    ;;
esac
}
main "$@"
exit
