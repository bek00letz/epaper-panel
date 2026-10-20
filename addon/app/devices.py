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
from render import theme as T

# The view's top-level keys that belong to the device and to the library.
# Everything else (pages, rotation) belongs to the design.
DEVICE_KEYS = ("display", "orientation", "rotate_seconds", "quiet_hours")
LIBRARY_KEYS = ("custom_presets", "location_presets")

STORE = "devices.json"
VERSION = 1


# ---------------------------------------------------------------- files

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
        _write(_path("designs", "1.json"),
               {k: v for k, v in spec.items() if k not in DEVICE_KEYS + LIBRARY_KEYS})
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
        "name": T.get_display(spec.get("display"))["name"],
        "design": "1",
        # Its key is the install's frame token (frame_token.py), so the panel's
        # download address, and the option that sets it, keep working.
        "install_token": True,
        # Its Home Assistant entities keep the names they always had.
        "entity_suffix": "",
        # Panel setup's copy of the size was kept in step with the pages'; the device's is the one now.
        "setup": {k: v for k, v in setup.items() if k != "display"},
    }
    device.update({k: spec[k] for k in DEVICE_KEYS if k in spec})
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


def add(kind: str, name: str, display: str, design: str | None = None, **fields) -> dict:
    """A new device with its own key. It shows `design`, or a new design of the starter pages."""
    store = _load()
    if design is None:
        design = str(store["next_design"])
        store["next_design"] += 1
    elif _clean_id(design) not in designs_in_use(store):
        raise KeyError(f"no design {design}")
    dev_id = str(store["next_device"])
    store["next_device"] += 1
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or f"screen_{dev_id}"
    # Fixed at creation, so renaming a screen never renames its entities.
    taken = {d.get("entity_suffix") for d in store["devices"]}
    suffix, n = f"_{slug}", 2
    while suffix in taken:
        suffix, n = f"_{slug}_{n}", n + 1
    dev = {"id": dev_id, "kind": kind, "name": name.strip()[:60] or f"Screen {dev_id}", "design": design,
           "key": secrets.token_urlsafe(24), "entity_suffix": suffix, "display": T.get_display(display)["id"],
           **fields}
    store["devices"].append(dev)
    _save(store)
    return dev


def designs_in_use(store: dict | None = None) -> set[str]:
    return {d["design"] for d in (store or _load())["devices"]}


# ---------------------------------------------------------------- designs and the library

def design(design_id) -> dict:
    """A design's pages and rotation. One that was never saved is the shipped starter pages."""
    found = _read(_path("designs", f"{_clean_id(design_id)}.json"), None)
    if not isinstance(found, dict):
        found = {k: v for k, v in _defaults().items() if k not in DEVICE_KEYS + LIBRARY_KEYS}
    return found


def library() -> dict:
    found = _read(_path("library.json"), {})
    return found if isinstance(found, dict) else {}


# ---------------------------------------------------------------- the view

def view(device_id=None) -> dict:
    """The device's pages and settings in the one shape the editor and renderer use."""
    dev = resolve(device_id)
    out = dict(design(dev["design"]))
    out.update({k: dev[k] for k in DEVICE_KEYS if k in dev})
    out.update({k: v for k, v in library().items() if k in LIBRARY_KEYS})
    return out


def save_view(spec: dict, device_id=None) -> None:
    """Store a checked view (layouts_store.sanitize_layouts): its parts go to the design, device and library."""
    dev = resolve(device_id)
    _write(_path("designs", f"{dev['design']}.json"),
           {k: v for k, v in spec.items() if k not in DEVICE_KEYS + LIBRARY_KEYS})
    lib = library()
    lib.update({k: spec[k] for k in LIBRARY_KEYS if k in spec})
    _write(_path("library.json"), lib)
    update(dev["id"], **{k: spec[k] for k in DEVICE_KEYS if k in spec})


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
