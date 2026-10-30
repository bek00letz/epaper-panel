"""Readers: one small module per provider, each turning what that app keeps on this computer into
the report's shape (shape.Provider). Adding a provider is adding a module here; nothing else in
the reporter, and nothing in the add-on, names one.

A reader module has:

    ID     its provider id ("claude"), part of its sensors' names, never changed
    NAME   what a person calls it ("Claude Code")
    def read(ctx: Context) -> shape.Provider | shape.Skipped

`read` never raises for something it can't find (that's Skipped "not_found" or "no_limits"); an
unexpected error is caught here and reported as "error", its details only in the log.
"""
from __future__ import annotations

import importlib
import json
import os
import pkgutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .. import shape


@dataclass
class Context:
    home: Path                              # the person's home folder (a test's own in the tests)
    state: Path                             # the reporter's folder for its caches
    now: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    settings: dict = field(default_factory=dict)   # this reader's own settings ({"account": "Work"})
    env: dict = field(default_factory=lambda: dict(os.environ))
    log: Optional[object] = None

    def cache(self, name: str) -> "Cache":
        return Cache(self.state / f"cache-{name}.json")


class Cache:
    """A reader's small memory between runs (what it has read of each file), kept as JSON."""

    def __init__(self, path: Path):
        self.path = path
        try:
            self.data = json.loads(path.read_text())
        except (OSError, ValueError):
            self.data = {}
        if not isinstance(self.data, dict):
            self.data = {}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(self.data))
        tmp.replace(self.path)


def modules() -> list:
    """Every reader, in name order."""
    out = []
    for info in sorted(pkgutil.iter_modules(__path__), key=lambda m: m.name):
        if info.name.startswith("_"):
            continue
        mod = importlib.import_module(f"{__name__}.{info.name}")
        if hasattr(mod, "read") and hasattr(mod, "ID"):
            out.append(mod)
    return out


def read_all(ctx_for) -> tuple[list, list]:
    """(providers found, skipped) from every reader. `ctx_for(module)` gives each its Context."""
    found, skipped = [], []
    for mod in modules():
        ctx = ctx_for(mod)
        try:
            got = mod.read(ctx)
        except Exception as exc:                  # one reader that breaks never stops the others
            if ctx.log:
                ctx.log(f"{mod.NAME}: couldn't be read ({type(exc).__name__}: {exc})")
            got = shape.Skipped(mod.ID, mod.NAME, "error")
        if isinstance(got, shape.Provider):
            try:
                for w in got.windows:
                    shape.check_window(w)
            except ValueError as exc:
                if ctx.log:
                    ctx.log(f"{mod.NAME}: a window isn't in the report's shape ({exc})")
                got = shape.Skipped(mod.ID, mod.NAME, "error")
        (found if isinstance(got, shape.Provider) else skipped).append(got)
    return found, skipped
