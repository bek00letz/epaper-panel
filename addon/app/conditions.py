"""Page conditions: when a page shows, when an alert fires and when it ends.

The editor's simple form (`web/app/conditions.js`) compiles a sensor, a
comparison and a value to a Home Assistant template. A sensor with no value
(unavailable, unknown, or gone) never meets "isn't" or a number comparison:
`float(0)` would read it as 0, so "battery is below 20" came true every time
Home Assistant started. The form used to write those without the guard;
`guarded` adds it to a condition saved then, so it's fixed without a re-save.
"""
from __future__ import annotations

import re

TRUE = ("true", "on", "yes", "1")

# How long an alert holds, in minutes: for one that ends after a time, the
# time; for one that ends when something happens, the most it holds.
HOLD_DEFAULT = 10
UNTIL_LIMIT_DEFAULT = 120
HOLD_MAX = 1440

# The simple form's "isn't" and number comparisons as written before the guard.
_UNGUARDED = re.compile(
    r"^\{\{\s*("
    r"not\s+is_state\(\s*'(?P<ne>[^']+)'\s*,\s*'[^']*'\s*\)"
    r"|states\(\s*'(?P<num>[^']+)'\s*\)\s*\|\s*(?:int|float)\([^)]*\)\s*(?:>=|<=|>|<)\s*-?\d+(?:\.\d+)?"
    r")\s*\}\}$")


def guarded(expr: str) -> str:
    """The condition with the no-value guard, if it's a simple one written without it."""
    s = str(expr or "").strip()
    m = _UNGUARDED.match(s)
    if not m:
        return s
    ent = m.group("ne") or m.group("num")
    return "{{ has_value('%s') and %s }}" % (ent, m.group(1))


def is_true(value) -> bool:
    return str(value).strip().lower() in TRUE


def ending(page: dict) -> str:
    """An alert's Until condition when it ends "when something happens", else ""."""
    if page.get("ends") != "until":
        return ""
    return str(page.get("until_if") or "").strip()


def hold_minutes(page: dict) -> int:
    default = UNTIL_LIMIT_DEFAULT if page.get("ends") == "until" else HOLD_DEFAULT
    try:
        minutes = int(page.get("hold_minutes") or default)
    except (TypeError, ValueError):
        minutes = default
    return max(1, min(HOLD_MAX, minutes))
