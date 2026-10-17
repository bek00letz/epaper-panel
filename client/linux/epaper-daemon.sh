#!/usr/bin/env bash
# ==============================================================================
# E-Paper Client Polling Daemon with Strict ETag 304 Caching
# Optimized for battery-powered Linux, Kindle, Kobo, and Android (Termux) devices.
# ==============================================================================
set -euo pipefail

SERVER_URL="${EPAPER_SERVER:-http://homeassistant.local:7410}"
FRAME_ENDPOINT="${EPAPER_ENDPOINT:-/frame.png}"
POLL_INTERVAL="${EPAPER_INTERVAL:-300}"  # 5 minutes
FRAME_TOKEN="${EPAPER_TOKEN:-}"
CACHE_DIR="${EPAPER_CACHE_DIR:-${HOME:-/tmp}/.cache/epaper}"
DRAW_CMD="${EPAPER_DRAW_CMD:-}"
ONCE="${EPAPER_ONCE:-0}"

# Parse command line flags
while [[ $# -gt 0 ]]; do
  case "$1" in
    --server|-s)
      SERVER_URL="$2"
      shift 2
      ;;
    --interval|-i)
      POLL_INTERVAL="$2"
      shift 2
      ;;
    --token|-t)
      FRAME_TOKEN="$2"
      shift 2
      ;;
    --draw|-d)
      DRAW_CMD="$2"
      shift 2
      ;;
    --endpoint|-e)
      FRAME_ENDPOINT="$2"
      shift 2
      ;;
    --once|-1)
      ONCE=1
      shift
      ;;
    --help|-h)
      echo "Usage: $(basename "$0") [options]"
      echo ""
      echo "Options:"
      echo "  -s, --server <url>       Server URL (default: http://homeassistant.local:7410)"
      echo "  -i, --interval <sec>     Sleep duration between polls in seconds (default: 300)"
      echo "  -e, --endpoint <path>    Image path: /frame.png or /frames.png (default: /frame.png)"
      echo "  -t, --token <token>      Optional Bearer or Frame authorization token"
      echo "  -d, --draw <command>     Command to draw image (receives frame file path as \$1)"
      echo "                           Examples: 'fbink -g -c', 'eips -g', or 'feh --fullscreen'"
      echo "  -1, --once               Poll once and exit immediately (ideal for RTC sleep/cron)"
      echo "  -h, --help               Show this help message"
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 1
      ;;
  esac
done

mkdir -p "$CACHE_DIR"
ETAG_FILE="$CACHE_DIR/last_etag"
FRAME_FILE="$CACHE_DIR/current_frame.png"
FRAME_TMP="$CACHE_DIR/incoming_frame.tmp"
HEADERS_TMP="$CACHE_DIR/headers.tmp"

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

draw_frame() {
  local target="$1"
  if [[ -n "$DRAW_CMD" ]]; then
    # Run user custom draw command
    eval "$DRAW_CMD \"$target\""
  elif command -v fbink >/dev/null 2>&1; then
    # Kobo / Linux Framebuffer (FBInk)
    fbink -g -c "file=$target"
  elif command -v eips >/dev/null 2>&1; then
    # Kindle Native (eips)
    eips -g "$target"
  elif command -v feh >/dev/null 2>&1 && [[ -n "${DISPLAY:-}" ]]; then
    # Desktop X11 / Wayland
    feh --fullscreen --no-fehbg "$target" &
  else
    log "Notice: No display command specified and neither fbink nor eips found. Frame saved to $target."
  fi
}

poll_once() {
  local last_etag=""
  if [[ -f "$ETAG_FILE" ]]; then
    last_etag="$(cat "$ETAG_FILE" | tr -d '\r\n ')"
  fi

  local headers_arg=()
  if [[ -n "$last_etag" ]]; then
    headers_arg+=(-H "If-None-Match: $last_etag")
  fi
  if [[ -n "$FRAME_TOKEN" ]]; then
    headers_arg+=(-H "Authorization: Bearer $FRAME_TOKEN")
  fi

  local full_url="${SERVER_URL%/}${FRAME_ENDPOINT}"
  local http_code

  # Fetch image conditionally
  http_code=$(curl -s -S -m 12 -w "%{http_code}" \
    "${headers_arg[@]}" \
    -D "$HEADERS_TMP" \
    "$full_url" \
    -o "$FRAME_TMP" 2>/dev/null || echo "000")

  if [[ "$http_code" == "304" ]]; then
    log "HTTP 304 Not Modified — Airspace/smart home unchanged. Aborting redraw to save battery."
    rm -f "$FRAME_TMP" "$HEADERS_TMP"
    return 0
  elif [[ "$http_code" == "200" ]]; then
    # Extract new ETag from response headers if present
    local new_etag
    new_etag=$(grep -i '^etag:' "$HEADERS_TMP" 2>/dev/null | head -n1 | awk '{print $2}' | tr -d '\r\n"')
    if [[ -n "$new_etag" ]]; then
      echo "$new_etag" > "$ETAG_FILE"
    fi
    mv -f "$FRAME_TMP" "$FRAME_FILE"
    rm -f "$HEADERS_TMP"
    log "HTTP 200 OK — New frame received (ETag: ${new_etag:-none}). Redrawing screen."
    draw_frame "$FRAME_FILE"
    return 0
  else
    log "HTTP Error $http_code fetching $full_url. Retrying next cycle."
    rm -f "$FRAME_TMP" "$HEADERS_TMP"
    return 1
  fi
}

log "E-paper client daemon starting (Server: $SERVER_URL, Interval: ${POLL_INTERVAL}s)"

if [[ "$ONCE" -eq 1 ]]; then
  poll_once
  exit $?
fi

while true; do
  poll_once || true
  sleep "$POLL_INTERVAL"
done
