#!/bin/sh
# Shared load gate for local agents and the nightly watch on one machine.
# Usage: sh load_gate.sh pytest <command...>   one of five test slots (run pytest at -n 2)
#        sh load_gate.sh heavy <command...>    replay batch, full suite or docker build, alone
# Five slots at -n 2 fill the local cap of 10 processes. A heavy run, itself at most 10 processes,
# takes the heavy lock and then all five slots, so no test runs beside it.
# The lock files live in POKESIM_LOAD_GATE, by default ~/.local/state/pokesim-load.
D=${POKESIM_LOAD_GATE:-$HOME/.local/state/pokesim-load}
mkdir -p "$D"
mode=$1
shift
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
    exec flock "$D/heavy" flock "$D/slot1" flock "$D/slot2" flock "$D/slot3" flock "$D/slot4" flock "$D/slot5" "$@"
    ;;
  *)
    echo "usage: sh load_gate.sh pytest|heavy <command...>" >&2
    exit 2
    ;;
esac
