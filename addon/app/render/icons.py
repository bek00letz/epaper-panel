"""The icons the panel can draw, by name: the one place a render or the editor asks.

Sets by prefix ("mdi", and custom ones like "local" or "phu"), each a whole
set of outlines (`vector` records). Material Design Icons ship with the
add-on (`icons/mdi.json.gz`, the version Home Assistant served when it was
built), so a first start, a Home Assistant restart or Home Assistant being
unreachable still draws every icon. When Home Assistant has a different set,
or custom ones, `iconsets` copies each whole into the add-on's data and
`install`s it here; it's used from then on. Nothing here fetches: a render
only reads what's in memory.

"custom:" is the add-on's own drawings (`layout.CUSTOM_ICONS`), never a set.
"""
from __future__ import annotations

import gzip
import json
import re
import threading
from pathlib import Path

SHIPPED = Path(__file__).parent.parent / "icons" / "mdi.json.gz"
BUILT_IN = "custom"                 # the add-on's own drawings (layout.CUSTOM_ICONS)
DEFAULT = "mdi"

# The way back (the user's call, 21 Oct): True draws Material Design Icons from
# the old font (fonts/mdi.ttf) as before, and lists only what's in it. Kept,
# switched off, until drawing from outlines has proven itself.
FROM_FONT = False

PREFIX_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
NAME_RE = re.compile(r"^\w[\w .+\-/]{0,127}$")      # as sets name them: "Hydro-Québec", "pets/cat"

_lock = threading.Lock()
_sets: dict[str, dict] = {}        # prefix -> {"icons": {name: record}, "version", "from", "name"}
_shipped: dict | None = None


def split(name) -> tuple[str, str]:
    """("mdi", "cat") for "mdi:cat"; a name without a prefix is Material Design's. A custom set's
    names keep their case, as Home Assistant's do ("phu:France2"); Material Design's are lower case."""
    s = str(name or "").strip()
    prefix, _, rest = s.partition(":")
    if not rest:
        prefix, rest = DEFAULT, prefix
    prefix = prefix.strip().lower()
    return prefix, rest.strip().lower() if prefix == DEFAULT else rest.strip()


def shipped() -> dict:
    """The set the add-on ships with: {"prefix", "version", "icons"}."""
    global _shipped
    if _shipped is None:
        try:
            _shipped = json.loads(gzip.decompress(SHIPPED.read_bytes()))
        except (OSError, ValueError):
            _shipped = {"prefix": DEFAULT, "version": "", "icons": {}}
    return _shipped


def install(prefix: str, data: dict) -> None:
    """Use this whole set from now on (a copy `iconsets` made). Swapped in one go."""
    with _lock:
        _sets[prefix] = data


def remove(prefix: str) -> None:
    with _lock:
        _sets.pop(prefix, None)


def set_for(prefix: str) -> dict | None:
    """A set as it's drawn now: a copy when there is one, else the shipped one for Material Design."""
    got = _sets.get(prefix)
    if got is not None:
        return got
    return shipped() if prefix == DEFAULT else None


def get(name):
    """The outline for an icon ("mdi:cat", "local:cat-outside"), or None when no set has it."""
    prefix, rest = split(name)
    s = set_for(prefix)
    return (s or {}).get("icons", {}).get(rest) if rest else None


def sets() -> list[dict]:
    """What can be drawn, set by set, for the editor: [{"prefix", "name", "count", "version", "from"}]."""
    out = []
    for prefix in [DEFAULT] + sorted(p for p in _sets if p != DEFAULT):
        s = set_for(prefix)
        if not s:
            continue
        out.append({"prefix": prefix, "name": s.get("name") or ("Material Design" if prefix == DEFAULT else prefix),
                    "count": len(s.get("icons") or {}), "version": s.get("version") or "", "from": s.get("from") or "shipped"})
    return out


def names(prefix: str) -> list[str]:
    return sorted((set_for(prefix) or {}).get("icons", {}))
