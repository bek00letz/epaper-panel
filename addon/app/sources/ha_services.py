"""Weather forecasts, calendar events and to-do lists, through Home Assistant's actions."""

import health
import json
import time
import urllib.parse

import runtime
from config import HA_TOKEN, valid_entity_id
from fixture import fixture_todo
from ha import ha_json


_weather_cache = {}
_calendar_cache = {}


async def default_weather(session) -> str:
    """The weather a Weather widget without one shows: the first Home Assistant has (by name), never a
    guessed entity ID. "" when there's none."""
    if not HA_TOKEN:
        return "weather.forecast_home"                  # the offline fixture's
    states = runtime.ENTITY_CACHE.get("items") or []
    if not states:
        try:
            states = await ha_json(session, "/states")
        except Exception:
            return ""
    ids = sorted(s["entity_id"] for s in states if isinstance(s, dict) and str(s.get("entity_id", "")).startswith("weather."))
    return ids[0] if ids else ""


@runtime.live(300)
async def fetch_weather_forecast(session, entity_id, fallback=None):
    eid = str(entity_id or "").strip()
    if not valid_entity_id(eid):
        return fallback
    now = time.time()
    cached = _weather_cache.get(eid)
    if cached and (now - cached["at"] < 600):
        return cached["data"]

    base_data = {}
    if isinstance(fallback, dict):
        base_data = dict(fallback)
    elif isinstance(fallback, str) and fallback.strip():
        try:
            base_data = json.loads(fallback)
        except Exception:
            pass

    if not HA_TOKEN:
        return base_data

    try:
        st = await ha_json(session, f"/states/{urllib.parse.quote(eid, safe='.')}")
        attrs = st.get("attributes", {})
        base_data.update({
            "entity": eid,
            "condition": st.get("state", base_data.get("condition", "cloudy")),
            "temperature": attrs.get("temperature", base_data.get("temperature")),
            "unit": attrs.get("temperature_unit", base_data.get("unit", "°C")),
            "humidity": attrs.get("humidity", base_data.get("humidity")),
            "wind_speed": attrs.get("wind_speed", base_data.get("wind_speed")),
            "wind_unit": attrs.get("wind_speed_unit", base_data.get("wind_unit", "km/h")),
            "attribution": attrs.get("attribution", "")
        })

        f_resp = await ha_json(session, "/services/weather/get_forecasts?return_response=1",
                               method="POST", json={"entity_id": eid, "type": "daily"})
        # HA REST API wraps ?return_response=1 in {"service_response": {eid: {"forecast": [...]}}}
        payload = (f_resp.get("service_response") or f_resp.get("response") or f_resp) if isinstance(f_resp, dict) else {}
        forecast_list = None
        if isinstance(payload, dict) and eid in payload and isinstance(payload[eid], dict):
            forecast_list = payload[eid].get("forecast")
        if not isinstance(forecast_list, list) or not forecast_list:
            for f_type in ("twice_daily", "hourly"):
                try:
                    f_resp2 = await ha_json(session, "/services/weather/get_forecasts?return_response=1",
                                            method="POST", json={"entity_id": eid, "type": f_type})
                    p2 = (f_resp2.get("service_response") or f_resp2.get("response") or f_resp2) if isinstance(f_resp2, dict) else {}
                    if isinstance(p2, dict) and eid in p2 and isinstance(p2[eid], dict):
                        cand = p2[eid].get("forecast")
                        if isinstance(cand, list) and cand:
                            forecast_list = cand
                            break
                except Exception:
                    pass
        if (not isinstance(forecast_list, list) or not forecast_list) and isinstance(attrs.get("forecast"), list):
            forecast_list = attrs.get("forecast")
        if isinstance(forecast_list, list) and forecast_list:
            base_data["forecast"] = forecast_list

        _weather_cache[eid] = {"at": now, "data": base_data}
        runtime.prune(_weather_cache)
        return base_data
    except Exception as exc:
        print(f"fetch_weather_forecast error for {eid}: {health.describe(exc)}", flush=True)
        return base_data


