"""Pages and data sources on disk: loading, migrating and checking what the editor saves."""

import hashlib
import json
import os
import re

import feeds
from render import binding, epf, layout, sleep, stripmeta, subitems, theme as T
import conditions
import config
import devices
from config import PAGE_RE, valid_entity_id


def load_sources():
    """Configured data sources, migrating the old add-on options once."""
    existing = feeds.load(config.DATA_DIR)
    if existing:
        return existing
    seeded = []
    if os.environ.get("JELLYFIN_KEY"):
        seeded.append({"type": "jellyfin", "name": "watch",
                       "base": os.environ.get("JELLYFIN_BASE", ""),
                       "user": os.environ.get("JELLYFIN_USER", ""),
                       "key": os.environ["JELLYFIN_KEY"], "days": 30,
                       "friendly_name": "Next to watch"})
    if seeded:
        feeds.save(config.DATA_DIR, seeded)
        print(f"migrated {len(seeded)} source(s) from add-on options", flush=True)
    return seeded


def load_layouts(device_id=None):
    """A device's pages and settings (devices.view); the first device when none is named."""
    return devices.view(device_id)


LEGACY_ENTITY_MAP = {
    "sensor.overhead_aircraft_count": "sensor.epaper_flights_overhead",
    "sensor.closest_aircraft": "sensor.epaper_closest_aircraft",
    "sensor.f1_status": "sensor.epaper_racing_f1",
    "sensor.formula_e_status": "sensor.epaper_racing_fe",
}


def migrate_legacy_entity_refs(text: str) -> str:
    """Upgrade legacy non-prefixed add-on sensor names to canonical sensor.epaper_* names."""
    if not text or not isinstance(text, str):
        return text
    out = text
    for old_id, new_id in LEGACY_ENTITY_MAP.items():
        if old_id in out:
            out = out.replace(old_id, new_id)
    # Migrate sensor.sports_<slug> -> sensor.epaper_sports_<slug>
    out = re.sub(r"\bsensor\.sports_([a-z0-9_]+)\b", r"sensor.epaper_sports_\1", out)
    # Also upgrade old racing show_if `states('sensor.epaper_racing_f1') in ['IN', 'PRE']` -> `is_state('sensor.epaper_racing_f1', 'active')`
    out = re.sub(
        r"states\(\s*'(sensor\.epaper_racing_[a-z0-9_]+)'\s*\)\s+in\s+\[\s*'IN'\s*,\s*'PRE'\s*\]",
        r"is_state('\1', 'active')",
        out,
    )
    return out


# Saved places for the flight widget: the user's own, at most this many (they
# sit as one row of buttons in the editor's sidebar).
MAX_PLACES = 4


