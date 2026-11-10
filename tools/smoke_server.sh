#!/bin/sh
# Start PokeSim in a throwaway data directory, run `pokesim smoke` against it and stop it again.
# Usage: tools/smoke_server.sh accounts|none [port [smoke options such as --rom red.gb]]
# In accounts mode the first admin gets a random password that is never shown. The check itself
# uses the command line token the server writes.
set -eu
mode=$1
shift
port=${1:-8765}
if [ $# -gt 0 ]; then
    shift
fi
data=$(mktemp -d)
server=
stop() {
    if [ -n "$server" ]; then
        kill "$server" 2>/dev/null || true
        wait "$server" 2>/dev/null || true
    fi
    rm -rf "$data"
}
trap stop EXIT
if [ "$mode" = accounts ]; then
    POKESIM_ADMIN_USER=smoke-admin
    POKESIM_ADMIN_PASSWORD=$(python -c 'import secrets; print(secrets.token_urlsafe(24))')
    export POKESIM_ADMIN_USER POKESIM_ADMIN_PASSWORD
fi
AUTH=$mode python -m pokesim serve --data-dir "$data" --host 127.0.0.1 --port "$port" \
    --public-url "http://127.0.0.1:$port" --no-browser > "$data/server.log" 2>&1 &
server=$!
unset POKESIM_ADMIN_USER POKESIM_ADMIN_PASSWORD
if ! python - "$port" <<'EOF'
import sys
import time
import urllib.request

deadline = time.monotonic() + 90
while time.monotonic() < deadline:
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{sys.argv[1]}/health/ready', timeout=2) as response:
            if response.status == 200:
                sys.exit(0)
    except OSError:
        pass
    time.sleep(1)
sys.exit(1)
EOF
then
    echo "PokeSim did not get ready on port $port" >&2
    tail -n 40 "$data/server.log" >&2
    exit 1
fi
if ! python -m pokesim smoke --data-dir "$data" "$@"; then
    tail -n 40 "$data/server.log" >&2
    exit 1
fi
