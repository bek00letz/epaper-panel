"""Data-driven page rendering.

A page is a list of positioned elements. There is deliberately no layout
algorithm: every element carries its own box and draws into it, which is
exactly what a drag-and-drop editor produces and what makes the editor's
preview trustworthy -- what you place is what renders.

Element shape (all coordinates in panel pixels, 792x272):

    {"type": "number", "x": 170, "y": 20, "w": 300, "h": 130,
     "value": "{{ states('sensor.solar_today_production') }}",
     "decimals": 1, "align": "left"}

Values may be Jinja templates. They are NOT rendered here -- Home Assistant
renders them all in one request and the results are passed in as `vals`,
keyed by the element's index. That keeps this module free of network calls
and makes it testable with a plain dict.
"""
import calendar
from datetime import datetime, date
import json
import math
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from . import theme as T
from . import binding
from .binding import template_for

_FONTS = Path(__file__).parent.parent / "fonts"
_MDI_TTF = _FONTS / "mdi.ttf"
_MDI_MAP = _FONTS / "mdi-codepoints.json"

_mdi_codepoints = None

def mm_per_px(display=None):
    disp = T.get_display(display)
    return disp["mm_w"] / disp["w"]


MM_PER_PX = 139.1 / T.W          # ~0.176 mm; CrowPanel 5.79" default


# Cap height is ~0.7em, and legibility bands scale with viewing distance.
def legibility(size_px, distance_m=3.0, display=None):
    ratio = mm_per_px(display)
    mm = size_px * 0.7 * ratio
    d = max(0.1, float(distance_m or 3.0))
    factor = d / 3.0
    if mm < 4.4 * factor:
        verdict = f"too small at {d:.1f}m"
    elif mm < 13.0 * factor:
        verdict = f"squint at {d:.1f}m"
    elif mm < 19.0 * factor:
        verdict = f"comfortable"
    else:
        verdict = f"effortless"
    return round(mm, 1), verdict


@lru_cache(maxsize=128)
def _mdi_font(size: int):
    clamped = max(8, min(T.H, int(size)))
    return ImageFont.truetype(str(_MDI_TTF), clamped)


def mdi_codepoint(name):
    """Map 'mdi:washing-machine' (or bare 'washing-machine') to a codepoint."""
    global _mdi_codepoints
    if _mdi_codepoints is None:
        try:
            _mdi_codepoints = json.loads(_MDI_MAP.read_text())
        except Exception:
            _mdi_codepoints = {}
    return _mdi_codepoints.get(str(name).removeprefix("mdi:"))


def draw_cat(draw, x=0, y=0, height=200):
    """Sitting cat in profile, facing right, traced at a nominal 200px tall."""
    dx = x - 96
    dy = y
    scale = max(0.1, min(3.0, height / 200.0))

    def P(pts):
        return [(dx + px * scale, dy + py * scale) for px, py in pts]

    draw.polygon(P([(124, 96), (112, 130), (106, 170), (104, 202),
                    (176, 202), (206, 198), (222, 176), (224, 146),
                    (210, 116), (188, 96)]), fill=T.BLACK)
    draw.ellipse(P([(114, 24), (198, 108)]), fill=T.BLACK)          # head
    draw.polygon(P([(122, 44), (112, 4), (152, 30)]), fill=T.BLACK)  # left ear
    draw.polygon(P([(160, 30), (200, 4), (190, 44)]), fill=T.BLACK)  # right ear
    draw.line(P([(202, 196), (248, 188), (268, 166), (272, 136),
                 (262, 112), (246, 102)]),
              fill=T.BLACK, width=max(3, int(14 * scale)), joint="curve")


CUSTOM_ICONS = {
    "cat-sitting": draw_cat,
}


def _fit_glyph(ch, box_w, box_h, start=200):
    """Largest font size at which the glyph's ink fits the box."""
    lo, hi, best = 8, max(8, min(T.H, int(start))), 8
    while lo <= hi:
        mid = (lo + hi) // 2
        f = _mdi_font(mid)
        l, t, r, b = f.getbbox(ch)
        if (r - l) <= box_w and (b - t) <= box_h:
            best, lo = mid, mid + 1
        else:
            hi = mid - 1
    return best


