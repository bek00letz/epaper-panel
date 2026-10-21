"""Turn a structured entity binding into a Jinja template.

Dragging an entity gets you its state. Everything else -- when it last
changed, an attribute, saying "outside" instead of "Outdoor Cat" -- used to
mean hand-writing Jinja, which put the editor out of reach for exactly the
cases people want most.

An element may instead describe what it wants:

    {"entity": "sensor.cat_location", "show": "last_changed",
     "format": "time", "prefix": "since "}

A raw `value` template still wins when present, so nothing already built
breaks and power users keep the full language.
"""
import json
from datetime import datetime

try:
    from . import clock
except ImportError:                     # imported as a top-level module
    from render import clock

TIME_FORMATS = {
    "time":     "%H:%M",
    "time_12":  "%-I:%M %p",
    "date":     "%-d %b",
    "day_date": "%a, %-d %b",
    "day_full": "%A, %-d %B",
    "datetime": "%-d %b %H:%M",
}


def pattern(fmt: str) -> str:
    """A format's strftime pattern; a time of day follows the panel's 12/24-hour setting (clock.py)."""
    if fmt in ("time", "datetime"):
        return clock.pattern(fmt)
    return TIME_FORMATS.get(fmt, clock.pattern("time"))


def now_text(el, now: datetime | None = None) -> str:
    """`show: "now"`: the add-on's own clock in the element's format (time by default), never asked of Home Assistant."""
    return clock.strftime(now or datetime.now(), pattern(el.get("format") or "time"))


def _quote(s):
    return (
        str(s)
        .replace("\\", "\\\\")
        .replace("'", "\\'")
        .replace("\n", "\\n")
        .replace("\r", "\\r")
    )


def template_for(el):
    """The Jinja a text/number element should render, or "" if it has none.

    Note: `prefix` and `suffix` are applied in Python after template
    resolution and number formatting (`layout.element_text`), so they can
    neither break `float()` on numeric elements nor inject Jinja syntax.
    """
    raw = el.get("value")
    if isinstance(raw, str) and raw.strip():
        return raw                                   # explicit template wins

    if el.get("show") == "now":                      # the clock: answered by the add-on (local_value)
        return "{{ now().strftime('" + _quote(pattern(el.get("format") or "time")) + "') }}"
    ent = (el.get("entity") or "").strip()
    if not ent:
        return ""

    show = el.get("show") or "state"
    if show == "change_today":
        return ""                                    # from long-term statistics, by the render cycle (frames)
    if show == "attribute":
        core = f"state_attr('{_quote(ent)}', '{_quote(el.get('attribute', ''))}')"
    elif show in ("last_changed", "last_updated"):
        qent = _quote(ent)
        cond = f"(states['{qent}'] is defined and states['{qent}'] is not none and states['{qent}'].{show} is defined)"
        src = f"states['{qent}'].{show}"
        fmt = el.get("format") or "relative"
        if fmt == "relative":
            core = f"relative_time({src}) if {cond} else ''"
        else:
            core = f"as_timestamp({src}) | timestamp_custom('{pattern(fmt)}') if {cond} else ''"
    elif show == "days_until":
        # Days remaining until a calendar event or future date sensor
        if ent.startswith("calendar."):
            src = f"state_attr('{_quote(ent)}', 'start_time')"
        else:
            src = f"states('{_quote(ent)}')"
        core = f"((as_timestamp({src}) - as_timestamp(now())) / 86400) | round(0, 'ceil') | int"
    elif show == "date_formatted":
        fmt = el.get("format") or "date"
        pat = pattern(fmt) if fmt in TIME_FORMATS else TIME_FORMATS["date"]
        if ent.startswith("calendar."):
            src = f"state_attr('{_quote(ent)}', 'start_time')"
        else:
            src = f"states('{_quote(ent)}')"
        core = f"as_timestamp({src}) | timestamp_custom('{pat}')"
    elif show == "unit":
        # The value itself; the renderer turns it into the unit it's shown in
        # and applies the replacements to that word (layout.element_text).
        return "{{ states('" + _quote(ent) + "') }}"
    elif show == "calendar_title":
        core = f"state_attr('{_quote(ent)}', 'message')"
    else:
        core = f"states('{_quote(ent)}')"

    # Replacements cover the common "say it in my words" case without a
    # chain of | replace() the user has to write by hand.
    repl_map = el.get("replace")
    if isinstance(repl_map, dict):
        for find, repl in repl_map.items():
            core = f"({core}) | replace('{_quote(str(find))}', '{_quote(str(repl))}')"

    return "{{ " + core + " }}"


LOCAL_SHOWS = ("state", "attribute", "unit")


def local_value(el, registry):
    """Resolve a binding to one of the add-on's own entities without Home Assistant.

    The add-on computed these values itself, so asking Home Assistant for them
    back would only add a round trip and a dependency on the entity existing
    there. Returns None when the element is not such a binding, so the caller
    falls back to a template.
    """
    raw = el.get("value")
    if isinstance(raw, str) and raw.strip():
        return None
    if el.get("show") == "now":
        return now_text(el)
    ent = (el.get("entity") or "").strip()
    info = registry.get(ent) if ent else None
    if info is None:
        return None
    show = el.get("show") or "state"
    if show not in LOCAL_SHOWS:
        return None
    if show == "attribute":
        val = (info.get("attributes") or {}).get(el.get("attribute", ""))
    else:
        val = info.get("state")
    if val is None:
        text = ""
    elif isinstance(val, (list, dict)):
        text = json.dumps(val, ensure_ascii=False)
    else:
        text = str(val)
    repl_map = el.get("replace")
    if isinstance(repl_map, dict) and show != "unit":
        for find, repl in repl_map.items():
            text = text.replace(str(find), str(repl))
    return text
