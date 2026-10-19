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
LINK = PanelLink(HASS, lambda: ESPHOME_DEVICE)
PUBLISHER: "mqtt_bridge.EntityPublisher | None" = None
WIDGET_LINGER = Linger()
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


FRAMES = Frames()

# Which alert page, if any, currently owns the screen.
ALERT = {"name": None, "until": 0.0, "fired": {}}
FEED_ITEMS = {}


MQTT_DISCOVERED: set[str] = set()


LAST_PANEL_PUSH_TIME = time.time()


# Caches keyed by what pages ask for (a place, a league, an entity) keep only
# what was used in the last day, so editing pages for months doesn't grow them.
CACHE_DAY = 86400.0


def prune(cache: dict, max_age: float = CACHE_DAY) -> None:
    now = time.time()
    for k in [k for k, v in cache.items() if isinstance(v, dict) and now - v.get("at", now) > max_age]:
        del cache[k]


# How many bytes of frame file the panel can hold. New firmware says so on
# every download (?cap=), remembered across restarts; older firmware holds 1 MiB.
FIT: dict | None = None                     # what frames.fit_counts left out, for the editor
_capacity: int | None = None


def panel_capacity() -> int:
    global _capacity
    if _capacity is None:
        import config
        from render import epf
        try:
            _capacity = int((config.DATA_DIR / "panel_capacity").read_text())
        except (OSError, ValueError):
            _capacity = epf.DEFAULT_CAPACITY
    return _capacity


def set_panel_capacity(value: int) -> bool:
    """Remember what the panel says it holds. Returns whether it changed."""
    global _capacity
    import config
    value = max(256 * 1024, min(16 * 1024 * 1024, int(value)))
    if value == panel_capacity():
        return False
    _capacity = value
    try:
        (config.DATA_DIR / "panel_capacity").write_text(str(value))
    except OSError:
        pass
    print(f"frames: the panel holds {value // 1024} KB of pages", flush=True)
    return True
