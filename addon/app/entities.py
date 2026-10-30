"""The add-on's own values: recording them, and mirroring them into Home Assistant."""

import json
import re
import time
import urllib.parse

import devices
import feeds
import health
import shapes
import notify
import runtime
from config import HA_BASE, HA_TOKEN, PUBLISH_VIA_STATES_API, RETIRED_SENSORS, valid_entity_id
from ha import call_ha_service, ha_json
from layouts_store import load_layouts, load_sources
from sources.flights import fetch_overhead_aircraft, place_of
from render import race as race_words, sport, todo, words
from sources.geo import get_home_locale, get_home_timezone
from sources import needs_you
from sources.ha_services import fetch_todo_items, todo_list_id
from sources.racing import SERIES, compute_racing_active_window, fetch_racing_data, series_slug
from sources.sports import compute_sports_active_window, league_slug


async def publish_entity(session, entity_id, state, attrs=None, register_mqtt=True, keep_attrs=False):
    """Record one of the add-on's computed values.

    The record is what pages read (binding.local_value) and what the editor's
    picker lists. It is mirrored into Home Assistant as an MQTT entity when a
    broker exists. A state of None is "unknown": blank on a page, unknown in
    Home Assistant. keep_attrs keeps the attributes it had.
    """
    if not valid_entity_id(entity_id):
        return
    clean_id = entity_id.strip()
    if keep_attrs and attrs is None:
        attrs = dict((runtime.PUBLISHED.get(clean_id) or {}).get("attributes") or {})
    merged_attrs = dict(attrs or {})
    if clean_id.startswith("sensor.epaper_"):
        merged_attrs.setdefault("source", "epaper_studio")
        fn = merged_attrs.get("friendly_name") or clean_id
        if not str(fn).startswith("E-Paper"):
            merged_attrs["friendly_name"] = f"E-Paper · {fn}"
        runtime.PUBLISHED[clean_id] = {
            "entity_id": clean_id,
            "state": "" if state is None else str(state)[:255],
            "attributes": merged_attrs,
            "register_mqtt": register_mqtt,
            "at": time.time(),
        }
        if runtime.PUBLISHER is not None and register_mqtt:
            runtime.PUBLISHER.set(clean_id, None if state is None else str(state)[:255], merged_attrs)
    if not PUBLISH_VIA_STATES_API or not HA_TOKEN:
        return
    safe_eid = urllib.parse.quote(clean_id, safe=".")
    try:
        await ha_json(session, f"/states/{safe_eid}", method="POST",
                      json={"state": str(state)[:255], "attributes": merged_attrs})
    except Exception as exc:
        print(f"publish {clean_id} failed: {health.describe(exc)}", flush=True)


async def publish_category_sensors(session, cur_f):
    """Retired: see RETIRED_SENSORS. Still published for a page that binds to one."""
    if not cur_f or not cur_f.rendered_at:
        return
    if not retired_sensors_in_use(load_layouts(devices.primary()["id"])):
        return
    try:
        await publish_entity(session, "sensor.epaper_category_count", cur_f.cat_count,
                             {"friendly_name": "E-Paper Category Count", "icon": "mdi:view-grid-outline",
                              "offsets": cur_f.cat_offsets, "sizes": cur_f.cat_sizes, "names": cur_f.cat_names})
        await publish_entity(session, "sensor.epaper_category_offsets", ",".join(map(str, cur_f.cat_offsets)),
                             {"friendly_name": "E-Paper Category Offsets", "icon": "mdi:format-list-numbered"})
        await publish_entity(session, "sensor.epaper_category_sizes", ",".join(map(str, cur_f.cat_sizes)),
                             {"friendly_name": "E-Paper Category Sizes", "icon": "mdi:format-list-bulleted"})
        await publish_entity(session, "sensor.epaper_category_pill_widths", ",".join(map(str, cur_f.cat_pill_widths)),
                             {"friendly_name": "E-Paper Category Pill Widths", "icon": "mdi:ruler"})
        await publish_entity(session, "sensor.epaper_category_names", ",".join(cur_f.cat_names),
                             {"friendly_name": "E-Paper Category Names", "icon": "mdi:tag-multiple-outline"})
    except Exception as exc:
        print(f"publish category sensors error: {health.describe(exc)}", flush=True)


