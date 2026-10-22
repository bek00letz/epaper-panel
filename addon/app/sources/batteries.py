"""Which batteries you charge yourself, by their device (the Batteries preset's first ticks).

A phone, a watch, a laptop, a car or a home battery says whether it's charging: its device has a
charging-state entity beside the battery level (a binary sensor of device class battery_charging,
or a sensor whose states are charging and not charging). A battery you swap, in a remote or a
door sensor, has none. Read from Home Assistant's entity registry (which entity is on which
device) and its states (each entity's device class, state and options), so it doesn't depend on
how anything is named. A battery with no device gets None, and the editor falls back to names.
"""
from __future__ import annotations

import runtime
from config import HA_TOKEN
from ha import ha_json

# What a charging-state sensor says (lower case): Home Assistant's mobile app, laptops, cars, inverters.
CHARGING_WORDS = {"charging", "not charging", "not_charging", "discharging", "full", "fully charged"}


def says_charging(st: dict) -> bool:
    """Whether a state (as /api/states gives it) is a charging state."""
    attrs = st.get("attributes") or {}
    if attrs.get("device_class") == "battery_charging":
        return True
    said = {str(st.get("state") or "").strip().lower()}
    said |= {str(o).strip().lower() for o in attrs.get("options") or [] if isinstance(o, str)}
    return bool(said & CHARGING_WORDS) and "charging" in " ".join(said)


def is_battery(st: dict) -> bool:
    attrs = st.get("attributes") or {}
    return (str(st.get("entity_id", "")).startswith("sensor.") and attrs.get("device_class") == "battery"
            and str(attrs.get("unit_of_measurement") or "").strip() == "%")


def charged_by_you(registry: list, states: list) -> dict:
    """{battery sensor: True (its device says whether it's charging), False (it has a device that
    doesn't), None (no device: the editor goes by its name)}."""
    device_of = {e.get("entity_id"): e.get("device_id") for e in registry or [] if isinstance(e, dict)}
    charging_devices = {device_of.get(st.get("entity_id")) for st in states or [] if isinstance(st, dict) and says_charging(st)}
    charging_devices.discard(None)
    out = {}
    for st in states or []:
        if isinstance(st, dict) and is_battery(st):
            dev = device_of.get(st["entity_id"])
            out[st["entity_id"]] = None if not dev else dev in charging_devices
    return out


async def fetch(session) -> dict:
    """charged_by_you() for this Home Assistant; {} offline (the editor goes by names)."""
    if not HA_TOKEN:
        return {}
    registry = await runtime.HASS.ws({"type": "config/entity_registry/list"})
    states = await ha_json(session, "/states")
    return charged_by_you(registry, states)
