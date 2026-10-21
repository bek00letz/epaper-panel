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