async def publish_flights(session, lat, lon, radius, label, suffix="", own=""):
    aircraft = await fetch_overhead_aircraft(session, radius_km=radius, lat=lat, lon=lon, own=own)
    if aircraft is None:
        # No list, or only one too old to trust: unknown, not a stale count.
        await publish_entity(session, f"sensor.epaper_flights_overhead{suffix}", None, None, keep_attrs=True)
        await publish_entity(session, f"sensor.epaper_closest_aircraft{suffix}", None, None, keep_attrs=True)
        return
    where = label or "Home"
    attrs = {
        "unit_of_measurement": "aircraft",
        "friendly_name": f"E-Paper · Flights overhead ({label})" if label else "E-Paper · Flights overhead",
        "closest_callsign": aircraft[0]["callsign"] if aircraft else "None",
        "radius_km": radius,
        "location_name": where,
        "icon": "mdi:airplane",
    }
    if lat is not None and lon is not None:
        attrs["latitude"], attrs["longitude"] = lat, lon
    if aircraft:
        a = aircraft[0]
        attrs["closest_distance_km"] = a["distance_km"]
        attrs["closest_bearing"] = a["bearing_cardinal"]
        attrs["closest_route"] = f"{a['origin']} → {a['destination']}" if a.get("origin") and a.get("destination") else ""
        attrs["closest_model"] = a.get("model", "")
    await publish_entity(session, f"sensor.epaper_flights_overhead{suffix}", len(aircraft), attrs)
    if not aircraft:
        # Nothing overhead: no closest aircraft either (it used to keep the last one).
        await publish_entity(session, f"sensor.epaper_closest_aircraft{suffix}", None, None, keep_attrs=True)
    if aircraft:
        a = aircraft[0]
        alt_m, spd_ms = float(a.get("altitude_m") or 0.0), float(a.get("velocity_ms") or 0.0)
        await publish_entity(session, f"sensor.epaper_closest_aircraft{suffix}", a["callsign"], {
            "friendly_name": f"E-Paper · Closest aircraft ({label})" if label else "E-Paper · Closest aircraft",
            "distance_km": a.get("distance_km"), "bearing": a.get("bearing_cardinal"),
            "altitude_m": int(alt_m), "altitude_ft": int(alt_m * 3.28084),
            "speed_kts": int(spd_ms * 1.94384), "speed_kmh": int(spd_ms * 3.6),
            "track_deg": int(a.get("track_deg") or 0), "country": a.get("country"),
            "model": a.get("model", ""), "location_name": where, "icon": "mdi:airplane"})


def _source_key(src: dict) -> tuple:
    return ("source", json.dumps(src, sort_keys=True, default=str))


async def publish_sources(session):
    """Your data sources, fetched in the background (live_data): a render only
    reads their latest values and never waits on a slow or dead server.

    A source that fails keeps its last good value and its entity; health
    records the failure, which shows in the editor and as a problem sensor.
    """
    srcs = [s for s in load_sources() if isinstance(s, dict)]
    ctx = {"ha_base": HA_BASE, "ha_token": HA_TOKEN, "session": session}
    for src in srcs:
        slug = feeds.clean_slug(src.get("name"))
        if src.get("type") not in feeds.REGISTRY or not slug or feeds.fills(src):
            continue                    # one that fills a widget isn't a sensor: the widget reads it
        name = f"Source “{slug}”"

        async def fetch(src=src, name=name):
            # Its words ("3 days ago") are in its sensor, for every page and Home Assistant alike: in
            # Home Assistant's language.
            country, language = await get_home_locale(session)
            try:
                with words.speaking(language, country):
                    rows = await feeds.run_one(src, {**ctx, "session": runtime.SESSION or session})
            except Exception as exc:
                health.fail(name, exc, kind="source")
                raise
            health.ok(name, kind="source")
            return rows

        rows = await runtime.LIVE.read(_source_key(src), fetch, feeds.interval_of(src))
        for entity_id, state, attrs in rows or []:
            if attrs and "items" in attrs:
                runtime.FEED_ITEMS[entity_id] = attrs["items"]
            await publish_entity(session, entity_id, state, attrs)
    return set().union(*(feeds.source_entities(s) for s in srcs)) if srcs else set()


