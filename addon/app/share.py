"""Sharing pages as a file (ROADMAP: Share a page; the user's calls, 26 Oct).

A shared file is one versioned JSON, saved as `<name>.epaper.json`. Nothing is uploaded: the editor
saves it and the person sends it however they like. What the file never holds:

- the sender's entity IDs, wherever they appear (an element's sensor, a Devices grid's items, a
  page's condition, a template, an icon that follows a sensor): each becomes a numbered slot, which
  whoever opens the file fills with their own, the way New page asks for a preset's sensors. A slot
  keeps only what ranks the importer's sensors (its kind, device class and unit) and where it's used.
  Their names never go in;
- the guest Wi-Fi's name and password (a "wifi" slot: the importer's own network is asked for);
- a flight widget's place (the importer's own home is used), the sender's own data sources (a
  Jellyfin page asks for the importer's Jellyfin; a widget filled by one goes back to the add-on's
  services), a page's phone notifications, a battery rule's ticks;
- anything of the device's or the install's: quiet hours, timers, saved places, keys.

Words the sender typed (page names, labels, titles) are the design, so they're kept as written; the
editor lists them before the file is saved (`words`).

Opening a file checks it, upgrades an older one (UPGRADES) and refuses, saying why, a newer one or
one with something this version can't draw: never a broken page. Filling the slots is the editor's
(app/share.js `fill`), from the answers New page's steps give.
"""
from __future__ import annotations

import copy
import json
import re

import config
import feeds
from layouts_store import sanitize_layouts
from render import layout

FORMAT = "epaper-page"
VERSION = 1
MAX_BYTES = 2_000_000           # as a design's pages (0.10.1)
CANVAS = "792x272"              # what a file without one was drawn on: the 5.79", as the presets are

# Home Assistant's entity domains, for finding IDs inside templates; the domains of the sender's own
# entities are added to them, so one from an integration newer than this list is found too.
HA_DOMAINS = frozenset((
    "ai_task alarm_control_panel assist_satellite automation binary_sensor button calendar camera "
    "climate conversation counter cover date datetime device_tracker event fan group humidifier image "
    "image_processing input_boolean input_button input_datetime input_number input_select input_text "
    "lawn_mower light lock media_player notify number person plant remote scene schedule script select "
    "sensor siren stt sun switch text time timer todo tts update vacuum valve wake_word water_heater "
    "weather zone").split())
EVERY_HOME = frozenset({"sun.sun", "zone.home"})           # the same entity in every home: kept as is

# A flight widget's place, kept by the add-on per place under a suffix taken from its label.
_FLIGHTS = re.compile(r"^sensor\.epaper_(flights_overhead|closest_aircraft)_[a-z0-9_]+$")
_PLACE_KEYS = ("lat", "lon", "lng", "latitude", "longitude", "location_name")
_TOKEN = re.compile(r"%slot:(\d+)(?:\.([a-z]+))?%")
_KINDS = ("entity", "jellyfin", "wifi")
_WIFI_PARTS = ("ssid", "password", "auth")


class Refused(ValueError):
    """A file that can't be opened, with the reason in the person's words."""


def file_name(title: str) -> str:
    """`Kitchen.epaper.json`: the page's (or device's) name, safe on every system."""
    base = re.sub(r"\s+", " ", re.sub(r"[\\/:*?\"<>|\x00-\x1f]+", " ", str(title or ""))).strip(" .")[:60]
    return f"{base or 'Page'}.epaper.json"


# ---------------------------------------------------------------- export

