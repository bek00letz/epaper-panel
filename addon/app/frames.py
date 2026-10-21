"""Building the frames: which pages are live, their values, alerts, quiet hours, rendering, packing."""

import asyncio
import hashlib
import io
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
from email.utils import formatdate

from render import binding, epf, layout, sleep, stripmeta, subitems, theme as T
import conditions
import devices
import health
import kinds
import runtime
from config import HA_TOKEN, SLEEP_PAGE, valid_entity_id
from entities import publish_category_sensors, publish_computed, publish_entity, sync_entities
from ha import curve_series, ha_json, resolve_templates
from panel_ops import push_panel_update
from sources.flights import fetch_overhead_aircraft, place_of
from sources.geo import get_home_timezone
from sources.ha_services import fetch_calendar_events, fetch_todo_items, fetch_weather_forecast, todo_list_id
from sources import energy
from sources.home import fetch_sun
from sources.racing import compute_racing_active_window, fetch_racing_data
from sources.sports import compute_sports_active_window, fetch_sports_match
from runtime import Frames


def quiet_window(qh: dict) -> tuple[str, str]:
    """Quiet hours' start and end, as HH:MM."""
    return str(qh.get("start") or "23:00").strip()[:5], str(qh.get("end") or "07:00").strip()[:5]


def in_quiet_schedule(qh: dict, now: datetime) -> bool:
    """Whether the clock is inside quiet hours' schedule. Only the clock: no presence, no network."""
    if not qh.get("enabled"):
        return False
    start_str, end_str = quiet_window(qh)
    cur_mins = now.hour * 60 + now.minute
    try:
        sh, sm = [int(x) for x in start_str.split(":")]
        eh, em = [int(x) for x in end_str.split(":")]
    except (TypeError, ValueError):
        return False
    s_mins, e_mins = sh * 60 + sm, eh * 60 + em
    if s_mins == e_mins:
        return False
    return (cur_mins >= s_mins or cur_mins < e_mins) if s_mins > e_mins else (s_mins <= cur_mins < e_mins)


async def evaluate_quiet_hours(session, spec: dict, dev: dict | None = None) -> tuple[bool, str]:
    """Whether a device's quiet hours are on now, and why. `dev` names its entity (the first device's when None)."""
    qh = spec.get("quiet_hours") if isinstance(spec.get("quiet_hours"), dict) else {}
    enabled = bool(qh.get("enabled", False))
    start_str, end_str = quiet_window(qh)
    pres_ent = str(qh.get("presence_entity") or "").strip()
    allow_alerts = bool(qh.get("allow_alerts", True))

    active = False
    reason = "disabled"
    if enabled:
        if in_quiet_schedule(qh, datetime.now()):
            active = True
            reason = f"schedule ({start_str}–{end_str})"

        if not active and pres_ent and valid_entity_id(pres_ent):
            try:
                if HA_TOKEN:
                    safe_eid = urllib.parse.quote(pres_ent, safe=".")
                    st_obj = await ha_json(session, f"/states/{safe_eid}")
                    st_val = str(st_obj.get("state") or "").strip().lower()
                    if st_val in ("not_home", "away", "0", "off"):
                        active = True
                        reason = f"away ({pres_ent}: {st_val})"
            except Exception:
                pass
        if not active:
            reason = "outside quiet window"

    dev = dev or {}
    await publish_entity(session, devices.entity_id("sensor.epaper_quiet_hours", dev), "active" if active else "inactive", {
        "friendly_name": "E-Paper Quiet Hours" if not dev.get("entity_suffix") else f"{dev['name']} · Quiet hours",
        "icon": "mdi:weather-night" if active else "mdi:weather-sunny",
        "enabled": enabled,
        "reason": reason,
        "start": start_str,
        "end": end_str,
        "presence_entity": pres_ent,
        "allow_alerts": allow_alerts,
    })
    return active, reason


def _png(img) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def _etag(data: bytes) -> str:
    return f'"{hashlib.sha256(data).hexdigest()[:16]}"'