async def publish_todo_due(session, spec: dict, home_tz) -> set[str]:
    """For each to-do list on a page, how many of its items are due today or
    overdue (sensor.epaper_todo_<list>_due), for a page's "only when" or an
    alert. The list's own state already counts what's open."""
    lists = {todo_list_id(el.get("entity")) for p in (spec.get("pages") or {}).values()
             for el in p.get("elements", []) if el.get("type") == "todo_list"} - {""}
    wanted = set()
    for eid in sorted(lists):
        sensor_id = todo.due_sensor(eid)
        wanted.add(sensor_id)
        try:
            data = await fetch_todo_items(session, eid)
            if not data:
                continue                                  # not fetched yet
            due = todo.items_for(data.get("items"), "due", todo.now_in(home_tz))
            await publish_entity(session, sensor_id, len(due), {
                "friendly_name": f"E-Paper · {data.get('name') or eid} due",
                "icon": "mdi:clipboard-text-clock-outline",
                "items": [i["summary"] for i in due],
            })
        except Exception as exc:
            print(f"publish to-do due sensor failed: {health.describe(exc)}", flush=True)
    return wanted


NEEDS_YOU_NAMES = {"notifications": ("Notifications", "mdi:bell-outline"), "updates": ("Updates", "mdi:package-up"),
                   "repairs": ("Repairs", "mdi:wrench-outline")}


def aircraft_places(flight_elements) -> list[tuple]:
    """The places Planes pages watch, each once: (lat, lon, radius, label, own).

    A place is where it is: pages at the same spot share it, whatever distance each
    watches (each page still picks its own planes, widgets._planes_near). Its sensors
    count out to the largest of those distances. Its name and its planes' source (the
    add-on's feeds, or yours) come from the first page that names them."""
    places: list[tuple] = []
    for el in flight_elements:
        lat, lon, radius, label = place_of(el)
        own = shapes.own_source(el)
        for i, (q_lat, q_lon, q_radius, q_label, q_own) in enumerate(places):
            if (q_lat, q_lon) == (lat, lon):
                places[i] = (lat, lon, max(radius, q_radius), q_label or label, q_own or own)
                break
        else:
            places.append((lat, lon, radius, label, own))
    return places


def place_suffixes(places) -> list[str]:
    """Each aircraft place's sensor suffix, in order: none for the first, then its
    label, its coordinates, or "home", and a number on the end when two would share one."""
    out: list[str] = []
    for i, (lat, lon, _radius, label, *_) in enumerate(places):
        if i == 0:
            out.append("")
            continue
        base = (re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")
                or (f"{lat:.2f}_{lon:.2f}".replace("-", "m").replace(".", "_") if lat is not None
                    else "home"))
        suffix, n = "_" + base, 2
        while suffix in out:
            suffix, n = f"_{base}_{n}", n + 1
        out.append(suffix)
    return out


async def publish_needs_you(session, spec: dict) -> set[str]:
    """How many notifications, updates and Repairs issues Home Assistant has
    (sensor.epaper_notifications, _updates, _repairs), for a page's "only
    when" or an alert, answered by the add-on itself (conditions.local).

    They stay the add-on's own values, never entities in Home Assistant: it
    has these numbers already, and the user's rule (22 Oct) is no entities
    nobody asked for. Something that asks for one makes it on demand.
    Returns the entities to keep in Home Assistant: none."""
    used = needs_you.counts_in(spec)
    wanted: set[str] = set()
    try:
        got = await needs_you.counts(session, used)
    except Exception as exc:
        print(f"publish what needs you failed: {health.describe(exc)}", flush=True)
        return wanted
    for key in sorted(used):
        if got.get(key) is None:
            continue                                      # not read yet
        name, icon = NEEDS_YOU_NAMES[key]
        attrs = {"friendly_name": name, "icon": icon}
        if key == "updates":
            attrs.update(needs_you.by_group(await needs_you.fetch_updates(session)))
        await publish_entity(session, needs_you.SENSOR[key], got[key], attrs, register_mqtt=False)
    return wanted


