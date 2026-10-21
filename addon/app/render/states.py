"""What a state is called, and its icon: Home Assistant's own words, by domain and device class.

A Status page shows any entity's state in words. A door says Open and
Closed, a motion sensor Detected and Clear, a person Home and Away: the
words Home Assistant itself uses (its frontend's English), so a switch never
reads "Open". Looked up by "domain.device_class", then the domain; the
person can still change the words on the page. Served to the editor in the
catalog (/api/catalog), the one table both use.
"""
from __future__ import annotations

ON_OFF = {"on": ("On", "mdi:toggle-switch"), "off": ("Off", "mdi:toggle-switch-off-outline")}


def _bs(on: str, off: str, icon_on: str, icon_off: str) -> dict:
    return {"on": (on, icon_on), "off": (off, icon_off)}


STATES: dict[str, dict[str, tuple[str, str]]] = {
    # binary_sensor, by device class (on, then off)
    "binary_sensor.battery": _bs("Low", "Normal", "mdi:battery-alert", "mdi:battery"),
    "binary_sensor.battery_charging": _bs("Charging", "Not charging", "mdi:battery-charging", "mdi:battery"),
    "binary_sensor.carbon_monoxide": _bs("Detected", "Clear", "mdi:molecule-co", "mdi:check-circle-outline"),
    "binary_sensor.cold": _bs("Cold", "Normal", "mdi:snowflake", "mdi:thermometer"),
    "binary_sensor.connectivity": _bs("Connected", "Disconnected", "mdi:check-network-outline", "mdi:close-network-outline"),
    "binary_sensor.door": _bs("Open", "Closed", "mdi:door-open", "mdi:door-closed"),
    "binary_sensor.garage_door": _bs("Open", "Closed", "mdi:garage-open", "mdi:garage"),
    "binary_sensor.gas": _bs("Detected", "Clear", "mdi:alert-circle", "mdi:check-circle-outline"),
    "binary_sensor.heat": _bs("Hot", "Normal", "mdi:fire", "mdi:thermometer"),
    "binary_sensor.light": _bs("Light detected", "No light", "mdi:brightness-5", "mdi:brightness-3"),
    "binary_sensor.lock": _bs("Unlocked", "Locked", "mdi:lock-open", "mdi:lock"),
    "binary_sensor.moisture": _bs("Wet", "Dry", "mdi:water", "mdi:water-off"),
    "binary_sensor.motion": _bs("Detected", "Clear", "mdi:motion-sensor", "mdi:motion-sensor-off"),
    "binary_sensor.moving": _bs("Moving", "Not moving", "mdi:axis-arrow", "mdi:circle-outline"),
    "binary_sensor.occupancy": _bs("Detected", "Clear", "mdi:home-account", "mdi:home-outline"),
    "binary_sensor.opening": _bs("Open", "Closed", "mdi:square-outline", "mdi:square"),
    "binary_sensor.plug": _bs("Plugged in", "Unplugged", "mdi:power-plug", "mdi:power-plug-off"),
    "binary_sensor.power": _bs("On", "Off", "mdi:power-plug", "mdi:power-plug-off"),
    "binary_sensor.presence": _bs("Home", "Away", "mdi:home", "mdi:home-outline"),
    "binary_sensor.problem": _bs("Problem", "OK", "mdi:alert-circle", "mdi:check-circle"),
    "binary_sensor.running": _bs("Running", "Not running", "mdi:play", "mdi:stop"),
    "binary_sensor.safety": _bs("Unsafe", "Safe", "mdi:alert-circle", "mdi:check-circle"),
    "binary_sensor.smoke": _bs("Detected", "Clear", "mdi:smoke-detector-alert", "mdi:smoke-detector"),
    "binary_sensor.sound": _bs("Detected", "Clear", "mdi:music-note", "mdi:music-note-off"),
    "binary_sensor.tamper": _bs("Tampering detected", "Clear", "mdi:alert", "mdi:check-circle-outline"),
    "binary_sensor.update": _bs("Update available", "Up-to-date", "mdi:package-up", "mdi:package"),
    "binary_sensor.vibration": _bs("Detected", "Clear", "mdi:vibrate", "mdi:crop-portrait"),
    "binary_sensor.window": _bs("Open", "Closed", "mdi:window-open", "mdi:window-closed"),
    "binary_sensor": _bs("On", "Off", "mdi:checkbox-marked-circle", "mdi:checkbox-blank-circle-outline"),
    # other domains, by state
    "switch": ON_OFF,
    "input_boolean": ON_OFF,
    "light": {"on": ("On", "mdi:lightbulb-on"), "off": ("Off", "mdi:lightbulb-outline")},
    "fan": {"on": ("On", "mdi:fan"), "off": ("Off", "mdi:fan-off")},
    "lock": {"locked": ("Locked", "mdi:lock"), "unlocked": ("Unlocked", "mdi:lock-open"), "open": ("Open", "mdi:lock-open"),
             "jammed": ("Jammed", "mdi:lock-alert"), "locking": ("Locking", "mdi:lock-clock"), "unlocking": ("Unlocking", "mdi:lock-clock")},
    "cover": {"open": ("Open", "mdi:window-shutter-open"), "closed": ("Closed", "mdi:window-shutter"),
              "opening": ("Opening", "mdi:arrow-up-box"), "closing": ("Closing", "mdi:arrow-down-box")},
    "cover.garage": {"open": ("Open", "mdi:garage-open"), "closed": ("Closed", "mdi:garage"),
                     "opening": ("Opening", "mdi:arrow-up-box"), "closing": ("Closing", "mdi:arrow-down-box")},
    "cover.door": {"open": ("Open", "mdi:door-open"), "closed": ("Closed", "mdi:door-closed"),
                   "opening": ("Opening", "mdi:door-open"), "closing": ("Closing", "mdi:door-closed")},
    "person": {"home": ("Home", "mdi:home-account"), "not_home": ("Away", "mdi:account-arrow-right")},
    "device_tracker": {"home": ("Home", "mdi:home-account"), "not_home": ("Away", "mdi:account-arrow-right")},
    "media_player": {"playing": ("Playing", "mdi:play"), "paused": ("Paused", "mdi:pause"), "idle": ("Idle", "mdi:sleep"),
                     "on": ("On", "mdi:power"), "off": ("Off", "mdi:power-off"), "standby": ("Standby", "mdi:power-sleep"),
                     "buffering": ("Buffering", "mdi:timer-sand")},
    "alarm_control_panel": {"disarmed": ("Disarmed", "mdi:shield-off"), "armed_home": ("Armed home", "mdi:shield-home"),
                            "armed_away": ("Armed away", "mdi:shield-lock"), "armed_night": ("Armed night", "mdi:shield-moon"),
                            "armed_vacation": ("Armed vacation", "mdi:shield-airplane"), "arming": ("Arming", "mdi:shield-sync"),
                            "pending": ("Pending", "mdi:shield-sync"), "triggered": ("Triggered", "mdi:bell-ring")},
    "climate": {"off": ("Off", "mdi:power-off"), "heat": ("Heat", "mdi:fire"), "cool": ("Cool", "mdi:snowflake"),
                "heat_cool": ("Heat/Cool", "mdi:sun-snowflake-variant"), "auto": ("Auto", "mdi:thermostat-auto"),
                "dry": ("Dry", "mdi:water-percent"), "fan_only": ("Fan only", "mdi:fan")},
    "vacuum": {"cleaning": ("Cleaning", "mdi:robot-vacuum"), "docked": ("Docked", "mdi:home-import-outline"),
               "returning": ("Returning", "mdi:home-import-outline"), "idle": ("Idle", "mdi:robot-vacuum-off"),
               "paused": ("Paused", "mdi:pause"), "error": ("Error", "mdi:alert-circle")},
    "timer": {"idle": ("Idle", "mdi:timer-outline"), "active": ("Active", "mdi:timer"), "paused": ("Paused", "mdi:timer-pause")},
    "sun": {"above_horizon": ("Above horizon", "mdi:white-balance-sunny"), "below_horizon": ("Below horizon", "mdi:weather-night")},
    "update": {"on": ("Update available", "mdi:package-up"), "off": ("Up-to-date", "mdi:package")},
}


