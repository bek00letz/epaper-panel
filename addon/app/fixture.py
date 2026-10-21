"""Offline stand-in for Home Assistant (render/fixture.json), for running without a token."""

import json
import re
from datetime import datetime, timedelta, timezone

import runtime
from config import FIXTURE_PATH
from layouts_store import migrate_legacy_entity_refs


_fixture_cache = None


def load_fixture():
    global _fixture_cache
    if _fixture_cache is None:
        try:
            _fixture_cache = json.loads(FIXTURE_PATH.read_text())
        except Exception:
            _fixture_cache = {"states": {}, "pv_curve_w": []}
    return _fixture_cache


def fixture_todo(entity_id: str) -> dict | None:
    """A to-do list as fetch_todo_items gives it, offline. Due dates are
    counted from today (`due_in_days`), so the sample never goes stale."""
    fx = load_fixture()
    items = (fx.get("todo") or {}).get(entity_id)
    if items is None:
        return None
    today = datetime.now().date()
    out = []
    for k, raw in enumerate(items):
        due = raw.get("due") or ""
        if raw.get("due_in_days") is not None:
            due = (today + timedelta(days=int(raw["due_in_days"]))).isoformat()
        out.append({"uid": f"{entity_id}-{k}", "summary": raw.get("summary", ""), "status": "needs_action", "due": due})
    name = ((fx.get("states") or {}).get(entity_id) or {}).get("friendly_name") or entity_id
    return {"entity": entity_id, "name": name, "items": out}


