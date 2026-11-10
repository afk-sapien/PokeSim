#!/bin/sh
# Run local PokeSim apps, the dev instance and temporary sims, inside the capped PokeSim user slices.
# Usage: sh tools/local_sims.sh install
#        sh tools/local_sims.sh start <unit> <env dir> <code dir> <data dir> <port> <revision>
# install copies deploy/systemd/pokesim*.slice into the systemd user directory and reloads systemd, once
# per machine. pokesim.slice caps all local PokeSim work at 12 cores and 22G. Sims share
# pokesim-sims.slice (12G) and tools/load_gate.sh runs share pokesim-tests.slice (10G), and the slices'
# CPU weights let a test run win the CPU over the sims.
# start stops <unit> if it runs and starts it again as a transient service in pokesim-sims.slice, at
# nice 19 with MemoryMax=12G (POKESIM_SIM_MEMORY overrides it), AUTH=none on 127.0.0.1 and no browser.
# GEN2_DATA_DIR passes through when it is set. Stopping sends SIGTERM to the app alone, so it stops its
# own workers and saves.
set -eu
HERE=$(cd "$(dirname "$0")/.." && pwd)
UNITS=${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user
usage() {
  echo "usage: sh tools/local_sims.sh install | start <unit> <env dir> <code dir> <data dir> <port> <revision>" >&2
  exit 2
}
[ $# -ge 1 ] || usage
mode=$1
shift
case $mode in
  install)
    mkdir -p "$UNITS"
    for slice in "$HERE"/deploy/systemd/pokesim*.slice; do
      cp "$slice" "$UNITS/"
    done
    systemctl --user daemon-reload
    echo "local sims: slices installed in $UNITS"
    ;;
  start)
    [ $# -eq 6 ] || usage
    unit=$1 env=$2 code=$3 data=$4 port=$5 revision=$6
    # Any slice name reports loaded, so look for the unit file that holds the caps.
    if [ -z "$(systemctl --user show -p FragmentPath --value pokesim-sims.slice)" ]; then
      echo "local sims: run sh tools/local_sims.sh install first" >&2
      exit 1
    fi
    if systemctl --user is-active -q "$unit"; then
      systemctl --user stop "$unit"
    fi
    systemctl --user reset-failed "$unit" 2>/dev/null || true
    set -- --user --unit "$unit" --collect --slice=pokesim-sims.slice \
      -p Nice=19 -p "MemoryMax=${POKESIM_SIM_MEMORY:-12G}" -p KillMode=mixed -p TimeoutStopSec=120 \
      -p "WorkingDirectory=$code" --setenv=AUTH=none --setenv="POKESIM_REVISION=$revision"
    if [ -n "${GEN2_DATA_DIR:-}" ]; then
      set -- "$@" --setenv="GEN2_DATA_DIR=$GEN2_DATA_DIR"
    fi
    exec systemd-run "$@" "$env/bin/pokesim" app --data-dir "$data" --host 127.0.0.1 --port "$port" \
      --public-url "http://127.0.0.1:$port" --no-browser
    ;;
  *)
    usage
    ;;
esac
