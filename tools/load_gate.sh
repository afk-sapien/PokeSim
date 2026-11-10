#!/bin/sh
# Shared load gate for local agents and the nightly watch on one machine.
# Usage: sh load_gate.sh pytest <command...>   one of five test slots (run pytest at -n 2)
#        sh load_gate.sh heavy <command...>    replay batch, full suite or docker build, alone
# Five slots at -n 2 fill 10 processes. A heavy run, itself at most 12 processes (pytest -n 12),
# takes the heavy lock and then all five slots, so no test runs beside it.
# The lock files live in POKESIM_LOAD_GATE, by default ~/.local/state/pokesim-load.
# A heavy run exports POKESIM_LOAD_GATE_HEAVY=1, and a load gate inside it runs its command at once,
# since waiting on a lock its own parent holds would never end.
# Every gated command runs at nice 10 or lower priority, so callers need not remember to add it.
# Where the PokeSim slices are installed (sh tools/local_sims.sh install), every gated command runs as a
# systemd scope in POKESIM_LOAD_GATE_SLICE, by default pokesim-tests.slice, so test runs and the sims
# together stay inside the 12 core cap and test runs stay under 10G. An empty value runs without a scope.
n=$(ps -o nice= -p $$ | tr -d ' ')
if [ "${n:-0}" -lt 10 ]; then
  exec nice -n $((10 - ${n:-0})) sh "$0" "$@"
fi
D=${POKESIM_LOAD_GATE:-$HOME/.local/state/pokesim-load}
mkdir -p "$D"
mode=$1
shift
if [ "$POKESIM_LOAD_GATE_HEAVY" = 1 ] && { [ "$mode" = pytest ] || [ "$mode" = heavy ]; }; then
  exec "$@"
fi
SLICE=${POKESIM_LOAD_GATE_SLICE-pokesim-tests.slice}
if [ -n "$SLICE" ] && { [ "$mode" = pytest ] || [ "$mode" = heavy ]; } && command -v systemd-run >/dev/null 2>&1; then
  # systemd makes up any slice it is asked about and calls it loaded, so only a unit file proves the
  # caps exist. No user manager (a CI container) runs the command without a scope or a warning.
  if unit=$(systemctl --user show -p FragmentPath --value "$SLICE" 2>/dev/null); then
    if [ -n "$unit" ]; then
      set -- systemd-run --user --scope --quiet --collect --slice="$SLICE" "$@"
    else
      echo "load gate: $SLICE is not installed, so this run is not capped. Install it with sh tools/local_sims.sh install" >&2
    fi
  fi
fi
case $mode in
  pytest)
    while :; do
      for i in 1 2 3 4 5; do
        flock -n -E 75 "$D/slot$i" "$@"
        rc=$?
        [ "$rc" -ne 75 ] && exit "$rc"
      done
      sleep 5
    done
    ;;
  heavy)
    flock -n "$D/heavy" true || echo "load gate: waiting for the heavy lock in $D" >&2
    POKESIM_LOAD_GATE_HEAVY=1
    export POKESIM_LOAD_GATE_HEAVY
    exec flock "$D/heavy" flock "$D/slot1" flock "$D/slot2" flock "$D/slot3" flock "$D/slot4" flock "$D/slot5" "$@"
    ;;
  *)
    echo "usage: sh load_gate.sh pytest|heavy <command...>" >&2
    exit 2
    ;;
esac
