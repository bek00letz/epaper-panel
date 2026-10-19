"""Optional data sources.

The renderer knows only Home Assistant entities. Anything it cannot get from
HA -- a media server's unwatched list, some API's number -- is fetched here
and *published into HA* as an entity. Pages then bind to it like anything
else.

That keeps the separation honest: with no sources configured the add-on is
simply "render my HA entities onto a panel", which is what most people want.
Jellyfin is one source among several, not a feature of the renderer.

A source is a dict in /data/sources.json:

    {"type": "jellyfin", "name": "watch", "base": "...", "key": "..."}

Each returns [(entity_id, state, attributes)] for the caller to publish.
"""
import copy
import secrets
import importlib
import json
import os
import re
from pathlib import Path

REGISTRY = ("jellyfin", "rest", "statistics")
SECRET_MASK = "••••••••"


def clean_slug(name: str) -> str:
    """Normalize a source name into a safe Home Assistant entity slug."""
    return re.sub(r"[^a-z0-9_]+", "_", str(name or "").strip().lower()).strip("_")


def load(data_dir):
    try:
        cfg = json.loads((Path(data_dir) / "sources.json").read_text())
    except Exception:
        return []
    items = [s for s in (cfg if isinstance(cfg, list) else cfg.get("sources", [])) if isinstance(s, dict)]
    if any(not s.get("id") for s in items):
        # Sources from before 0.10.1 get the id that lets them be renamed safely.
        for s in items:
            s.setdefault("id", secrets.token_hex(6))
        save(data_dir, items)
    return items


def save(data_dir, sources):
    p = Path(data_dir) / "sources.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(sources, indent=2))
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    tmp.replace(p)


def mask_secrets(sources):
    """Return a copy of sources with API keys and auth headers masked for the UI."""
    out = []
    for s in sources:
        c = copy.deepcopy(s)
        if c.get("key"):
            c["key"] = SECRET_MASK
        if c.get("headers"):
            c["headers"] = SECRET_MASK
        out.append(c)
    return out


def unmask_secrets(incoming, existing):
    """Restore masked secrets from the stored sources when saving or testing.

    Matched by the source's id, which never changes, so renaming a source
    keeps its key. Sources saved before ids existed are matched by name once
    and get an id.
    """
    by_id = {s["id"]: s for s in (existing or []) if isinstance(s, dict) and s.get("id")}
    by_name = {clean_slug(s.get("name")): s for s in (existing or []) if isinstance(s, dict) and s.get("name")}
    out = []
    for idx, s in enumerate(incoming or []):
        if not isinstance(s, dict):
            continue
        c = copy.deepcopy(s)
        slug = clean_slug(c.get("name"))
        c["name"] = slug
        prev = by_id.get(c.get("id")) if c.get("id") else None
        if prev is None:
            prev = by_name.get(slug) or {}
        c["id"] = str(c.get("id") or prev.get("id") or secrets.token_hex(6))
        if c.get("key") == SECRET_MASK and isinstance(prev, dict):
            c["key"] = prev.get("key", "")
        if c.get("headers") == SECRET_MASK and isinstance(prev, dict):
            c["headers"] = prev.get("headers", "")
        out.append(c)
    return out


# How often each kind of source is fetched in the background, in seconds. A
# source can ask for its own `interval` (at least 30 s).
INTERVALS = {"jellyfin": 120, "rest": 60, "statistics": 300}


def interval_of(src: dict) -> float:
    try:
        return max(30.0, float(src.get("interval")))
    except (TypeError, ValueError):
        return float(INTERVALS.get(src.get("type"), 120))


def source_entities(src: dict) -> set[str]:
    """The entity IDs a configured source publishes, whether or not it is answering."""
    slug = clean_slug(src.get("name"))
    if not slug or src.get("type") not in REGISTRY:
        return set()
    ids = {f"sensor.epaper_{slug}"}
    if src.get("type") == "jellyfin":
        ids.add(f"sensor.epaper_{slug}_count")
    return ids


async def run_one(src, ctx):
    """Fetch one source. Raises when it fails, so the caller can keep the last good value."""
    kind = src.get("type")
    slug = clean_slug(src.get("name"))
    if kind not in REGISTRY or not slug:
        return []
    mod = importlib.import_module(f".{kind}", __package__)
    return await mod.fetch({**src, "name": slug}, ctx) or []


async def run_all(sources, ctx, errors=None):
    """Fetch every configured source now (the editor's Test). One failure never stops the rest."""
    import health
    out = []
    for src in sources:
        if not isinstance(src, dict):
            continue
        try:
            out.extend(await run_one(src, ctx))
        except Exception as exc:
            text = health.describe(exc)
            print(f"source {clean_slug(src.get('name'))} ({src.get('type')}) failed: {text}", flush=True)
            if errors is not None:
                errors.append(text)
    return out