@runtime.live(120)
async def fetch_calendar_events(session, entity_id, days=31, fallback=None):
    raw_eid = str(entity_id or "").strip()
    if not raw_eid:
        return fallback
    now = time.time()
    cached = _calendar_cache.get(raw_eid)
    if cached and (now - cached["at"] < 300):
        return cached["data"]

    if not HA_TOKEN:
        return fallback

    # Support comma-separated list of calendar entities for family/multi-calendar merging
    eids = [e.strip() for e in raw_eid.split(",") if e.strip()]
    if not eids:
        return fallback

    try:
        all_events = []
        for eid in eids:
            try:
                c_resp = await ha_json(session, "/services/calendar/get_events?return_response=1",
                                       method="POST", json={"entity_id": eid, "duration": {"days": days}})
                payload = (c_resp.get("service_response") or c_resp.get("response") or c_resp) if isinstance(c_resp, dict) else {}
                cal_events = []
                if isinstance(payload, dict) and eid in payload and isinstance(payload[eid], dict):
                    cal_events = payload[eid].get("events") or []
                
                # Tag each event with source calendar badge
                short_badge = eid.replace("calendar.", "").upper()[:4]
                for ev in cal_events:
                    ev_copy = dict(ev)
                    ev_copy["calendar"] = eid
                    ev_copy["cal_badge"] = short_badge
                    all_events.append(ev_copy)
            except Exception as e_inner:
                print(f"calendar fetch error for {eid}: {e_inner!r}", flush=True)

        # Deduplicate and sort chronologically by start timestamp
        def _event_key(ev):
            raw_st = ev.get("start") or ev.get("start_time") or ""
            return str(raw_st)

        all_events.sort(key=_event_key)
        _calendar_cache[raw_eid] = {"at": now, "data": all_events}
        runtime.prune(_calendar_cache)
        return all_events
    except Exception as exc:
        print(f"fetch_calendar_events error for {raw_eid}: {health.describe(exc)}", flush=True)
        return fallback


def todo_list_id(entity_id) -> str:
    """A to-do list's entity ID, or "" if it isn't one."""
    eid = str(entity_id or "").strip()
    return eid if eid.startswith("todo.") and valid_entity_id(eid) else ""


@runtime.live(60)
async def fetch_todo_items(session, entity_id, fallback=None):
    """A to-do list's open items, in the list's own order, and its name:
    {"entity", "name", "items": [{"uid", "summary", "due"}...]}.

    Through Home Assistant's `todo.get_items`, so it works for every kind of
    list (Shopping list, Local To-do, Google Tasks, Todoist...). A failure
    raises, so the last list it had stays on the page.
    """
    eid = todo_list_id(entity_id)
    if not eid:
        return fallback
    if not HA_TOKEN:
        return fixture_todo(eid)
    st = await ha_json(session, f"/states/{urllib.parse.quote(eid, safe='.')}")
    resp = await ha_json(session, "/services/todo/get_items?return_response=1",
                         method="POST", json={"entity_id": eid, "status": ["needs_action"]})
    payload = (resp.get("service_response") or resp.get("response") or resp) if isinstance(resp, dict) else {}
    found = payload.get(eid) if isinstance(payload, dict) else None
    if not isinstance(found, dict) or not isinstance(found.get("items"), list):
        raise ValueError(f"{eid} gave no items")
    items = [{"uid": str(i.get("uid") or ""), "summary": str(i.get("summary") or "").strip(),
              "status": i.get("status") or "needs_action", "due": i.get("due") or ""}
             for i in found["items"] if isinstance(i, dict)]
    name = ((st or {}).get("attributes") or {}).get("friendly_name") or eid.split(".", 1)[1].replace("_", " ").capitalize()
    return {"entity": eid, "name": str(name), "items": items}
