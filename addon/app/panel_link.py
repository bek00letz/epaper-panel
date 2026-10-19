"""How the add-on reaches the physical panel, through Home Assistant.

The panel is an ESPHome device, and the add-on talks to it two ways:

  * actions such as `esphome.<node>_refresh_now`, named after the ESPHome node;
  * a few of its entities (refresh interval, IP, Wi-Fi), named however the
    user has since renamed them.

Neither name is guessed. Actions are found in Home Assistant's service list.
Entities are found by their registry unique_id, which ESPHome derives from the
firmware's own entity names and which survives any rename.

A refresh the panel must not miss -- new content, an alert, waking up after
quiet hours -- stays pending until Home Assistant confirms it was delivered,
and is retried with a backoff until then.
"""
from __future__ import annotations

import re
import time

from hass import Hass, HassError

# Actions every panel firmware exposes; a node offering all of them is a panel.
PANEL_ACTIONS = ("refresh_now", "page_step", "show_page")

# Firmware entity names, as ESPHome puts them into unique_ids.
ENTITY_KEYS = {
    "refresh": ("number", "Refresh interval"),
    "ip": ("text_sensor", "Panel IP"),
    "wifi": ("sensor", "Panel Wi-Fi"),
}

DISCOVERY_TTL = 300.0
RETRY_STEPS = (5.0, 15.0, 30.0, 60.0)


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(s).lower()).strip("_")


def unique_id_is(uid: str, domain: str, name: str) -> bool:
    """Match ESPHome's unique_id for an entity, in both formats it has used.

    Current:  `44:1B:F6:D1:45:04/0/number/Refresh interval`
    Older:    `441bf6d14504-number-refresh_interval`
    """
    uid = str(uid or "")
    parts = uid.split("/")
    if len(parts) >= 3 and parts[-2] == domain and parts[-1].lower() == name.lower():
        return True
    return uid.lower().endswith(f"-{domain}-{_slug(name)}")


