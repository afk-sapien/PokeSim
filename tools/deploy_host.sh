#!/bin/sh
# Build one commit into an image and deploy it to the managed app on a Docker host over SSH.
# Usage: DEPLOY_HOST=<ssh alias> sh tools/deploy_host.sh <full commit sha>
#        DEPLOY_HOST=<ssh alias> sh tools/deploy_host.sh --rollback-to <full commit sha>
#   DEPLOY_DIR    app folder on the host with compose.yaml and .env, required
#   VERSION       image version, by default the version in pyproject.toml at that commit
#   MIN_FREE_GB   free space the host and this machine must keep, by default 10
#   CHECK_CORE    pokecore version the image must hold, optional
#   CHECK_FILE and CHECK_TEXT   a file in the pokesim package that must contain the text, optional
# The commit must contain the deployed commit, read from the running image's revision label, so a
# deploy never drops work the app already runs. Only --rollback-to deploys a commit outside that line.
# Its data schema, the PRAGMA user_version of app.sqlite, must not be older than the live data's,
# even for a rollback, because an older app refuses newer data. The image carries it as a label.
# The commit must have green `ci gate` and `install gate` checks on GitHub. The script stops the app,
# takes a cold backup of the folder, tests it with gzip -t, starts the new image with up --wait and runs
# the smoke check. If any step after the backup fails, it puts .env back and restarts the old image.
# It keeps the 5 newest pre-*.tar.gz backups and the json files beside them, keeps the PokeSim images
# of those backups and the running one, and removes every other pokesim, pokesim-local and
# ghcr.io/afk-sapien/pokesim tag. Other images are never touched.
# While it runs, DEPLOY_DIR/deploy.lock names the commit, so the alert watch stays quiet. Each deploy
# appends one line to DEPLOY_DIR/deploy.log.
set -eu
ROLLBACK=
if [ "${1:-}" = --rollback-to ]; then
  ROLLBACK=1
  shift
fi
SHA=${1:?usage: DEPLOY_HOST=<ssh alias> sh tools/deploy_host.sh [--rollback-to] <full commit sha>}
HOST=${DEPLOY_HOST:?set DEPLOY_HOST to the SSH alias of the Docker host}
DIR=${DEPLOY_DIR:?set DEPLOY_DIR to the app folder on the host}
MIN_FREE_GB=${MIN_FREE_GB:-10}
REPO=afk-sapien/PokeSim
ROOT=$(git rev-parse --show-toplevel)

case $SHA in
  *[!0-9a-f]* | '') echo "deploy: $SHA is not a full commit sha" >&2; exit 2 ;;
esac
[ ${#SHA} -eq 40 ] || { echo "deploy: $SHA is not a full commit sha" >&2; exit 2; }
SHORT=$(echo "$SHA" | cut -c1-7)
git -C "$ROOT" fetch -q origin
git -C "$ROOT" cat-file -e "$SHA^{commit}"
VERSION=${VERSION:-$(git -C "$ROOT" show "$SHA:pyproject.toml" | sed -n 's/^version = "\(.*\)"/\1/p' | head -1)}
TAG=pokesim:$VERSION-local-$SHORT
SCHEMA=$(git -C "$ROOT" show "$SHA:pokesim/app/registry.py" | sed -n 's/^SCHEMA = \([0-9]*\)$/\1/p' | head -1)
[ -n "$SCHEMA" ] || { echo "deploy: no SCHEMA in pokesim/app/registry.py at $SHORT" >&2; exit 1; }

# The image the host is set to run, the commit in its revision label, and the schema of the live data.
# compose run reads the data through the app's own mounts, so this works while the app is stopped too.
live=$(ssh -o BatchMode=yes "$HOST" sh -s -- "$DIR" <<'LIVE'
set -eu
cd "$1"
image=$(sed -n 's/^POKESIM_IMAGE=//p' .env)
docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$image"
docker compose run --rm -T --no-deps --entrypoint python pokesim -c "
import sqlite3
from pathlib import Path
path = Path('/data/app.sqlite')
print(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True).execute('PRAGMA user_version').fetchone()[0] if path.exists() else 0)" </dev/null
LIVE
) || { echo "deploy: could not read the running image and data schema on $HOST, refusing" >&2; exit 1; }
DEPLOYED=$(echo "$live" | sed -n 1p)
LIVE_SCHEMA=$(echo "$live" | sed -n 2p)
case $LIVE_SCHEMA in
  '' | *[!0-9]*) echo "deploy: could not read the live data schema on $HOST ($LIVE_SCHEMA), refusing" >&2; exit 1 ;;
esac
if [ "$SCHEMA" -lt "$LIVE_SCHEMA" ]; then
  echo "deploy: $SHORT has data schema $SCHEMA, older than the live data's $LIVE_SCHEMA, refusing" >&2
  exit 1
fi
if [ -z "$ROLLBACK" ]; then
  if ! git -C "$ROOT" cat-file -e "$DEPLOYED^{commit}" 2>/dev/null; then
    echo "deploy: the running image names commit '$DEPLOYED', which this clone does not have, refusing" >&2
    echo "deploy: fetch it, or pass --rollback-to to deploy $SHORT anyway" >&2
    exit 1
  fi
  if ! git -C "$ROOT" merge-base --is-ancestor "$DEPLOYED" "$SHA"; then
    echo "deploy: $SHORT does not contain the deployed commit $(echo "$DEPLOYED" | cut -c1-7), refusing" >&2
    echo "deploy: pass --rollback-to to deploy it anyway" >&2
    exit 1
  fi
fi