async def enrich_page_values(session, page, vals):
    home_tz = await get_home_timezone(session)
    for i, el in enumerate(page.get("elements", [])):
        t = el.get("type")
        if t == "weather_forecast":
            wdata = await fetch_weather_forecast(session, el.get("entity", "weather.forecast_home"), fallback=vals.get(i))
            if wdata:
                vals[i] = wdata
        elif t in ("calendar_month", "calendar_agenda"):
            cal_ent = el.get("entity")
            if cal_ent:
                cal_data = await fetch_calendar_events(session, cal_ent, days=31, fallback=vals.get(i))
                if cal_data:
                    vals[i] = cal_data
        elif t == "todo_list":
            if todo_list_id(el.get("entity")):
                todo_data = await fetch_todo_items(session, todo_list_id(el.get("entity")))
                if todo_data:
                    vals[i] = {**todo_data, "tz": home_tz}   # "Today" is Home Assistant's today
        elif t == "sun_times":
            sun_data = await fetch_sun(session)
            if sun_data is not None:
                vals[i] = {**sun_data, "tz": home_tz}
        elif t == "energy_total":
            got = await energy.fetch_total(session, str(el.get("source") or "solar"), str(el.get("entity") or ""),
                                           str(el.get("period") or "month"))
            if got is not None:
                vals[i] = got
        elif t == "grid_now":
            ent, inv = str(el.get("entity") or ""), bool(el.get("invert"))
            power = await energy.fetch_grid_power(session, ent, inv)
            hours = await energy.fetch_grid_hours(session, ent, inv)
            if power is not None or hours is not None:
                vals[i] = {"watts": None, "bars": [], "today": None, **(hours or {}), **(power or {})}
        elif t == "energy_cost":
            got = await energy.fetch_cost(session)
            if got is not None:
                vals[i] = got
        elif t == "flight_tracker":
            custom_lat, custom_lon, radius, _ = place_of(el)
            fl_data = await fetch_overhead_aircraft(session, radius_km=radius, lat=custom_lat, lon=custom_lon)
            if fl_data is not None:
                vals[i] = fl_data
        elif t == "sports_racing":
            entity_or_series = el.get("entity") or el.get("series") or "f1"
            el_tz = el.get("timezone") or home_tz
            race_data = await fetch_racing_data(session, entity_or_series, fallback=vals.get(i), tz_name=el_tz)
            if race_data:
                vals[i] = race_data
        elif t == "sports_match":
            entity_or_league = el.get("entity") or el.get("league") or "soccer/eng.1"
            team = el.get("team")
            el_tz = el.get("timezone") or home_tz
            match_data = await fetch_sports_match(session, entity_or_league, team=team, fallback=vals.get(i), tz_name=el_tz)
            if match_data:
                vals[i] = match_data


def as_int(value, default: int) -> int:
    """A number from a page element, or the default for anything else (null, "24h", Infinity)."""
    try:
        return int(float(value))
    except (TypeError, ValueError, OverflowError):
        return default


async def _fetch_feed_items(session, elements):
    """Items of a feed sensor the add-on doesn't publish itself, read once from Home Assistant."""
    for el in elements:
        ent = str(el.get("entity", ""))
        if ent.startswith("sensor.epaper_") and not ent.endswith("_count") and not ent.startswith("sensor.epaper_category_") and not ent.startswith("sensor.epaper_panel_"):
            own_items = ((runtime.PUBLISHED.get(ent) or {}).get("attributes") or {}).get("items")
            if own_items:
                runtime.FEED_ITEMS[ent] = own_items
            if ent not in runtime.FEED_ITEMS and valid_entity_id(ent):
                try:
                    st_data = await ha_json(session, f"/states/{ent}")
                    items = (st_data.get("attributes") or {}).get("items")
                    if items:
                        runtime.FEED_ITEMS[ent] = items
                except Exception:
                    pass


def fit_counts(wants: list[int], page_bytes: int, capacity: int, extra_pages: int = 1) -> list[int]:
    """How many items each page shows so the frame file fits the panel.

    Every page keeps its first item; then one more item per page, round by
    round in rotation order, while there is room. Items within a page are
    already in order of importance (your team, live games, the closest
    aircraft, the newest episode), so the ones left out are the least
    important. If even one item per page doesn't fit, pages at the end of the
    rotation are left out. `extra_pages`: the sleep screen.
    """
    def fits(pages: int, cats: int) -> bool:
        return epf.encoded_size(pages + extra_pages, cats + extra_pages, page_bytes) <= capacity

    n = len(wants)
    while n and not fits(n, n):
        n -= 1
    counts = [1] * n + [0] * (len(wants) - n)
    total = n
    grew = True
    while grew:
        grew = False
        for i in range(n):
            if counts[i] < wants[i] and fits(total + 1, n):
                counts[i] += 1
                total += 1
                grew = True
    return counts


