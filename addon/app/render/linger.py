"""Keep a conditional page on screen for a while after its condition last held.

Some conditions flicker by nature: a plane crosses the edge of the radius and
the flight page appears, leaves, and comes back a minute later. Each flicker
reshapes the rotation under the person looking at it. A page that has
appeared therefore stays until its condition has been false for `seconds`.
"""
from __future__ import annotations

import time

DEFAULT_SECONDS = 300.0


class Linger:
    def __init__(self, seconds: float = DEFAULT_SECONDS):
        self.seconds = float(seconds)
        self._last_true: dict[str, float] = {}

    def keep(self, name: str, is_true: bool, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        if is_true:
            self._last_true[name] = now
            return True
        seen = self._last_true.get(name)
        if seen is not None and now - seen < self.seconds:
            return True
        self._last_true.pop(name, None)
        return False

    def forget_except(self, names) -> None:
        keep = set(names)
        for n in list(self._last_true):
            if n not in keep:
                del self._last_true[n]