async def publish_computed(session):
    """Run configured data sources and publish on-demand sensors for active E-Paper Studio widgets."""
    # Everything the configuration produces, answering or not: a value whose
    # service is down keeps its entity (mqtt_bridge withdraws only the rest).
    prune_published()
    wanted = await publish_sources(session)
    import kinds                                      # here: kinds' modules import this one
    for dev in kinds.shown_devices():
        wanted |= {devices.entity_id(base, dev) for base in
                   ("sensor.epaper_quiet_hours", "sensor.epaper_panel_last_render", "sensor.epaper_panel_pages",
                    *kinds.of(dev).entities(dev))}

    # Every design some screen shows: their widgets all need their values.
    cur_spec = {"pages": {f"{d}:{name}": page for d in sorted(devices.designs_in_use())
                          for name, page in (devices.design(d).get("pages") or {}).items()}}
    spec_text = json.dumps(cur_spec)
    home_tz = await get_home_timezone(session)

    # Elements by the publisher their widget's gate names (widgets.py Gate.publish): never by type here.
    import widgets
    by_publisher: dict[str, list] = {"flights": [], "sports": [], "racing": []}
    for p in cur_spec.get("pages", {}).values():
        for el in p.get("elements", []):
            w = widgets.get(el.get("type")) if isinstance(el, dict) else None
            gate = w.gates(el) if w else None
            if gate is not None and gate.publish:
                by_publisher.setdefault(gate.publish, []).append(el)
    flight_elements, sports_elements, racing_elements = (by_publisher["flights"], by_publisher["sports"],
                                                         by_publisher["racing"])

    # 1. Aircraft overhead: one pair of sensors per distinct place. The first
    #    place keeps the original names, so existing pages and automations stay
    #    put; others get the place's label (or coordinates) as a suffix.
    places = aircraft_places(flight_elements)
    if not places and ("epaper_flights_overhead" in spec_text or "epaper_closest_aircraft" in spec_text
                       or "overhead_aircraft_count" in spec_text):
        places.append((None, None, 35.0, "", ""))
    for (lat, lon, radius, label, own), suffix in zip(places, place_suffixes(places)):
        wanted |= {f"sensor.epaper_flights_overhead{suffix}", f"sensor.epaper_closest_aircraft{suffix}"}
        try:
            await publish_flights(session, lat, lon, radius, label, suffix, own)
        except Exception as exc:
            print(f"publish aircraft sensor failed: {health.describe(exc)}", flush=True)

    # 2. On-demand Sports Matchday Window sensors (only for leagues actually present in pages)
    try:
        leagues_to_publish = []
        for el in sports_elements:
            lg = el.get("league") or "soccer/eng.1"
            el_tz = el.get("timezone") or home_tz
            team = el.get("team")
            pre_b, post_b = widgets.hours_around(el, "pre_buffer_hours"), widgets.hours_around(el, "post_buffer_hours")
            leagues_to_publish.append((lg, pre_b, post_b, el_tz, team, shapes.own_source(el)))
            wanted.add(f"sensor.epaper_sports_{league_slug(lg)[1]}")

        seen_leagues = set()
        for lg, pre_b, post_b, s_tz, team, own in leagues_to_publish:
            key = f"{lg}:{team or ''}"
            if key in seen_leagues:
                continue
            seen_leagues.add(key)
            win_info = await compute_sports_active_window(session, lg, pre_buffer_hours=pre_b, post_buffer_hours=post_b, tz_name=s_tz, team=team, own=own)
            if not win_info:
                continue                                  # not fetched yet
            slug = win_info["slug"]
            sensor_id = f"sensor.epaper_sports_{slug}"
            sport_icon = "mdi:soccer"
            if "nba" in slug or "basketball" in lg:
                sport_icon = "mdi:basketball"
            elif "nfl" in slug or "football" in lg:
                sport_icon = "mdi:football"
            elif "mlb" in slug or "baseball" in lg:
                sport_icon = "mdi:baseball"
            elif "nhl" in slug or "hockey" in lg:
                sport_icon = "mdi:hockey-puck"

            await publish_entity(
                session, sensor_id, win_info["state"],
                {
                    "friendly_name": f"E-Paper · {win_info['league_name'] or slug.replace('_', ' ').title()} {sport.words(league_slug(lg)[0]).day}",
                    "is_active": win_info["is_active"],
                    "is_live": win_info["is_live"],
                    "matches_today": win_info["matches_today"],
                    "first_kickoff": win_info["first_kickoff"],
                    "first_kickoff_local": win_info.get("first_kickoff_local"),
                    "last_kickoff": win_info["last_kickoff"],
                    "last_kickoff_local": win_info.get("last_kickoff_local"),
                    "window_start": win_info["window_start"],
                    "window_start_local": win_info.get("window_start_local"),
                    "window_end": win_info["window_end"],
                    "window_end_local": win_info.get("window_end_local"),
                    "time_zone": win_info.get("time_zone"),
                    "pre_buffer_hours": win_info["pre_buffer_hours"],
                    "post_buffer_hours": win_info["post_buffer_hours"],
                    "team_filter": win_info.get("team_filter", ""),
                    "matches_summary": win_info["matches_summary"],
                    "icon": sport_icon
                }
            )
    except Exception as exc:
        print(f"publish sports matchday sensor failed: {health.describe(exc)}", flush=True)

    # 3. On-demand Motorsport Session/Race Window sensors (only for series actually present in pages)
    try:
        series_to_publish = []
        for el in racing_elements:
            ser = el.get("series") or "f1"
            el_tz = el.get("timezone") or home_tz
            w_mode = el.get("window_mode") or "session"
            pre_b, post_b = widgets.hours_around(el, "pre_buffer_hours"), widgets.hours_around(el, "post_buffer_hours")
            series_to_publish.append((ser, pre_b, post_b, w_mode, el_tz, shapes.own_source(el)))
            wanted.add(f"sensor.epaper_racing_{series_slug(ser)[0]}")

        seen_series = set()
        for ser, pre_b, post_b, w_mode, r_tz, own in series_to_publish:
            if series_slug(ser)[0] in seen_series:       # "irl" and "indycar" are one sensor
                continue
            seen_series.add(series_slug(ser)[0])
            win_info = await compute_racing_active_window(session, ser, pre_buffer_hours=pre_b, post_buffer_hours=post_b, window_mode=w_mode, tz_name=r_tz, own=own)
            if not win_info:
                continue                                  # not fetched yet
            slug = win_info["slug"]
            sensor_id = f"sensor.epaper_racing_{slug}"
            r_data = await fetch_racing_data(session, slug, tz_name=r_tz, own=own, post_buffer_hours=post_b)
            r_icon = SERIES[slug].icon
            country, language = await get_home_locale(session)
            with words.speaking(language, country):             # its words as a page says them, in Home Assistant's language
                r_detail = race_words.detail(r_data) if r_data else ""
                r_clock = race_words.forms(r_data)[0] if r_data else ""
            await publish_entity(
                session, sensor_id, win_info["state"],
                {
                    "friendly_name": f"E-Paper · {win_info['series_name']} Window",
                    "is_active": win_info["is_active"],
                    "is_live": win_info["is_live"],
                    "session_status": (r_data or {}).get("status", "PRE"),
                    "event_name": (r_data or {}).get("event_name") or win_info["event_name"],
                    "circuit": (r_data or {}).get("circuit") or win_info["circuit"],
                    "session_name": win_info["session_name"],
                    "detail": r_detail,
                    "clock": r_clock,
                    "window_mode": win_info["window_mode"],
                    "window_start": win_info["window_start"],
                    "window_start_local": win_info["window_start_local"],
                    "window_end": win_info["window_end"],
                    "window_end_local": win_info["window_end_local"],
                    "pre_buffer_hours": win_info["pre_buffer_hours"],
                    "post_buffer_hours": win_info["post_buffer_hours"],
                    "icon": r_icon,
                }
            )
    except Exception as exc:
        print(f"publish racing window sensor failed: {health.describe(exc)}", flush=True)

    # 4. To-do lists on pages: how many items are due today or overdue.
    wanted |= await publish_todo_due(session, cur_spec, home_tz)

    # 5. What needs you in Home Assistant, counted, when a page shows it or waits for it.
    wanted |= await publish_needs_you(session, cur_spec)

    wanted |= retired_sensors_in_use(cur_spec)
    wanted |= publish_health()
    wanted |= notify.kept()                           # pages that notify a phone
    if runtime.PUBLISHER is not None:
        runtime.PUBLISHER.keep(wanted)
    await sync_entities()