def record_fit(plans: list[dict], counts: list[int], capacity: int, previous: dict | None = None,
               device_name: str = "the panel") -> dict:
    """What was left out to fit a panel, for the editor and Home Assistant."""
    trimmed = [{"page": p["name"], "shown": c, "of": p["want"]} for p, c in zip(plans, counts) if c < p["want"]]
    fit = {"capacity": capacity, "pages_shown": sum(counts),
           "pages_wanted": sum(p["want"] for p in plans), "trimmed": trimmed}
    if trimmed and fit["trimmed"] != (previous or {}).get("trimmed"):
        what = ", ".join(f"{t['page']} {t['shown']} of {t['of']}" for t in trimmed)
        print(f"frames: {device_name} holds {fit['pages_shown']} of {fit['pages_wanted']} pages; showing {what}", flush=True)
    return fit


def split_page_values(page):
    """A page's values the add-on already holds, and templates for the rest.

    Bindings to the add-on's own sensors are answered from its own record, so
    they work without a broker and never wait on Home Assistant.
    """
    local, templates = {}, {}
    els = page.get("elements", [])
    for i, tpl in layout.collect_templates(page).items():
        if isinstance(i, int) and i < len(els):
            val = binding.local_value(els[i], runtime.PUBLISHED)
            if val is not None:
                local[i] = val
                continue
        templates[i] = tpl
    return local, templates


async def gather_values(session, spec, names):
    """Resolve every template on every named page in one request."""
    batch, index = {}, []
    out = {n: {} for n in names}
    for name in names:
        local, templates = split_page_values(spec["pages"][name])
        out[name].update(local)
        for i, tpl in templates.items():
            key = f"{name}:{i}"
            batch[key] = tpl
            index.append((name, i, key))
    resolved = await resolve_templates(session, batch)
    for name, i, key in index:
        out[name][i] = resolved.get(key, "")
    for name in names:
        await enrich_page_values(session, spec["pages"][name], out[name])
    return out


def _is_builtin_widget_gate(page: dict) -> dict | None:
    """Return the composite element that drives this page's active window if applicable."""
    els = page.get("elements") or []
    widget = next((e for e in els if isinstance(e, dict) and e.get("type") in ("sports_match", "sports_racing", "flight_tracker")), None)
    if not widget:
        return None
    show_if = str(page.get("show_if") or "").strip()
    if not show_if or widget.get("auto_window"):
        return widget
    # Also intercept any show_if that points to our built-in sports/racing/flight sensors
    # so switching leagues or series in the widget inspector always evaluates the widget's live config!
    builtin_patterns = (
        "sensor.epaper_sports_",
        "sensor.sports_",
        "sensor.epaper_racing_",
        "sensor.f1_status",
        "sensor.formula_e_status",
        "sensor.epaper_flights_overhead",
        "sensor.overhead_aircraft_count",
    )
    if any(pat in show_if for pat in builtin_patterns):
        return widget
    return None


async def _evaluate_widget_gate(session, widget: dict, home_tz: str) -> bool:
    """Directly evaluate the active window for a sports_match, sports_racing, or flight_tracker widget."""
    wtype = widget.get("type")
    el_tz = widget.get("timezone") or home_tz
    try:
        pre_b = float(widget.get("pre_buffer_hours")) if widget.get("pre_buffer_hours") is not None else 2.0
    except (ValueError, TypeError):
        pre_b = 2.0
    try:
        post_b = float(widget.get("post_buffer_hours")) if widget.get("post_buffer_hours") is not None else 2.0
    except (ValueError, TypeError):
        post_b = 2.0

    if wtype == "sports_match":
        lg = widget.get("league") or "soccer/eng.1"
        team = widget.get("team")
        win = await compute_sports_active_window(session, lg, pre_buffer_hours=pre_b, post_buffer_hours=post_b, tz_name=el_tz, team=team)
        return bool((win or {}).get("is_active"))                # None: not fetched yet
    if wtype == "sports_racing":
        series = widget.get("series") or "f1"
        w_mode = widget.get("window_mode") or "session"
        win = await compute_racing_active_window(session, series, pre_buffer_hours=pre_b, post_buffer_hours=post_b, window_mode=w_mode, tz_name=el_tz)
        return bool((win or {}).get("is_active"))
    if wtype == "flight_tracker":
        custom_lat, custom_lon, radius, _ = place_of(widget)
        aircraft = await fetch_overhead_aircraft(session, radius_km=radius, lat=custom_lat, lon=custom_lon)
        return len(aircraft or []) > 0
    return True


