"""The add-on's own values: recording them, and mirroring them into Home Assistant."""

import json
import urllib.parse

import feeds
import runtime
from config import HA_BASE, HA_TOKEN, PUBLISH_VIA_STATES_API, RETIRED_SENSORS, valid_entity_id
from ha import call_ha_service, ha_json
from layouts_store import load_layouts, load_sources
from sources.flights import fetch_overhead_aircraft
from sources.geo import get_home_timezone
from sources.racing import compute_racing_active_window, fetch_racing_data
from sources.sports import compute_sports_active_window


async def publish_entity(session, entity_id, state, attrs=None, register_mqtt=True):
    """Record one of the add-on's computed values.

    The record is what pages read (binding.local_value) and what the editor's
    picker lists. It is mirrored into Home Assistant as an MQTT entity when a
    broker exists.
    """
    if not valid_entity_id(entity_id):
        return
    clean_id = entity_id.strip()
    merged_attrs = dict(attrs or {})
    if clean_id.startswith("sensor.epaper_"):
        merged_attrs.setdefault("source", "epaper_studio")
        fn = merged_attrs.get("friendly_name") or clean_id
        if not str(fn).startswith("E-Paper"):
            merged_attrs["friendly_name"] = f"E-Paper · {fn}"
        runtime.PUBLISHED[clean_id] = {
            "entity_id": clean_id,
            "state": str(state)[:255],
            "attributes": merged_attrs,
            "register_mqtt": register_mqtt,
        }
        if runtime.PUBLISHER is not None and register_mqtt:
            runtime.PUBLISHER.set(clean_id, str(state)[:255], merged_attrs)
    if not PUBLISH_VIA_STATES_API or not HA_TOKEN:
        return
    safe_eid = urllib.parse.quote(clean_id, safe=".")
    try:
        await ha_json(session, f"/states/{safe_eid}", method="POST",
                      json={"state": str(state)[:255], "attributes": merged_attrs})
    except Exception as exc:
        print(f"publish {clean_id} failed: {exc!r}", flush=True)


async def publish_category_sensors(session, cur_f):
    """Retired: see RETIRED_SENSORS. Still published for a page that binds to one."""
    if not cur_f or not cur_f.rendered_at:
        return
    if not retired_sensors_in_use(load_layouts()):
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
        print(f"publish category sensors error: {exc!r}", flush=True)


