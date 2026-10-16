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

TIME_FORMATS = {
    "time":     "%H:%M",
    "time_12":  "%-I:%M %p",
    "date":     "%-d %b",
    "day_date": "%a, %-d %b",
    "day_full": "%A, %-d %B",
    "datetime": "%-d %b %H:%M",
}


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

    ent = (el.get("entity") or "").strip()
    if not ent:
        return ""

    show = el.get("show") or "state"
    if show == "attribute":
        core = f"state_attr('{_quote(ent)}', '{_quote(el.get('attribute', ''))}')"
    elif show in ("last_changed", "last_updated"):
        src = f"states['{_quote(ent)}'].{show}"
        fmt = el.get("format") or "relative"
        if fmt == "relative":
            core = f"relative_time({src})"
        else:
            pattern = TIME_FORMATS.get(fmt, TIME_FORMATS["time"])
            core = f"as_timestamp({src}) | timestamp_custom('{pattern}')"
    elif show == "days_until":
        # Days remaining until a calendar event or future date sensor
        if ent.startswith("calendar."):
            src = f"state_attr('{_quote(ent)}', 'start_time')"
        else:
            src = f"states('{_quote(ent)}')"
        core = f"((as_timestamp({src}) - as_timestamp(now())) / 86400) | round(0, 'ceil') | int"
    elif show == "date_formatted":
        fmt = el.get("format") or "date"
        pattern = TIME_FORMATS.get(fmt, TIME_FORMATS["date"])
        if ent.startswith("calendar."):
            src = f"state_attr('{_quote(ent)}', 'start_time')"
        else:
            src = f"states('{_quote(ent)}')"
        core = f"as_timestamp({src}) | timestamp_custom('{pattern}')"
    elif show == "calendar_title":
        core = f"state_attr('{_quote(ent)}', 'message')"
    else:
        core = f"states('{_quote(ent)}')"

    # Replacements cover the common "say it in my words" case without a
    # chain of | replace() the user has to write by hand.
    for find, repl in (el.get("replace") or {}).items():
        core = f"({core}) | replace('{_quote(find)}', '{_quote(repl)}')"

    return "{{ " + core + " }}"
