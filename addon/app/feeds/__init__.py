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
import importlib
import json
from pathlib import Path

REGISTRY = ("jellyfin", "rest", "statistics")


def load(data_dir):
    try:
        cfg = json.loads((Path(data_dir) / "sources.json").read_text())
    except Exception:
        return []
    return cfg if isinstance(cfg, list) else cfg.get("sources", [])


def save(data_dir, sources):
    p = Path(data_dir) / "sources.json"
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(sources, indent=2))
    tmp.replace(p)


async def run_all(sources, ctx):
    """Fetch every configured source. One failure never stops the rest."""
    out = []
    for src in sources:
        kind = src.get("type")
        if kind not in REGISTRY or not src.get("name"):
            continue
        try:
            mod = importlib.import_module(f".{kind}", __package__)
            out.extend(await mod.fetch(src, ctx) or [])
        except Exception as exc:
            print(f"source {src.get('name')} ({kind}) failed: {exc!r}", flush=True)
    return out