async def publish_computed(session):
    """Run configured data sources and publish on-demand sensors for active E-Paper Studio widgets."""
    srcs = load_sources()
    if srcs:
        ctx = {"ha_base": HA_BASE, "ha_token": HA_TOKEN, "session": session}
        for entity_id, state, attrs in await feeds.run_all(srcs, ctx):
            if attrs and "items" in attrs:
                runtime.FEED_ITEMS[entity_id] = attrs["items"]
            await publish_entity(session, entity_id, state, attrs)

    cur_spec = load_layouts()
    spec_text = json.dumps(cur_spec)
    home_tz = await get_home_timezone(session)

    flight_elements = []
    sports_elements = []
    racing_elements = []
    for p in cur_spec.get("pages", {}).values():
        for el in p.get("elements", []):
            t = el.get("type")
            if t == "flight_tracker":
                flight_elements.append(el)
            elif t == "sports_match":
                sports_elements.append(el)
            elif t == "sports_racing":
                racing_elements.append(el)

    # 1. On-demand Overhead Aircraft sensors (only when flight_tracker or flight sensor is used)
    if flight_elements or "epaper_flights_overhead" in spec_text or "epaper_closest_aircraft" in spec_text or "overhead_aircraft_count" in spec_text:
        try:
            flight_radius = 35.0
            custom_lat = None
            custom_lon = None
            custom_loc = None
            if flight_elements:
                el = flight_elements[0]
                flight_radius = float(el.get("radius") or 35.0)
                if el.get("lat") is not None and el.get("lon") is not None:
                    try:
                        custom_lat = float(el.get("lat"))
                        custom_lon = float(el.get("lon"))
                    except (ValueError, TypeError):
                        pass
                if el.get("location_name"):
                    custom_loc = str(el.get("location_name")).strip()

            aircraft = await fetch_overhead_aircraft(session, radius_km=flight_radius, lat=custom_lat, lon=custom_lon)
            if aircraft is None:
                raise LookupError("no flight data yet")     # skip this cycle; don't publish a false zero
            closest_cs = aircraft[0]["callsign"] if aircraft else "None"
            friendly_sensor_name = f"E-Paper · Flights Overhead ({custom_loc})" if custom_loc else "E-Paper · Flights Overhead"
            attrs = {
                "unit_of_measurement": "aircraft",
                "friendly_name": friendly_sensor_name,
                "closest_callsign": closest_cs,
                "radius_km": flight_radius,
                "location_name": custom_loc or "Home",
                "icon": "mdi:airplane"
            }
            if custom_lat is not None and custom_lon is not None:
                attrs["latitude"] = custom_lat
                attrs["longitude"] = custom_lon
            if aircraft:
                attrs["closest_distance_km"] = aircraft[0]["distance_km"]
                attrs["closest_bearing"] = aircraft[0]["bearing_cardinal"]
                attrs["closest_route"] = aircraft[0].get("origin", "") + " → " + aircraft[0].get("destination", "") if (aircraft[0].get("origin") and aircraft[0].get("destination")) else ""
                attrs["closest_model"] = aircraft[0].get("model", "")
            await publish_entity(session, "sensor.epaper_flights_overhead", len(aircraft), attrs)
            if aircraft:
                ac0 = aircraft[0]
                alt_m0 = float(ac0.get("altitude_m") or 0.0)
                spd_ms0 = float(ac0.get("velocity_ms") or 0.0)
                await publish_entity(session, "sensor.epaper_closest_aircraft", closest_cs,
                                     {"friendly_name": "E-Paper · Closest Aircraft",
                                      "distance_km": ac0.get("distance_km"),
                                      "bearing": ac0.get("bearing_cardinal"),
                                      "altitude_m": int(alt_m0),
                                      "altitude_ft": int(alt_m0 * 3.28084),
                                      "speed_kts": int(spd_ms0 * 1.94384),
                                      "speed_kmh": int(spd_ms0 * 3.6),
                                      "track_deg": int(ac0.get("track_deg") or 0),
                                      "country": ac0.get("country"),
                                      "model": ac0.get("model", ""),
                                      "location_name": custom_loc or "Home",
                                      "icon": "mdi:airplane"})
        except Exception as exc:
            if not isinstance(exc, LookupError):
                print(f"publish aircraft sensor failed: {exc!r}", flush=True)

    # 2. On-demand Sports Matchday Window sensors (only for leagues actually present in pages)
    try:
        leagues_to_publish = []
        for el in sports_elements:
            lg = el.get("league") or "soccer/eng.1"
            el_tz = el.get("timezone") or home_tz
            team = el.get("team")
            try:
                pre_b = float(el.get("pre_buffer_hours")) if el.get("pre_buffer_hours") is not None else 2.0
            except (ValueError, TypeError):
                pre_b = 2.0
            try:
                post_b = float(el.get("post_buffer_hours")) if el.get("post_buffer_hours") is not None else 2.0
            except (ValueError, TypeError):
                post_b = 2.0
            leagues_to_publish.append((lg, pre_b, post_b, el_tz, team))

        seen_leagues = set()
        for lg, pre_b, post_b, s_tz, team in leagues_to_publish:
            key = f"{lg}:{team or ''}"
            if key in seen_leagues:
                continue
            seen_leagues.add(key)
            win_info = await compute_sports_active_window(session, lg, pre_buffer_hours=pre_b, post_buffer_hours=post_b, tz_name=s_tz, team=team)
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
                    "friendly_name": f"E-Paper · {win_info['league_name']} Matchday",
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
        print(f"publish sports matchday sensor failed: {exc!r}", flush=True)

    # 3. On-demand Motorsport Session/Race Window sensors (only for series actually present in pages)
    try:
        series_to_publish = []
        for el in racing_elements:
            ser = el.get("series") or "f1"
            el_tz = el.get("timezone") or home_tz
            w_mode = el.get("window_mode") or "session"
            try:
                pre_b = float(el.get("pre_buffer_hours")) if el.get("pre_buffer_hours") is not None else 2.0
            except (ValueError, TypeError):
                pre_b = 2.0
            try:
                post_b = float(el.get("post_buffer_hours")) if el.get("post_buffer_hours") is not None else 2.0
            except (ValueError, TypeError):
                post_b = 2.0
            series_to_publish.append((ser, pre_b, post_b, w_mode, el_tz))

        seen_series = set()
        for ser, pre_b, post_b, w_mode, r_tz in series_to_publish:
            if ser in seen_series:
                continue
            seen_series.add(ser)
            win_info = await compute_racing_active_window(session, ser, pre_buffer_hours=pre_b, post_buffer_hours=post_b, window_mode=w_mode, tz_name=r_tz)
            if not win_info:
                continue                                  # not fetched yet
            slug = win_info["slug"]
            sensor_id = f"sensor.epaper_racing_{slug}"
            r_data = await fetch_racing_data(session, slug, tz_name=r_tz)
            r_icon = "mdi:car-electric" if slug == "fe" else "mdi:racing-helmet"
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
                    "detail": (r_data or {}).get("detail", ""),
                    "clock": (r_data or {}).get("clock", ""),
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
        print(f"publish racing window sensor failed: {exc!r}", flush=True)

    await sync_entities()


def retired_sensors_in_use(spec: dict) -> set[str]:
    text = json.dumps(spec.get("pages") or {})
    return {eid for eid in RETIRED_SENSORS if eid in text}


async def sync_entities():
    """Mirror the add-on's values into Home Assistant (no-op without a broker)."""
    if runtime.PUBLISHER is None:
        return
    try:
        await runtime.PUBLISHER.sync()
    except Exception as exc:
        print(f"mqtt sync failed: {exc!r}", flush=True)


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