def sanitize_layouts(spec: dict) -> dict:
    """Validate and normalize a layout spec before saving."""
    raw_pages = spec.get("pages")
    if not isinstance(raw_pages, dict):
        raise ValueError("pages must be an object")
    pages = {}
    for name, p in raw_pages.items():
        clean_name = str(name).strip()
        if not PAGE_RE.match(clean_name) or not isinstance(p, dict):
            continue
        tier = p.get("tier") if p.get("tier") in ("rotate", "when", "alert") else "rotate"
        els = []
        for raw_el in (p.get("elements") or []):
            if not isinstance(raw_el, dict):
                continue
            el = dict(raw_el)
            if isinstance(el.get("entity"), str) and el["entity"]:
                el["entity"] = migrate_legacy_entity_refs(el["entity"].strip())
            if isinstance(el.get("show_if"), str) and el["show_if"]:
                el["show_if"] = migrate_legacy_entity_refs(el["show_if"].strip())
            els.append(el)
        entry = {"tier": tier, "elements": els}
        if p.get("show_if") and isinstance(p.get("show_if"), str):
            entry["show_if"] = migrate_legacy_entity_refs(p["show_if"].strip())
        if isinstance(p.get("notify"), str) and re.match(r"^[a-z0-9]{6,16}$", p["notify"]):
            entry["notify"] = p["notify"]                 # its phone notifications (notify.py)
        if tier == "alert":
            if p.get("ends") == "until":
                entry["ends"] = "until"
                if isinstance(p.get("until_if"), str) and p["until_if"].strip():
                    entry["until_if"] = migrate_legacy_entity_refs(p["until_if"].strip())
            entry["hold_minutes"] = conditions.hold_minutes({**p, "ends": entry.get("ends")})
        pages[clean_name] = entry

    raw_rot = spec.get("rotation")
    rotation = []
    if isinstance(raw_rot, list):
        for r in raw_rot:
            rn = str(r).strip()
            if rn in pages and pages[rn].get("tier") != "alert":
                rotation.append(rn)
    try:
        orient = int(spec.get("orientation") or 0)
    except (TypeError, ValueError):
        orient = 0
    if orient not in (0, 90, 180, 270):
        orient = 0
    display = spec.get("display")
    disp_id = T.get_display(display)["id"]

    raw_qh = spec.get("quiet_hours") if isinstance(spec.get("quiet_hours"), dict) else {}
    qh_start = str(raw_qh.get("start") or "23:00").strip()[:5]
    qh_end = str(raw_qh.get("end") or "07:00").strip()[:5]
    if not re.match(r"^\d{2}:\d{2}$", qh_start):
        qh_start = "23:00"
    if not re.match(r"^\d{2}:\d{2}$", qh_end):
        qh_end = "07:00"
    qh_pres = str(raw_qh.get("presence_entity") or "").strip()
    if qh_pres and not valid_entity_id(qh_pres):
        qh_pres = ""
    quiet_hours = {
        "enabled": bool(raw_qh.get("enabled", False)),
        "start": qh_start,
        "end": qh_end,
        "presence_entity": qh_pres,
        "allow_alerts": bool(raw_qh.get("allow_alerts", True)),
        "sleep_screen": bool(raw_qh.get("sleep_screen", True)),
    }

    raw_presets = spec.get("custom_presets")
    custom_presets = []
    if isinstance(raw_presets, list):
        for cp in raw_presets[:50]:
            # The editor has always sent `title`; until 0.10 only `name` was
            # kept, so every preset saved from the editor vanished.
            title = cp.get("title") or cp.get("name") if isinstance(cp, dict) else None
            if title and isinstance(cp.get("elements"), list):
                custom_presets.append({
                    "id": str(cp.get("id") or f"custom_{len(custom_presets)+1}")[:40],
                    "name": str(title)[:60],
                    "title": str(title)[:60],
                    "desc": str(cp.get("desc") or "Custom saved layout preset")[:140],
                    "tier": cp.get("tier") if cp.get("tier") in ("rotate", "when", "alert") else "rotate",
                    "show_if": migrate_legacy_entity_refs(str(cp.get("show_if") or "").strip()),
                    "elements": [el for el in cp["elements"] if isinstance(el, dict)],
                })

    places = []
    for raw in spec.get("location_presets") or []:
        if len(places) == MAX_PLACES:
            break
        try:
            lat, lon = float(raw.get("lat")), float(raw.get("lon"))
        except (TypeError, ValueError, AttributeError):
            continue
        if -90 <= lat <= 90 and -180 <= lon <= 180:
            label = str(raw.get("label") or "").strip()[:12] or f"{lat:.2f},{lon:.2f}"
            places.append({"label": label, "lat": round(lat, 5), "lon": round(lon, 5)})

    return {
        "display": disp_id,
        "location_presets": places,
        "orientation": orient,
        "quiet_hours": quiet_hours,
        "custom_presets": custom_presets,
        "rotation": rotation,
        "pages": pages,
    }


def layouts_etag(spec: dict | None = None, device_id=None) -> str:
    """A version for the saved pages: changes whenever what's saved changes."""
    if spec is None:
        spec = load_layouts(device_id)
    canon = json.dumps(spec, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canon.encode()).hexdigest()[:16]


def load_draft(device_id=None) -> dict | None:
    """The editor's unsent changes for a device: {version, base_etag, base, spec}, or None."""
    try:
        d = json.loads(devices.draft_path(device_id).read_text())
    except Exception:
        return None
    if not isinstance(d, dict) or not isinstance(d.get("spec"), dict):
        return None
    return d


def save_draft(draft: dict, device_id=None) -> None:
    path = devices.draft_path(device_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(draft))
    tmp.replace(path)


def clear_draft(device_id=None) -> None:
    try:
        devices.draft_path(device_id).unlink()
    except FileNotFoundError:
        pass


def save_layouts(spec, device_id=None):
    """Store a device's pages and settings: the pages go to its design, the rest to the device and library."""
    devices.save_view(spec, device_id)
