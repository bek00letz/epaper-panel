#!/usr/bin/with-contenv bashio
set -e

# Deprecated options, read only to migrate them into the editor once.
bashio::config.has_value 'jellyfin_base'  && export JELLYFIN_BASE="$(bashio::config 'jellyfin_base')"   || true
bashio::config.has_value 'jellyfin_user'  && export JELLYFIN_USER="$(bashio::config 'jellyfin_user')"   || true
bashio::config.has_value 'jellyfin_key'   && export JELLYFIN_KEY="$(bashio::config 'jellyfin_key')"     || true
bashio::config.has_value 'esphome_device' && export ESPHOME_DEVICE="$(bashio::config 'esphome_device')" || true
bashio::config.has_value 'frame_token'    && export FRAME_TOKEN="$(bashio::config 'frame_token')"       || true
export REFRESH_SECONDS="$(bashio::config 'refresh_seconds')"
export HA_BASE="http://supervisor/core"
export HA_TOKEN="${SUPERVISOR_TOKEN}"
export DATA_DIR="/data"

bashio::log.info "Starting e-paper panel service"
exec python3 -u /opt/epaper/server.py
