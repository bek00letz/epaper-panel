#!/bin/sh
# Makes the development environments:
# - the add-on's Python and exactly its packages (addon/requirements.txt), linked as ./.venv;
# - ESPHome, at the version the panels are built with, linked as ./.esphome-venv (the
#   firmware tests and local compiles use it).
#
#   scripts/dev-env.sh
#
# It uses a Python that uv installs and keeps, not the system's or Homebrew's, so an
# upgrade elsewhere can't break it. The version matches the add-on's image (Alpine 3.24,
# addon/build.yaml). Running it again rebuilds the environment from scratch.
set -eu
PYTHON=3.14
ESPHOME=2026.10.1                                             # what Home Assistant's ESPHome builds them with
HERE=$(cd "$(dirname "$0")/.." && pwd)
VENV=${EPAPER_VENV:-$HOME/.local/share/epaper-panel/venv}   # outside the repo, and outside iCloud
ESPHOME_VENV=${EPAPER_ESPHOME_VENV:-$HOME/.local/share/epaper-panel/esphome-venv}

if ! command -v uv >/dev/null 2>&1; then
  echo "This needs uv: https://docs.astral.sh/uv/getting-started/installation/" >&2
  exit 1
fi
uv python install "$PYTHON"
mkdir -p "$(dirname "$VENV")"
uv venv --clear --managed-python --python "$PYTHON" "$VENV"
uv pip install --python "$VENV/bin/python" -r "$HERE/addon/requirements.txt"
ln -sfn "$VENV" "$HERE/.venv"
uv venv --clear --managed-python --python "$PYTHON" "$ESPHOME_VENV"
uv pip install --python "$ESPHOME_VENV/bin/python" "esphome==$ESPHOME"
ln -sfn "$ESPHOME_VENV" "$HERE/.esphome-venv"
echo "Ready: $("$VENV/bin/python" -V) in .venv, ESPHome $("$ESPHOME_VENV/bin/esphome" version | sed 's/Version: //') in .esphome-venv"