def eval_fixture_template(tpl: str) -> str:
    """Evaluate common HA templates against fixture.json when running offline."""
    states = dict(load_fixture().get("states", {}))
    for eid, info in runtime.PUBLISHED.items():
        attrs = dict(info.get("attributes") or {})
        attrs["state"] = info.get("state", "")
        states[eid] = attrs
    s = migrate_legacy_entity_refs(str(tpl or "").strip())

    # Handle dynamic_grid JSON template: `[{% for e in [...] %}`
    if "[{% for e in [" in s and 'states(e) | to_json' in s:
        m_ents = re.search(r"for e in \[([^\]]+)\]", s)
        res = []
        if m_ents:
            for raw_eid in m_ents.group(1).split(","):
                eid = raw_eid.strip(" '\"")
                if not eid:
                    continue
                st = states.get(eid) or {}
                cur_state = st.get("state", "on")
                fname = st.get("friendly_name") or eid.split(".")[-1].replace("_", " ").title()
                res.append({
                    "entity": eid,
                    "state": str(cur_state),
                    "name": fname,
                    "changed": "25m ago"
                })
        return json.dumps(res)

    # Handle weather_forecast JSON template
    if '"condition": {{ states(' in s and '"temperature": {{ state_attr(' in s:
        return json.dumps({
            "condition": "rainy",
            "temperature": 8.5,
            "unit": "°C",
            "humidity": 95,
            "wind_speed": 6.1,
            "wind_unit": "km/h",
            "forecast": [
                {"datetime": "2026-10-17T09:00:00+00:00", "condition": "rainy", "temperature": 11.2, "templow": 8.5, "precipitation": 1.0},
                {"datetime": "2026-10-18T09:00:00+00:00", "condition": "partlycloudy", "temperature": 15.5, "templow": 4.6, "precipitation": 0.0},
                {"datetime": "2026-10-19T09:00:00+00:00", "condition": "partlycloudy", "temperature": 17.3, "templow": 7.7, "precipitation": 0.0},
                {"datetime": "2026-10-20T09:00:00+00:00", "condition": "cloudy", "temperature": 15.1, "templow": 7.8, "precipitation": 0.1},
                {"datetime": "2026-10-21T09:00:00+00:00", "condition": "rainy", "temperature": 22.7, "templow": 10.6, "precipitation": 0.6}
            ]
        })

    # Handle calendar template
    if '"message": {{ (state_attr(' in s and '"start_time": {{ (state_attr(' in s:
        return json.dumps([
            {"time_label": "TODAY 19:30", "summary": "Dinner with Sarah", "sub": "Trattoria Al Borgo"},
            {"time_label": "TUE 20 OCT", "summary": "Dentist Appointment", "sub": "09:00 AM • Dr. Popa"},
            {"time_label": "THU 22 OCT", "summary": "Trash & Recycling Pickup", "sub": "Bins out by 07:00"},
            {"time_label": "FRI 30 OCT", "summary": "Trip to Munich", "sub": "Flight LH1657"}
        ])

    if s.startswith("{{") and s.endswith("}}"):
        expr = s[2:-2].strip()
    else:
        expr = s

    # The simple form's no-value guard: `has_value('entity') and <condition>`
    m = re.match(r"^has_value\(\s*'([^']+)'\s*\)\s+and\s+(.+)$", expr)
    if m:
        cur = (states.get(m.group(1)) or {}).get("state")
        if cur is None or str(cur) in ("unavailable", "unknown"):
            return "False"
        expr = m.group(2).strip()

    # Handle `not is_state('entity', 'val')`
    m = re.match(r"^not\s+is_state\(\s*'([^']+)'\s*,\s*'([^']+)'\s*\)$", expr)
    if m:
        cur = (states.get(m.group(1)) or {}).get("state", "")
        return "True" if str(cur) != m.group(2) else "False"

    # Handle `states('entity') | float(0) < 20` and the like
    m = re.match(r"^states\(\s*'([^']+)'\s*\)\s*\|\s*(int|float)\([^)]*\)\s*(>=|<=|>|<)\s*(-?\d+(?:\.\d+)?)$", expr)
    if m:
        try:
            val = float((states.get(m.group(1)) or {}).get("state", 0))
        except (TypeError, ValueError):
            val = 0.0
        if m.group(2) == "int":
            val = float(int(val))
        b = float(m.group(4))
        held = {">": val > b, "<": val < b, ">=": val >= b, "<=": val <= b}[m.group(3)]
        return "True" if held else "False"

    # Handle `is_state('entity', 'val')`
    m = re.match(r"^is_state\(\s*'([^']+)'\s*,\s*'([^']+)'\s*\)$", expr)
    if m:
        eid, target = m.group(1), m.group(2)
        cur = (states.get(eid) or {}).get("state", "")
        return "True" if str(cur) == target else "False"

    # Handle zone check on `in_zones`
    if "in_zones" in expr:
        return "False"

    # Extract base value from `states('...')`, `state_attr('...', '...')`, or `states['...'].last_changed`
    val = ""
    m_state = re.search(r"states\(\s*'([^']+)'\s*\)", expr)
    m_attr = re.search(r"state_attr\(\s*'([^']+)'\s*,\s*'([^']+)'\s*\)", expr)
    m_prop = re.search(r"states\[\s*'([^']+)'\s*\]\.(last_changed|last_updated)", expr)

    # Check if calculating days until a date/event
    if "/ 86400" in expr and "as_timestamp" in expr:
        m_attr = re.search(r"state_attr\(\s*'([^']+)'\s*,\s*'([^']+)'\s*\)", expr)
        m_state = re.search(r"states\(\s*'([^']+)'\s*\)", expr)
        raw_date = None
        if m_attr:
            raw_date = (states.get(m_attr.group(1)) or {}).get(m_attr.group(2))
        elif m_state:
            raw_date = (states.get(m_state.group(1)) or {}).get("state")
        if raw_date:
            try:
                from datetime import timezone
                target_dt = datetime.fromisoformat(str(raw_date).replace("Z", "+00:00"))
                now_dt = datetime.now(timezone.utc if target_dt.tzinfo else None)
                delta = target_dt - now_dt
                val = str(max(0, int(round(delta.total_seconds() / 86400))))
            except Exception:
                val = "4"
        else:
            val = "4"
        return val

    if m_attr:
        eid, attr = m_attr.group(1), m_attr.group(2)
        raw = (states.get(eid) or {}).get(attr)
        val = "" if raw is None else str(raw)
        if "timestamp_custom" in expr:
            m_fmt = re.search(r"timestamp_custom\(\s*'([^']+)'\s*\)", expr)
            fmt = m_fmt.group(1) if m_fmt else "%-d %b"
            try:
                dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
                val = dt.strftime(fmt)
            except Exception:
                val = str(raw)
        elif "[:-3]" in expr and len(val) > 3:
            val = val[:-3]
    elif m_prop:
        eid, prop = m_prop.group(1), m_prop.group(2)
        raw = (states.get(eid) or {}).get(prop, "")
        if "relative_time" in expr:
            val = "2 hours ago"
        elif "timestamp_custom" in expr:
            m_fmt = re.search(r"timestamp_custom\(\s*'([^']+)'\s*\)", expr)
            fmt = m_fmt.group(1) if m_fmt else "%H:%M"
            try:
                dt = datetime.fromisoformat(str(raw))
                val = dt.strftime(fmt)
            except Exception:
                val = str(raw)
        else:
            val = str(raw)
    elif m_state:
        eid = m_state.group(1)
        raw = (states.get(eid) or {}).get("state")
        val = "" if raw is None else str(raw)
        if "timestamp_custom" in expr:
            m_fmt = re.search(r"timestamp_custom\(\s*'([^']+)'\s*\)", expr)
            fmt = m_fmt.group(1) if m_fmt else "%-d %b"
            try:
                dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
                val = dt.strftime(fmt)
            except Exception:
                val = str(raw)

    # Apply any chained `| replace('find', 'repl')`
    for m_rep in re.finditer(r"\|\s*replace\(\s*'((?:\\'|[^'])*)'\s*,\s*'((?:\\'|[^'])*)'\s*\)", expr):
        find = m_rep.group(1).replace("\\'", "'").replace("\\\\", "\\")
        repl = m_rep.group(2).replace("\\'", "'").replace("\\\\", "\\")
        val = val.replace(find, repl)

    return val
