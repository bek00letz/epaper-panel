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

A time (when it last changed, a date sensor) is asked of Home Assistant as the time
itself and written here (`shown`), in the screen's language: Home Assistant's own
date formats and relative time speak English whatever its language is.
"""
import json
import re
from datetime import datetime

try:
    from . import clock, words
except ImportError:                     # imported as a top-level module
    from render import clock, words

TIME_FORMATS = {
    "time":     "%H:%M",
    "time_12":  "%-I:%M %p",
    "date":     "%-d %b",
    "day_date": "%a, %-d %b",
    "day_full": "%A, %-d %B",
    "datetime": "%-d %b %H:%M",
}


# The formats that are dates, written in the screen's language (render/words.py's patterns).
DATE_FORMATS = ("date", "day_date", "day_full")
# What shows a time the add-on writes itself, from the time Home Assistant gives.
TIME_SHOWS = ("last_changed", "last_updated", "date_formatted")


def pattern(fmt: str) -> str:
    """A format's strftime pattern; a time of day follows the panel's 12/24-hour setting (clock.py),
    a date the screen's language."""
    if fmt in ("time", "datetime"):
        return clock.pattern(fmt)
    if fmt in DATE_FORMATS:
        return words.date_pattern(fmt)
    return TIME_FORMATS.get(fmt, clock.pattern("time"))


def shows_time(el) -> bool:
    """Whether an element's binding shows a time the add-on writes (`shown`)."""
    raw = el.get("value")
    return not (isinstance(raw, str) and raw.strip()) and el.get("show") in TIME_SHOWS \
        and bool(str(el.get("entity") or "").strip())


def _replaced(el, text: str) -> str:
    repl_map = el.get("replace")
    if isinstance(repl_map, dict):
        for find, repl in repl_map.items():
            text = text.replace(str(find), str(repl))
    return text


def shown(el, got, now: datetime | None = None) -> str:
    """A time binding's words from the time Home Assistant gave (an ISO time in its zone): "2 hours",
    "14:05", "Tue, 21 Oct", in the element's format and the screen's language, with its replacements."""
    raw = "" if got is None else str(got).strip()
    try:
        when = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return _replaced(el, raw)                    # not a time: as it came ("", or Home Assistant's own words)
    show = el.get("show")
    fmt = el.get("format") or ("relative" if show in ("last_changed", "last_updated") else "date")
    if fmt == "relative":
        now = now or (datetime.now(when.tzinfo) if when.tzinfo else datetime.now())
        text = clock.span((now - when).total_seconds())
    else:
        if show == "date_formatted" and fmt not in TIME_FORMATS:
            fmt = "date"
        text = clock.strftime(when, pattern(fmt))
    return _replaced(el, text)


# A template that is only the clock, `{{ now().strftime('%A') }}`: the add-on's clock too.
CLOCK = re.compile(r"^\s*\{\{\s*now\(\)\.strftime\(\s*'([^'{}\\]*)'\s*\)\s*\}\}\s*$")


def clock_pattern(el) -> str | None:
    """The pattern of an element that shows only the add-on's own clock: `show: "now"` (time by
    default), or a template that is only now().strftime(...). None for anything else. Its value is
    the time (local_value), written when the page is drawn (now_text), in the screen's language:
    Home Assistant's strftime would say the weekday in English whatever its language."""
    raw = el.get("value")
    if isinstance(raw, str) and raw.strip():
        m = CLOCK.match(raw)
        return m.group(1) if m else None
    if el.get("show") == "now":
        return pattern(el.get("format") or "time")
    return None


def now_text(el, now=None) -> str:
    """The add-on's own clock in the element's format, in the screen's language: `now` is the time
    (a datetime, or the ISO time local_value gave), or now. A value that isn't a time (the date a
    sleeping device shows instead, clocktime.py) is shown as it is."""
    if isinstance(now, str):
        try:
            now = datetime.fromisoformat(now)
        except ValueError:
            return now
    return clock.strftime(now or datetime.now(), clock_pattern(el) or pattern("time"))


def _quote(s):
    return (
        str(s)
        .replace("\\", "\\\\")
        .replace("'", "\\'")
        .replace("\n", "\\n")
        .replace("\r", "\\r")
    )


def template_for(el, readable=False):
    """The Jinja a text/number element should render, or "" if it has none.

    Note: `prefix` and `suffix` are applied in Python after template
    resolution and number formatting (`layout.element_text`), so they can
    neither break `float()` on numeric elements nor inject Jinja syntax.
    A time (TIME_SHOWS) is asked as the time itself, written by `shown`;
    `readable` writes it as Home Assistant would format it instead, for a
    person to read and edit (as_template).
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
        if not readable:
            return "{{ (as_timestamp(" + src + ") | timestamp_local) if " + cond + " else '' }}"
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
        if not readable:
            return "{{ as_timestamp(" + src + ") | timestamp_local }}"
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


def as_template(el) -> str:
    """What an element shows, written out as a template: the editor's From › Template starts from
    it, so switching shows the same thing (a sensor's detail and format, the clock, words you
    replaced; text's Before and After, which a template's text doesn't add). A plain text becomes
    itself as a string; "" for nothing at all."""
    raw = el.get("value")
    if isinstance(raw, str) and ("{{" in raw or "{%" in raw):
        return raw
    bound = {k: v for k, v in el.items() if k != "value"}
    ent = str(el.get("entity") or "").strip()
    tpl = template_for(bound, readable=True)
    if not tpl and ent:
        tpl = "{{ states('" + _quote(ent) + "') }}"        # a total today comes from statistics, not a template
    if not tpl:
        text = str(raw if raw is not None else "")
        return "{{ '" + _quote(text) + "' }}" if text else ""
    if el.get("type") == "text":
        lit = lambda t: ("{{ '" + _quote(t) + "' }}") if any(c in t for c in "{}%#") else t
        tpl = lit(str(el.get("prefix") or "")) + tpl + lit(str(el.get("suffix") or ""))
    return tpl


LOCAL_SHOWS = ("state", "attribute", "unit")


def local_value(el, registry):
    """Resolve a binding to one of the add-on's own entities without Home Assistant.

    The add-on computed these values itself, so asking Home Assistant for them
    back would only add a round trip and a dependency on the entity existing
    there. Returns None when the element is not such a binding, so the caller
    falls back to a template.
    """
    if clock_pattern(el) is not None:
        return datetime.now().isoformat(timespec="seconds")      # the time; its words when drawn (now_text)
    raw = el.get("value")
    if isinstance(raw, str) and raw.strip():
        return None
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
