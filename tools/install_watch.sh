#!/bin/sh
# Install the overnight and alert watch as systemd user units that run from the watch's own clone.
# Usage: sh tools/install_watch.sh
# Put the settings in ~/.config/pokesim-watch.env first, one VAR=value per line:
#   POKESIM_WATCH_HOST, POKESIM_WATCH_SITE, POKESIM_WATCH_ALERT_COMMAND and POKESIM_WATCH_NTFY.
# The units are copied and reloaded. The timers are enabled only with --enable.
set -eu
HERE=$(cd "$(dirname "$0")/.." && pwd)
CLONE=${POKESIM_WATCH_POKESIM:-$HOME/.local/share/pokesim-overnight/pokesim}
UNITS=${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user
ENV_FILE=${XDG_CONFIG_HOME:-$HOME/.config}/pokesim-watch.env
[ -f "$ENV_FILE" ] || { echo "install: write $ENV_FILE first, see this script's header" >&2; exit 1; }
[ -d "$CLONE/.git" ] || git clone -q https://github.com/afk-sapien/PokeSim.git "$CLONE"
git -C "$CLONE" fetch -q origin
git -C "$CLONE" reset -q --hard origin/main
mkdir -p "$UNITS"
for unit in "$HERE"/deploy/systemd/*; do
  cp "$unit" "$UNITS/"
done
systemctl --user daemon-reload
echo "install: units in $UNITS, running from $CLONE"
if [ "${1:-}" = --enable ]; then
  systemctl --user enable --now pokesim-overnight.timer pokesim-alerts.timer
else
  echo "install: enable with: systemctl --user enable --now pokesim-overnight.timer pokesim-alerts.timer"
fi
