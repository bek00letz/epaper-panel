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
    "network": ("text_sensor", "Panel Wi-Fi network"),      # firmware 0.14.1 and later
    # The panel's own settings, shown in the editor (firmware 0.9.5 and later).
    "sleep": ("switch", "Sleep"),
    "ghost_after": ("number", "Ghost clear after"),
    "ghost_mode": ("select", "Ghost clearing"),
    "clear_ghosting": ("button", "Clear ghosting"),
}

# What each device setting is, and how Home Assistant changes it.
DEVICE_SETTINGS = ("sleep", "ghost_after", "ghost_mode", "clear_ghosting")

DISCOVERY_TTL = 300.0
RETRY_STEPS = (5.0, 15.0, 30.0, 60.0)


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(s).lower()).strip("_")


def unique_id_is(uid: str, domain: str, name: str) -> bool:
    """Match ESPHome's unique_id for an entity, in both formats it has used.

    Current:  `00:00:5E:00:53:01/0/number/Refresh interval`
    Older:    `00005e005301-number-refresh_interval`
    """
    uid = str(uid or "")
    parts = uid.split("/")
    if len(parts) >= 3 and parts[-2] == domain and parts[-1].lower() == name.lower():
        return True
    return uid.lower().endswith(f"-{domain}-{_slug(name)}")


class PanelLink:
    def __init__(self, hass: Hass, preferred_node=lambda: "", sole=lambda: True, ha_name=lambda: ""):
        """`preferred_node`: the panel's ESPHome node, if set up. `sole`: whether the
        add-on drives only one panel, so the only one in Home Assistant must be it.
        `ha_name`: the name its firmware gives it in Home Assistant, which tells
        several panels' entities apart."""
        self.hass = hass
        self._preferred = preferred_node
        self._sole = sole
        self._ha_name = ha_name
        self.node: str | None = None
        self.entities: dict[str, str] = {}
        self.problem: str = "not looked for the panel yet"
        self._discovered_at = 0.0

        self.pending: str | None = None
        self._attempts = 0
        self._next_attempt = 0.0
        self.last_ok_at: float | None = None
        self.last_error: str | None = None

    def preferred_node(self) -> str:
        return _slug(self._preferred() or "")

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
        elif len(nodes) == 1 and self._sole():
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
            self.problem = (f"Home Assistant has no panel called {preferred} (it has {', '.join(nodes)}). "
                            "Check the device name in Panel setup" if preferred else
                            f"found {len(nodes)} panel{'' if len(nodes) == 1 else 's'} ({', '.join(nodes)}). "
                            "Set the device name in Panel setup to pick one")
            self.entities = {}
            return False

        self.entities = await self._find_entities(single_panel=len(nodes) == 1 and self._sole())
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
        panels = {dev_id: ents for dev_id, ents in by_device.items() if "refresh" in ents}
        if len(panels) == 1 and single_panel:
            return next(iter(panels.values()))
        # Several panels: each one's firmware names it after its screen, and Home
        # Assistant's device has that name. Exactly one match, or report rather than guess.
        want = (self._ha_name() or "").strip()
        if not want:
            return {}
        try:
            registry = await self.hass.ws({"type": "config/device_registry/list"})
        except HassError as exc:
            print(f"panel: couldn't read the device registry: {exc}", flush=True)
            return {}
        named = [d.get("id") for d in registry or [] if d.get("name") == want and d.get("id") in panels]
        return panels[named[0]] if len(named) == 1 else {}

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

    async def device_settings(self) -> dict:
        """The panel's Sleep and ghost-clearing settings as Home Assistant has them.

        A setting the panel doesn't have (older firmware) or that Home
        Assistant can't read is None, so the editor can leave it out.
        """
        await self.discover()
        out = {"available": bool(self.node), "problem": "" if self.node else self.problem,
               "sleep": None, "ghost_after": None, "ghost_mode": None, "ghost_modes": [],
               "can_clear": bool(self.entities.get("clear_ghosting"))}
        for key in ("sleep", "ghost_after", "ghost_mode"):
            ent = self.entities.get(key)
            if not ent:
                continue
            try:
                st = await self.hass.rest("GET", f"/states/{ent}")
            except HassError:
                continue
            val = st.get("state")
            if val in (None, "", "unknown", "unavailable"):
                continue
            if key == "sleep":
                out["sleep"] = val == "on"
            elif key == "ghost_after":
                try:
                    out["ghost_after"] = int(float(val))
                except (TypeError, ValueError):
                    pass
            else:
                out["ghost_mode"] = val
                out["ghost_modes"] = list((st.get("attributes") or {}).get("options") or [])
        return out

    async def set_device_setting(self, key: str, value) -> tuple[bool, str]:
        """Change one of the panel's settings through Home Assistant. Returns (accepted, error)."""
        if key not in DEVICE_SETTINGS:
            return False, "not a panel setting"
        if not await self.discover():
            return False, self.problem
        ent = self.entities.get(key)
        if not ent:
            return False, "this panel's firmware doesn't have that setting yet. Reinstall it from Panel setup"
        if key == "sleep":
            call = ("switch", "turn_on" if value else "turn_off", {"entity_id": ent})
        elif key == "ghost_after":
            try:
                n = max(2, min(60, int(value)))
            except (TypeError, ValueError):
                return False, "the number of refreshes must be a whole number"
            call = ("number", "set_value", {"entity_id": ent, "value": n})
        elif key == "ghost_mode":
            call = ("select", "select_option", {"entity_id": ent, "option": str(value)})
        else:
            call = ("button", "press", {"entity_id": ent})
        try:
            await self.hass.rest("POST", f"/services/{call[0]}/{call[1]}", json=call[2])
            return True, ""
        except HassError as exc:
            return False, _human_error(str(exc))

    async def connection(self) -> dict:
        await self.discover()
        out = {"connected": False, "ip": None, "rssi": None, "network": None, "node": self.node, "problem": self.problem}
        for key, field in (("ip", "ip"), ("wifi", "rssi"), ("network", "network")):
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