def prune_published(max_age: float = runtime.CACHE_DAY) -> None:
    """Forget values nothing has published for a day (a removed widget or source)."""
    now = time.time()
    for eid in [e for e, info in runtime.PUBLISHED.items() if now - info.get("at", now) > max_age]:
        runtime.PUBLISHED.pop(eid, None)
        runtime.FEED_ITEMS.pop(eid, None)


def publish_health() -> set[str]:
    """One problem sensor per outside service in Home Assistant, so a service
    that stops answering is never silent (health.py). Returns their IDs."""
    ids = set()
    if runtime.PUBLISHER is None:
        return ids
    for e in health.status():
        slug = feeds.clean_slug(e["name"])
        if not slug:
            continue
        runtime.PUBLISHER.set_problem(slug, e["name"], e["problem"], {
            "kind": e["kind"], "error": e["error"] or "",
            "last_success": _iso(e["ok_at"]), "failing_since": _iso(e["failing_since"]),
            "icon": "mdi:cloud-alert" if e["problem"] else "mdi:cloud-check-outline"})
        ids.add(f"binary_sensor.epaper_problem_{slug}")
    return ids


def _iso(ts):
    if ts is None:
        return None
    from datetime import datetime
    return datetime.fromtimestamp(ts).astimezone().isoformat(timespec="seconds")