# Only a commit whose own gate checks passed is deployed.
for gate in 'ci gate' 'install gate'; do
  result=$(gh api "repos/$REPO/commits/$SHA/check-runs?check_name=$(echo "$gate" | sed 's/ /%20/g')" \
    --jq '[.check_runs[] | select(.status == "completed") | .conclusion] | if index("success") then "success" else (first // "missing") end')
  if [ "$result" != success ]; then
    echo "deploy: $SHORT has no green '$gate' check ($result), refusing" >&2
    exit 1
  fi
done

free_gb() { df -Pk "$1" | awk 'NR == 2 { print int($4 / 1048576) }'; }
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
if [ "$(free_gb "$WORK")" -lt "$MIN_FREE_GB" ]; then
  echo "deploy: this machine has under $MIN_FREE_GB GB free, refusing" >&2
  exit 1
fi

git -C "$ROOT" archive "$SHA" | tar x -C "$WORK"
docker build -q --build-arg VERSION="$VERSION" --build-arg REVISION="$SHA" --build-arg SCHEMA="$SCHEMA" -t "$TAG" "$WORK"
docker run --rm --entrypoint python -e CHECK_CORE="${CHECK_CORE:-}" -e CHECK_FILE="${CHECK_FILE:-}" \
  -e CHECK_TEXT="${CHECK_TEXT:-}" -e REVISION="$SHA" "$TAG" -c "
import importlib.metadata as m, importlib.util as u, os
from pathlib import Path
if os.environ['CHECK_CORE']:
    assert m.version('pokecore') == os.environ['CHECK_CORE'], m.version('pokecore')
if os.environ['CHECK_FILE']:
    package = Path(u.find_spec('pokesim').submodule_search_locations[0])
    assert os.environ['CHECK_TEXT'] in (package.parent / os.environ['CHECK_FILE']).read_text(encoding='utf-8'), 'change missing from image'
print('image ok, pokesim', m.version('pokesim'), 'pokecore', m.version('pokecore'))"

# The host step holds the lock from the first check to the last prune.
docker save "$TAG" | nice -n 10 gzip -1 | ssh "$HOST" 'gunzip | docker load' >/dev/null
ssh "$HOST" sh -s -- "$DIR" "$SHA" "$TAG" "$MIN_FREE_GB" <<'REMOTE'
set -eu
DIR=$1 SHA=$2 TAG=$3 MIN_FREE_GB=$4
SHORT=$(echo "$SHA" | cut -c1-7)
cd "$DIR"
TS=$(date -u +%Y%m%dT%H%M%SZ)
log() { echo "$TS $SHA $TAG $1" >> deploy.log; echo "deploy: $1"; }
if [ -e deploy.lock ] && [ -n "$(find deploy.lock -mmin -15)" ]; then
  echo "deploy: another deploy holds $DIR/deploy.lock: $(cat deploy.lock)" >&2
  exit 1
fi
echo "$SHA $TS" > deploy.lock
trap 'rm -f "$DIR/deploy.lock"' EXIT

# A backup needs room for itself beside the newest one, and the host keeps its floor after that.
newest=$(ls -t backups/pre-*.tar.gz 2>/dev/null | head -1)
need_kb=$((MIN_FREE_GB * 1048576))
[ -n "$newest" ] && need_kb=$((need_kb + $(du -k "$newest" | cut -f1) * 2))
free_kb=$(df -Pk . | awk 'NR == 2 { print $4 }')
if [ "$free_kb" -lt "$need_kb" ]; then
  log "refused: $((free_kb / 1048576)) GB free, $((need_kb / 1048576)) GB needed"
  exit 1
fi

OLD=$(sed -n 's/^POKESIM_IMAGE=//p' .env)
BACKUP=backups/pre-local-$SHORT-$TS.tar.gz
docker compose stop -t 120
docker run --rm -v "$DIR":/w -w /w alpine tar czf "$BACKUP" --exclude=./app/backups --exclude=./backups \
  --exclude='./backup-20260921*' --exclude='./releases/preview-*' .
if ! gzip -t "$BACKUP"; then
  docker compose up -d --wait
  log "failed: backup $BACKUP does not pass gzip -t, the old image runs again"
  exit 1
fi
cp .env ".env.bak-$TS-pre-local-$SHORT"

rollback() {
  cp ".env.bak-$TS-pre-local-$SHORT" .env
  docker compose up -d --wait || true
  log "failed: $1, rolled back to $OLD, backup $BACKUP"
  exit 1
}
sed -i "s|^POKESIM_IMAGE=.*|POKESIM_IMAGE=$TAG|" .env
docker compose up -d --wait || rollback "the new image did not become healthy"
docker exec "$(docker compose ps -q pokesim)" pokesim smoke --data-dir /data || rollback "the smoke check failed"
log "deployed, backup $BACKUP"

# Keep the 5 newest backups, the json files beside them and the images those backups name.
ls -t backups/pre-*.tar.gz | tail -n +6 | while read -r old; do rm -f "$old"; done
keep=$(ls backups/pre-*.tar.gz | sed -n 's/.*pre-[a-z]*-\([0-9a-f]\{7\}\)-.*/\1/p')
running=$(docker inspect --format '{{.Config.Image}}' "$(docker compose ps -q pokesim)")
docker images --format '{{.Repository}}:{{.Tag}}' | while read -r image; do
  case ${image%%:*} in
    pokesim | pokesim-local | ghcr.io/afk-sapien/pokesim) ;;
    *) continue ;;
  esac
  [ "$image" = "$running" ] && continue
  short=$(echo "${image##*:}" | sed -n 's/.*-\([0-9a-f]\{7\}\)$/\1/p')
  [ -n "$short" ] && echo "$keep" | grep -qx "$short" && continue
  docker rmi "$image" >/dev/null && echo "deploy: removed $image"
done
df -h . | tail -1
REMOTE
