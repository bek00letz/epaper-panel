"""Which batteries you charge yourself, by their device (the Batteries preset's first ticks).

A phone, a watch, a laptop, a car or a home battery says whether it's charging: its device has a
charging-state entity beside the battery level (a binary sensor of device class battery_charging,
or a sensor whose states are charging and not charging). A battery you swap, in a remote or a
door sensor, has none. Read from Home Assistant's entity registry (which entity is on which
device) and its states (each entity's device class, state and options), so it doesn't depend on
how anything is named. A battery with no device gets None, and the editor falls back to names.
"""
from __future__ import annotations

import re

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


# ---------------------------------------------------------------- Batteries as a rule (review 2 #5)
#
# A Batteries page stores a rule, not the batteries that existed the day it was made (the user's call,
# 22 Oct): every battery of its kind ("swap": you change it; "charge": you charge it, from
# charged_by_you), past the page's number, minus the ones unticked (`except`), plus any of the other
# kind ticked (`also`). Resolved at each render from Home Assistant's battery entities, binary
# "battery low" sensors included: they count as below whenever they're on. Its `items` are each
# battery's own settings (a threshold, an icon, a name), never the list.

KINDS = ("swap", "charge")


def is_battery_low_sensor(st: dict) -> bool:
    """A binary sensor of device class battery: on means low (Zigbee and Z-Wave devices)."""
    attrs = st.get("attributes") or {}
    return str(st.get("entity_id", "")).startswith("binary_sensor.") and attrs.get("device_class") == "battery"


def _by_name(eid: str, ids: set) -> bool:
    """With no device to ask: a charging-state sensor named beside it, as the mobile app names them
    (the editor's presets.chargedByYou, for a battery Home Assistant gave no device)."""
    base = eid.split(".", 1)[1]
    for suffix in ("_battery_level", "_battery"):
        if base.endswith(suffix):
            base = base[: -len(suffix)]
            break
    return any(x in ids for x in (f"sensor.{base}_battery_state", f"sensor.{base}_charging",
                                  f"binary_sensor.{base}_charging", f"binary_sensor.{base}_battery_charging"))


def every_battery(registry: list, states: list) -> list[dict]:
    """Every battery Home Assistant has, a level in % or a low sensor: [{"entity", "state", "name",
    "unit", "device_class", "changed", "kind"}], `kind` swap or charge."""
    device_of = {e.get("entity_id"): e.get("device_id") for e in registry or [] if isinstance(e, dict)}
    charging = {device_of.get(st.get("entity_id")) for st in states or [] if isinstance(st, dict) and says_charging(st)}
    charging.discard(None)
    ids = {st.get("entity_id") for st in states or [] if isinstance(st, dict)}
    out = []
    for st in states or []:
        if not isinstance(st, dict) or not (is_battery(st) or is_battery_low_sensor(st)):
            continue
        eid, attrs, dev = st["entity_id"], st.get("attributes") or {}, device_of.get(st["entity_id"])
        yours = (dev in charging) if dev else _by_name(eid, ids)
        out.append({"entity": eid, "state": str(st.get("state") or ""), "name": attrs.get("friendly_name") or "",
                    "unit": attrs.get("unit_of_measurement") or "", "device_class": "battery",
                    "changed": st.get("last_changed") or "", "kind": "charge" if yours else "swap"})
    return out


def chosen(el: dict, every: list[dict]) -> list[dict]:
    """The batteries a page's rule picks, in Home Assistant's order: its kind, minus `except`, plus `also`."""
    kind = el.get("batteries") if el.get("batteries") in KINDS else "swap"
    left_out = set(el.get("except") or [])
    also = set(el.get("also") or [])
    return [b for b in every if (b["kind"] == kind and b["entity"] not in left_out) or b["entity"] in also]


def past(b: dict, el: dict) -> bool:
    """Whether a battery is past its page's number (or its own): a level below or at least it; a low
    sensor counts as below while it's on, and never as charged."""
    rule = el.get("filter_rule") if el.get("filter_rule") in ("below", "at_least") else "below"
    own = next((it.get("threshold") for it in el.get("items") or [] if isinstance(it, dict)
                and it.get("entity") == b["entity"] and it.get("threshold") not in (None, "")), None)
    if b["entity"].startswith("binary_sensor."):
        return rule == "below" and b["state"].lower() == "on"
    try:
        level, limit = float(b["state"]), float(own if own is not None else el.get("filter_value"))
    except (TypeError, ValueError):
        return False
    return level < limit if rule == "below" else level >= limit


def offline() -> list[dict]:
    """every_battery() from the offline fixture (render/fixture.json): examples, never someone's."""
    from fixture import load_fixture
    states = [{"entity_id": eid, "state": info.get("state"),
               "attributes": {"device_class": info.get("device_class"), "unit_of_measurement": info.get("unit"),
                              "friendly_name": info.get("friendly_name")}}
              for eid, info in (load_fixture().get("states") or {}).items()]
    return every_battery([], states)


@runtime.live(120)
async def fetch_every(session) -> list[dict]:
    """every_battery() for this Home Assistant, in the background (a render never waits)."""
    if not HA_TOKEN:
        return offline()
    registry = await runtime.HASS.ws({"type": "config/entity_registry/list"})
    states = await ha_json(session, "/states")
    return every_battery(registry, states)


# ---------------------------------------------------------------- pages made before the rule

# The condition a Devices grid wrote over its own list (the editor's conditions.gridShowIf).
_GRID_PART = re.compile(r"^\(has_value\('([^']+)'\) and states\('\1'\) \| float\(0\) (?:<|>=) -?\d+(?:\.\d+)?\)$")


def _grid_wrote(show_if: str) -> bool:
    s = str(show_if or "").strip()
    if not (s.startswith("{{") and s.endswith("}}")):
        return False
    return all(_GRID_PART.match(p.strip()) for p in re.split(r"\s+or\s+(?=\(has_value)", s[2:-2].strip()))


def migrate(pages: dict, every: list[dict]) -> list[str]:
    """Batteries pages made before the rule follow it from now on (the user's call, 22 Oct), showing
    what they showed: its kind is the one its way picks (low: swapped; charged: charged), the
    batteries of that kind not ticked go in `except`, those of the other kind ticked in `also`. Only a
    Devices grid by a number whose every item is one of Home Assistant's batteries. The condition it
    wrote over its old list goes: the rule decides now (widgets.py's gate). Returns the pages changed."""
    known = {b["entity"]: b for b in every}
    changed = []
    for name, page in (pages or {}).items():
        for el in (page or {}).get("elements") or []:
            if not isinstance(el, dict) or el.get("type") != "dynamic_grid" or el.get("batteries"):
                continue
            items = [it.get("entity") for it in el.get("items") or [] if isinstance(it, dict) and it.get("entity")]
            if el.get("filter_rule") not in ("below", "at_least") or not items or not all(e in known for e in items):
                continue
            kind = "swap" if el["filter_rule"] == "below" else "charge"
            ticked = set(items)
            el["batteries"] = kind
            el["except"] = [b["entity"] for b in every if b["kind"] == kind and b["entity"] not in ticked]
            el["also"] = [e for e in items if known[e]["kind"] != kind]
            if _grid_wrote(page.get("show_if")):
                page.pop("show_if", None)
            changed.append(name)
    return changed
