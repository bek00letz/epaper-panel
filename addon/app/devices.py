"""Devices, designs and the shared library: which screens the add-on drives, and what each one shows.

A **device** is a screen: its kind, size and orientation, how long it shows
each page, its quiet hours, its key, and its kind's own setup (a CrowPanel's
ESPHome settings). A **design** is what a screen shows: pages and rotation.
Several devices can show the same design. The **library** is the user's own
saved presets and places, shared by every design.

The editor and the renderer both work with one shape, the device's *view*:
its design's pages and rotation, plus its own settings, plus the library.
That is exactly what `layouts.json` held before devices existed, so pages,
drafts and version tags carry over unchanged.

On disk, in DATA_DIR:

    devices.json         the devices and id counters (0600: keys, Wi-Fi password)
    designs/<id>.json    one design each; one never saved is the shipped starter pages
    library.json         saved presets and places
    drafts/<id>.json     the editor's unsent changes, per device
    state/<id>.json      what a device last reported (how much it holds), not settings

The first start with devices moves `layouts.json`, `panel_setup.json`,
`draft.json` and `panel_capacity` in as device 1 and design 1, and leaves
those files as they were: the previous add-on version still finds them.
"""
from __future__ import annotations

import hmac
import json
import os
import re
import secrets
from pathlib import Path

import config
import frame_token
from render import arrange, theme as T

# The view's top-level keys that belong to the device and to the library.
# Everything else (pages, rotation) belongs to the design. How often a screen
# updates and turns its pages is the device's too, but set on its own, never
# sent with the pages (timing.py).
DEVICE_KEYS = ("display", "orientation", "quiet_hours")
TIMER_KEYS = ("rotate_seconds",)                # what a single-panel install kept with its pages
LIBRARY_KEYS = ("custom_presets", "location_presets")

STORE = "devices.json"
VERSION = 1


# ---------------------------------------------------------------- files

# The first panel's name in Home Assistant, which never changes: renaming it in
# the editor changes only what the editor calls it (panel_setup.ha_name).
FIRST_PANEL_NAME = "E-paper panel"

def _path(*parts) -> Path:
    return config.DATA_DIR.joinpath(*parts)


def _read(path: Path, default):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