def _anchor_x(align, x, w):
    return {"left": x, "center": x + w // 2, "right": x + w}.get(align, x)


def _clamp_box(el, default_w=200, default_h=60, display=None):
    disp = T.get_display(display)
    max_dim = max(disp["w"], disp["h"])
    x = max(-max_dim, min(max_dim * 2, int(el.get("x", 0))))
    y = max(-max_dim, min(max_dim * 2, int(el.get("y", 0))))
    w = max(1, min(max_dim * 2, int(el.get("w", default_w))))
    h = max(1, min(max_dim * 2, int(el.get("h", default_h))))
    return x, y, w, h


def _draw_text(img, d, el, text, metrics=None, distance_m=3.0, display=None):
    if not text:
        return
    x, y, w, h = _clamp_box(el, 200, 60, display=display)
    align = el.get("align", "left")
    bold = el.get("bold") not in (False, "false", 0, "0")
    family = str(el.get("font") or "lato").lower()

    size = max(8, min(360, int(el["size"]))) if el.get("size") else T.fit_size(text, w, h, 200, bold=bold, family=family)
    f = T.font(size, bold=bold, family=family)
    if metrics is not None:
        mm, verdict = legibility(size, distance_m=distance_m, display=display)
        t = text.strip()
        metrics.append({"size": size, "mm": mm, "verdict": verdict,
                        "overflow": T.text_width(text, f) > w,
                        # A list or dict rendered as a string is almost always
                        # the wrong attribute picked, not a deliberate choice.
                        "collection": t.startswith(("[", "{")) and t.endswith(("]", "}"))})
    ax = _anchor_x(align, x, w)
    anchor = {"left": "lm", "center": "mm", "right": "rm"}.get(align, "lm")
    d.text((ax, y + h // 2), text, font=f, fill=T.BLACK, anchor=anchor)


def _draw_icon(img, d, el, _text, display=None):
    name = str(el.get("icon", ""))
    x, y, w, h = _clamp_box(el, 100, 100, display=display)
    if name.startswith("custom:"):
        art = CUSTOM_ICONS.get(name.removeprefix("custom:"))
        if art:
            art(d, x, y, h)
        return
    cp = mdi_codepoint(name)
    if cp is None:
        return
    ch = chr(cp)
    size = max(8, min(360, int(el["size"]))) if el.get("size") else _fit_glyph(ch, w, h)
    f = _mdi_font(size)
    d.text((x + w // 2, y + h // 2), ch, font=f, fill=T.BLACK, anchor="mm")


def _draw_line(img, d, el, _text, display=None):
    x, y, w, h = _clamp_box(el, 200, 2, display=display)
    thick = max(1, min(32, int(el.get("thickness", 2))))
    if h >= w:                                   # taller than wide -> vertical
        d.line([(x + w // 2, y), (x + w // 2, y + h)], fill=T.BLACK, width=thick)
    else:
        d.line([(x, y + h // 2), (x + w, y + h // 2)], fill=T.BLACK, width=thick)


def _draw_curve(img, d, el, _text, series=None, display=None):
    """Filled area chart, dot-screened, with a solid top edge."""
    pts = [float(p) for p in (series or el.get("_series") or []) if p is not None]
    if len(pts) < 2:
        return
    x0, y0, w, h = _clamp_box(el, 250, 100, display=display)
    x1, y1 = x0 + w, y0 + h

    lo = min(0.0, min(pts))
    hi = max(pts)
    span = (hi - lo) or 1.0
    n = len(pts)
    coords = [(x0 + i * w / (n - 1), y1 - ((v - lo) / span) * h) for i, v in enumerate(pts)]

    mask = Image.new("1", img.size, 0)
    ImageDraw.Draw(mask).polygon(coords + [(x1, y1), (x0, y1)], fill=1)
    pattern = Image.new("L", img.size, T.WHITE)
    px = pattern.load()
    for yy in range(0, img.size[1], 3):
        for xx in range(0, img.size[0], 3):
            px[xx, yy] = T.BLACK
    img.paste(pattern, (0, 0), mask)

    d.line(coords, fill=T.BLACK, width=3, joint="curve")
    d.line([(x0, y1), (x1, y1)], fill=T.BLACK, width=1)


def _fmt_number(raw, el):
    raw_str = str(raw).strip()
    try:
        v = float(raw_str)
    except (TypeError, ValueError):
        return el.get("fallback") or "--"
    # If explicit Jinja template was used in value, preserve its custom precision!
    if isinstance(el.get("value"), str) and "{{" in el.get("value"):
        return f"{el.get('prefix', '')}{raw_str}{el.get('suffix', '')}"
    dec = max(0, min(6, int(el.get("decimals", 0))))
    formatted = f"{v:.{dec}f}"
    if not (isinstance(el.get("value"), str) and el.get("value").strip()):
        return f"{el.get('prefix', '')}{formatted}{el.get('suffix', '')}"
    return formatted


def _fit_text(text, max_w, f):
    if not text:
        return ""
    if T.text_width(text, f) <= max_w:
        return text
    t = str(text)
    while len(t) > 1 and T.text_width(t + "…", f) > max_w:
        t = t[:-1]
    return t + "…"


def _draw_icon_glyph(d, name, cx, cy, sz):
    name = str(name or "")
    if name.startswith("custom:"):
        art = CUSTOM_ICONS.get(name.removeprefix("custom:"))
        if art:
            art(d, cx, cy - sz // 2, sz)
        return
    cp = mdi_codepoint(name)
    if cp is not None:
        f = _mdi_font(sz)
        d.text((cx, cy), chr(cp), font=f, fill=T.BLACK, anchor="mm")


def _resolve_spot_icon(it, state):
    st = str(state or "").strip().lower()
    # 1. Custom state-to-icon mapping
    si = it.get("state_icons")
    if isinstance(si, dict):
        for k, v in si.items():
            if str(k).strip().lower() == st and v:
                return str(v)
    is_inactive = st in ("off", "idle", "closed", "locked", "disarmed", "standby", "0")
    if is_inactive and it.get("icon_off"):
        return str(it["icon_off"])
    base_icon = str(it.get("icon") or "mdi:power")
    if is_inactive:
        if base_icon == "mdi:lightbulb":
            return "mdi:lightbulb-off"
        elif base_icon == "mdi:radiator":
            return "mdi:radiator-disabled"
        elif base_icon == "mdi:power":
            return "mdi:power-off"
        elif base_icon == "mdi:lock":
            return "mdi:lock-open"
        elif base_icon == "mdi:door-closed":
            return "mdi:door-open"
        elif base_icon == "mdi:window-closed":
            return "mdi:window-open"
    return base_icon


def _compute_grid_boxes(x, y, w, h, n, cols, rows, gap=10):
    rows = max(1, rows)
    cols = max(1, cols)
    ch_card = max(16, (h - (rows - 1) * gap) // rows)
    boxes = []
    items_left = n
    curr_y = y
    for r in range(rows):
        items_in_row = min(cols, items_left)
        if items_in_row <= 0:
            break
        cw = max(16, (w - (items_in_row - 1) * gap) // items_in_row)
        row_x = x
        for c in range(items_in_row):
            boxes.append((row_x, curr_y, cw, ch_card))
            row_x += cw + gap
        curr_y += ch_card + gap
        items_left -= items_in_row
    return boxes


def _draw_dynamic_grid(img, d, el, raw_val, display=None):
    x, y, w, h = _clamp_box(el, 752, 214, display=display)
    has_resolved = False
    info_by_ent = {}
    if raw_val is not None:
        if isinstance(raw_val, str) and raw_val.strip() != "":
            try:
                parsed = json.loads(raw_val)
                if isinstance(parsed, list):
                    has_resolved = True
                    info_by_ent = {x.get("entity"): x for x in parsed if isinstance(x, dict)}
            except Exception:
                pass
        elif isinstance(raw_val, list):
            has_resolved = True
            info_by_ent = {x.get("entity"): x for x in raw_val if isinstance(x, dict)}

    configured_items = el.get("items") or []
    filter_state = str(el.get("filter_state") or "on").strip().lower()

    active_items = []
    for it in configured_items:
        if not isinstance(it, dict):
            continue
        ent = it.get("entity", "").strip()
        name = it.get("name") or ""
        hide_name = bool(it.get("hide_name", False))

        if has_resolved:
            res = info_by_ent.get(ent, {})
            state = str(res.get("state") or "").strip()
            friendly = res.get("name") or ""
            changed = res.get("changed") or ""

            is_active = (state and state not in ("unavailable", "unknown")) if filter_state in ("*", "any") else (state.lower() == filter_state)
            if is_active:
                chosen_icon = _resolve_spot_icon(it, state)
                active_items.append({
                    "entity": ent,
                    "name": name or friendly or ent.split(".")[-1].replace("_", " ").title(),
                    "icon": chosen_icon,
                    "state": state,
                    "changed": changed,
                    "hide_name": hide_name,
                    "raw_item": it
                })
        else:
            state = it.get("state") or "on"
            chosen_icon = _resolve_spot_icon(it, state)
            active_items.append({
                "entity": ent,
                "name": name or (ent.split(".")[-1].replace("_", " ").title() if ent else "Active Spot"),
                "icon": chosen_icon,
                "state": state,
                "changed": "25m ago",
                "hide_name": hide_name,
                "raw_item": it
            })

    if not configured_items and not active_items:
        active_items = [{
            "entity": "switch.sample_1",
            "name": "Sample Zone",
            "icon": "mdi:radiator",
            "state": "on",
            "changed": "30m ago",
            "hide_name": False
        }]

    # Global display settings
    show_labels = str(el.get("show_labels") or "both").lower()
    icon_sz_setting = str(el.get("icon_size") or "auto").lower()
    sec_mode = el.get("secondary_mode", "runtime")

    if icon_sz_setting == "huge":
        req_icon_sz = 80
    elif icon_sz_setting == "large":
        req_icon_sz = 64
    elif icon_sz_setting == "medium":
        req_icon_sz = 48
    else:
        req_icon_sz = None

    def format_sec(item):
        if show_labels in ("name_only", "icons_only"):
            return ""
        if sec_mode == "none":
            return ""
        if sec_mode == "state":
            return item.get("state", "")
        ch = item.get("changed", "").strip()
        if ch:
            clean_ch = ch.removesuffix(" ago").replace(" minutes", "m").replace(" hours", "h").replace(" minute", "m").replace(" hour", "h")
            return f"on for {clean_ch}"
        return "active"

    hdr_title = str(el.get("header_title") or "").strip()
    hdr_icon = str(el.get("header_icon") or "").strip()
    has_header = bool(hdr_title or hdr_icon)

    if has_header:
        hdr_h = 28
        hx = x
        hy = y + 2
        if hdr_icon:
            _draw_icon_glyph(d, hdr_icon, hx + 12, hy + 12, 22)
            hx += 28
        if hdr_title:
            f_ht = T.font(18, bold=True)
            d.text((hx, hy + 12), hdr_title, font=f_ht, fill=T.BLACK, anchor="lm")

        badge_str = f"{len(active_items)} / {len(configured_items)} ON" if configured_items else f"{len(active_items)} ACTIVE"
        f_hb = T.font(12, bold=True)
        bw = T.text_width(badge_str, f_hb) + 16
        bx0 = x + w - bw
        by0 = y + 2
        d.rounded_rectangle([(bx0, by0), (bx0 + bw, by0 + 20)], radius=4, outline=T.BLACK, width=1)
        d.text((bx0 + bw // 2, by0 + 10), badge_str, font=f_hb, fill=T.BLACK, anchor="mm")

        y += hdr_h + 8
        h -= hdr_h + 8

    n = len(active_items)
    if n == 0:
        d.rounded_rectangle([(x, y), (x + w, y + h)], radius=10, outline=T.BLACK, width=1)
        idle_icon = hdr_icon or "mdi:power-sleep"
        _draw_icon_glyph(d, idle_icon, x + w // 2, y + h // 2 - 20, 48)
        f_idle1 = T.font(20, bold=True)
        d.text((x + w // 2, y + h // 2 + 18), "All Entities Idle", font=f_idle1, fill=T.BLACK, anchor="mm")
        f_idle2 = T.font(13, bold=False)
        d.text((x + w // 2, y + h // 2 + 38), "Automatically skipped from rotation when show_if is configured", font=f_idle2, fill=T.BLACK, anchor="mm")
        return

    is_wide = (w >= h)

    # 1 Item: Hero Card
    if n == 1:
        it = active_items[0]
        sec = format_sec(it)
        hide_txt = (show_labels == "icons_only") or it.get("hide_name", False)
        d.rounded_rectangle([(x, y), (x + w, y + h)], radius=12, outline=T.BLACK, width=2)
        if is_wide:
            if hide_txt:
                isz = req_icon_sz or min(110, h - 36)
                _draw_icon_glyph(d, it["icon"], x + w // 2, y + h // 2, isz)
            else:
                isz = req_icon_sz or min(88, h - 36)
                _draw_icon_glyph(d, it["icon"], x + 24 + isz // 2, y + h // 2, isz)
                tx = x + 24 + isz + 24
                name_f = T.font(32, bold=True)
                name_txt = _fit_text(it["name"], w - isz - 210, name_f)
                d.text((tx, y + h // 2 - (14 if sec else 0)), name_txt, font=name_f, fill=T.BLACK, anchor="lm")
                if sec:
                    sec_f = T.font(18, bold=False)
                    d.text((tx, y + h // 2 + 18), sec, font=sec_f, fill=T.BLACK, anchor="lm")
            bw, bh = 84, 28
            bx0 = x + w - bw - 24
            by0 = y + (h - bh) // 2
            d.rounded_rectangle([(bx0, by0), (bx0 + bw, by0 + bh)], radius=6, fill=T.BLACK)
            d.text((bx0 + bw // 2, by0 + bh // 2), "ACTIVE", font=T.font(13, bold=True), fill=T.WHITE, anchor="mm")
        else:
            mid_y = y + h // 2
            if hide_txt:
                isz = req_icon_sz or min(100, w // 2)
                _draw_icon_glyph(d, it["icon"], x + w // 2, mid_y, isz)
            else:
                isz = req_icon_sz or min(80, w // 3)
                _draw_icon_glyph(d, it["icon"], x + w // 2, mid_y - (50 if sec else 30), isz)
                name_f = T.font(28, bold=True)
                name_txt = _fit_text(it["name"], w - 32, name_f)
                d.text((x + w // 2, mid_y + (20 if sec else 30)), name_txt, font=name_f, fill=T.BLACK, anchor="mm")
                if sec:
                    sec_f = T.font(18, bold=False)
                    d.text((x + w // 2, mid_y + 54), sec, font=sec_f, fill=T.BLACK, anchor="mm")
            pw, ph = 36, 18
            d.rounded_rectangle([(x + w - pw - 10, y + 10), (x + w - 10, y + 10 + ph)], radius=4, fill=T.BLACK)
            d.text((x + w - 10 - pw // 2, y + 10 + ph // 2), "ON", font=T.font(10, bold=True), fill=T.WHITE, anchor="mm")
        return

    # Multi-card layout mode
    # Legacy layout_4 support: if layout_4 == "columns" and layout_mode not explicitly given, use columns
    layout_mode = el.get("layout_mode") or ("columns" if el.get("layout_4") == "columns" else "grid")
    gap = 10 if n <= 4 else 8

    # Determine grid rows and cols
    if layout_mode == "columns" or n <= 3:
        if is_wide:
            cols = n
            rows = 1
        else:
            cols = 1
            rows = n
        boxes = _compute_grid_boxes(x, y, w, h, n, cols, rows, gap=gap)
    else:
        # 2D Grid Layout (n >= 4)
        if is_wide:
            if n == 4:
                cols, rows = 2, 2
            elif n <= 6:
                cols, rows = 3, 2  # 2 rows x 3 cols (2x3)
            elif n <= 8:
                cols, rows = 4, 2  # 2 rows x 4 cols (2x4)
            else:
                rows = 3
                cols = math.ceil(n / rows)
        else:
            if n == 4:
                cols, rows = 2, 2
            elif n <= 6:
                cols, rows = 2, 3  # 3 rows x 2 cols (3x2)
            elif n <= 8:
                cols, rows = 2, 4  # 4 rows x 2 cols (4x2)
            else:
                cols = 2
                rows = math.ceil(n / cols)
        boxes = _compute_grid_boxes(x, y, w, h, n, cols, rows, gap=gap)

    # Render each card
    for it, (cx0, cy0, cw_i, ch_i) in zip(active_items, boxes):
        cx1, cy1 = cx0 + cw_i, cy0 + ch_i
        d.rounded_rectangle([(cx0, cy0), (cx1, cy1)], radius=10, outline=T.BLACK, width=2)

        # State Badge
        st_txt = str(it.get("state") or "on").upper()
        if len(st_txt) > 6:
            st_txt = st_txt[:6]
        f_badge = T.font(9, bold=True)
        bw = max(28, T.text_width(st_txt, f_badge) + 10)
        ph = 16
        bx0 = cx1 - bw - 6
        by0 = cy0 + 6
        d.rounded_rectangle([(bx0, by0), (bx0 + bw, by0 + ph)], radius=4, fill=T.BLACK)
        d.text((bx0 + bw // 2, by0 + ph // 2), st_txt, font=f_badge, fill=T.WHITE, anchor="mm")

        sec = format_sec(it)
        hide_txt = (show_labels == "icons_only") or it.get("hide_name", False)

        if hide_txt:
            # Centered Icon Only
            max_avail = min(cw_i - 20, ch_i - 20)
            if req_icon_sz:
                isz = min(req_icon_sz, max_avail)
            else:
                isz = min(80, max(42, int(min(cw_i, ch_i) * 0.62)))
            _draw_icon_glyph(d, it["icon"], cx0 + cw_i // 2, cy0 + ch_i // 2, isz)
        else:
            # Icon + Labels
            if cw_i > ch_i * 1.25:
                # Horizontal orientation (wide card)
                max_avail = ch_i - 22
                if req_icon_sz:
                    isz = min(req_icon_sz, max_avail)
                else:
                    isz = min(54, max(36, ch_i - 32))
                _draw_icon_glyph(d, it["icon"], cx0 + 14 + isz // 2, cy0 + ch_i // 2, isz)
                tx = cx0 + 14 + isz + 12
                name_f = T.font(min(22, max(15, cw_i // 13)), bold=True)
                avail_tw = max(30, bx0 - tx - 6)
                name_txt = _fit_text(it["name"], avail_tw, name_f)
                d.text((tx, cy0 + ch_i // 2 - (10 if sec else 0)), name_txt, font=name_f, fill=T.BLACK, anchor="lm")
                if sec:
                    sec_f = T.font(min(14, max(11, cw_i // 18)), bold=False)
                    d.text((tx, cy0 + ch_i // 2 + 13), sec, font=sec_f, fill=T.BLACK, anchor="lm")
            else:
                # Vertical orientation (square/tall card)
                max_avail = min(cw_i - 18, int(ch_i * 0.45))
                if req_icon_sz:
                    isz = min(req_icon_sz, max_avail)
                else:
                    isz = min(50, max(32, int(cw_i * 0.38)))

                mid_x = cx0 + cw_i // 2
                icon_y = cy0 + ch_i * (0.33 if sec else 0.38)
                _draw_icon_glyph(d, it["icon"], mid_x, icon_y, isz)
                name_f = T.font(min(18, max(14, cw_i // 10)), bold=True)
                name_txt = _fit_text(it["name"], cw_i - 16, name_f)
                d.text((mid_x, cy0 + ch_i * (0.68 if sec else 0.74)), name_txt, font=name_f, fill=T.BLACK, anchor="mm")
                if sec:
                    sec_f = T.font(min(13, max(10, cw_i // 13)), bold=False)
                    d.text((mid_x, cy0 + ch_i * 0.86), sec, font=sec_f, fill=T.BLACK, anchor="mm")

def _parse_val_json(raw_val):
    if raw_val is None:
        return None
    if isinstance(raw_val, (dict, list)):
        return raw_val
    if isinstance(raw_val, str) and raw_val.strip():
        try:
            return json.loads(raw_val)
        except Exception:
            return raw_val
    return None


def _draw_calendar_month(img, d, el, raw_val, display=None):
    x, y, w, h = _clamp_box(el, 360, 240, display=display)
    show_border = el.get("show_border") not in (False, "false", 0, "0")
    if show_border:
        d.rounded_rectangle([(x, y), (x + w, y + h)], radius=12, outline=T.BLACK, width=1)
        x += 6; y += 4; w -= 12; h -= 8

    now = datetime.now()
    try:
        year = int(el.get("year") or now.year)
    except (ValueError, TypeError):
        year = now.year
    try:
        month = int(el.get("month") or now.month)
    except (ValueError, TypeError):
        month = now.month
    month = max(1, min(12, month))
    year = max(1970, min(2100, year))
    today_day = now.day if (year == now.year and month == now.month) else -1
    highlight_today = el.get("highlight_today") not in (False, "false", 0, "0")

    fw_raw = el.get("first_weekday", 0)
    first_weekday = 6 if str(fw_raw).lower() in ("6", "sun", "sunday") else 0

    event_days = set()
    val_parsed = _parse_val_json(raw_val)
    if isinstance(val_parsed, list):
        for ev in val_parsed:
            if isinstance(ev, dict):
                st = ev.get("start")
                if isinstance(st, str):
                    try:
                        edt = datetime.fromisoformat(st.replace("Z", "+00:00"))
                        if edt.year == year and edt.month == month:
                            event_days.add(edt.day)
                    except Exception:
                        pass
            elif isinstance(ev, int):
                event_days.add(ev)
    elif isinstance(val_parsed, dict) and "event_days" in val_parsed:
        for ed in val_parsed["event_days"]:
            try:
                event_days.add(int(ed))
            except Exception:
                pass

    show_header = el.get("show_header") not in (False, "false", 0, "0")
    header_h = min(32, max(20, h // 8)) if show_header else 0

    if show_header:
        month_name = calendar.month_name[month].upper()
        header_text = f"{month_name} {year}"
        header_f = T.font(min(20, max(13, int(header_h * 0.72))), bold=True)
        d.text((x + w // 2, y + header_h // 2), header_text, font=header_f, fill=T.BLACK, anchor="mm")

    show_weekdays = el.get("show_weekdays") not in (False, "false", 0, "0")
    col_w = w / 7.0

    if show_weekdays:
        weekday_h = min(20, max(14, int(header_h * 0.6 if header_h else 18)))
        day_names_long = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"] if first_weekday == 0 else ["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"]
        day_names_short = ["M", "T", "W", "T", "F", "S", "S"] if first_weekday == 0 else ["S", "M", "T", "W", "T", "F", "S"]
        use_long = col_w >= 34
        day_labels = day_names_long if use_long else day_names_short
        wf = T.font(min(13, max(9, int(col_w * 0.3))), bold=True)
        wy = y + header_h + 1
        for c_idx, label in enumerate(day_labels):
            cx = x + int((c_idx + 0.5) * col_w)
            d.text((cx, wy + weekday_h // 2), label, font=wf, fill=T.BLACK, anchor="mm")
        div_y = wy + weekday_h + 1
        d.line([(x + 6, div_y), (x + w - 6, div_y)], fill=T.BLACK, width=1)
        grid_y = div_y + 4
    else:
        grid_y = y + header_h + 4

    c = calendar.Calendar(firstweekday=first_weekday)
    weeks = c.monthdayscalendar(year, month)
    num_rows = len(weeks)
    grid_h = max(10, y + h - grid_y - 4)
    row_h = grid_h / float(num_rows)
    cell_f_sz = min(19, max(11, int(min(col_w * 0.45, row_h * 0.52))))
    font_day = T.font(cell_f_sz, bold=False)
    font_day_today = T.font(cell_f_sz, bold=True)

    for r_idx, week in enumerate(weeks):
        cy = grid_y + int((r_idx + 0.5) * row_h)
        for c_idx, day in enumerate(week):
            if day == 0:
                continue
            cx = x + int((c_idx + 0.5) * col_w)
            is_today = (day == today_day) and highlight_today
            has_event = day in event_days

            if is_today:
                rad = int(min(col_w * 0.4, row_h * 0.4))
                d.ellipse([(cx - rad, cy - rad), (cx + rad, cy + rad)], fill=T.BLACK)
                d.text((cx, cy), str(day), font=font_day_today, fill=T.WHITE, anchor="mm")
                if has_event:
                    d.ellipse([(cx - 2, cy + rad + 2), (cx + 2, cy + rad + 5)], fill=T.BLACK)
            else:
                d.text((cx, cy), str(day), font=font_day, fill=T.BLACK, anchor="mm")
                if has_event:
                    d.ellipse([(cx - 2, cy + cell_f_sz // 2 + 2), (cx + 2, cy + cell_f_sz // 2 + 5)], fill=T.BLACK)


def _draw_calendar_agenda(img, d, el, raw_val, display=None):
    x, y, w, h = _clamp_box(el, 375, 250, display=display)
    show_border = el.get("show_border") not in (False, "false", 0, "0")
    if show_border:
        d.rounded_rectangle([(x, y), (x + w, y + h)], radius=12, outline=T.BLACK, width=1)

    title = str(el.get("title") or "Upcoming Events").upper()
    d.text((x + 14, y + 14), title, font=T.font(12, bold=True), fill=T.BLACK, anchor="lm")

    events = []
    val_parsed = _parse_val_json(raw_val)
    if isinstance(val_parsed, list):
        events = [ev for ev in val_parsed if isinstance(ev, dict)]
    elif isinstance(val_parsed, dict) and "events" in val_parsed:
        events = [ev for ev in val_parsed["events"] if isinstance(ev, dict)]
    elif isinstance(val_parsed, dict) and val_parsed.get("message"):
        events = [{
            "summary": val_parsed.get("message"),
            "start": val_parsed.get("start_time"),
            "end": val_parsed.get("end_time")
        }]

    if not events and raw_val is None:
        # Default preview sample events
        events = [
            {"time_label": "TODAY 19:30", "summary": "Dinner with Sarah", "sub": "Trattoria Al Borgo"},
            {"time_label": "TUE 20 OCT", "summary": "Dentist Appointment", "sub": "09:00 AM • Dr. Popa"},
            {"time_label": "THU 22 OCT", "summary": "Trash & Recycling Pickup", "sub": "Bins out by 07:00"},
            {"time_label": "FRI 30 OCT", "summary": "Trip to Munich", "sub": "Flight LH1657"}
        ]

    count_badge = f"{len(events)} EVENTS" if events else "NONE"
    bf = T.font(9, bold=True)
    bw = T.text_width(count_badge, bf) + 12
    d.rounded_rectangle([(x + w - bw - 14, y + 6), (x + w - 14, y + 22)], radius=4, fill=T.BLACK)
    d.text((x + w - 14 - bw // 2, y + 14), count_badge, font=bf, fill=T.WHITE, anchor="mm")
    d.line([(x + 10, y + 28), (x + w - 10, y + 28)], fill=T.BLACK, width=1)

    if not events:
        d.text((x + w // 2, y + h // 2), "No upcoming events scheduled", font=T.font(13, bold=False), fill=T.BLACK, anchor="mm")
        return

    list_y = y + 34
    avail_h = (y + h - 10) - list_y
    max_items = max(1, min(6, int(el.get("max_events", 4))))
    display_events = events[:max_items]
    item_h = avail_h // len(display_events)

    now = datetime.now()
    today_ymd = now.strftime("%Y-%m-%d")

    for idx, ev in enumerate(display_events):
        iy0 = list_y + idx * item_h
        iy_mid = iy0 + item_h // 2

        # Format time badge
        dt_str = ev.get("time_label")
        if not dt_str:
            raw_st = ev.get("start") or ev.get("start_time") or ""
            if raw_st:
                try:
                    s_clean = str(raw_st).replace("Z", "+00:00")
                    if len(s_clean) == 10:  # all day "YYYY-MM-DD"
                        edt = datetime.fromisoformat(s_clean)
                        if s_clean == today_ymd:
                            dt_str = "TODAY"
                        else:
                            dt_str = edt.strftime("%a %-d %b").upper()
                    else:
                        edt = datetime.fromisoformat(s_clean)
                        if edt.strftime("%Y-%m-%d") == today_ymd:
                            dt_str = f"TODAY {edt.strftime('%H:%M')}"
                        else:
                            dt_str = edt.strftime("%a %-d %b").upper()
                except Exception:
                    dt_str = "SOON"
            else:
                dt_str = "EVENT"

        df = T.font(10, bold=True)
        pill_w = max(52, T.text_width(dt_str, df) + 12)
        pill_h = 18
        py0 = iy_mid - pill_h // 2
        d.rounded_rectangle([(x + 12, py0), (x + 12 + pill_w, py0 + pill_h)], radius=4, fill=T.BLACK)
        d.text((x + 12 + pill_w // 2, iy_mid), dt_str, font=df, fill=T.WHITE, anchor="mm")

        # Title
        cal_badge = ev.get("cal_badge")
        title_x = x + 12 + pill_w + 10
        title_w = (x + w - 14) - title_x
        if cal_badge:
            cbf = T.font(9, bold=True)
            cb_w = max(24, T.text_width(cal_badge, cbf) + 8)
            d.rounded_rectangle([(x + w - 14 - cb_w, iy_mid - 8), (x + w - 14, iy_mid + 8)], radius=3, outline=T.BLACK, width=1)
            d.text((x + w - 14 - cb_w // 2, iy_mid), cal_badge, font=cbf, fill=T.BLACK, anchor="mm")
            title_w -= (cb_w + 8)

        tf = T.font(min(15, max(12, int(item_h * 0.32))), bold=True)
        summary = ev.get("summary") or ev.get("message") or "Untitled Event"
        title_txt = _fit_text(summary, title_w, tf)

        sub_txt = ev.get("sub") or ev.get("location") or ""
        d.text((title_x, iy_mid - (7 if sub_txt else 0)), title_txt, font=tf, fill=T.BLACK, anchor="lm")

        if sub_txt:
            sf = T.font(min(12, max(10, int(item_h * 0.24))), bold=False)
            sub_fit = _fit_text(sub_txt, title_w, sf)
            d.text((title_x, iy_mid + 9), sub_fit, font=sf, fill=T.BLACK, anchor="lm")

        if idx < len(display_events) - 1:
            div_y = iy0 + item_h - 1
            d.line([(x + 14, div_y), (x + w - 14, div_y)], fill=T.BLACK, width=1)


_WEATHER_ICON_MAP = {
    "clear-night": "mdi:weather-night",
    "cloudy": "mdi:weather-cloudy",
    "fog": "mdi:weather-fog",
    "hail": "mdi:weather-hail",
    "lightning": "mdi:weather-lightning",
    "lightning-rainy": "mdi:weather-lightning-rainy",
    "partlycloudy": "mdi:weather-partly-cloudy",
    "pouring": "mdi:weather-pouring",
    "rainy": "mdi:weather-rainy",
    "snowy": "mdi:weather-snowy",
    "snowy-rainy": "mdi:weather-snowy-rainy",
    "sunny": "mdi:weather-sunny",
    "windy": "mdi:weather-windy",
    "windy-variant": "mdi:weather-windy-variant",
    "exceptional": "mdi:alert-circle-outline",
}


def _draw_weather_forecast(img, d, el, raw_val, display=None):
    x, y, w, h = _clamp_box(el, 752, 235, display=display)
    show_border = el.get("show_border") not in (False, "false", 0, "0")
    if show_border:
        d.rounded_rectangle([(x, y), (x + w, y + h)], radius=12, outline=T.BLACK, width=1)

    data = _parse_val_json(raw_val)
    if not isinstance(data, dict):
        data = {
            "condition": "rainy",
            "temperature": 8.5,
            "unit": "°C",
            "humidity": 95,
            "wind_speed": 6.1,
            "wind_unit": "km/h",
            "forecast": [
                {"datetime": "2026-10-17T09:00:00+00:00", "condition": "rainy", "temperature": 11.2, "templow": 8.5, "precipitation": 1.0, "precipitation_probability": 85},
                {"datetime": "2026-10-18T09:00:00+00:00", "condition": "partlycloudy", "temperature": 15.5, "templow": 4.6, "precipitation": 0.0, "precipitation_probability": 10},
                {"datetime": "2026-10-19T09:00:00+00:00", "condition": "partlycloudy", "temperature": 17.3, "templow": 7.7, "precipitation": 0.0, "precipitation_probability": 5},
                {"datetime": "2026-10-20T09:00:00+00:00", "condition": "cloudy", "temperature": 15.1, "templow": 7.8, "precipitation": 0.1, "precipitation_probability": 30},
                {"datetime": "2026-10-21T09:00:00+00:00", "condition": "rainy", "temperature": 22.7, "templow": 10.6, "precipitation": 0.6, "precipitation_probability": 70}
            ]
        }

    cond = str(data.get("condition") or "partlycloudy").lower()
    temp = data.get("temperature", "--")
    unit = str(data.get("unit") or "°C")
    humidity = data.get("humidity")
    wind = data.get("wind_speed")
    wind_unit = str(data.get("wind_unit") or "km/h")
    forecast = data.get("forecast") or []

    cur_icon = _WEATHER_ICON_MAP.get(cond, "mdi:weather-cloudy")

    # Split vs Stacked mode: split when wide landscape, stacked when portrait or tall card
    is_split = (w >= 480) or (w >= 340 and w >= h)
    if is_split:
        hero_w = int(w * 0.42)
        fore_x = x + hero_w
        fore_w = w - hero_w

        hero_mid_y = y + h // 2 - 14
        isz = min(68, max(42, h // 3))
        _draw_icon_glyph(d, cur_icon, x + 24 + isz // 2, hero_mid_y, isz)

        tx = x + 24 + isz + 16
        temp_str = f"{temp}{unit}" if str(temp).endswith("°") or unit.startswith("°") else f"{temp}°"
        tf = T.font(min(42, max(26, h // 5)), bold=True)
        d.text((tx, hero_mid_y - 10), temp_str, font=tf, fill=T.BLACK, anchor="lm")

        cond_str = cond.replace("-", " ").title()
        cf = T.font(min(17, max(13, h // 13)), bold=True)
        d.text((tx, hero_mid_y + 18), cond_str, font=cf, fill=T.BLACK, anchor="lm")

        chips_y = y + h - 22
        chip_parts = []
        if humidity is not None:
            chip_parts.append(f"HUM: {humidity}%")
        if wind is not None:
            chip_parts.append(f"WIND: {wind} {wind_unit}")
        if forecast:
            today_f = forecast[0]
            th = today_f.get("temperature")
            tl = today_f.get("templow")
            if th is not None and tl is not None:
                chip_parts.append(f"H: {th:.0f}°  L: {tl:.0f}°")
            pop = today_f.get("precipitation_probability")
            precip = today_f.get("precipitation")
            if pop is not None and float(pop) > 0:
                chip_parts.append(f"RAIN: {float(pop):.0f}%")
            elif precip is not None and float(precip) > 0:
                chip_parts.append(f"RAIN: {float(precip):.1f}mm")

        if chip_parts:
            chip_text = "   •   ".join(chip_parts)
            avail_chip_w = fore_x - x - 36
            csz = 11
            if T.text_width(chip_text, T.font(csz, bold=True)) > avail_chip_w:
                csz = 10
            if T.text_width(chip_text, T.font(csz, bold=True)) > avail_chip_w:
                csz = 9
            mf = T.font(csz, bold=True)
            d.text((x + 20, chips_y), chip_text, font=mf, fill=T.BLACK, anchor="lm")

        # Vertical divider
        d.line([(fore_x, y + 14), (fore_x, y + h - 14)], fill=T.BLACK, width=1)

        # Forecast strip (4 days)
        display_forecast = forecast[1:5] if len(forecast) > 4 else forecast[:4]
        n_days = len(display_forecast)
        if n_days > 0:
            day_w = fore_w / float(n_days)
            for i, fcast in enumerate(display_forecast):
                cx = fore_x + int((i + 0.5) * day_w)
                dt_raw = fcast.get("datetime")
                day_name = f"DAY {i+1}"
                if dt_raw:
                    try:
                        dt = datetime.fromisoformat(str(dt_raw).replace("Z", "+00:00"))
                        day_name = dt.strftime("%a").upper()
                    except Exception:
                        pass

                d.text((cx, y + 24), day_name, font=T.font(12, bold=True), fill=T.BLACK, anchor="mm")
                f_cond = str(fcast.get("condition") or "cloudy").lower()
                f_icon = _WEATHER_ICON_MAP.get(f_cond, "mdi:weather-cloudy")
                _draw_icon_glyph(d, f_icon, cx, y + h // 2 - 2, 34)

                hi = fcast.get("temperature")
                lo = fcast.get("templow")
                hl_str = f"{hi:.0f}° / {lo:.0f}°" if (hi is not None and lo is not None) else f"{hi or lo or '--'}°"
                d.text((cx, y + h - 34), hl_str, font=T.font(12, bold=True), fill=T.BLACK, anchor="mm")

                pop = fcast.get("precipitation_probability")
                precip = fcast.get("precipitation")
                if pop is not None and float(pop) > 0:
                    d.text((cx, y + h - 18), f"{float(pop):.0f}% rain", font=T.font(10, bold=False), fill=T.BLACK, anchor="mm")
                elif precip is not None and float(precip) > 0:
                    d.text((cx, y + h - 18), f"{float(precip):.1f} mm", font=T.font(10, bold=False), fill=T.BLACK, anchor="mm")
        else:
            d.text((fore_x + fore_w // 2, y + h // 2), "Forecast loading…", font=T.font(13, bold=False), fill=T.BLACK, anchor="mm")
    else:
        # Stacked layout (portrait or narrow cards)
        hero_h = int(h * 0.32)
        mid_y = y + hero_h // 2 - 8
        isz = min(54, max(36, hero_h // 2))
        _draw_icon_glyph(d, cur_icon, x + 36, mid_y, isz)
        temp_str = f"{temp}{unit}" if str(temp).endswith("°") or unit.startswith("°") else f"{temp}°"
        d.text((x + 84, mid_y - 10), temp_str, font=T.font(min(38, max(24, int(w * 0.1))), bold=True), fill=T.BLACK, anchor="lm")
        d.text((x + 84, mid_y + 18), cond.replace("-", " ").title(), font=T.font(15, bold=True), fill=T.BLACK, anchor="lm")

        parts = []
        if humidity is not None:
            parts.append(f"HUM: {humidity}%")
        if wind is not None:
            parts.append(f"WIND: {wind} {wind_unit}")
        if parts:
            d.text((x + 20, y + hero_h - 14), "   •   ".join(parts), font=T.font(11, bold=True), fill=T.BLACK, anchor="lm")

        d.line([(x + 10, y + hero_h), (x + w - 10, y + hero_h)], fill=T.BLACK, width=1)

        display_forecast = forecast[1:5] if len(forecast) > 4 else forecast[:4]
        n_days = min(4, len(display_forecast))
        if n_days > 0:
            row_h = (h - hero_h - 14) / float(n_days)
            for i, fcast in enumerate(display_forecast[:n_days]):
                ry = y + hero_h + 8 + int(i * row_h)
                ry_mid = ry + int(row_h * 0.5)
                dt_raw = fcast.get("datetime")
                day_name = f"DAY {i+1}"
                if dt_raw:
                    try:
                        dt = datetime.fromisoformat(str(dt_raw).replace("Z", "+00:00"))
                        day_name = dt.strftime("%A").upper()
                    except Exception:
                        pass
                d.text((x + 20, ry_mid), day_name, font=T.font(13, bold=True), fill=T.BLACK, anchor="lm")
                f_cond = str(fcast.get("condition") or "cloudy").lower()
                _draw_icon_glyph(d, _WEATHER_ICON_MAP.get(f_cond, "mdi:weather-cloudy"), x + w // 2 - 10, ry_mid, 30)
                hi = fcast.get("temperature")
                lo = fcast.get("templow")
                hl_str = f"{hi:.0f}° / {lo:.0f}°" if (hi is not None and lo is not None) else f"{hi or lo or '--'}°"
                d.text((x + w - 20, ry_mid), hl_str, font=T.font(13, bold=True), fill=T.BLACK, anchor="rm")
                if i < n_days - 1:
                    d.line([(x + 14, ry + int(row_h)), (x + w - 14, ry + int(row_h))], fill=T.BLACK, width=1)


_CARDINAL_DEG = {
    'N': 0, 'NNE': 22.5, 'NE': 45, 'ENE': 67.5, 'E': 90, 'ESE': 112.5, 'SE': 135, 'SSE': 157.5,
    'S': 180, 'SSW': 202.5, 'SW': 225, 'WSW': 247.5, 'W': 270, 'WNW': 292.5, 'NW': 315, 'NNW': 337.5
}


def _draw_radar_scope(d, sx, sy, sw, sh, max_r_km, ac_list, tracked_cs=""):
    cx = sx + sw // 2
    cy = sy + sh // 2
    r_scope = max(30, min(sw, sh) // 2 - 12)

    # Outer range ring
    d.ellipse([(cx - r_scope, cy - r_scope), (cx + r_scope, cy + r_scope)], outline=T.BLACK, width=2)
    # Intermediate range ring
    mid_r = r_scope // 2
    d.ellipse([(cx - mid_r, cy - mid_r), (cx + mid_r, cy + mid_r)], outline=T.BLACK, width=1)

    # Crosshairs
    d.line([(cx - r_scope, cy), (cx + r_scope, cy)], fill=T.BLACK, width=1)
    d.line([(cx, cy - r_scope), (cx, cy + r_scope)], fill=T.BLACK, width=1)
    # Center Home marker
    d.ellipse([(cx - 3, cy - 3), (cx + 3, cy + 3)], fill=T.BLACK)

    # Cardinal labels
    cf = T.font(9, bold=True)
    d.text((cx, cy - r_scope + 8), "N", font=cf, fill=T.BLACK, anchor="mm")
    d.text((cx + r_scope - 8, cy), "E", font=cf, fill=T.BLACK, anchor="mm")
    d.text((cx, cy + r_scope - 8), "S", font=cf, fill=T.BLACK, anchor="mm")
    d.text((cx - r_scope + 8, cy), "W", font=cf, fill=T.BLACK, anchor="mm")

    # Range scale label
    rf = T.font(8, bold=True)
    d.text((cx + mid_r + 3, cy - 5), f"{int(max_r_km // 2)}k", font=rf, fill=T.BLACK, anchor="lm")

    # Plot aircraft blips
    for ac in ac_list[:8]:
        d_km = float(ac.get("distance_km") or 0.0)
        b_deg = ac.get("bearing_deg")
        if b_deg is None:
            b_deg = _CARDINAL_DEG.get(ac.get("bearing_cardinal", "N"), 0.0)

        norm_r = min(1.0, max(0.04, d_km / float(max_r_km or 35.0)))
        pix_r = norm_r * (r_scope - 6)
        rad = math.radians(b_deg)
        px = int(cx + pix_r * math.sin(rad))
        py = int(cy - pix_r * math.cos(rad))

        cs = str(ac.get("callsign") or ac.get("icao24") or "").strip().upper()
        is_tracked = (cs == tracked_cs) or (not tracked_cs and ac == ac_list[0])

        # Directional airplane chevron
        track = float(ac.get("track_deg") or 0.0)
        t_rad = math.radians(track)
        plen = 9 if is_tracked else 6
        pwid = 6 if is_tracked else 4
        pts = [(0, -plen), (pwid, plen * 0.7), (0, plen * 0.3), (-pwid, plen * 0.7)]
        cos_t, sin_t = math.cos(t_rad), math.sin(t_rad)
        rot_pts = [(px + int(lx * cos_t - ly * sin_t), py + int(lx * sin_t + ly * cos_t)) for lx, ly in pts]
        d.polygon(rot_pts, fill=T.BLACK)

        if is_tracked:
            sz = 12
            d.line([(px - sz, py - sz), (px - sz + 4, py - sz)], fill=T.BLACK, width=1)
            d.line([(px - sz, py - sz), (px - sz, py - sz + 4)], fill=T.BLACK, width=1)
            d.line([(px + sz, py - sz), (px + sz - 4, py - sz)], fill=T.BLACK, width=1)
            d.line([(px + sz, py - sz), (px + sz, py - sz + 4)], fill=T.BLACK, width=1)
            d.line([(px - sz, py + sz), (px - sz + 4, py + sz)], fill=T.BLACK, width=1)
            d.line([(px - sz, py + sz), (px - sz, py + sz - 4)], fill=T.BLACK, width=1)
            d.line([(px + sz, py + sz), (px + sz - 4, py + sz)], fill=T.BLACK, width=1)
            d.line([(px + sz, py + sz), (px + sz, py + sz - 4)], fill=T.BLACK, width=1)

        if cs:
            lx = px + 9 if px >= cx else px - 9
            anchor = "lm" if px >= cx else "rm"
            d.text((lx, py - 6), cs, font=T.font(9, bold=True), fill=T.BLACK, anchor=anchor)


def _draw_flight_tracker(img, d, el, raw_val, display=None):
    x, y, w, h = _clamp_box(el, 752, 235, display=display)
    show_border = el.get("show_border") not in (False, "false", 0, "0")
    if show_border:
        d.rounded_rectangle([(x, y), (x + w, y + h)], radius=12, outline=T.BLACK, width=1)

    radius = max(5, min(250, int(el.get("radius") or 35)))
    aircraft_list = []
    val_parsed = _parse_val_json(raw_val)
    if isinstance(val_parsed, list):
        aircraft_list = [a for a in val_parsed if isinstance(a, dict)]
    elif isinstance(val_parsed, dict) and "aircraft" in val_parsed:
        aircraft_list = [a for a in val_parsed["aircraft"] if isinstance(a, dict)]
    elif isinstance(val_parsed, dict) and val_parsed.get("callsign"):
        aircraft_list = [val_parsed]

    if not aircraft_list and raw_val is None:
        aircraft_list = [
            {
                "callsign": "BAW71LK",
                "country": "United Kingdom • British Airways",
                "icao24": "40089A",
                "distance_km": 8.4,
                "bearing_deg": 225.0,
                "bearing_cardinal": "SW",
                "altitude_m": 10370,
                "velocity_ms": 233.2,
                "track_deg": 302,
                "vertical_rate": 0.0
            },
            {
                "callsign": "THY41Y",
                "country": "Turkey • Turkish Airlines",
                "icao24": "4BA982",
                "distance_km": 19.2,
                "bearing_deg": 45.0,
                "bearing_cardinal": "NE",
                "altitude_m": 11887,
                "velocity_ms": 253.3,
                "track_deg": 140,
                "vertical_rate": -1.5
            }
        ]

    style = str(el.get("style") or "card").lower()

    if not aircraft_list:
        mid_x = x + w // 2
        mid_y = y + h // 2
        _draw_icon_glyph(d, "mdi:radar", mid_x, mid_y - 24, 52)
        d.text((mid_x, mid_y + 16), "AIRSPACE CLEAR", font=T.font(18, bold=True), fill=T.BLACK, anchor="mm")
        d.text((mid_x, mid_y + 38), f"No aircraft overhead within {radius} km", font=T.font(12, bold=False), fill=T.BLACK, anchor="mm")
        return

    sub_idx = int(el.get("sub_index", 0))
    sub_total = len(aircraft_list) if aircraft_list else 1
    if sub_idx >= sub_total:
        sub_idx = 0

    ac = aircraft_list[sub_idx]
    callsign = str(ac.get("callsign") or ac.get("icao24") or "UNKNOWN").strip().upper()
    country = ac.get("country") or "Commercial Flight"
    dist_km = float(ac.get("distance_km") or 0.0)
    bearing = ac.get("bearing_cardinal") or "OVERHEAD"
    alt_m = float(ac.get("altitude_m") or 0.0)
    alt_ft = int(alt_m * 3.28084) if alt_m else 0
    speed_ms = float(ac.get("velocity_ms") or 0.0)
    speed_kts = int(speed_ms * 1.94384) if speed_ms else 0
    speed_kmh = int(speed_ms * 3.6) if speed_ms else 0
    track = int(ac.get("track_deg", 0)) if ac.get("track_deg") is not None else 0
    v_rate = float(ac.get("vertical_rate") or 0.0)
    climb_arrow = " ↑" if v_rate > 1.0 else (" ↓" if v_rate < -1.0 else " →")

    if style == "radar":
        # Pure Circular PPI Radar Scope
        _draw_radar_scope(d, x + 6, y + 6, w - 12, h - 12, radius, aircraft_list, tracked_cs=callsign)
        d.text((x + 16, y + 16), f"AIRSPACE RADAR · {radius} KM", font=T.font(11, bold=True), fill=T.BLACK, anchor="lm")
        target_str = f"TARGET: {callsign} ({dist_km:.1f} KM {bearing})"
        if sub_total > 1:
            target_str = f"[{sub_idx + 1}/{sub_total}] {target_str}"
        d.text((x + w - 16, y + 16), target_str, font=T.font(11, bold=True), fill=T.BLACK, anchor="rm")
        return

    if style == "split" and w >= 480:
        # Split mode: Scope on left, telemetry card on right
        scope_w = min(h - 10, int(w * 0.38))
        _draw_radar_scope(d, x + 8, y + 8, scope_w, h - 16, radius, aircraft_list, tracked_cs=callsign)
        d.line([(x + scope_w + 14, y + 14), (x + scope_w + 14, y + h - 14)], fill=T.BLACK, width=1)

        tx0 = x + scope_w + 26
        tw = w - scope_w - 38
        top_y = y + 16

        cs_f = T.font(28, bold=True)
        d.text((tx0, top_y + 14), callsign, font=cs_f, fill=T.BLACK, anchor="lm")

        sub_f = T.font(12, bold=False)
        sub_title = _fit_text(country, max(40, tw - 120), sub_f)
        d.text((tx0 + 2, top_y + 36), sub_title, font=sub_f, fill=T.BLACK, anchor="lm")

        dist_badge = f"{dist_km:.1f} KM {bearing}" if dist_km > 0 else "OVERHEAD"
        bf = T.font(10, bold=True)
        bw = T.text_width(dist_badge, bf) + 14
        bh = 22
        bx1 = x + w - 16
        bx0 = bx1 - bw
        d.rounded_rectangle([(bx0, top_y + 4), (bx1, top_y + 4 + bh)], radius=5, fill=T.BLACK)
        d.text((bx0 + bw // 2, top_y + 4 + bh // 2), dist_badge, font=bf, fill=T.WHITE, anchor="mm")

        if sub_total > 1:
            pag_str = f"{sub_idx + 1}/{sub_total}"
            pb_w = T.text_width(pag_str, bf) + 12
            pbx1 = bx0 - 6
            pbx0 = pbx1 - pb_w
            d.rounded_rectangle([(pbx0, top_y + 4), (pbx1, top_y + 4 + bh)], radius=5, outline=T.BLACK, width=1)
            d.text((pbx0 + pb_w // 2, top_y + 4 + bh // 2), pag_str, font=bf, fill=T.BLACK, anchor="mm")

        div_y = y + 74
        d.line([(tx0, div_y), (x + w - 16, div_y)], fill=T.BLACK, width=1)

        cols_y = div_y + 8
        cols_h = y + h - cols_y - 10
        n_cols = 3
        cw = tw / float(n_cols)

        metrics_list = [
            ("ALTITUDE", f"{alt_ft:,} ft{climb_arrow}", f"{int(alt_m):,} m"),
            ("SPEED", f"{speed_kts} kts", f"{speed_kmh} km/h"),
            ("HEADING", f"{track}°", str(ac.get("icao24", "")).upper() or "--")
        ]

        for i, (label, val_main, val_sub) in enumerate(metrics_list):
            col_x = tx0 + int(i * cw)
            mid_col_x = col_x + int(cw * 0.5)
            if i > 0:
                d.line([(col_x, cols_y + 6), (col_x, cols_y + cols_h - 6)], fill=T.BLACK, width=1)
            d.text((mid_col_x, cols_y + 12), label, font=T.font(9, bold=True), fill=T.BLACK, anchor="mm")
            d.text((mid_col_x, cols_y + cols_h * 0.50), val_main, font=T.font(16, bold=True), fill=T.BLACK, anchor="mm")
            d.text((mid_col_x, cols_y + cols_h * 0.82), val_sub, font=T.font(10, bold=False), fill=T.BLACK, anchor="mm")
        return

    # Style: "card" (Original Full-Width Telemetry Card, untouched)
    top_y = y + 16
    _draw_icon_glyph(d, "mdi:airplane", x + 30, top_y + 18, 44)

    cs_f = T.font(32, bold=True)
    d.text((x + 65, top_y + 16), callsign, font=cs_f, fill=T.BLACK, anchor="lm")

    sub_f = T.font(13, bold=False)
    sub_title = _fit_text(country, max(60, w - 240), sub_f)
    d.text((x + 67, top_y + 38), sub_title, font=sub_f, fill=T.BLACK, anchor="lm")

    dist_badge = f"{dist_km:.1f} KM {bearing}" if dist_km > 0 else "OVERHEAD"
    bf = T.font(11, bold=True)
    bw = T.text_width(dist_badge, bf) + 16
    bh = 24
    bx1 = x + w - 20
    bx0 = bx1 - bw
    d.rounded_rectangle([(bx0, top_y + 6), (bx1, top_y + 6 + bh)], radius=6, fill=T.BLACK)
    d.text((bx0 + bw // 2, top_y + 6 + bh // 2), dist_badge, font=bf, fill=T.WHITE, anchor="mm")

    if sub_total > 1:
        more_txt = f"FLIGHT {sub_idx + 1} OF {sub_total}"
        mf = T.font(10, bold=True)
        d.text((bx1, top_y + 40), more_txt, font=mf, fill=T.BLACK, anchor="rm")

    div_y = y + 76
    d.line([(x + 16, div_y), (x + w - 16, div_y)], fill=T.BLACK, width=1)

    cols_y = div_y + 8
    cols_h = y + h - cols_y - 10
    n_cols = 4
    cw = (w - 32) / float(n_cols)

    metrics_list = [
        ("ALTITUDE", f"{alt_ft:,} ft{climb_arrow}", f"{int(alt_m):,} m"),
        ("GROUND SPEED", f"{speed_kts} kts", f"{speed_kmh} km/h"),
        ("HEADING", f"{track}°", bearing),
        ("SQUAWK / ICAO", str(ac.get("icao24", "")).upper() or "--", "ADS-B")
    ]

    for i, (label, val_main, val_sub) in enumerate(metrics_list):
        col_x = x + 16 + int(i * cw)
        mid_col_x = col_x + int(cw * 0.5)

        if i > 0:
            d.line([(col_x, cols_y + 6), (col_x, cols_y + cols_h - 6)], fill=T.BLACK, width=1)

        d.text((mid_col_x, cols_y + 14), label, font=T.font(10, bold=True), fill=T.BLACK, anchor="mm")
        d.text((mid_col_x, cols_y + cols_h * 0.52), val_main, font=T.font(18, bold=True), fill=T.BLACK, anchor="mm")
        d.text((mid_col_x, cols_y + cols_h * 0.82), val_sub, font=T.font(11, bold=False), fill=T.BLACK, anchor="mm")


def _draw_sports_racing(img, d, el, raw_val, display=None):
    x, y, w, h = _clamp_box(el, 752, 235, display=display)
    show_border = el.get("show_border") not in (False, "false", 0, "0")
    if show_border:
        d.rounded_rectangle([(x, y), (x + w, y + h)], radius=12, outline=T.BLACK, width=1)

    data = _parse_val_json(raw_val)
    if not isinstance(data, dict):
        data = {
            "series": "F1",
            "event_name": "Italian Grand Prix",
            "circuit": "Autodromo Nazionale Monza",
            "session": "Race",
            "status": "IN",
            "lap": 42,
            "total_laps": 53,
            "leader": "VER",
            "standings": [
                {"pos": 1, "driver": "VER", "team": "Red Bull", "gap": "LEADER", "tyre": "M"},
                {"pos": 2, "driver": "NOR", "team": "McLaren", "gap": "+2.1s", "tyre": "H"},
                {"pos": 3, "driver": "PIA", "team": "McLaren", "gap": "+4.8s", "tyre": "H"},
                {"pos": 4, "driver": "LEC", "team": "Ferrari", "gap": "+7.3s", "tyre": "H"},
                {"pos": 5, "driver": "SAI", "team": "Ferrari", "gap": "+11.0s", "tyre": "M"},
                {"pos": 6, "driver": "HAM", "team": "Mercedes", "gap": "+14.2s", "tyre": "M"},
                {"pos": 7, "driver": "RUS", "team": "Mercedes", "gap": "+18.9s", "tyre": "H"},
                {"pos": 8, "driver": "ALO", "team": "Aston Martin", "gap": "+25.1s", "tyre": "M"},
                {"pos": 9, "driver": "TSU", "team": "RB", "gap": "+32.0s", "tyre": "H"},
                {"pos": 10, "driver": "HUL", "team": "Haas", "gap": "+38.4s", "tyre": "H"}
            ]
        }

    series = str(data.get("series") or "F1").upper()
    event_name = str(data.get("event_name") or "Formula 1 Grand Prix").upper()
    status = str(data.get("status") or "IN").upper()
    lap = data.get("lap")
    total_laps = data.get("total_laps")
    standings = data.get("standings") or []

    # Header
    _draw_icon_glyph(d, "mdi:flag-checkered", x + 24, y + 21, 24)
    hf = T.font(13, bold=True)
    header_txt = _fit_text(f"{series} · {event_name}", w - 180, hf)
    d.text((x + 44, y + 21), header_txt, font=hf, fill=T.BLACK, anchor="lm")

    # Status badge at top right
    status_txt = f"LAP {lap}/{total_laps}" if (lap and total_laps) else (data.get("clock") or status)
    bf = T.font(11, bold=True)
    bw = T.text_width(status_txt, bf) + 16
    bx1 = x + w - 16
    bx0 = bx1 - bw
    d.rounded_rectangle([(bx0, y + 10), (bx1, y + 32)], radius=5, fill=T.BLACK)
    d.text((bx0 + bw // 2, y + 21), status_txt, font=bf, fill=T.WHITE, anchor="mm")

    d.line([(x + 14, y + 42), (x + w - 14, y + 42)], fill=T.BLACK, width=1)

    if not standings:
        # Pre-race or schedule view
        mid_x = x + w // 2
        mid_y = y + h // 2
        _draw_icon_glyph(d, "mdi:racing-helmet", mid_x, mid_y - 20, 46)
        circ = data.get("circuit") or "Grand Prix Circuit"
        d.text((mid_x, mid_y + 18), circ, font=T.font(16, bold=True), fill=T.BLACK, anchor="mm")
        detail = data.get("detail") or "Session scheduled soon"
        d.text((mid_x, mid_y + 40), detail, font=T.font(12, bold=False), fill=T.BLACK, anchor="mm")
        return

    # Leaderboard (Top 10: 1-5 left, 6-10 right)
    col_w = (w - 30) // 2
    mid_div = x + col_w + 15
    d.line([(mid_div, y + 48), (mid_div, y + h - 14)], fill=T.BLACK, width=1)

    display_drivers = standings[:10]
    n_rows = 5
    row_h = (h - 56) // n_rows

    for idx, drv in enumerate(display_drivers):
        is_right = idx >= 5
        cx0 = (x + 15) if not is_right else (mid_div + 15)
        r_idx = idx if not is_right else (idx - 5)
        ry = y + 48 + r_idx * row_h
        ry_mid = ry + row_h // 2
        rw = (mid_div - 15) if not is_right else (x + w - 15)

        pos_str = f"P{drv.get('pos', idx + 1)}"
        code = str(drv.get("driver") or drv.get("code") or drv.get("name") or "DRV")[:3].upper()
        team = str(drv.get("team") or drv.get("constructor") or "")
        gap = str(drv.get("gap") or drv.get("interval") or "")
        tyre = str(drv.get("tyre") or "")[:1].upper()

        d.text((cx0 + 2, ry_mid), pos_str, font=T.font(10, bold=True), fill=T.BLACK, anchor="lm")
        d.text((cx0 + 32, ry_mid), code, font=T.font(13, bold=True), fill=T.BLACK, anchor="lm")

        off_x = cx0 + 66
        if tyre in ("S", "M", "H", "I", "W"):
            d.rounded_rectangle([(off_x, ry_mid - 7), (off_x + 14, ry_mid + 7)], radius=3, outline=T.BLACK, width=1)
            d.text((off_x + 7, ry_mid), tyre, font=T.font(9, bold=True), fill=T.BLACK, anchor="mm")
            off_x += 18

        if team:
            avail_tw = max(30, rw - off_x - (T.text_width(gap, T.font(11, bold=True)) + 12 if gap else 0))
            team_fit = _fit_text(team, avail_tw, T.font(11, bold=False))
            d.text((off_x, ry_mid), team_fit, font=T.font(11, bold=False), fill=T.BLACK, anchor="lm")

        if gap:
            d.text((rw, ry_mid), gap, font=T.font(11, bold=True), fill=T.BLACK, anchor="rm")

        if r_idx < n_rows - 1:
            d.line([(cx0, ry + row_h - 1), (rw, ry + row_h - 1)], fill=T.BLACK, width=1)


def _draw_sports_match(img, d, el, raw_val, display=None):
    x, y, w, h = _clamp_box(el, 752, 235, display=display)
    show_border = el.get("show_border") not in (False, "false", 0, "0")
    if show_border:
        d.rounded_rectangle([(x, y), (x + w, y + h)], radius=12, outline=T.BLACK, width=1)

    raw_parsed = _parse_val_json(raw_val)
    sub_idx = int(el.get("sub_index", 0))
    sub_total = 1

    if isinstance(raw_parsed, list) and raw_parsed:
        sub_total = len(raw_parsed)
        if sub_idx >= sub_total:
            sub_idx = 0
        data = raw_parsed[sub_idx]
    elif isinstance(raw_parsed, dict):
        data = raw_parsed
    else:
        data = {
            "league": "PREMIER LEAGUE",
            "venue": "Emirates Stadium",
            "clock": "74' · 2ND HALF",
            "status": "IN",
            "home_team": "ARSENAL",
            "home_score": 2,
            "home_stats": "14 Shots · 58% Poss",
            "away_team": "CHELSEA",
            "away_score": 1,
            "away_stats": "6 Shots · 42% Poss",
            "events_home": "Saka (22'), Havertz (58')",
            "events_away": "Palmer (41' pen)"
        }

    league = str(data.get("league") or "MATCH").upper()
    venue = str(data.get("venue") or "").upper()
    header_title = f"{league} · {venue}" if venue else league
    clock = str(data.get("clock") or data.get("status") or "LIVE").upper()

    d.text((x + 20, y + 20), header_title, font=T.font(13, bold=True), fill=T.BLACK, anchor="lm")

    # Clock / Status badge
    bf = T.font(11, bold=True)
    bw = T.text_width(clock, bf) + 16
    bx1 = x + w - 16
    bx0 = bx1 - bw
    d.rounded_rectangle([(bx0, y + 10), (bx1, y + 32)], radius=5, fill=T.BLACK)
    d.text((bx0 + bw // 2, y + 21), clock, font=bf, fill=T.WHITE, anchor="mm")

    # Sub-item pagination badge (e.g. [ 2 / 5 ])
    if sub_total > 1:
        pag_badge = f"{sub_idx + 1}/{sub_total}"
        pb_f = T.font(10, bold=True)
        pb_w = T.text_width(pag_badge, pb_f) + 14
        pbx1 = bx0 - 8
        pbx0 = pbx1 - pb_w
        d.rounded_rectangle([(pbx0, y + 10), (pbx1, y + 32)], radius=5, outline=T.BLACK, width=1)
        d.text((pbx0 + pb_w // 2, y + 21), pag_badge, font=pb_f, fill=T.BLACK, anchor="mm")

    d.line([(x + 14, y + 42), (x + w - 14, y + 42)], fill=T.BLACK, width=1)

    mid_x = x + w // 2
    hero_y = y + int(h * 0.44)

    h_name = str(data.get("home_team") or "HOME").upper()
    a_name = str(data.get("away_team") or "AWAY").upper()
    h_score = str(data.get("home_score") if data.get("home_score") is not None else "-")
    a_score = str(data.get("away_score") if data.get("away_score") is not None else "-")

    # Team names font
    tf = T.font(min(28, max(18, w // 28)), bold=True)
    d.text((mid_x - 130, hero_y - 18), _fit_text(h_name, int(w * 0.3), tf), font=tf, fill=T.BLACK, anchor="rm")
    d.text((mid_x + 130, hero_y - 18), _fit_text(a_name, int(w * 0.3), tf), font=tf, fill=T.BLACK, anchor="lm")

    # Stats under team names
    h_stat = str(data.get("home_stats") or "")
    a_stat = str(data.get("away_stats") or "")
    sf = T.font(11, bold=False)
    if h_stat:
        d.text((mid_x - 130, hero_y + 14), h_stat, font=sf, fill=T.BLACK, anchor="rm")
    if a_stat:
        d.text((mid_x + 130, hero_y + 14), a_stat, font=sf, fill=T.BLACK, anchor="lm")

    # Big Scores in center
    sc_f = T.font(min(62, max(44, int(h * 0.28))), bold=True)
    d.text((mid_x - 55, hero_y - 4), h_score, font=sc_f, fill=T.BLACK, anchor="mm")
    d.text((mid_x, hero_y - 8), "—", font=T.font(32, bold=True), fill=T.BLACK, anchor="mm")
    d.text((mid_x + 55, hero_y - 4), a_score, font=sc_f, fill=T.BLACK, anchor="mm")

    # Match highlights / scorers
    ev_h = str(data.get("events_home") or "")
    ev_a = str(data.get("events_away") or "")
    if ev_h or ev_a:
        div_y2 = y + h - 54
        d.line([(x + 20, div_y2), (x + w - 20, div_y2)], fill=T.BLACK, width=1)
        ef = T.font(12, bold=True)
        if ev_h:
            d.text((mid_x - 30, y + h - 26), _fit_text(ev_h, int(w * 0.42), ef), font=ef, fill=T.BLACK, anchor="rm")
        if ev_a:
            d.text((mid_x + 30, y + h - 26), _fit_text(ev_a, int(w * 0.42), ef), font=ef, fill=T.BLACK, anchor="lm")


DRAWERS = {
    "text": _draw_text,
    "number": _draw_text,          # same drawing, value formatted first
    "icon": _draw_icon,
    "line": _draw_line,
    "curve": _draw_curve,
    "dynamic_grid": _draw_dynamic_grid,
    "calendar_month": _draw_calendar_month,
    "calendar_agenda": _draw_calendar_agenda,
    "weather_forecast": _draw_weather_forecast,
    "flight_tracker": _draw_flight_tracker,
    "sports_racing": _draw_sports_racing,
    "sports_match": _draw_sports_match,
}


def element_text(el, vals, idx):
    """The string an element should display, after template resolution."""
    if el["type"] == "number":
        return _fmt_number(vals.get(idx, el.get("value", "")), el)
    if el["type"] == "text":
        got = vals.get(idx)
        base = str(got) if got is not None else str(el.get("value", "") or "")
        if not (isinstance(el.get("value"), str) and el.get("value").strip()):
            return f"{el.get('prefix', '')}{base}{el.get('suffix', '')}"
        return base
    return ""


def render_page(page, vals, *, clock="", label="", cat_label="", sub_label="", battery_pct=None, series=None,
                metrics=None, orientation=0, distance_m=3.0, display=None):
    """Draw one page. `vals` maps element index -> resolved template result."""
    img, d = T.new_canvas(orientation=orientation, display=display)
    for i, el in enumerate(page.get("elements", [])):
        drawer = DRAWERS.get(el.get("type"))
        if drawer is None:
            continue
        try:
            if el["type"] == "curve":
                drawer(img, d, el, "", (series or {}).get(i), display=display)
            elif el["type"] in ("text", "number"):
                got = []
                drawer(img, d, el, element_text(el, vals, i), got, distance_m=distance_m, display=display)
                if metrics is not None and got:
                    entry = {"i": i, **got[0]}
                    if el["type"] == "number":
                        raw = vals.get(i, el.get("value", ""))
                        try:
                            float(str(raw).strip())
                        except (TypeError, ValueError):
                            # "--" on the panel means exactly this and nothing
                            # else, so say so rather than let it look broken.
                            entry["not_a_number"] = str(raw)[:60]
                    metrics.append(entry)
            elif el["type"] in ("dynamic_grid", "calendar_month", "calendar_agenda", "weather_forecast", "flight_tracker", "sports_racing", "sports_match"):
                drawer(img, d, el, vals.get(i), display=display)
            else:
                drawer(img, d, el, element_text(el, vals, i), display=display)
        except Exception:
            # One bad element must never cost the whole page.
            continue
    T.footer(d, clock=clock, label=label, cat_label=cat_label, sub_label=sub_label,
             battery_pct=battery_pct, orientation=orientation, display=display)
    return img


def collect_templates(page):
    """Every templated string on a page, as {element_index: template}.

    Elements may carry a raw `value` template or a structured entity
    binding; binding.template_for resolves either to Jinja.
    """
    out = {}
    for i, el in enumerate(page.get("elements", [])):
        if el.get("type") in ("text", "number"):
            tpl = template_for(el)
            if tpl and "{{" in tpl:
                out[i] = tpl
        elif el.get("type") == "dynamic_grid":
            items = el.get("items", [])
            ents = [it.get("entity", "").strip() for it in items if isinstance(it, dict) and it.get("entity", "").strip()]
            if ents:
                ents_quoted = ", ".join(f"'{binding._quote(e)}'" for e in ents)
                tpl = (
                    "[{% for e in [" + ents_quoted + "] %}"
                    '{"entity": {{ e | to_json }}, '
                    '"state": {{ states(e) | to_json }}, '
                    '"name": {{ (state_attr(e, "friendly_name") or "") | to_json }}, '
                    '"changed": {{ (relative_time(states[e].last_changed) if (states[e] is defined and states[e] is not none and states[e].last_changed is defined) else "") | to_json }}}'
                    "{% if not loop.last %},{% endif %}{% endfor %}]"
                )
                out[i] = tpl
        elif el.get("type") == "weather_forecast":
            ent = str(el.get("entity") or "weather.forecast_home").strip()
            ent_q = f"'{binding._quote(ent)}'"
            tpl = (
                "{"
                f'"entity": {ent_q}, '
                f'"condition": {{{{ states({ent_q}) | to_json }}}}, '
                f'"temperature": {{{{ state_attr({ent_q}, "temperature") | to_json }}}}, '
                f'"unit": {{{{ (state_attr({ent_q}, "temperature_unit") or "°C") | to_json }}}}, '
                f'"humidity": {{{{ state_attr({ent_q}, "humidity") | to_json }}}}, '
                f'"wind_speed": {{{{ state_attr({ent_q}, "wind_speed") | to_json }}}}, '
                f'"wind_unit": {{{{ (state_attr({ent_q}, "wind_speed_unit") or "km/h") | to_json }}}}, '
                f'"attribution": {{{{ (state_attr({ent_q}, "attribution") or "") | to_json }}}}'
                "}"
            )
            out[i] = tpl
        elif el.get("type") in ("calendar_month", "calendar_agenda"):
            ent = str(el.get("entity") or "").strip()
            if ent:
                ent_q = f"'{binding._quote(ent)}'"
                tpl = (
                    "{"
                    f'"entity": {ent_q}, '
                    f'"state": {{{{ states({ent_q}) | to_json }}}}, '
                    f'"message": {{{{ (state_attr({ent_q}, "message") or "") | to_json }}}}, '
                    f'"start_time": {{{{ (state_attr({ent_q}, "start_time") or "") | to_json }}}}, '
                    f'"end_time": {{{{ (state_attr({ent_q}, "end_time") or "") | to_json }}}}'
                    "}"
                )
                out[i] = tpl
        elif el.get("type") in ("sports_racing", "sports_match"):
            ent = str(el.get("entity") or "").strip()
            if ent and ("." in ent):
                ent_q = f"'{binding._quote(ent)}'"
                tpl = (
                    "{"
                    f'"entity": {ent_q}, '
                    f'"state": {{{{ states({ent_q}) | to_json }}}}, '
                    f'"attributes": {{{{ states[{ent_q}].attributes | to_json if (states[{ent_q}] is defined and states[{ent_q}] is not none) else {{}} }}}}'
                    "}"
                )
                out[i] = tpl
    return out
