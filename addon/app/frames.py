"""Building the frames: which pages are live, their values, alerts, quiet hours, rendering, packing."""
import asyncio
import hashlib
import io
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
from email.utils import formatdate
from PIL import Image

from render import binding, epf, layout, sleep, stripmeta, subitems, theme as T
import runtime
from config import HA_TOKEN, SLEEP_PAGE, valid_entity_id
from entities import publish_category_sensors, publish_computed, publish_entity, sync_entities
from ha import curve_series, ha_json, resolve_templates
from layouts_store import load_layouts
from panel_ops import push_panel_update
from sources.flights import fetch_overhead_aircraft
from sources.geo import get_home_timezone
from sources.ha_services import fetch_calendar_events, fetch_weather_forecast
from sources.racing import compute_racing_active_window, fetch_racing_data
from sources.sports import compute_sports_active_window, fetch_sports_match
from runtime import Frames


async def evaluate_quiet_hours(session, spec: dict) -> tuple[bool, str]:
    """Determine if Night / Quiet Hours (Zero-Ghosting Deep Idle) is currently active."""
    qh = spec.get("quiet_hours") if isinstance(spec.get("quiet_hours"), dict) else {}
    enabled = bool(qh.get("enabled", False))
    start_str = str(qh.get("start") or "23:00").strip()[:5]
    end_str = str(qh.get("end") or "07:00").strip()[:5]
    pres_ent = str(qh.get("presence_entity") or "").strip()
    allow_alerts = bool(qh.get("allow_alerts", True))

    active = False
    reason = "disabled"
    if enabled:
        now_t = datetime.now()
        cur_mins = now_t.hour * 60 + now_t.minute
        try:
            sh, sm = [int(x) for x in start_str.split(":")]
            eh, em = [int(x) for x in end_str.split(":")]
            s_mins = sh * 60 + sm
            e_mins = eh * 60 + em
            if s_mins != e_mins:
                in_window = (cur_mins >= s_mins or cur_mins < e_mins) if s_mins > e_mins else (s_mins <= cur_mins < e_mins)
                if in_window:
                    active = True
                    reason = f"schedule ({start_str}–{end_str})"
        except Exception:
            pass

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

    await publish_entity(session, "sensor.epaper_quiet_hours", "active" if active else "inactive", {
        "friendly_name": "E-Paper Quiet Hours",
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
        elif t == "flight_tracker":
            radius = float(el.get("radius") or 35)
            custom_lat = el.get("lat") or el.get("latitude")
            custom_lon = el.get("lon") or el.get("lng") or el.get("longitude")
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
        return bool(win.get("is_active"))
    if wtype == "sports_racing":
        series = widget.get("series") or "f1"
        w_mode = widget.get("window_mode") or "session"
        win = await compute_racing_active_window(session, series, pre_buffer_hours=pre_b, post_buffer_hours=post_b, window_mode=w_mode, tz_name=el_tz)
        return bool(win.get("is_active"))
    if wtype == "flight_tracker":
        radius = float(widget.get("radius") or 35.0)
        custom_lat = widget.get("lat") or widget.get("latitude")
        custom_lon = widget.get("lon") or widget.get("lng") or widget.get("longitude")
        aircraft = await fetch_overhead_aircraft(session, radius_km=radius, lat=custom_lat, lon=custom_lon)
        return len(aircraft or []) > 0
    return True


async def eligible_pages(session, spec):
    """Pages whose tier and show_if (or built-in widget active window) say they belong in the rotation now."""
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
            template_gates[n] = p["show_if"]

    passed = await resolve_templates(session, template_gates) if template_gates else {}
    widget_results: dict[str, bool] = {}
    for n, w_el in widget_gates.items():
        try:
            is_on = await _evaluate_widget_gate(session, w_el, home_tz)
        except Exception as exc:
            print(f"widget gate eval error for {n}: {exc!r}", flush=True)
            is_on = False
        # Live widgets flicker (a plane at the edge of the radius); once a page
        # has appeared it stays a few minutes, so the rotation keeps its shape.
        widget_results[n] = runtime.WIDGET_LINGER.keep(n, is_on)
    runtime.WIDGET_LINGER.forget_except(widget_gates)

    live = []
    for name in rotation:
        page = defs.get(name)
        if page is None or page.get("tier") == "alert":
            continue
        if name in widget_results:
            if not widget_results[name]:
                continue
        elif name in template_gates:
            if str(passed.get(name, "")).strip().lower() not in ("true", "on", "yes", "1"):
                continue
        live.append(name)
    return live or [n for n in rotation if n in defs and defs[n].get("tier") != "alert"][:1]


async def check_alerts(session, spec):
    """Alert pages never rotate. They seize the screen when their condition
    turns true, hold, then hand it back.

    Edge-triggered, not level: an alert that stays true all evening fires
    once, rather than grabbing the panel every refresh.
    """
    now = time.time()
    defs = spec.get("pages", {})
    alerts = {n: p for n, p in defs.items()
              if p.get("tier") == "alert" and p.get("show_if")}
    if not alerts:
        runtime.ALERT["name"], runtime.ALERT["until"] = None, 0.0
        return None

    states = await resolve_templates(session, {n: p["show_if"] for n, p in alerts.items()})
    truthy = {n for n, v in states.items()
              if str(v).strip().lower() in ("true", "on", "yes", "1")}

    # release an expired or no-longer-true alert
    if runtime.ALERT["name"] and (now > runtime.ALERT["until"] or runtime.ALERT["name"] not in truthy):
        print(f"alert {runtime.ALERT['name']} released", flush=True)
        runtime.ALERT["name"], runtime.ALERT["until"] = None, 0.0

    for name in truthy:
        if runtime.ALERT["fired"].get(name):
            continue                                  # already handled this episode
        hold = max(1, min(1440, int(alerts[name].get("hold_minutes", 10)))) * 60
        runtime.ALERT.update(name=name, until=now + hold)
        runtime.ALERT["fired"][name] = True
        print(f"alert {name} fired, holding {hold}s", flush=True)
        break

    for name in list(runtime.ALERT["fired"]):                  # re-arm when it goes false
        if name not in truthy:
            runtime.ALERT["fired"].pop(name, None)

    return runtime.ALERT["name"]


async def build_frames(session):
    await publish_computed(session)
    spec = load_layouts()
    orient = int(spec.get("orientation") or 0)
    if orient not in (0, 90, 180, 270):
        orient = 0
    display = spec.get("display", T.DEFAULT_DISPLAY)
    disp = T.get_display(display)
    dw, dh = disp["w"], disp["h"]
    alert = await check_alerts(session, spec)
    if alert and alert in spec.get("pages", {}):
        # Serve a 1-page strip while an alert is active: decodes in ~1s on
        # the ESP32 and prevents its 5-minute interval from rotating away.
        live = [alert]
    else:
        live = await eligible_pages(session, spec)

    quiet_active, quiet_reason = await evaluate_quiet_hours(session, spec)
    try:
        rot_sec = max(5, min(3600, int(spec.get("rotate_seconds") or 30)))
    except (TypeError, ValueError):
        rot_sec = 30

    if not live:
        cw, _ = T.canvas_dims(orient, display=display)
        empty_page = {"elements": [{"type": "text", "value": "no pages", "x": 24, "y": 60, "w": cw - 48, "h": 120}]}
        img = await asyncio.to_thread(
            layout.render_page, empty_page, {},
            clock=datetime.now().strftime("%H:%M"), label="empty", orientation=orient, display=display)
        one = T.orient_for_panel(T.to_1bit(img), orient, display=display)
        png = _png(one)
        cat_ids = [stripmeta.identity("empty")]
        sub_ids = [stripmeta.identity("empty:0")]
        # No pills on the empty page: width 0 tells the panel to draw no highlight.
        fg = T.footer_geometry(clock=datetime.now().strftime("%H:%M"), orientation=orient, display=display)
        epf_data = epf.encode_epf(
            pages=[one], cat_ids=cat_ids, cat_offsets=[0], cat_sizes=[1], cat_pill_widths=[0], sub_ids=sub_ids,
            display_model=display, width=dw, height=dh, rotate_sec=rot_sec, quiet_hours=quiet_active,
            alert_interrupt=False, orientation_180=(orient == 180), geometry=panel_geometry(fg, orient, display),
        )
        return png, png, [png], [], [0], [1], ["empty"], [110], quiet_active, quiet_reason, rot_sec, cat_ids, sub_ids, epf_data, epf_data

    vals = await gather_values(session, spec, set(live))

    series = {}
    for name in set(live):
        for i, el in enumerate(spec["pages"][name].get("elements", [])):
            if el.get("type") in ("curve", "bar_chart") and el.get("entity"):
                series.setdefault(name, {})[i] = await curve_series(
                    session, el["entity"], int(el.get("hours", 24)))

    imgs = []
    cat_offsets = []
    cat_sizes = []
    cat_names = []
    cat_pill_widths = []
    cat_sub_keys = []
    clock = datetime.now().strftime("%H:%M")       # one clock for the whole strip
    geo = None

    for cat_i, cat_name in enumerate(live):
        page_def = spec["pages"][cat_name]
        page_vals = vals.get(cat_name, {})
        elements = page_def.get("elements", [])

        # Fetch any uncached feed items
        for el in elements:
            ent = str(el.get("entity", ""))
            if ent.startswith("sensor.epaper_") and not ent.endswith("_count") and not ent.startswith("sensor.epaper_category_") and not ent.startswith("sensor.epaper_panel_"):
                own_items = ((runtime.PUBLISHED.get(ent) or {}).get("attributes") or {}).get("items")
                if ent not in runtime.FEED_ITEMS and own_items:
                    runtime.FEED_ITEMS[ent] = own_items
                if ent not in runtime.FEED_ITEMS:
                    try:
                        st_data = await ha_json(session, f"/states/{ent}")
                        items = (st_data.get("attributes") or {}).get("items")
                        if items:
                            runtime.FEED_ITEMS[ent] = items
                    except Exception:
                        pass

        sub_count, sub_type, sub_keys, feed_items, feed_entity = subitems.inspect_category_subitems(
            page_def, page_vals, runtime.FEED_ITEMS
        )
        cat_sub_keys.append(sub_keys)

        cat_display_name = cat_name.replace("_", " ").upper()
        cat_label = f"{cat_i + 1}/{len(live)}  {cat_display_name}"
        # The same numbers the footer is drawn with, so the panel's highlight
        # lands exactly on the pill in every orientation.
        fg = T.footer_geometry(clock=clock, cat_label=cat_label, has_sub=sub_count > 1,
                               orientation=orient, display=display)
        if geo is None:
            geo = panel_geometry(fg, orient, display)
        cat_offsets.append(len(imgs))
        cat_sizes.append(sub_count)
        cat_names.append(cat_name)
        cat_pill_widths.append(fg["cat_w"])

        # Render each sub-item for this category
        for s_idx in range(sub_count):
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

                    if is_detail:
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

            sub_label = f"{s_idx + 1}/{sub_count}" if sub_count > 1 else ""

            img = await asyncio.to_thread(
                layout.render_page, cloned_page, cloned_vals,
                clock=clock,
                label=cat_display_name,
                cat_label=cat_label,
                sub_label=sub_label,
                battery_pct=None, series=series.get(cat_name), orientation=orient, display=display)
            imgs.append(T.orient_for_panel(T.to_1bit(img), orient, display=display))

    # The sleep screen always goes first, so the panel can fall asleep
    # instantly (dial centre held, or its Sleep switch) without asking us.
    # The panel never pages onto it. During quiet hours with the sleep screen
    # on, it's also marked "auto": the panel goes to sleep by itself.
    cat_flags = [0] * len(cat_offsets)
    qh = spec.get("quiet_hours") or {}
    if not alert:
        auto = quiet_active and qh.get("sleep_screen", True)
        text = (sleep.wake_text(quiet_reason, qh.get("end") or "07:00") if quiet_active
                else sleep.MANUAL_TEXT)
        sleep_img = await asyncio.to_thread(sleep.render_sleep_page, text, orient, display)
        imgs.insert(0, T.orient_for_panel(T.to_1bit(sleep_img), orient, display=display))
        cat_offsets = [0] + [o + 1 for o in cat_offsets]
        cat_sizes = [1] + cat_sizes
        cat_names = [SLEEP_PAGE] + cat_names
        cat_pill_widths = [0] + cat_pill_widths
        cat_sub_keys = [[f"{SLEEP_PAGE}:{text}"]] + cat_sub_keys     # new text, new identity: the panel redraws it
        cat_flags = [epf.CAT_FLAG_SLEEP | (epf.CAT_FLAG_SLEEP_AUTO if auto else 0)] + cat_flags
        live = [SLEEP_PAGE] + list(live)

    slice_pngs = [_png(im) for im in imgs]
    slices_digest = hashlib.md5(b"".join(slice_pngs)).digest()
    etag_b0, etag_b1 = slices_digest[0], slices_digest[1]

    cat_ids, sub_ids = subitems.compute_identities(live, cat_sub_keys)
    meta = stripmeta.StripMeta(
        offsets=cat_offsets,
        sizes=cat_sizes,
        pill_widths=cat_pill_widths,
        cat_ids=cat_ids,
        sub_ids=sub_ids,
        quiet=quiet_active,
        rotate_seconds=rot_sec,
        content_hash=(etag_b0 << 8) | etag_b1,
        interrupt=bool(alert)
    )
    payload = stripmeta.encode(meta)
    meta_rows = stripmeta.rows_needed(len(payload), dw)

    strip = Image.new("1", (dw, dh * len(imgs) + meta_rows), 1)
    for i, im in enumerate(imgs):
        strip.paste(im, (0, i * dh))
    stripmeta.paint(strip, dh * len(imgs), payload)

    epf_data = epf.encode_epf(
        pages=imgs,
        cat_ids=cat_ids,
        cat_offsets=cat_offsets,
        cat_sizes=cat_sizes,
        cat_pill_widths=cat_pill_widths,
        sub_ids=sub_ids,
        display_model=display,
        width=dw,
        height=dh,
        rotate_sec=rot_sec,
        quiet_hours=quiet_active,
        alert_interrupt=bool(alert),
        orientation_180=(orient == 180),
        content_hash=int.from_bytes(slices_digest[:8], "big"),
        geometry=geo,
        cat_flags=cat_flags,
    )
    epf_single = epf.extract_page_epf(epf_data, 0)

    return _png(strip), slice_pngs[0], slice_pngs, live, cat_offsets, cat_sizes, cat_names, cat_pill_widths, quiet_active, quiet_reason, rot_sec, cat_ids, sub_ids, epf_data, epf_single


def panel_geometry(fg: dict, orient: int, display: str) -> epf.OverlayGeometry:
    cw, ch = fg["canvas"]
    return epf.OverlayGeometry(
        logical_w=cw, logical_h=ch, quarter_turns=(int(orient) // 90) % 4,
        mirror_x=T.get_display(display)["id"] in epf.MIRRORED_MODELS,
        pill_y0=fg["pill_y0"], pill_y1=fg["pill_y1"], cat_x0=fg["cat_x0"],
        sub_x0=fg["sub_x0"], sub_x1=fg["sub_x1"])


async def refresh_frames(session):
    """Build a new Frames snapshot and atomically swap runtime.FRAMES."""
    res = await build_frames(session)
    strip, single, slices, names, cat_offsets, cat_sizes, cat_names, cat_pill_widths, quiet_active, quiet_reason, rot_sec, cat_ids, sub_ids, epf_strip, epf_single = res
    old_f = runtime.FRAMES
    has_prev = old_f is not None and getattr(old_f, "rendered_at", None)
    struct_changed = (
        has_prev and (
            old_f.cat_offsets != cat_offsets or
            old_f.cat_sizes != cat_sizes or
            old_f.cat_names != cat_names or
            getattr(old_f, "cat_pill_widths", None) != cat_pill_widths or
            getattr(old_f, "cat_ids", None) != cat_ids or
            getattr(old_f, "sub_ids", None) != sub_ids
        )
    )
    quiet_changed = bool(has_prev and getattr(old_f, "quiet_active", False) != quiet_active)
    rot_changed = bool(has_prev and getattr(old_f, "rotate_seconds", 30) != rot_sec)
    nxt = Frames()
    nxt.strip, nxt.single, nxt.slices, nxt.names = strip, single, slices, names
    nxt.strip_etag = _etag(strip)
    nxt.single_etag = _etag(single)
    nxt.epf_strip = epf_strip
    nxt.epf_single = epf_single
    nxt.epf_strip_etag = f'"{hashlib.blake2s(epf_strip, digest_size=8).hexdigest()}"'
    nxt.epf_single_etag = f'"{hashlib.blake2s(epf_single, digest_size=8).hexdigest()}"'
    if has_prev and old_f.strip_etag == nxt.strip_etag and getattr(old_f, "last_modified", ""):
        nxt.last_modified = old_f.last_modified
    else:
        nxt.last_modified = formatdate(timeval=None, localtime=False, usegmt=True)
    nxt.rendered_at = datetime.now().astimezone().isoformat(timespec="seconds")
    nxt.cat_offsets = cat_offsets
    nxt.cat_sizes = cat_sizes
    nxt.cat_names = cat_names
    nxt.cat_pill_widths = cat_pill_widths
    nxt.cat_ids = cat_ids
    nxt.sub_ids = sub_ids
    nxt.cat_count = len(cat_offsets)
    nxt.quiet_active = quiet_active
    nxt.quiet_reason = quiet_reason
    nxt.rotate_seconds = rot_sec
    runtime.FRAMES = nxt
    print(f"rendered {names} ({len(strip)}B strip, {nxt.cat_count} cats, offsets: {cat_offsets}, sizes: {cat_sizes}, rot: {rot_sec}s, quiet: {quiet_active} [{quiet_reason}])", flush=True)
    await publish_entity(session, "sensor.epaper_panel_last_render", nxt.rendered_at,
                         {"friendly_name": "E-Paper · Last render", "icon": "mdi:clock-check-outline",
                          "pages_count": len([n for n in nxt.names if n != SLEEP_PAGE]),
                          "active_pages": [n for n in nxt.names if n != SLEEP_PAGE],
                          "device_class": "timestamp"})
    await publish_category_sensors(session, nxt)
    await sync_entities()
    if quiet_changed:
        # Delivered with retries: the panel stops fetching on its own during
        # quiet hours, so missing the wake-up would leave it asleep.
        print(f"Quiet Hours state transitioned to {quiet_active} ({quiet_reason}) -- syncing panel state", flush=True)
        runtime.LAST_PANEL_PUSH_TIME = time.time()
        await push_panel_update("quiet hours " + ("started" if quiet_active else "ended"))
    elif struct_changed or rot_changed:
        spec = load_layouts()
        allow_alerts = bool((spec.get("quiet_hours") or {}).get("allow_alerts", True))
        if quiet_active and not (runtime.ALERT["name"] and allow_alerts):
            print(f"Layout/rotation changed during Quiet Hours ({quiet_reason}) -- deferring panel push", flush=True)
        else:
            print("Category structure or rotation interval changed -- pushing immediate refresh to panel", flush=True)
            runtime.LAST_PANEL_PUSH_TIME = time.time()
            await push_panel_update("pages changed")
    return nxt
