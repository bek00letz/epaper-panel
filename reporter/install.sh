#!/bin/bash
# Sets up the AI usage reporter on a Mac or Linux. The editor (Settings › AI usage) gives the line to run:
#
#   curl -fsSL https://raw.githubusercontent.com/bek00letz/epaper-panel/<ref>/reporter/install.sh \
#     | bash -s -- --ref <ref> --address <add-on address> --code <code>
#
# It fetches the reporter at that release of the add-on (as the panel's firmware is), copies it to
# its own folder, and runs its setup. From a checkout, setup.sh does the same without fetching.
set -euo pipefail

REPO="bek00letz/epaper-panel"
REF="main"
FROM=""
ARGS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --ref) REF="$2"; shift 2 ;;
    --from) FROM="$2"; shift 2 ;;
    *) ARGS+=("$1"); shift ;;
  esac
done

case "$(uname -s)" in
  Darwin) HOME_DIR="$HOME/Library/Application Support/e-Paper Usage Reporter" ;;
  *) HOME_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/epaper-usage-reporter" ;;
esac
APP="$HOME_DIR/app"

if ! PY="$(command -v python3)"; then
  echo "The reporter needs Python 3.9 or later, and this computer has none. Install it, then run this again." >&2
  exit 1
fi
if ! "$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null; then
  if [ "$(uname -s)" = "Darwin" ]; then
    echo "Your Mac's Python needs the Command Line Tools. Run: xcode-select --install, then this again." >&2
  else
    echo "The reporter needs Python 3.9 or later. Update Python, then run this again." >&2
  fi
  exit 1
fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
if [ -z "$FROM" ]; then
  if ! curl -fsSL "https://github.com/$REPO/archive/$REF.tar.gz" | tar -xz -C "$TMP"; then
    echo "Couldn't download the reporter ($REF). Check this computer's internet connection and try again." >&2
    exit 1
  fi
  FROM="$(find "$TMP" -mindepth 2 -maxdepth 2 -type d -name reporter | head -n 1)"
fi
if [ ! -f "$FROM/run.py" ]; then
  echo "The reporter wasn't where it should be. Copy the command from the editor again." >&2
  exit 1
fi

mkdir -p "$APP"
rm -rf "$APP/epaper_usage"
cp -R "$FROM/epaper_usage" "$FROM/run.py" "$APP/"
find "$APP" -name '__pycache__' -type d -prune -exec rm -rf {} +
exec "$PY" "$APP/run.py" setup "${ARGS[@]}"