def retired_sensors_in_use(spec: dict) -> set[str]:
    text = json.dumps(spec.get("pages") or {})
    return {eid for eid in RETIRED_SENSORS if eid in text}


async def sync_entities():
    """Mirror the add-on's values into Home Assistant (no-op without a broker). In the
    background: a render never waits on the broker."""
    if runtime.PUBLISHER is not None:
        runtime.PUBLISHER.request_sync()


async def publish_mqtt_discovery(session, frames):
    """Retired in 0.9: replaced by mqtt_bridge, which talks to the broker directly,
    publishes only changes and keeps entities unavailable while the add-on is down.
    No longer called; kept until 0.9 has proven itself, then delete."""
    if not HA_TOKEN:
        return
    try:
        dev_info = {
            "identifiers": ["epaper_panel_hub"],
            "name": "E-Paper Studio",
            "manufacturer": "Elecrow",
            "model": "CrowPanel E-Paper",
            "sw_version": "0.8.27"
        }
        if "epaper_panel_refresh_button" not in runtime.MQTT_DISCOVERED:
            btn_payload = {
                "name": "E-Paper Refresh Now",
                "unique_id": "epaper_panel_refresh_button",
                "command_topic": "homeassistant/epaper_panel/refresh",
                "icon": "mdi:refresh",
                "device": dev_info
            }
            await call_ha_service(session, "mqtt", "publish", {
                "topic": "homeassistant/button/epaper_panel/refresh/config",
                "payload": json.dumps(btn_payload),
                "retain": True
            })
            runtime.MQTT_DISCOVERED.add("epaper_panel_refresh_button")

        for eid, info in list(runtime.PUBLISHED.items()):
            if not eid.startswith("sensor.epaper_") or not info.get("register_mqtt", True):
                continue
            obj_id = eid.split(".", 1)[1]  # e.g. epaper_sports_premier_league
            attrs = dict(info.get("attributes") or {})
            fname = attrs.get("friendly_name") or obj_id.replace("_", " ").title()
            icon = attrs.get("icon") or "mdi:tablet-dashboard"
            dev_class = attrs.get("device_class")
            unit = attrs.get("unit_of_measurement")

            state_topic = f"homeassistant/epaper_panel/{obj_id}/state"
            attr_topic = f"homeassistant/epaper_panel/{obj_id}/attributes"

            if obj_id not in runtime.MQTT_DISCOVERED:
                cfg_payload = {
                    "name": fname,
                    "unique_id": f"epaper_studio_{obj_id}",
                    "default_entity_id": f"sensor.{obj_id}",
                    "object_id": obj_id,
                    "state_topic": state_topic,
                    "json_attributes_topic": attr_topic,
                    "icon": icon,
                    "device": dev_info,
                }
                if dev_class:
                    cfg_payload["device_class"] = dev_class
                if unit:
                    cfg_payload["unit_of_measurement"] = unit
                await call_ha_service(session, "mqtt", "publish", {
                    "topic": f"homeassistant/sensor/epaper_panel/{obj_id}/config",
                    "payload": json.dumps(cfg_payload),
                    "retain": True,
                })
                runtime.MQTT_DISCOVERED.add(obj_id)

            await call_ha_service(session, "mqtt", "publish", {
                "topic": state_topic,
                "payload": str(info.get("state", "")),
                "retain": True,
            })
            clean_attrs = {k: v for k, v in attrs.items() if k not in ("friendly_name", "icon", "unit_of_measurement", "device_class")}
            await call_ha_service(session, "mqtt", "publish", {
                "topic": attr_topic,
                "payload": json.dumps(clean_attrs),
                "retain": True,
            })
    except Exception:
        pass