def _write(path: Path, data, private: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    if private:
        os.chmod(tmp, 0o600)
    tmp.replace(path)


def _clean_id(value) -> str:
    """Ids name files, so only digits are accepted."""
    s = str(value or "").strip()
    if not re.fullmatch(r"[0-9]{1,6}", s):
        raise KeyError(f"no device or design {s[:12]!r}")
    return s


# ---------------------------------------------------------------- the store

def _defaults() -> dict:
    try:
        return json.loads(config.DEFAULTS_PATH.read_text())
    except (OSError, ValueError):
        return {"rotation": [], "pages": {}}


def _migrate() -> dict:
    """Move a single-panel install in as device 1 and design 1. Old files stay as they were."""
    spec = _read(config.layouts_path(), None)
    saved = isinstance(spec, dict)
    if not saved:
        spec = _defaults()
    setup = _read(config.panel_setup_path(), {})
    setup = setup if isinstance(setup, dict) else {}

    if saved:
        made_on = arrange.canvas_key(*T.canvas_dims(spec.get("orientation") or 0, spec.get("display")))
        _write(_path("designs", "1.json"),
               {**{k: v for k, v in spec.items() if k not in DEVICE_KEYS + TIMER_KEYS + LIBRARY_KEYS},
                "canvas": made_on})
    library = {k: spec[k] for k in LIBRARY_KEYS if k in spec}
    if library:
        _write(_path("library.json"), library)
    draft = _read(config.draft_path(), None)
    if isinstance(draft, dict):
        _write(_path("drafts", "1.json"), draft)
    try:
        capacity = int(_path("panel_capacity").read_text())
        _write(_path("state", "1.json"), {"capacity": capacity})
    except (OSError, ValueError):
        pass

    device = {
        "id": "1",
        "kind": "crowpanel",
        # What Home Assistant already calls the panel (its firmware's friendly name).
        "name": FIRST_PANEL_NAME,
        "design": "1",
        # Its key is the install's frame token (frame_token.py), so the panel's
        # download address, and the option that sets it, keep working.
        "install_token": True,
        # Its Home Assistant entities keep the names they always had.
        "entity_suffix": "",
        # Panel setup's copy of the size was kept in step with the pages'; the device's is the one now.
        "setup": {k: v for k, v in setup.items() if k != "display"},
    }
    device.update({k: spec[k] for k in DEVICE_KEYS + TIMER_KEYS if k in spec})
    store = {"version": VERSION, "next_device": 2, "next_design": 2, "devices": [device]}
    _write(_path(STORE), store, private=True)                 # written last: the move is done
    print("devices: this install's panel is now device 1", flush=True)
    return store


def _load() -> dict:
    store = _read(_path(STORE), None)
    if not isinstance(store, dict) or not isinstance(store.get("devices"), list) or not store["devices"]:
        store = _migrate()
    return store


def _save(store: dict) -> None:
    _write(_path(STORE), store, private=True)


def all_devices() -> list[dict]:
    """Every device, in the order they were added."""
    return _load()["devices"]


def get(device_id) -> dict:
    device_id = _clean_id(device_id)
    for dev in all_devices():
        if dev["id"] == device_id:
            return dev
    raise KeyError(f"no device {device_id}")


def primary() -> dict:
    """The first device: what a client that doesn't name one means."""
    return all_devices()[0]


def resolve(device_id=None) -> dict:
    """A device by id, or the first when none is named."""
    return primary() if device_id in (None, "") else get(device_id)


def update(device_id, **fields) -> dict:
    """Change some of a device's own fields (never its id, kind or key)."""
    store = _load()
    for dev in store["devices"]:
        if dev["id"] == _clean_id(device_id):
            for k, v in fields.items():
                if k in ("id", "kind", "key", "install_token"):
                    raise ValueError(f"a device's {k} doesn't change")
                if v is None:
                    dev.pop(k, None)
                else:
                    dev[k] = v
            _save(store)
            return dev
    raise KeyError(f"no device {device_id}")


def add(kind: str, name: str, display: str, design: str | None = None, *, orientation: int = 0,
        copy_from: str | None = None, **fields) -> dict:
    """A new device with its own key.

    Its pages, like setting up a phone: `design` shows another device's design
    (linked); `copy_from` copies that device's pages, as placed for the new
    screen; neither gives it a new design of the starter page.
    """
    store = _load()
    dev_id = str(store["next_device"])
    store["next_device"] += 1
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or f"screen_{dev_id}"
    # Fixed at creation, so renaming a screen never renames its entities.
    taken = {d.get("entity_suffix") for d in store["devices"]}
    suffix, n = f"_{slug}", 2
    while suffix in taken:
        suffix, n = f"_{slug}_{n}", n + 1
    dev = {"id": dev_id, "kind": kind, "name": name.strip()[:60] or f"Screen {dev_id}",
           "key": secrets.token_urlsafe(24), "entity_suffix": suffix, "display": T.get_display(display)["id"],
           "orientation": int(orientation) if int(orientation or 0) in (0, 90, 180, 270) else 0, **fields}
    if design is not None:
        if _clean_id(design) not in designs_in_use(store):
            raise KeyError(f"no design {design}")
        dev["design"] = design
    else:
        dev["design"] = str(store["next_design"])
        store["next_design"] += 1
        if copy_from is not None:
            source = get(copy_from)
            found = design_with_ids(source["design"])
            new = arrange.bake(found, design_canvas(source["design"], found), canvas_of(dev))
        else:
            new = starter_design()
        _save_design(dev["design"], new)
    store["devices"].append(dev)
    _save(store)
    return dev


def rekey(device_id) -> str:
    """Give a device a new key. The old one stops working at once."""
    store = _load()
    for dev in store["devices"]:
        if dev["id"] == _clean_id(device_id):
            if dev.get("install_token"):
                raise ValueError("The first panel's key is the install's frame token.")
            dev["key"] = secrets.token_urlsafe(24)
            _save(store)
            return dev["key"]
    raise KeyError(f"no device {device_id}")


def unlink(device_id) -> dict:
    """Give a device its own copy of the design it shares, as placed for it. A no-op if it doesn't share."""
    dev = get(device_id)
    store = _load()
    if sum(1 for d in store["devices"] if d["design"] == dev["design"]) < 2:
        return dev
    found = design_with_ids(dev["design"])
    new_id = str(store["next_design"])
    store["next_design"] += 1
    _save_design(new_id, arrange.bake(found, design_canvas(dev["design"], found), canvas_of(dev)))
    for d in store["devices"]:
        if d["id"] == dev["id"]:
            d["design"] = new_id
            dev = d
    _save(store)
    return dev


REMEMBER_REMOVED = 10


def remove(device_id) -> dict:
    """Take a device out. It's remembered (with its key) so it can be put back; its design is kept."""
    store = _load()
    dev = get(device_id)
    if len(store["devices"]) < 2:
        raise ValueError("This is the only screen, so it can't be removed.")
    store["devices"] = [d for d in store["devices"] if d["id"] != dev["id"]]
    store["removed"] = ([dev] + [d for d in store.get("removed") or [] if d.get("id") != dev["id"]])[:REMEMBER_REMOVED]
    _save(store)
    return dev


def restore(device_id) -> dict:
    """Put back a device that `remove` took out (the undo)."""
    store = _load()
    device_id = _clean_id(device_id)
    dev = next((d for d in store.get("removed") or [] if d.get("id") == device_id), None)
    if dev is None or any(d["id"] == device_id for d in store["devices"]):
        raise ValueError("That screen can't be put back any more.")
    store["removed"] = [d for d in store["removed"] if d.get("id") != device_id]
    store["devices"].append(dev)
    store["devices"].sort(key=lambda d: int(d["id"]))
    _save(store)
    return dev


def designs_in_use(store: dict | None = None) -> set[str]:
    return {d["design"] for d in (store or _load())["devices"]}


# ---------------------------------------------------------------- designs and the library

# The shipped starter pages were made for the 5.79" panel, landscape.
SHIPPED_CANVAS = arrange.canvas_key(*T.canvas_dims(0, T.DEFAULT_DISPLAY))
DESIGN_KEYS = ("canvas", "arrangements")


def design(design_id) -> dict:
    """A design: pages, rotation, the canvas it was made on, arrangements for other sizes.
    One that was never saved is the shipped starter pages."""
    found = _read(_path("designs", f"{_clean_id(design_id)}.json"), None)
    if not isinstance(found, dict):
        found = {k: v for k, v in _defaults().items() if k not in DEVICE_KEYS + TIMER_KEYS + LIBRARY_KEYS}
        found["canvas"] = SHIPPED_CANVAS
    return found


def canvas_of(dev: dict) -> str:
    """The canvas a device draws on: its size, turned for how it's mounted."""
    return arrange.canvas_key(*T.canvas_dims(dev.get("orientation") or 0, dev.get("display")))


def design_canvas(design_id, found: dict | None = None) -> str:
    """The canvas a design's own boxes are for."""
    found = found if found is not None else design(design_id)
    if found.get("canvas"):
        return str(found["canvas"])
    for dev in all_devices():
        if dev["design"] == str(design_id):
            return canvas_of(dev)
    return SHIPPED_CANVAS


def design_with_ids(design_id) -> dict:
    found = design(design_id)
    return {**found, "pages": arrange.ensure_ids(found.get("pages") or {})}


STARTER_PATH = Path(__file__).parent / "starter_design.json"


def starter_design() -> dict:
    """What "Set up as new" starts with: one page that works on any Home Assistant,
    arranged by hand for each shipped size."""
    found = _read(STARTER_PATH, None)
    if not isinstance(found, dict):
        found = {k: v for k, v in _defaults().items() if k not in DEVICE_KEYS + TIMER_KEYS + LIBRARY_KEYS}
        found["canvas"] = SHIPPED_CANVAS
    found["pages"] = arrange.ensure_ids(found.get("pages") or {})
    return found


def place(spec: dict, device_id, display, orientation) -> dict:
    """The view's pages (as edited on the device's current canvas) placed for another
    size or mounting: that size's arrangement, or automatically. For the editor,
    before the change is sent."""
    dev = resolve(device_id)
    found = design_with_ids(dev["design"])
    base = design_canvas(dev["design"], found)
    here = arrange.canvas_key(*T.canvas_dims(spec.get("orientation") or 0, spec.get("display")))
    there = arrange.canvas_key(*T.canvas_dims(orientation or 0, display))
    scratch = arrange.merge_pages(found, spec.get("pages") or {}, base, here)
    return arrange.pages_for(scratch, base, there)


def _save_design(design_id, found: dict) -> None:
    _write(_path("designs", f"{_clean_id(design_id)}.json"), found)


def library() -> dict:
    found = _read(_path("library.json"), {})
    return found if isinstance(found, dict) else {}


# ---------------------------------------------------------------- the view

def view(device_id=None) -> dict:
    """The device's pages and settings in the one shape the editor and renderer use.

    Pages are placed for the device's own canvas (render/arrange.py): on the
    canvas the design was made on, as they are; elsewhere from that size's
    arrangement, or automatically (marked `_auto`).
    """
    dev = resolve(device_id)
    found = design(dev["design"])
    base = design_canvas(dev["design"], found)
    out = {k: v for k, v in found.items() if k not in ("pages",) + DESIGN_KEYS}
    out["pages"] = arrange.pages_for({**found, "pages": arrange.ensure_ids(found.get("pages") or {})},
                                     base, canvas_of(dev))
    out.update({k: dev[k] for k in DEVICE_KEYS if k in dev})
    out.update({k: v for k, v in library().items() if k in LIBRARY_KEYS})
    return out


def save_view(spec: dict, device_id=None) -> None:
    """Store a checked view (layouts_store.sanitize_layouts): its parts go to the design, device and library.

    Settings that change the device's canvas apply first, so the pages are
    stored as placed on the canvas they were edited for.
    """
    dev = resolve(device_id)
    dev = update(dev["id"], **{k: spec[k] for k in DEVICE_KEYS if k in spec})
    found = design(dev["design"])
    base = design_canvas(dev["design"], found)
    rest = {k: v for k, v in spec.items()
            if k not in DEVICE_KEYS + TIMER_KEYS + LIBRARY_KEYS + ("pages",) + DESIGN_KEYS}
    merged = arrange.merge_pages({**found, "pages": arrange.ensure_ids(found.get("pages") or {})},
                                 spec.get("pages") or {}, base, canvas_of(dev))
    merged.update(rest)
    merged["canvas"] = base
    _save_design(dev["design"], merged)
    lib = library()
    lib.update({k: spec[k] for k in LIBRARY_KEYS if k in spec})
    _write(_path("library.json"), lib)


def all_views() -> list[tuple[dict, dict]]:
    """(device, view) for every device."""
    return [(dev, view(dev["id"])) for dev in all_devices()]


def draft_path(device_id=None) -> Path:
    return _path("drafts", f"{resolve(device_id)['id']}.json")


# ---------------------------------------------------------------- what a device reports

def state(device_id) -> dict:
    found = _read(_path("state", f"{_clean_id(device_id)}.json"), {})
    return found if isinstance(found, dict) else {}


def set_state(device_id, **fields) -> None:
    cur = state(device_id)
    cur.update(fields)
    _write(_path("state", f"{_clean_id(device_id)}.json"), cur)


# ---------------------------------------------------------------- keys

def key_of(dev: dict) -> str:
    return frame_token.token() if dev.get("install_token") else str(dev.get("key") or "")


def authenticate(provided: str) -> tuple[dict | None, str]:
    """Which device a request's key belongs to: (device, 'ok' | 'missing' | 'wrong').

    A request with no key is 'missing'. It is served only by the device that
    uses the install token, and only until that panel has first used it
    (frame_token's switch-over); the caller decides.
    """
    devs = all_devices()
    if not provided:
        return next((d for d in devs if d.get("install_token")), None), "missing"
    # Bytes, not str: compare_digest raises on non-ASCII text.
    given = provided.encode("utf-8", "replace")
    found = None
    for dev in devs:
        if hmac.compare_digest(given, key_of(dev).encode()):
            found = found or dev
    if found is None:
        return None, "wrong"
    if found.get("install_token"):
        frame_token.check(provided)                            # switches protection on for good
    return found, "ok"


def entity_id(base: str, dev: dict) -> str:
    """A per-device Home Assistant entity: the first device keeps the original name."""
    return f"{base}{dev.get('entity_suffix') or ''}"
