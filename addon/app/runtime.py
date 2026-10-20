"""Runtime state: what the running add-on holds: the current frames, the shared HTTP session, and the shared helpers."""

import os
import re
import time
import aiohttp

import live_data
from hass import Hass
from panel_link import PanelLink
from render.linger import Linger
from config import HA_BASE, HA_TOKEN


ESPHOME_DEVICE = (
    re.sub(r"[^a-z0-9_]+", "_", (os.environ.get("ESPHOME_DEVICE") or "crowpanel_epaper").strip().lower()).strip("_")
    or "crowpanel_epaper"
)

ENTITY_CACHE = {"at": 0.0, "items": []}
SESSION: aiohttp.ClientSession | None = None
HASS = Hass(HA_BASE, HA_TOKEN, lambda: SESSION)
PUBLISHER: "mqtt_bridge.EntityPublisher | None" = None
# Outside data is fetched in the background; renders only read it (live_data).
LIVE = live_data.LiveData()
live = lambda interval, stale_after=None: LIVE.decorate(interval, lambda: SESSION, stale_after)  # noqa: E731

PUBLISHED: dict[str, dict] = {}


class Frames:
    """The current render. Readers take a reference; the writer replaces it."""

    def __init__(self):
        self.strip = b""
        self.single = b""
        self.epf_strip: bytes = b""
        self.epf_single: bytes = b""
        self.slices: list[bytes] = []
        self.strip_etag = ""
        self.single_etag = ""
        self.epf_strip_etag = ""
        self.epf_single_etag = ""
        self.names: list[str] = []
        self.cat_offsets: list[int] = [0]
        self.cat_sizes: list[int] = [1]
        self.cat_pill_widths: list[int] = [110]
        self.cat_names: list[str] = []
        self.cat_ids: list[int] = []
        self.sub_ids: list[int] = []
        self.cat_count: int = 1
        self.quiet_active: bool = False
        self.quiet_reason: str = "disabled"
        self.rotate_seconds: int = 30
        self.last_modified: str = ""
        self.rendered_at = None
        self.error = None


class DeviceRuntime:
    """What the running add-on holds for one device: its current render and how to reach it."""

    def __init__(self, device_id: str):
        self.id = device_id
        self.frames = Frames()
        self.fit: dict | None = None             # what frames.fit_counts left out, for the editor
        self.link: PanelLink | None = None       # set by the device's kind when it can be reached
        self.kind: dict = {}                     # what the device's kind keeps between requests


_DEVICES: dict[str, DeviceRuntime] = {}


def device(device_id: str) -> DeviceRuntime:
    found = _DEVICES.get(device_id)
    if found is None:
        found = _DEVICES[device_id] = DeviceRuntime(device_id)
    return found


def forget_devices_except(ids) -> None:
    for k in [k for k in _DEVICES if k not in set(ids)]:
        del _DEVICES[k]


def new_alert() -> dict:
    return {"name": None, "until": 0.0, "fired": {}}


# Per design: which alert page, if any, currently owns its screens.
ALERTS: dict[str, dict] = {}

# Per design: conditional widget pages that stay a while after their condition.
LINGERS: dict[str, Linger] = {}


def alert(design_id: str) -> dict:
    return ALERTS.setdefault(design_id, new_alert())


def linger(design_id: str) -> Linger:
    return LINGERS.setdefault(design_id, Linger())


FEED_ITEMS = {}


MQTT_DISCOVERED: set[str] = set()

# The companion integration was updated at this start: Home Assistant runs the old copy until it restarts.
COMPANION_UPDATED = False


LAST_PANEL_PUSH_TIME = time.time()


# Caches keyed by what pages ask for (a place, a league, an entity) keep only
# what was used in the last day, so editing pages for months doesn't grow them.
CACHE_DAY = 86400.0


def prune(cache: dict, max_age: float = CACHE_DAY) -> None:
    now = time.time()
    for k in [k for k, v in cache.items() if isinstance(v, dict) and now - v.get("at", now) > max_age]:
        del cache[k]


# How many bytes of frame file a panel can hold. New firmware says so on
# every download (?cap=), remembered across restarts; older firmware holds 1 MiB.
def panel_capacity(device_id: str) -> int:
    import devices
    from render import epf
    try:
        return int(devices.state(device_id)["capacity"])
    except (KeyError, TypeError, ValueError):
        return epf.DEFAULT_CAPACITY


def set_panel_capacity(device_id: str, value: int) -> bool:
    """Remember what a panel says it holds. Returns whether it changed."""
    import devices
    value = max(256 * 1024, min(16 * 1024 * 1024, int(value)))
    if value == panel_capacity(device_id):
        return False
    devices.set_state(device_id, capacity=value)
    print(f"frames: device {device_id} holds {value // 1024} KB of pages", flush=True)
    return True