class _Slots:
    """The sender's entity IDs (and Wi-Fi), each turned into a numbered slot the first time it's met."""

    def __init__(self, entities: list[dict], sources: list[dict]):
        self.known = {e["entity_id"]: e for e in entities if isinstance(e, dict) and e.get("entity_id")}
        domains = HA_DOMAINS | {eid.split(".", 1)[0] for eid in self.known}
        self.find = re.compile(r"(?<![\w%])(" + "|".join(sorted(map(re.escape, domains), key=len, reverse=True))
                               + r")\.([a-z0-9_]+)(?![\w(])")
        # Your data sources' sensors are named after them: {name: type}.
        self.sources = {feeds.clean_slug(s.get("name")): s.get("type") for s in sources
                        if isinstance(s, dict) and feeds.clean_slug(s.get("name"))}
        self.slots: list[dict] = []
        self.by_key: dict[str, dict] = {}

    def slot(self, key: str, kind: str, **facts) -> dict:
        s = self.by_key.get(key)
        if s is None:
            s = {"id": len(self.slots) + 1, "kind": kind, **facts, "needed": False, "uses": []}
            self.slots.append(s)
            self.by_key[key] = s
        return s

    def entity(self, eid: str) -> str:
        """The token an ID becomes, or the ID itself when it's the same in every home."""
        if eid in EVERY_HOME:
            return eid
        flights = _FLIGHTS.match(eid)
        if flights:                              # its place stays home: the importer's is Home
            return "sensor.epaper_" + flights.group(1)
        if eid.startswith("sensor.epaper_"):
            name = eid[len("sensor.epaper_"):]
            src = next((n for n in sorted(self.sources, key=len, reverse=True) if name == n or name.startswith(n + "_")), None)
            if src and self.sources[src] == "jellyfin":       # a Jellyfin source's sensors: yours is asked for
                s = self.slot("jellyfin:" + src, "jellyfin", domain="sensor")
                return f"%slot:{s['id']}%" + name[len(src):]
            # The add-on's own (scores, races, planes, notifications) are named alike in every home; one
            # named after something of yours (a data source, a to-do list) is a sensor the importer picks.
            if not src and not name.startswith("todo_"):
                return eid
        e = self.known.get(eid) or {}
        s = self.slot(eid, "entity", domain=eid.split(".", 1)[0], device_class=e.get("device_class") or "",
                      unit=e.get("unit") or "")
        return f"%slot:{s['id']}%"

    def text(self, value: str, use: dict, condition: bool) -> str:
        out = self.find.sub(lambda m: self.entity(m.group(0)), value)
        for m in _TOKEN.finditer(out):
            s = self.slots[int(m.group(1)) - 1]
            if s["kind"] != "wifi" and use not in s["uses"]:
                s["uses"].append(use)
            # A condition or a template can't do without its sensor: it's asked for, not skipped.
            if condition or "{{" in value or "{%" in value:
                s["needed"] = True
        return out

    def walk(self, node, use: dict, condition: bool = False):
        if isinstance(node, str):
            return self.text(node, use, condition)
        if isinstance(node, list):
            return [self.walk(x, use, condition) for x in node]
        if isinstance(node, dict):
            return {k: self.walk(v, use, condition) for k, v in node.items()}
        return node

    def wifi(self, ssid: str, password: str) -> dict:
        return self.slot("wifi:" + ssid, "wifi", secrets=(ssid, password))


def _home_only(el: dict) -> dict:
    """An element without what belongs to the sender's home and isn't an entity (those are slots)."""
    el = {k: v for k, v in el.items() if k not in _PLACE_KEYS}
    if isinstance(el.get("data"), dict):                         # your own data source stays home
        data = {k: v for k, v in el["data"].items() if k != "source"}
        if data:
            el["data"] = data
        else:
            el.pop("data")
    if el.get("type") == "dynamic_grid" and el.get("batteries"):
        # A rule, not a list: every battery of its kind in the importer's home. The ticks were yours.
        el.update({"except": [], "also": [], "items": []})
    return el


def _wifi_tokens(node, slot: dict):
    """The network's name and password, wherever they appear (the code, the pill under it), as tokens."""
    ssid, password = slot["secrets"]
    n = slot["id"]

    def swap(v):
        if isinstance(v, str):
            if password and (v == password or (len(password) >= 6 and password in v)):
                v = v.replace(password, f"%slot:{n}.password%")
            if ssid and v == ssid:
                v = f"%slot:{n}.ssid%"
            return v
        if isinstance(v, list):
            return [swap(x) for x in v]
        if isinstance(v, dict):
            return {k: swap(x) for k, x in v.items()}
        return v
    return swap(node)


