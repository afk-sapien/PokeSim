#!/bin/sh
# Shared load gate for local agents and the nightly watch on one machine.
# Usage: sh load_gate.sh pytest <command...>   one of three test slots (run pytest at -n 2)
#        sh load_gate.sh heavy <command...>    replay batch, full suite or docker build, alone
# A heavy run takes the heavy lock and then all three slots, so no test runs beside it.
# The lock files live in POKESIM_LOAD_GATE, by default ~/.local/state/pokesim-load.
D=${POKESIM_LOAD_GATE:-$HOME/.local/state/pokesim-load}
mkdir -p "$D"
mode=$1
shift
case $mode in
  pytest)
    while :; do
      for i in 1 2 3; do
        flock -n -E 75 "$D/slot$i" "$@"
        rc=$?
        [ "$rc" -ne 75 ] && exit "$rc"
      done
      sleep 5
    done
    ;;
  heavy)
    exec flock "$D/heavy" flock "$D/slot1" flock "$D/slot2" flock "$D/slot3" "$@"
    ;;
  *)
    echo "usage: sh load_gate.sh pytest|heavy <command...>" >&2
    exit 2
    ;;
esac