class PanelLink:
    def __init__(self, hass: Hass, preferred_node=lambda: ""):
        self.hass = hass
        self._preferred = preferred_node
        self.node: str | None = None
        self.entities: dict[str, str] = {}
        self.problem: str = "not looked for the panel yet"
        self._discovered_at = 0.0

        self.pending: str | None = None
        self._attempts = 0
        self._next_attempt = 0.0
        self.last_ok_at: float | None = None
        self.last_error: str | None = None

    # ------------------------------------------------------------------ discovery
    async def discover(self, force: bool = False) -> bool:
        if not force and self.node and time.time() - self._discovered_at < DISCOVERY_TTL:
            return True
        if not self.hass.available:
            self.problem = "not connected to Home Assistant"
            return False
        try:
            services = await self.hass.rest("GET", "/services")
        except HassError as exc:
            self.problem = f"couldn't read Home Assistant's actions: {exc}"
            return False

        names = set()
        for dom in services or []:
            if isinstance(dom, dict) and dom.get("domain") == "esphome":
                names = set((dom.get("services") or {}).keys())
        nodes = sorted(n[: -len("_refresh_now")] for n in names
                       if n.endswith("_refresh_now")
                       and all(f"{n[: -len('_refresh_now')]}_{a}" in names for a in PANEL_ACTIONS))

        preferred = _slug(self._preferred() or "")
        if preferred in nodes:
            node = preferred
        elif len(nodes) == 1:
            node = nodes[0]
        else:
            node = None
        self.node = node
        self._discovered_at = time.time()

        if not nodes:
            self.problem = "no panel found in Home Assistant. Flash it, then add it under Settings → Devices"
            self.entities = {}
            return False
        if node is None:
            self.problem = (f"found {len(nodes)} panels ({', '.join(nodes)}). "
                            "Set the device name in Panel setup to pick one")
            self.entities = {}
            return False

        self.entities = await self._find_entities(single_panel=len(nodes) == 1)
        self.problem = ""
        return True

    async def _find_entities(self, single_panel: bool) -> dict[str, str]:
        """Entity IDs for the panel's refresh interval, IP and Wi-Fi, by unique_id."""
        try:
            entries = await self.hass.ws({"type": "config/entity_registry/list"})
        except HassError as exc:
            print(f"panel: couldn't read the entity registry: {exc}", flush=True)
            return {}
        by_device: dict[str, dict[str, str]] = {}
        for e in entries or []:
            if e.get("platform") != "esphome" or not e.get("device_id"):
                continue
            for key, (domain, name) in ENTITY_KEYS.items():
                if unique_id_is(e.get("unique_id"), domain, name):
                    by_device.setdefault(e["device_id"], {})[key] = e["entity_id"]
        panels = [ents for ents in by_device.values() if "refresh" in ents]
        if len(panels) == 1 and single_panel:
            return panels[0]
        # Several panel devices: there is no reliable link from an ESPHome node
        # name to its device, so report rather than guess.
        return {}

    # ------------------------------------------------------------------ actions
    async def call(self, action: str, data: dict | None = None) -> tuple[bool, str]:
        """Run `esphome.<node>_<action>`. Returns (delivered, error)."""
        if not await self.discover():
            return False, self.problem
        try:
            await self.hass.rest("POST", f"/services/esphome/{self.node}_{action}", json=data or {})
            return True, ""
        except HassError as exc:
            if exc.status in (400, 404) and "not found" in str(exc).lower():
                self._discovered_at = 0.0          # node renamed or removed: look again next time
            return False, _human_error(str(exc))

    def request_refresh(self, reason: str) -> None:
        """Ask the panel to fetch new frames. Coalesces; delivered by `deliver()`."""
        if self.pending is None:
            self._attempts = 0
            self._next_attempt = 0.0
        self.pending = reason

    async def deliver(self) -> bool:
        """Try to deliver a pending refresh, respecting the retry backoff."""
        if self.pending is None:
            return True
        now = time.time()
        if now < self._next_attempt:
            return False
        ok, err = await self.call("refresh_now")
        if ok:
            print(f"panel: refresh delivered ({self.pending})", flush=True)
            self.pending = None
            self._attempts = 0
            self.last_ok_at = now
            self.last_error = None
            return True
        if self.last_error != err:
            print(f"panel: refresh not delivered ({self.pending}): {err}. Will keep trying", flush=True)
        self.last_error = err
        self._next_attempt = now + RETRY_STEPS[min(self._attempts, len(RETRY_STEPS) - 1)]
        self._attempts += 1
        return False

    async def step(self, delta: int) -> tuple[bool, str]:
        return await self.call("page_step", {"delta": int(delta)})

    async def set_refresh_interval(self, minutes: int) -> tuple[bool, str]:
        if not await self.discover():
            return False, self.problem
        ent = self.entities.get("refresh")
        if not ent:
            return False, "couldn't find the panel's refresh interval in Home Assistant"
        try:
            await self.hass.rest("POST", "/services/number/set_value",
                                 json={"entity_id": ent, "value": int(minutes)})
            return True, ""
        except HassError as exc:
            return False, _human_error(str(exc))

    async def refresh_interval(self) -> int | None:
        """The interval the panel itself uses, in minutes, if it can be read."""
        ent = self.entities.get("refresh")
        if not ent:
            return None
        try:
            st = await self.hass.rest("GET", f"/states/{ent}")
            return max(1, int(float(st.get("state"))))
        except (HassError, TypeError, ValueError, AttributeError):
            return None

    async def connection(self) -> dict:
        await self.discover()
        out = {"connected": False, "ip": None, "rssi": None, "node": self.node, "problem": self.problem}
        for key, field in (("ip", "ip"), ("wifi", "rssi")):
            ent = self.entities.get(key)
            if not ent:
                continue
            try:
                st = await self.hass.rest("GET", f"/states/{ent}")
                val = st.get("state")
                if val not in (None, "", "unknown", "unavailable"):
                    out[field] = val
            except HassError:
                pass
        out["connected"] = bool(out["ip"] or out["rssi"])
        return out

    def status(self) -> dict:
        return {
            "node": self.node,
            "entities": dict(self.entities),
            "problem": self.problem,
            "pending_refresh": self.pending,
            "last_delivered_at": self.last_ok_at,
            "last_error": self.last_error,
        }


def _human_error(raw: str) -> str:
    low = raw.lower()
    if "not connected" in low or "connection not ready" in low:
        return "the panel is offline or reconnecting to Home Assistant"
    if "not found" in low:
        return "Home Assistant doesn't know this panel action. Was the panel renamed?"
    return raw[:200]