def export(pages: dict, rotation: list, canvas: str, entities: list[dict], sources: list[dict]) -> dict:
    """A file of `pages` ({name: page}, in their order), as drawn on `canvas` ("WxH"). `entities` is Home
    Assistant's list as the editor gets it (/api/entities), `sources` the configured data sources."""
    slots = _Slots(entities, sources)
    out = []
    for name, page in pages.items():
        if not isinstance(page, dict):
            continue
        page = copy.deepcopy({k: v for k, v in page.items() if k != "notify"})   # its notifications are yours
        els = [_home_only(el) for el in page.get("elements") or [] if isinstance(el, dict)]
        networks = []
        for el in els:
            if el.get("type") == "qr" and (el.get("wifi_ssid") or el.get("wifi_password")):
                s = slots.wifi(str(el.get("wifi_ssid") or ""), str(el.get("wifi_password") or ""))
                use = {"page": name, "type": "qr", "key": "wifi"}
                if use not in s["uses"]:
                    s["uses"].append(use)
                el.update({f"wifi_{part}": f"%slot:{s['id']}.{part}%" for part in _WIFI_PARTS})
                networks.append(s)
        for s in networks:                       # and the network's name wherever else it's written
            els = _wifi_tokens(els, s)
        page["elements"] = [{k: slots.walk(v, {"page": name, "type": el.get("type") or "", "key": k})
                             for k, v in el.items()} for el in els]
        for key in ("show_if", "until_if"):
            if page.get(key):
                page[key] = slots.walk(page[key], {"page": name, "type": "page", "key": key}, condition=True)
        out.append({"name": name, **page})
    for s in slots.slots:
        s.pop("secrets", None)
        if s["kind"] == "wifi":
            s["needed"] = True
    names = [p["name"] for p in out]
    return {"format": FORMAT, "version": VERSION, "made_with": config.ADDON_VERSION, "canvas": _canvas(canvas),
            "pages": out, "rotation": [r for r in rotation if r in names], "slots": slots.slots}


_ID_LIKE = re.compile(r"^[a-z0-9_:./#-]*$")
# Where a person types words: the basics' own, and every widget's text fields (its descriptor's).
_ENTITY_ID = re.compile(r"^[a-z_]+\.[a-z0-9_]+$")         # the add-on's own sensor, typed in: not words
_WORD_KEYS = {"value", "prefix", "suffix", "name", "label", "title", "header_title"}
_TEMPLATE = re.compile(r"\{\{.*?\}\}|\{%.*?%\}|\{#.*?#\}", re.S)


def words(file: dict) -> list[str]:
    """What the sender typed that goes in the file as written, for the editor to list before saving: the
    pages' names and every text on them, not IDs, settings, templates or the slots' tokens."""
    seen: list[str] = []
    import widgets
    typed = _WORD_KEYS | {f["key"] for w in widgets.WIDGETS.values() for f in w.fields if f.get("kind") == "text"}

    def add(v: str):
        v = v.strip()
        if v and v not in seen:
            seen.append(v)

    def walk(node, key=""):
        if isinstance(node, dict):
            for k, v in node.items():
                if k not in ("type", "id", "icon", "header_icon", "members"):
                    walk(v, k)
        elif isinstance(node, list):
            for x in node:
                walk(x, key)
        elif isinstance(node, str):
            # A template's own words count ("{{ ... }} in Anna's room"); its code doesn't.
            v = re.sub(r"\s+", " ", _TEMPLATE.sub(" … ", _TOKEN.sub("", node))).strip()
            if (v.strip(" …") and (key in typed or not _ID_LIKE.match(v)) and not _ENTITY_ID.match(v)
                    and any(c.isalpha() for c in v.replace("…", ""))):
                add(v)

    for p in file.get("pages") or []:
        add(str(p.get("name") or "").replace("_", " ").capitalize())
        walk(p.get("elements") or [])
    return seen


# ---------------------------------------------------------------- open

# An older file's format brought up to this one: {version it was: function(file) -> file of the next}.
UPGRADES: dict = {}

_NOT_OURS = "This file isn't a shared page, or it's damaged. Open a file that ends in .epaper.json."


def _canvas(raw) -> str:
    m = re.match(r"^(\d{2,4})x(\d{2,4})$", str(raw or ""))
    return f"{m.group(1)}x{m.group(2)}" if m else CANVAS


def drawable() -> set:
    """Every kind of element this version draws: its renderer's own list, and groups."""
    return set(layout.DRAWERS) | {"group"}


def _example(slot: dict) -> object:
    """What a thumbnail shows for a slot before it's filled: one of the add-on's example entities of its
    kind (render/fixture.json), never anyone's own."""
    if slot["kind"] == "wifi":
        return {"ssid": "Your network", "password": "", "auth": "WPA"}
    if slot["kind"] == "jellyfin":
        return "sensor.epaper_watch"
    from examples import load_fixture
    states = load_fixture().get("states") or {}
    same = [eid for eid in states if eid.split(".", 1)[0] == slot.get("domain")]
    for test in (lambda i: slot.get("device_class") and i.get("device_class") == slot["device_class"],
                 lambda i: slot.get("unit") and i.get("unit") == slot["unit"], lambda i: True):
        for eid in same:
            if test(states[eid]):
                return eid
    return ""


