#!/usr/bin/with-contenv bashio
set -e

export JELLYFIN_BASE="$(bashio::config 'jellyfin_base')"
export JELLYFIN_USER="$(bashio::config 'jellyfin_user')"
export JELLYFIN_KEY="$(bashio::config 'jellyfin_key')"
export REFRESH_SECONDS="$(bashio::config 'refresh_seconds')"
export HA_BASE="http://supervisor/core"
export HA_TOKEN="${SUPERVISOR_TOKEN}"
export DATA_DIR="/data"

bashio::log.info "Starting e-paper panel service"
exec python3 -u /opt/epaper/server.py