async def resolve_conditions(session, conds: dict) -> dict:
    """Conditions' values: those on the add-on's own values answered here
    (conditions.local), the rest by Home Assistant in one request."""
    out = {k: v for k, c in conds.items() if (v := conditions.local(c, runtime.PUBLISHED)) is not None}
    rest = {k: c for k, c in conds.items() if k not in out}
    if rest:
        out.update(await resolve_templates(session, rest))
    return out


async def eligible_pages(session, spec, linger):
    """Pages whose tier and show_if (or built-in widget active window) say they belong in the rotation now.

    `linger` is the design's (runtime.linger): pages that stay a while after their condition.
    """
    rotation = spec.get("rotation", [])
    defs = spec.get("pages", {})
    home_tz = await get_home_timezone(session)

    widget_gates: dict[str, dict] = {}
    template_gates: dict[str, str] = {}

    for n in set(rotation):
        p = defs.get(n)
        if not p or p.get("tier") != "when":
            continue
        w_gate = _is_builtin_widget_gate(p)
        if w_gate is not None:
            widget_gates[n] = w_gate
        elif p.get("show_if"):
            template_gates[n] = conditions.guarded(p["show_if"])

    passed = await resolve_conditions(session, template_gates) if template_gates else {}
    widget_results: dict[str, bool] = {}
    for n, w_el in widget_gates.items():
        try:
            is_on = await _evaluate_widget_gate(session, w_el, home_tz)
        except Exception as exc:
            print(f"widget gate eval error for {n}: {health.describe(exc)}", flush=True)
            is_on = False
        # Live widgets flicker (a plane at the edge of the radius); once a page
        # has appeared it stays a few minutes, so the rotation keeps its shape.
        widget_results[n] = linger.keep(n, is_on)
    linger.forget_except(widget_gates)

    live = []
    for name in rotation:
        page = defs.get(name)
        if page is None or page.get("tier") == "alert":
            continue
        if name in widget_results:
            if not widget_results[name]:
                continue
        elif name in template_gates:
            if not conditions.is_true(passed.get(name, "")):
                continue
        live.append(name)
    return live or [n for n in rotation if n in defs and defs[n].get("tier") != "alert"][:1]


async def check_alerts(session, spec, state: dict):
    """Alert pages never rotate. They seize the screen when their condition
    turns true, hold, then hand it back.

    Edge-triggered, not level: an alert that stays true all evening fires
    once, rather than grabbing the panel every refresh. `state` is the
    design's (runtime.alert): every screen showing it is seized together.

    An alert that ends "when something happens" (`conditions.ending`) is
    one whose condition is "it started and that hasn't happened yet":
    `hold_minutes` is then its limit. So it lets go when the start turns
    false, when its Until is met or at the limit, and it fires again when
    the Until is undone while the start still holds (the Watch unplugged at
    15%). An Until that can't be read isn't met.
    """
    now = time.time()
    defs = spec.get("pages", {})
    alerts = {n: p for n, p in defs.items()
              if p.get("tier") == "alert" and p.get("show_if")}
    if not alerts:
        state["name"], state["until"] = None, 0.0
        return None

    asks = {n: conditions.guarded(p["show_if"]) for n, p in alerts.items()}
    ends = {n: until for n, p in alerts.items() if (until := conditions.ending(p))}
    asks.update({f"{n}:until": conditions.guarded(until) for n, until in ends.items()})
    states = await resolve_conditions(session, asks)
    truthy = {n for n in alerts if conditions.is_true(states.get(n, ""))
              and not (n in ends and conditions.is_true(states.get(f"{n}:until", "")))}

    # release an expired or no-longer-true alert
    if state["name"] and (now > state["until"] or state["name"] not in truthy):
        print(f"alert {state['name']} released", flush=True)
        state["name"], state["until"] = None, 0.0

    for name in truthy:
        if state["fired"].get(name):
            continue                                  # already handled this episode
        hold = conditions.hold_minutes(alerts[name]) * 60
        state.update(name=name, until=now + hold)
        state["fired"][name] = True
        print(f"alert {name} fired, holding {hold}s", flush=True)
        break

    for name in list(state["fired"]):                  # re-arm when it goes false
        if name not in truthy:
            state["fired"].pop(name, None)

    return state["name"]