def _named(t: str) -> str:
    return str(t).replace("_", " ").strip().capitalize() or "Unnamed"


def open_file(text: str) -> dict:
    """A file's pages, checked and brought up to this version, and its slots: {pages: [{name, ...page}],
    rotation, canvas, slots, made_with}. Raises Refused with the reason in plain words."""
    if len(text.encode("utf-8", "ignore")) > MAX_BYTES:
        raise Refused("This file is too large to be a shared page.")
    try:
        file = json.loads(text)
    except ValueError:
        raise Refused(_NOT_OURS)
    if not isinstance(file, dict) or file.get("format") != FORMAT:
        raise Refused(_NOT_OURS)
    version = file.get("version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise Refused(_NOT_OURS)
    made_with = str(file.get("made_with") or "")[:20]
    if version > VERSION:
        newer = f" ({made_with})" if made_with else ""
        raise Refused(f"This was shared from a newer e-Paper Panel{newer}. Update the add-on, then open it again.")
    while version < VERSION:
        file, version = UPGRADES[version](file), version + 1

    raw_pages = file.get("pages")
    if not isinstance(raw_pages, list) or not raw_pages:
        raise Refused(_NOT_OURS)
    slots = [s for s in file.get("slots") or [] if isinstance(s, dict)]
    ids = {s.get("id") for s in slots}
    if any(s.get("kind") not in _KINDS or not isinstance(s.get("id"), int) for s in slots) or len(ids) != len(slots):
        raise Refused(_NOT_OURS)

    # Something this version can't draw: refused, saying what (the user's call), never left out.
    can = drawable()
    unknown = sorted({str(el.get("type")) for p in raw_pages if isinstance(p, dict)
                      for el in p.get("elements") or [] if isinstance(el, dict) and el.get("type") not in can})
    if unknown:
        what = ", ".join(_named(t) for t in unknown)
        one = len(unknown) == 1
        raise Refused(f"This has {'something' if one else 'things'} this version of e-Paper Panel can't show "
                      f"({what}). Update the add-on, then open it again.")

    pages, names = {}, []
    for p in raw_pages:
        if not isinstance(p, dict):
            continue
        name = re.sub(r"[^a-z0-9_]+", "_", str(p.get("name") or "").lower()).strip("_")[:40] or "page"
        base, k = name, 2
        while name in pages:
            name, k = f"{base}_{k}", k + 1
        names.append((p.get("name"), name))
        pages[name] = {k2: v for k2, v in p.items() if k2 not in ("name", "notify")}
    renamed = dict(names)
    # The pages are checked as a saved one is, with each slot standing in as an entity ID meanwhile, so
    # what's checked for being one (a "changed" condition) keeps its slot.
    stand_in = json.loads(_TOKEN.sub(lambda m: f"share_slot.n{m.group(1)}" + (f"__{m.group(2)}" if m.group(2) else ""),
                                     json.dumps(pages)))
    checked = sanitize_layouts({"pages": stand_in, "rotation": [renamed.get(r) for r in file.get("rotation") or []
                                                                 if r in renamed]})
    clean = json.loads(re.sub(r"share_slot\.n(\d+)(?:__([a-z]+))?",
                              lambda m: f"%slot:{m.group(1)}" + (f".{m.group(2)}" if m.group(2) else "") + "%",
                              json.dumps(checked)))
    if not clean["pages"]:
        raise Refused(_NOT_OURS)
    used = {int(m.group(1)) for m in _TOKEN.finditer(json.dumps(clean["pages"]))}
    if used - ids:
        raise Refused(_NOT_OURS)
    out_slots = []
    for s in slots:
        if s["id"] not in used:
            continue
        domain = str(s.get("domain") or "")
        out = {"id": s["id"], "kind": s["kind"], "needed": bool(s.get("needed")),
               "domain": domain if re.match(r"^[a-z_]+$", domain) else "",
               "device_class": str(s.get("device_class") or "")[:40], "unit": str(s.get("unit") or "")[:20],
               "uses": [{"page": renamed.get(u.get("page"), ""), "type": str(u.get("type") or ""), "key": str(u.get("key") or "")}
                        for u in s.get("uses") or [] if isinstance(u, dict) and u.get("page") in renamed]}
        out["example"] = _example(out)
        out_slots.append(out)
    return {"pages": [{"name": n, **clean["pages"][n]} for n in clean["pages"]], "rotation": clean["rotation"],
            "canvas": _canvas(file.get("canvas")), "slots": out_slots, "made_with": made_with}
