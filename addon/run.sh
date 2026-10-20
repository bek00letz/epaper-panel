#!/usr/bin/with-contenv bashio
set -e

# Deprecated options, read only to migrate them into the editor once.
bashio::config.has_value 'jellyfin_base'  && export JELLYFIN_BASE="$(bashio::config 'jellyfin_base')"   || true
bashio::config.has_value 'jellyfin_user'  && export JELLYFIN_USER="$(bashio::config 'jellyfin_user')"   || true
bashio::config.has_value 'jellyfin_key'   && export JELLYFIN_KEY="$(bashio::config 'jellyfin_key')"     || true
bashio::config.has_value 'esphome_device' && export ESPHOME_DEVICE="$(bashio::config 'esphome_device')" || true
bashio::config.has_value 'frame_token'    && export FRAME_TOKEN="$(bashio::config 'frame_token')"       || true
export REFRESH_SECONDS="$(bashio::config 'refresh_seconds')"
# TRMNL screens (kinds/trmnl.py): their routes exist only while this is on.
bashio::config.true 'trmnl' && export TRMNL="true" || true
export HA_BASE="http://supervisor/core"
export HA_TOKEN="${SUPERVISOR_TOKEN}"
export DATA_DIR="/data"
export ADDON_VERSION="$(bashio::app.version 2>/dev/null || bashio::addon.version)"

# The broker the Supervisor offers (the Mosquitto app), for the add-on's
# Home Assistant entities. Without one the panel works the same; the values
# are just not mirrored into Home Assistant.
if bashio::services.available "mqtt"; then
  export MQTT_HOST="$(bashio::services 'mqtt' 'host')"
  export MQTT_PORT="$(bashio::services 'mqtt' 'port')"
  export MQTT_USERNAME="$(bashio::services 'mqtt' 'username')"
  export MQTT_PASSWORD="$(bashio::services 'mqtt' 'password')"
else
  bashio::log.info "No MQTT broker: values stay inside the add-on"
fi

bashio::log.info "Starting e-paper panel service"
exec python3 -u /opt/epaper/server.py
