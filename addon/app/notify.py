"""Phone notifications for a page, the Home Assistant way.

The add-on doesn't send notifications: automations in Home Assistant do, so
there is one place where automations live and the person can trace and change
them (the user's call, 22 Oct). The add-on's part:

- A page that asks ("Also notify my phone…", the page's `notify` id) gets one
  binary sensor, made only then: on while its alert holds
  (binary_sensor.epaper_alert_<page>) or while its "Only when" condition holds
  (binary_sensor.epaper_showing_<page>). Its unique_id is the notify id, so a
  renamed page keeps its entity. Nothing else is created.
- The blueprint it ships (`blueprints/notify.yaml`), installed into Home
  Assistant's blueprints when the first notification is set up.
- A normal automation made from that blueprint, with the phones the person
  picked in the editor. After that it is Home Assistant's: the editor only
  reads which automations use the sensor (`search/related`).
- A sensor an automation still uses is never withdrawn: when its page stops
  asking (deleted, or the person kept the automation), it stays, off, until
  nothing uses it. Only automations made from our blueprint are ever deleted,
  and only when the person says so.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from datetime import datetime
from pathlib import Path

import config
import devices
import health
import mqtt_bridge
import runtime
from hass import HassError
from layouts_store import load_draft

BLUEPRINT_PATH = "epaper_panel/notify.yaml"          # under Home Assistant's blueprints/automation/
NOTIFY_ID = re.compile(r"^[a-z0-9]{6,16}$")
SIGNAL_UID = mqtt_bridge.UID_PREFIX + mqtt_bridge.SIGNAL_PREFIX
KINDS = {"alert": ("alert", "mdi:bell-ring-outline"), "when": ("showing", "mdi:eye-outline")}
PENDING_FOR = 900.0          # a sensor just set up, before the page carrying its id is saved
USAGE_FOR = 600.0            # how long "an automation uses it" is trusted before asking again

# Set up from the editor, not yet in a saved draft or the panel's pages: id -> {design, page, kind, at}.
PENDING: dict[str, dict] = {}
# When each "Only when" page started showing, for its fired_at.
_SINCE: dict[str, float] = {}
# entity_id -> (when asked, automations and scripts using it, or None when Home Assistant couldn't say).
_USAGE: dict[str, tuple[float, list | None]] = {}


def page_title(name: str) -> str:
    """As the editor shows a page's name (util.pageTitle)."""
    text = str(name or "").replace("_", " ")
    return text[:1].upper() + text[1:]


def kind_of(page: dict) -> str:
    return "alert" if page.get("tier") == "alert" else "when"


def default_entity_id(page: dict, name: str) -> str:
    word = KINDS[kind_of(page)][0]
    slug = re.sub(r"[^a-z0-9]+", "_", str(name).lower()).strip("_")[:48] or "page"
    return f"binary_sensor.epaper_{word}_{slug}"


def clean_id(value) -> str:
    value = str(value or "").strip()
    return value if NOTIFY_ID.match(value) else ""


# ---------------------------------------------------------------- what asks

def _stopped_path() -> Path:
    return config.DATA_DIR / "notify.json"


def _load_stopped() -> dict:
    try:
        data = json.loads(_stopped_path().read_text())
        return data.get("stopped") or {} if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_stopped(stopped: dict) -> None:
    try:
        tmp = _stopped_path().with_suffix(".tmp")
        tmp.write_text(json.dumps({"stopped": stopped}, indent=1, sort_keys=True))
        tmp.replace(_stopped_path())
    except Exception as exc:
        print(f"notify: couldn't save what was stopped: {health.describe(exc)}", flush=True)


def requested(now: float | None = None) -> dict[str, dict]:
    """Every page asking for notifications: notify id -> {design, page, page_def, sent}.

    The pages each device shows (sent: its sensor follows the page) and each
    device's unsent draft (its sensor exists, off until the page is sent), plus
    one just set up. A stopped one doesn't ask, whatever a page still says,
    until it's set up again."""
    now = time.time() if now is None else now
    out: dict[str, dict] = {}
    for design_id in sorted(devices.designs_in_use()):
        for name, page in (devices.design(design_id).get("pages") or {}).items():
            if isinstance(page, dict) and (nid := clean_id(page.get("notify"))):
                out.setdefault(nid, {"design": design_id, "page": name, "page_def": page, "sent": True})
    for dev in devices.all_devices():
        draft = load_draft(dev["id"]) or {}
        for name, page in ((draft.get("spec") or {}).get("pages") or {}).items():
            if isinstance(page, dict) and (nid := clean_id(page.get("notify"))):
                out.setdefault(nid, {"design": dev["design"], "page": name, "page_def": page, "sent": False})
    for nid, p in list(PENDING.items()):
        if now - p["at"] > PENDING_FOR:
            PENDING.pop(nid, None)
        else:
            out.setdefault(nid, {"design": p["design"], "page": p["page"], "page_def": p["page_def"], "sent": False})
    stopped = _load_stopped()
    return {nid: r for nid, r in out.items() if nid not in stopped}