class DesignState:
    """What a design has to say this cycle: its alert, live pages and their
    values. Worked out once and shared by every screen that shows the design."""

    def __init__(self, alert: str | None, live: list[str], plans: list[dict]):
        self.alert = alert
        self.live = live
        self.plans = plans


async def design_state(session, design_id: str, spec: dict) -> DesignState:
    alert = await check_alerts(session, spec, runtime.alert(design_id))
    if alert and alert in spec.get("pages", {}):
        # One page while an alert is active: decodes in ~1 s on the ESP32 and
        # keeps a 5-minute interval from rotating away from it.
        live = [alert]
    else:
        live = await eligible_pages(session, spec, runtime.linger(design_id))
    if not live:
        return DesignState(alert, [], [])

    vals = await gather_values(session, spec, set(live))

    series = {}
    for name in set(live):
        for i, el in enumerate(spec["pages"][name].get("elements", [])):
            if el.get("type") in ("curve", "bar_chart") and el.get("entity"):
                series.setdefault(name, {})[i] = await curve_series(
                    session, el["entity"], as_int(el.get("hours"), 24))

    # What each page wants to show (how many items).
    plans = []
    for cat_name in live:
        try:
            page_def = spec["pages"][cat_name]
            page_vals = vals.get(cat_name, {})
            elements = page_def.get("elements", [])
            await _fetch_feed_items(session, elements)
            sub_count, sub_type, sub_keys, feed_items, feed_entity = subitems.inspect_category_subitems(
                page_def, page_vals, runtime.FEED_ITEMS
            )
            plans.append({"name": cat_name, "page_def": page_def, "vals": page_vals, "elements": elements,
                          "want": sub_count, "sub_type": sub_type, "sub_keys": sub_keys,
                          "feed_items": feed_items, "feed_entity": feed_entity,
                          "series": series.get(cat_name)})
        except Exception as exc:
            # One page that can't be built must not cost the others.
            print(f"page {cat_name} left out: {health.describe(exc)}", flush=True)
    return DesignState(alert, live, plans)


async def draw_category(plan: dict, sub_count: int, page_no: int, *, footer: dict, page_def: dict, orient: int,
                        display: str, only: int | None = None) -> list:
    """Every item of one page, drawn at a display's size and turned for its mounting.

    `page_def` is the page as placed on this screen (devices.view); its
    elements are the design's, in the same order as the plan's values.
    `footer` is the strip's theme.footer_plan(), and this is page `page_no` of it.
    `only`: just that item (0-based) of the `sub_count`."""
    page_vals, elements = plan["vals"], page_def.get("elements", [])
    sub_type, feed_items, feed_entity = plan["sub_type"], plan["feed_items"], plan["feed_entity"]
    page_imgs = []
    # Render each sub-item for this category
    for s_idx in (range(sub_count) if only is None else [only]):
        cloned_page = {**page_def, "elements": []}
        cloned_vals = dict(page_vals)

        for el_idx, el in enumerate(elements):
            el_c = dict(el)
            if el.get("type") in ("flight_tracker", "sports_match"):
                el_c["sub_index"] = s_idx
            elif sub_type in ("feed", "watch") and feed_items and s_idx < len(feed_items):
                item_data = feed_items[s_idx]
                top_title = str(feed_items[0].get("title", "")).strip()
                top_detail = str(feed_items[0].get("detail", "")).strip()
                ent = str(el.get("entity", "")).strip()
                val_str = str(el.get("value", "")).strip()
                cur_val = str(cloned_vals.get(el_idx, "")).strip()

                # 1. Detail / Episode field
                is_detail = (
                    (ent and (ent == feed_entity or ent == "sensor.epaper_watch") and el.get("show") == "attribute" and "detail" in str(el.get("attribute", "")).lower())
                    or ("detail" in val_str.lower() and any(k in val_str.lower() for k in ("state_attr", "states", feed_entity, "watch", "jelly", "item")))
                    or (bool(top_detail) and cur_val == top_detail)
                )

                # 2. Show title field
                is_title = (
                    (ent and (ent == feed_entity or ent == "sensor.epaper_watch") and el.get("show") != "attribute")
                    or (bool(top_title) and cur_val == top_title)
                )

                own = subitems.item_value(el, feed_entity, item_data)
                if own is not None:
                    cloned_vals[el_idx] = own
                elif is_detail:
                    cloned_vals[el_idx] = item_data.get("detail", "")
                    if "value" in el_c and "{{" in str(el_c["value"]):
                        el_c["value"] = ""
                elif is_title:
                    cloned_vals[el_idx] = item_data.get("title", "")
                    if "value" in el_c and "{{" in str(el_c["value"]):
                        el_c["value"] = ""
                elif el.get("type") == "text" and any(k in val_str.lower() for k in ("watch", "deck", "media", "episode", "unwatch")) and sub_count > 1:
                    base_val = val_str.split("  [")[0]
                    el_c["value"] = f"{base_val}  [{s_idx + 1}/{sub_count}]"

            cloned_page["elements"].append(el_c)

        img = await asyncio.to_thread(
            layout.render_page, cloned_page, cloned_vals,
            footer=footer, page_no=page_no, item_no=s_idx, items=sub_count,
            series=plan["series"], orientation=orient, display=display)
        page_imgs.append(T.orient_for_panel(T.to_1bit(img), orient, display=display))
    return page_imgs


