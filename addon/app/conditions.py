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


# A simple-form condition, guarded or not: the sensor and what it asks.
_SIMPLE = re.compile(
    r"^\{\{\s*(?:has_value\(\s*'(?P<g>[^']+)'\s*\)\s+and\s+)?(?:"
    r"(?P<neg>not\s+)?is_state\(\s*'(?P<se>[^']+)'\s*,\s*'(?P<sv>[^']*)'\s*\)"
    r"|states\(\s*'(?P<ne>[^']+)'\s*\)\s*\|\s*(?P<f>int|float)\([^)]*\)\s*(?P<op>>=|<=|>|<)\s*(?P<nv>-?\d+(?:\.\d+)?)"
    r")\s*\}\}$")
NO_VALUE = (None, "unavailable", "unknown")


def local(expr: str, registry: dict):
    """Answer a simple-form condition on one of the add-on's own values
    (runtime.PUBLISHED) without Home Assistant, as pages read those values
    (binding.local_value): "True", "False", or None when it isn't one.

    Asked of Home Assistant, it only works while an MQTT broker carries the
    value there; without one, a "New to watch" or "due today" page never showed.
    """
    m = _SIMPLE.match(str(expr or "").strip())
    if not m:
        return None
    ent = m.group("se") or m.group("ne")
    if (m.group("g") and m.group("g") != ent) or ent not in registry:
        return None
    state = (registry.get(ent) or {}).get("state")
    state = None if state is None else str(state)
    if m.group("se"):
        if m.group("neg"):
            held = state not in NO_VALUE and state != m.group("sv")
        else:
            held = state == m.group("sv")
        return "True" if held else "False"
    if state in NO_VALUE:
        return "False"
    try:
        a = float(state)
    except ValueError:
        return "False"                # "nothing new" is no value, not 0 (as for Home Assistant's own, d9a8495)
    if m.group("f") == "int":
        a = float(int(a))
    b = float(m.group("nv"))
    held = {">": a > b, "<": a < b, ">=": a >= b, "<=": a <= b}[m.group("op")]
    return "True" if held else "False"


# The add-on's own values, wherever a template asks for them (inline()).
_Q = r"""(?:'(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*")"""
_OWN = r"""['"](sensor\.epaper_[a-z0-9_]+)['"]"""
_STATES = re.compile(r"states\(\s*" + _OWN + r"\s*\)")
_IS_STATE = re.compile(r"is_state\(\s*" + _OWN + r"\s*,\s*(" + _Q + r")\s*\)")
_HAS_VALUE = re.compile(r"has_value\(\s*" + _OWN + r"\s*\)")
_STATE_ATTR = re.compile(r"state_attr\(\s*" + _OWN + r"\s*,\s*['\"]([^'\"]+)['\"]\s*\)")


def literal(value) -> str:
    """A value as a Jinja literal."""
    if value is None:
        return "none"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(literal(v) for v in value) + "]"
    if isinstance(value, dict):
        return "{" + ", ".join(f"{literal(str(k))}: {literal(v)}" for k, v in value.items()) + "}"
    return "'" + str(value).replace("\\", "\\\\").replace("'", "\\'") + "'"


def inline(template: str, registry: dict) -> str:
    """A template with the add-on's own values (runtime.PUBLISHED) written in where it asks for them:
    states(), is_state(), has_value() and state_attr() on sensor.epaper_… . Home Assistant only has
    those through an MQTT broker; written in, any template works without one. Others are left alone."""
    text = str(template or "")
    if "sensor.epaper_" not in text:
        return text

    def state_of(eid):
        got = registry.get(eid)
        return None if got is None else got.get("state")

    def states(m):
        if m.group(1) not in registry:
            return m.group(0)
        st = state_of(m.group(1))
        return literal("unknown" if st is None else str(st))

    def is_state(m):
        if m.group(1) not in registry:
            return m.group(0)
        st = state_of(m.group(1))
        return f"({literal('unknown' if st is None else str(st))} == {m.group(2)})"

    def has_value(m):
        if m.group(1) not in registry:
            return m.group(0)
        st = state_of(m.group(1))
        return literal(st is not None and str(st) not in ("unavailable", "unknown"))

    def state_attr(m):
        if m.group(1) not in registry:
            return m.group(0)
        return literal(((registry.get(m.group(1)) or {}).get("attributes") or {}).get(m.group(2)))

    for pattern, fn in ((_IS_STATE, is_state), (_HAS_VALUE, has_value), (_STATE_ATTR, state_attr), (_STATES, states)):
        text = pattern.sub(fn, text)
    return text


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
