"""Settings from the environment, paths and fixed rules. Read at call time (tests change them)."""

import os
import re
from pathlib import Path


DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
WEB_DIR = Path(__file__).parent / "web"
HA_BASE = (os.environ.get("HA_BASE") or "http://supervisor/core").rstrip("/")
HA_TOKEN = (os.environ.get("HA_TOKEN") or "").strip()
REFRESH = max(10, min(3600, int(os.environ.get("REFRESH_SECONDS", "60") or 60)))
FRAME_TOKEN = (os.environ.get("FRAME_TOKEN") or "").strip()

FRAME_PORT = int(os.environ.get("FRAME_PORT", "8099") or 8099)
INGRESS_PORT = int(os.environ.get("INGRESS_PORT", "8080") or 8080)

def layouts_path() -> Path:
    return DATA_DIR / "layouts.json"


def draft_path() -> Path:
    """Editor changes saved as you go, not yet sent to the panel."""
    return DATA_DIR / "draft.json"


def panel_setup_path() -> Path:
    return DATA_DIR / "panel_setup.json"


# Home Assistant's configuration folder (mapped into the add-on), and its
# ESPHome folder, where Panel setup writes the panel's YAML.
HA_CONFIG_DIR = Path(os.environ.get("HA_CONFIG_DIR", "/config"))
ESPHOME_DIR = Path(os.environ.get("ESPHOME_DIR", "/config/esphome"))

DEFAULTS_PATH = Path(__file__).parent / "default_layouts.json"
FIXTURE_PATH = Path(__file__).parent / "render" / "fixture.json"

ADDON_VERSION = (os.environ.get("ADDON_VERSION") or "dev").strip()

# 0.8.x wrote values straight into Home Assistant's state machine as well as
# over MQTT, which made every sensor exist twice. MQTT discovery is now the one
# way entities are created (mqtt_bridge). Kept, switched off, until 0.9 has
# proven itself; delete afterwards.
PUBLISH_VIA_STATES_API = False

# 0.8.x pushed a refresh to the panel on a timer, on top of the panel's own
# timer doing the same. A screen's Update every (timing.py) is the one source of
# truth now; the add-on pushes only when there is something new. Switched off,
# not deleted.
PROACTIVE_TIMED_PUSH = False

# The sleep screen's name in the rotation; outside what PAGE_RE allows a user page to be called.
SLEEP_PAGE = "sleep screen"

# Firmware-plumbing sensors from before the frame file carried its own
# directory. Nothing reads them; they are withdrawn unless a page uses one.
RETIRED_SENSORS = (
    "sensor.epaper_category_count",
    "sensor.epaper_category_offsets",
    "sensor.epaper_category_sizes",
    "sensor.epaper_category_pill_widths",
    "sensor.epaper_category_names",
)

ENTITY_RE = re.compile(r"^[a-z0-9_]+\.[a-z0-9_]+$")
PAGE_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


def valid_entity_id(eid: str) -> bool:
    return bool(eid and ENTITY_RE.match(str(eid).strip()))


# The Supervisor's Ingress proxy. Under Home Assistant it is the only client
# the editor should ever see: anything else is another app on the internal
# network reaching the editor without a login.
INGRESS_GATEWAY = "172.30.32.2"
UNDER_SUPERVISOR = bool(os.environ.get("SUPERVISOR_TOKEN"))