def words(entity_id: str, device_class: str = "") -> dict[str, tuple[str, str]]:
    """{state: (word, icon)} for an entity: its domain and device class, then its domain; {} when none is known."""
    domain = str(entity_id or "").split(".", 1)[0]
    return STATES.get(f"{domain}.{device_class}") or STATES.get(domain) or {}


NO_STATE = ("", "unavailable", "unknown", "none")
MOST = 24                      # a list longer than this is a value, not a set of states


def offered(entity_id: str, device_class: str = "", options=(), seen=(), drawable=lambda icon: True) -> list[dict]:
    """The states an icon that follows an entity offers, each with an icon: [{"state", "word", "icon"}].

    In order: Home Assistant's own for its kind (`words`), the choices it lists (`options`), then
    what it was (`seen`: (state, icon) newest first, its state now first). One row per state,
    whatever its case, spelt as Home Assistant spells it; no value (unavailable, unknown) is never
    one, it's what "Anything else" is for. The icon is the one the entity itself had in that state
    when its icon changes with its state (a template's icon), else Home Assistant's for its kind,
    else the one it always has; "" when none is known. Only icons `drawable` says the panel can draw
    are offered, so a state never gets one that shows as nothing.
    """
    kind = words(entity_id, device_class)
    had: dict[str, str] = {}
    for st, ic in seen or ():
        k = str(st or "").strip().lower()
        if k not in NO_STATE and k not in had:
            had[k] = str(ic or "")
    own = {ic for ic in had.values() if ic}
    varies = len(own) > 1                 # its icon changes with its state (a template's)
    had = {k: ic if ic and drawable(ic) else "" for k, ic in had.items()}
    own = {ic for ic in own if drawable(ic)}
    out, keys = [], set()
    names = list(kind) + [str(o) for o in (options or ()) if isinstance(o, (str, int, float))]
    names += [str(st).strip() for st, _ in (seen or ())]
    for name in names:
        k = name.strip().lower()
        if k in NO_STATE or k in keys:
            continue
        keys.add(k)
        word, kind_icon = kind.get(name, (name, ""))
        kind_icon = kind_icon if kind_icon and drawable(kind_icon) else ""
        icon = had.get(k, "") or kind_icon if varies else kind_icon or next(iter(own), "")
        out.append({"state": name, "word": word, "icon": icon})
        if len(out) >= MOST:
            break
    return out


def catalog() -> dict:
    """The table as the editor reads it: {"<domain>[.<class>]": {state: {"word", "icon"}}}."""
    return {k: {st: {"word": w, "icon": i} for st, (w, i) in v.items()} for k, v in STATES.items()}