def kept() -> set[str]:
    """The sensors the configuration wants (entities.publish_computed keeps them): every
    one asked for, and every one an automation still used when last asked."""
    objs = {mqtt_bridge.SIGNAL_PREFIX + nid for nid in requested()}
    pub = runtime.PUBLISHER
    if pub is not None:
        objs |= {obj for obj, want in pub.desired.items()
                 if obj.startswith(mqtt_bridge.SIGNAL_PREFIX) and want["attrs"].get("page_removed")}
    return objs


# ---------------------------------------------------------------- the sensors

def _iso(ts: float | None) -> str | None:
    return datetime.fromtimestamp(ts).astimezone().isoformat(timespec="seconds") if ts else None


def signal(nid: str, req: dict, now: float | None = None) -> tuple[bool, dict]:
    """Whether a page's sensor is on now, and its attributes."""
    now = time.time() if now is None else now
    page, name = req["page_def"], req["page"]
    kind = kind_of(page)
    on, at = False, None
    if req["sent"] and kind == "alert":
        held = runtime.alert(req["design"]).get("active", {}).get(name)
        on, at = held is not None, held and held["at"]
    elif req["sent"] and page.get("tier") == "when":
        on = name in runtime.showing(req["design"])
    if kind == "when":
        if on:
            at = _SINCE.setdefault(nid, now)
        else:
            _SINCE.pop(nid, None)
    word, icon = KINDS[kind]
    title = page_title(name)
    return on, {"friendly_name": f"{title} {word}", "icon": icon,
                "default_entity_id": default_entity_id(page, name),
                "page": title, "kind": word, "fired_at": _iso(at)}


async def publish(hass) -> None:
    """Every requested page's sensor, then what's left of the rest: withdrawn, or kept
    (off) while an automation still uses it. Called once per render, after the alerts."""
    pub = runtime.PUBLISHER
    if pub is None:
        return
    reqs = requested()
    for nid, req in reqs.items():
        on, attrs = signal(nid, req)
        pub.set_signal(nid, on, attrs)
    for obj, seen in list(pub.last_seen.items()):
        nid = obj[len(mqtt_bridge.SIGNAL_PREFIX):]
        if not obj.startswith(mqtt_bridge.SIGNAL_PREFIX) or nid in reqs or seen == 0.0:
            continue
        eid = pub.entity_of(obj) or (pub.desired.get(obj) or {}).get("attrs", {}).get("default_entity_id")
        users = await usage(hass, eid) if eid else []
        if users is None or users:
            was = (pub.desired.get(obj) or {}).get("attrs") or {}
            pub.set_signal(nid, False, {**was, "fired_at": was.get("fired_at"), "page_removed": True})
        else:
            pub.retire(f"binary_sensor.{obj}")
            _SINCE.pop(nid, None)


# ---------------------------------------------------------------- Home Assistant

async def usage(hass, entity_id: str, fresh: bool = False) -> list | None:
    """Automations and scripts using an entity: [{id, entity_id, name, ours, targets, kind}],
    or None when Home Assistant couldn't say (then it counts as used)."""
    had = _USAGE.get(entity_id)
    if had and not fresh and time.time() - had[0] < USAGE_FOR:
        return had[1]
    try:
        found = await hass.ws({"type": "search/related", "item_type": "entity", "item_id": entity_id}) or {}
        out = []
        for kind in ("automation", "script"):
            for eid in sorted(found.get(kind) or []):
                out.append(await _describe(hass, kind, eid))
    except HassError as exc:
        print(f"notify: couldn't ask what uses {entity_id}: {exc}", flush=True)
        out = None
    _USAGE[entity_id] = (time.time(), out)
    return out


async def _describe(hass, kind: str, eid: str) -> dict:
    try:
        st = await hass.rest("GET", f"/states/{eid}") or {}
    except HassError:
        st = {}
    attrs = st.get("attributes") or {}
    item = {"kind": kind, "entity_id": eid, "id": str(attrs.get("id") or ""),
            "name": attrs.get("friendly_name") or eid, "ours": False, "targets": []}
    if kind == "automation" and item["id"]:
        try:
            cfg = await hass.rest("GET", f"/config/automation/config/{item['id']}") or {}
        except HassError:
            cfg = {}
        bp = cfg.get("use_blueprint") or {}
        if bp.get("path") == BLUEPRINT_PATH:
            item["ours"] = True
            targets = (bp.get("input") or {}).get("notify") or []
            item["targets"] = [targets] if isinstance(targets, str) else list(targets)
    return item


async def entity_of(hass, nid: str, wait: float = 0.0) -> str | None:
    """The entity ID Home Assistant gave a page's sensor, waiting up to `wait` seconds for
    it to appear (discovery takes a moment)."""
    uid = SIGNAL_UID + nid
    until = time.monotonic() + wait
    while True:
        try:
            for e in await hass.ws({"type": "config/entity_registry/list"}) or []:
                if e.get("platform") == "mqtt" and e.get("unique_id") == uid:
                    return e.get("entity_id")
        except HassError:
            pass
        if time.monotonic() >= until:
            return None
        await asyncio.sleep(0.5)
