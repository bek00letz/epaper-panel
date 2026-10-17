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
    items = cfg if isinstance(cfg, list) else cfg.get("sources", [])
    return [s for s in items if isinstance(s, dict)]


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
    """Restore masked secrets from existing stored sources when saving or testing."""
    by_name = {clean_slug(s.get("name")): s for s in (existing or []) if s.get("name")}
    out = []
    for idx, s in enumerate(incoming or []):
        if not isinstance(s, dict):
            continue
        c = copy.deepcopy(s)
        slug = clean_slug(c.get("name"))
        c["name"] = slug
        prev = by_name.get(slug) or {}
        if c.get("key") == SECRET_MASK and isinstance(prev, dict):
            c["key"] = prev.get("key", "")
        if c.get("headers") == SECRET_MASK and isinstance(prev, dict):
            c["headers"] = prev.get("headers", "")
        out.append(c)
    return out


async def run_all(sources, ctx):
    """Fetch every configured source. One failure never stops the rest."""
    out = []
    for src in sources:
        if not isinstance(src, dict):
            continue
        kind = src.get("type")
        slug = clean_slug(src.get("name"))
        if kind not in REGISTRY or not slug:
            continue
        normalized = {**src, "name": slug}
        try:
            mod = importlib.import_module(f".{kind}", __package__)
            out.extend(await mod.fetch(normalized, ctx) or [])
        except Exception as exc:
            print(f"source {slug} ({kind}) failed: {exc!r}", flush=True)
    return out