def empty_page(orient: int, display: str, clock: str | None = None):
    """What a screen shows when its design has no pages. `clock`: the footer's time (now)."""
    cw, _ = T.canvas_dims(orient, display=display)
    page = {"elements": [{"type": "text", "value": "no pages", "x": 24, "y": 60, "w": cw - 48, "h": 120}]}
    return layout.render_page(page, {}, clock=clock or datetime.now().strftime("%H:%M"), label="empty",
                              orientation=orient, display=display)


def panel_geometry(fg: dict, orient: int, display: str) -> epf.OverlayGeometry:
    cw, ch = fg["canvas"]
    return epf.OverlayGeometry(
        logical_w=cw, logical_h=ch, quarter_turns=(int(orient) // 90 + T.panel_turns(display)) % 4,
        mirror_x=T.get_display(display)["id"] in epf.MIRRORED_MODELS,
        pill_y0=fg["pill_y0"], pill_y1=fg["pill_y1"], cat_x0=fg["cat_x0"],
        sub_x0=fg["sub_x0"], sub_x1=fg["sub_x1"])


_lock: asyncio.Lock | None = None
_lock_loop = None


def _render_lock() -> asyncio.Lock:
    global _lock, _lock_loop
    loop = asyncio.get_running_loop()
    if _lock is None or _lock_loop is not loop:
        _lock, _lock_loop = asyncio.Lock(), loop
    return _lock


async def refresh_frames(session) -> dict[str, Frames]:
    """Render every device and swap in its new frames. Returns them by device id.

    One render at a time: the render loop, Send, Push, the Refresh button and
    the action endpoint can all ask at once, and an older render finishing
    last would put old pages back. Each waits its turn, and each render reads
    the pages as saved when it starts.
    """
    async with _render_lock():
        return await _refresh_all(session)


async def _refresh_all(session) -> dict[str, Frames]:
    await publish_computed(session)
    # Devices of a kind that's switched off aren't drawn (kinds.shown).
    views = [(dev, spec) for dev, spec in devices.all_views() if kinds.shown(dev)]
    runtime.forget_devices_except([dev["id"] for dev, _ in views])
    states: dict[str, DesignState] = {}
    out: dict[str, Frames] = {}
    for dev, spec in views:
        try:
            st = states.get(dev["design"])
            if st is None:
                st = states[dev["design"]] = await design_state(session, dev["design"], spec)
            out[dev["id"]] = await _refresh_device(session, dev, spec, st)
        except Exception as exc:
            # One screen that can't be drawn must not cost the others.
            print(f"{dev['name']}: render failed: {health.describe(exc)}", flush=True)
            runtime.device(dev["id"]).frames.error = health.describe(exc)
    await publish_category_sensors(session, runtime.device(devices.primary()["id"]).frames)
    await sync_entities()
    return out


async def _refresh_device(session, dev: dict, spec: dict, st: DesignState) -> Frames:
    rt = runtime.device(dev["id"])
    quiet_active, quiet_reason = await evaluate_quiet_hours(session, spec, dev)
    nxt = await kinds.of(dev).render(session, dev, spec, st, quiet_active, quiet_reason)
    old_f = rt.frames
    has_prev = bool(getattr(old_f, "rendered_at", None))
    quiet_changed = bool(has_prev and old_f.quiet_active != quiet_active)
    # Still in quiet hours, but the sleep screen says something else now ("back at
    # 06:00" became "back when someone's home"): the panel, asleep, won't fetch it
    # by itself. One wake when the words change, never on every render.
    qh_now = spec.get("quiet_hours") or {}
    sleep_text_changed = bool(has_prev and quiet_active and old_f.quiet_active
                              and _sleep_text(old_f.quiet_reason, qh_now) != _sleep_text(quiet_reason, qh_now))
    if has_prev and old_f.strip_etag == nxt.strip_etag and old_f.last_modified:
        nxt.last_modified = old_f.last_modified
    else:
        nxt.last_modified = formatdate(timeval=None, localtime=False, usegmt=True)
    nxt.rendered_at = datetime.now().astimezone().isoformat(timespec="seconds")
    nxt.quiet_active = quiet_active
    nxt.quiet_reason = quiet_reason
    rt.frames = nxt
    print(f"{dev['name']}: rendered {nxt.names} ({len(nxt.strip)}B strip, {nxt.cat_count} cats, "
          f"offsets: {nxt.cat_offsets}, sizes: {nxt.cat_sizes}, rot: {nxt.rotate_seconds}s, "
          f"quiet: {quiet_active} [{quiet_reason}])", flush=True)
    shown = [n for n in nxt.names if n != SLEEP_PAGE]
    await publish_entity(session, devices.entity_id("sensor.epaper_panel_last_render", dev), nxt.rendered_at,
                         {"friendly_name": _per_device("Last render", dev), "icon": "mdi:clock-check-outline",
                          "pages_count": len(shown), "active_pages": shown, "device_class": "timestamp"})
    fit = rt.fit or {}
    await publish_entity(session, devices.entity_id("sensor.epaper_panel_pages", dev), fit.get("pages_shown", len(nxt.names)), {
        "friendly_name": _per_device("Pages on the panel", dev), "icon": "mdi:book-open-page-variant-outline",
        "unit_of_measurement": "pages", "pages_wanted": fit.get("pages_wanted"),
        "capacity_kb": (fit.get("capacity") or 0) // 1024,
        "left_out": ", ".join(f"{t['page']}: {t['shown']} of {t['of']}" for t in fit.get("trimmed") or []) or "nothing"})
    # A screen's Update every (timing.py) is the contract: new content waits
    # for it, however often pages come and go (a panel on a battery may fetch
    # every hour). The add-on wakes it early only for alerts (render loop),
    # quiet hours starting, ending or changing what the sleep screen says, and what a person does (Send, Push, the
    # Refresh button, the action endpoint).
    qh = spec.get("quiet_hours") or {}
    if quiet_changed or (not has_prev and qh.get("enabled") and not quiet_active):
        # Delivered with retries: a panel stops fetching on its own during
        # quiet hours, so missing the wake-up would leave it asleep. After a
        # restart we can't know whether it is still asleep, so wake it once.
        print(f"{dev['name']}: quiet hours {'started' if quiet_active else 'ended'} ({quiet_reason})", flush=True)
        await push_panel_update(dev["id"], "quiet hours " + ("started" if quiet_active else "ended"))
    elif sleep_text_changed:
        print(f"{dev['name']}: still in quiet hours, now {quiet_reason}: showing the new sleep screen", flush=True)
        await push_panel_update(dev["id"], "sleep screen changed")
    return nxt


def _sleep_text(reason: str, qh: dict) -> str:
    """What the sleep screen says for a quiet-hours reason."""
    return sleep.wake_text(str(reason or ""), quiet_window(qh)[1])


def _per_device(label: str, dev: dict) -> str:
    """An entity's name: the first device's keep theirs, others say which screen."""
    return label if not dev.get("entity_suffix") else f"{dev['name']} · {label}"
