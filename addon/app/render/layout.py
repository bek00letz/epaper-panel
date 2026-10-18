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

    try:
        fscale = max(0.6, min(1.8, float(el.get("font_scale") or el.get("scale") or 1.0)))
    except (ValueError, TypeError):
        fscale = 1.0

    # 1 Item: Hero Card
    if n == 1:
        it = active_items[0]
        sec = format_sec(it)
        hide_txt = (show_labels == "icons_only") or it.get("hide_name", False)
        d.rounded_rectangle([(x, y), (x + w, y + h)], radius=12, outline=T.BLACK, width=2)
        if is_wide:
            if hide_txt:
                isz = req_icon_sz or min(120, h - 32)
                _draw_icon_glyph(d, it["icon"], x + w // 2, y + h // 2, isz)
            else:
                isz = req_icon_sz or min(96, h - 32)
                _draw_icon_glyph(d, it["icon"], x + 24 + isz // 2, y + h // 2, isz)
                tx = x + 24 + isz + 24
                name_sz = max(18, min(52, int(36 * fscale)))
                name_f = T.font(name_sz, bold=True)
                name_txt = _fit_text(it["name"], w - isz - 210, name_f)
                d.text((tx, y + h // 2 - (int(16 * fscale) if sec else 0)), name_txt, font=name_f, fill=T.BLACK, anchor="lm")
                if sec:
                    sec_f = T.font(max(13, min(32, int(20 * fscale))), bold=False)
                    d.text((tx, y + h // 2 + int(20 * fscale)), sec, font=sec_f, fill=T.BLACK, anchor="lm")
            bw, bh = 90, 32
            bx0 = x + w - bw - 24
            by0 = y + (h - bh) // 2
            d.rounded_rectangle([(bx0, by0), (bx0 + bw, by0 + bh)], radius=6, fill=T.BLACK)
            d.text((bx0 + bw // 2, by0 + bh // 2), "ACTIVE", font=T.font(14, bold=True), fill=T.WHITE, anchor="mm")
        else:
            mid_y = y + h // 2
            if hide_txt:
                isz = req_icon_sz or min(108, w // 2)
                _draw_icon_glyph(d, it["icon"], x + w // 2, mid_y, isz)
            else:
                isz = req_icon_sz or min(84, w // 3)
                _draw_icon_glyph(d, it["icon"], x + w // 2, mid_y - (50 if sec else 30), isz)
                name_f = T.font(max(18, min(44, int(30 * fscale))), bold=True)
                name_txt = _fit_text(it["name"], w - 32, name_f)
                d.text((x + w // 2, mid_y + (20 if sec else 30)), name_txt, font=name_f, fill=T.BLACK, anchor="mm")
                if sec:
                    sec_f = T.font(max(13, min(28, int(19 * fscale))), bold=False)
                    d.text((x + w // 2, mid_y + 54), sec, font=sec_f, fill=T.BLACK, anchor="mm")
            pw, ph = 40, 20
            d.rounded_rectangle([(x + w - pw - 10, y + 10), (x + w - 10, y + 10 + ph)], radius=4, fill=T.BLACK)
            d.text((x + w - 10 - pw // 2, y + 10 + ph // 2), "ON", font=T.font(11, bold=True), fill=T.WHITE, anchor="mm")
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
        f_badge = T.font(max(9, min(14, int(11 * fscale))), bold=True)
        bw = max(32, T.text_width(st_txt, f_badge) + 12)
        ph = max(18, int(19 * fscale))
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
                isz = min(84, max(44, int(min(cw_i, ch_i) * 0.64)))
            _draw_icon_glyph(d, it["icon"], cx0 + cw_i // 2, cy0 + ch_i // 2, isz)
        else:
            # Icon + Labels
            if cw_i > ch_i * 1.25:
                # Horizontal orientation (wide card)
                max_avail = ch_i - 20
                if req_icon_sz:
                    isz = min(req_icon_sz, max_avail)
                else:
                    isz = min(60, max(38, ch_i - 28))
                _draw_icon_glyph(d, it["icon"], cx0 + 14 + isz // 2, cy0 + ch_i // 2, isz)
                tx = cx0 + 14 + isz + 12
                base_name_sz = min(26, max(17, cw_i // 11))
                name_f = T.font(max(13, min(36, int(base_name_sz * fscale))), bold=True)
                avail_tw = max(30, bx0 - tx - 6)
                name_txt = _fit_text(it["name"], avail_tw, name_f)
                d.text((tx, cy0 + ch_i // 2 - (int(11 * fscale) if sec else 0)), name_txt, font=name_f, fill=T.BLACK, anchor="lm")
                if sec:
                    base_sec_sz = min(16, max(12, cw_i // 16))
                    sec_f = T.font(max(10, min(24, int(base_sec_sz * fscale))), bold=False)
                    d.text((tx, cy0 + ch_i // 2 + int(14 * fscale)), sec, font=sec_f, fill=T.BLACK, anchor="lm")
            else:
                # Vertical orientation (square/tall card)
                max_avail = min(cw_i - 18, int(ch_i * 0.46))
                if req_icon_sz:
                    isz = min(req_icon_sz, max_avail)
                else:
                    isz = min(56, max(34, int(cw_i * 0.40)))

                mid_x = cx0 + cw_i // 2
                icon_y = cy0 + ch_i * (0.32 if sec else 0.38)
                _draw_icon_glyph(d, it["icon"], mid_x, icon_y, isz)
                base_name_sz = min(22, max(15, cw_i // 9))
                name_f = T.font(max(12, min(32, int(base_name_sz * fscale))), bold=True)
                name_txt = _fit_text(it["name"], cw_i - 14, name_f)
                d.text((mid_x, cy0 + ch_i * (0.67 if sec else 0.74)), name_txt, font=name_f, fill=T.BLACK, anchor="mm")
                if sec:
                    base_sec_sz = min(15, max(11, cw_i // 12))
                    sec_f = T.font(max(10, min(22, int(base_sec_sz * fscale))), bold=False)
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


def _font_scale(el) -> float:
    try:
        return max(0.6, min(1.8, float(el.get("font_scale") or el.get("scale") or 1.0)))
    except (ValueError, TypeError):
        return 1.0


def _s(px: int, scale: float, min_px: int = 9, max_px: int = 120) -> int:
    return max(min_px, min(max_px, int(round(px * scale))))


def _fit_font(text: str, max_w: int, target_sz: int, min_sz: int = 11, bold: bool = True):
    """Return the largest font <= target_sz (>= min_sz) that fits text within max_w."""
    sz = max(min_sz, int(target_sz))
    while sz > min_sz:
        f = T.font(sz, bold=bold)
        if T.text_width(str(text), f) <= max_w:
            return f
        sz -= 1
    return T.font(min_sz, bold=bold)


def _draw_calendar_month(img, d, el, raw_val, display=None):
    x, y, w, h = _clamp_box(el, 360, 240, display=display)
    fscale = _font_scale(el)
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
    header_h = min(36, max(22, int(h * 0.14))) if show_header else 0

    if show_header:
        month_name = calendar.month_name[month].upper()
        header_text = f"{month_name} {year}"
        header_sz = _s(min(24, max(15, int(header_h * 0.76))), fscale, 13, 36)
        header_f = _fit_font(header_text, w - 20, header_sz, min_sz=12, bold=True)
        d.text((x + w // 2, y + header_h // 2), header_text, font=header_f, fill=T.BLACK, anchor="mm")

    show_weekdays = el.get("show_weekdays") not in (False, "false", 0, "0")
    col_w = w / 7.0

    if show_weekdays:
        weekday_h = min(24, max(16, int(header_h * 0.65 if header_h else 20)))
        day_names_long = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"] if first_weekday == 0 else ["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"]
        day_names_short = ["M", "T", "W", "T", "F", "S", "S"] if first_weekday == 0 else ["S", "M", "T", "W", "T", "F", "S"]
        use_long = col_w >= 34
        day_labels = day_names_long if use_long else day_names_short
        wf_sz = _s(min(16, max(11, int(col_w * 0.34))), fscale, 9, 22)
        wf = T.font(wf_sz, bold=True)
        wy = y + header_h + 1
        for c_idx, label in enumerate(day_labels):
            cx = x + int((c_idx + 0.5) * col_w)
            d.text((cx, wy + weekday_h // 2), label, font=wf, fill=T.BLACK, anchor="mm")
        div_y = wy + weekday_h + 2
        d.line([(x + 6, div_y), (x + w - 6, div_y)], fill=T.BLACK, width=1)
        grid_y = div_y + 3
    else:
        grid_y = y + header_h + 4

    c = calendar.Calendar(firstweekday=first_weekday)
    weeks = c.monthdayscalendar(year, month)
    num_rows = len(weeks)
    grid_h = max(10, y + h - grid_y - 2)
    row_h = grid_h / float(num_rows)
    base_cell_sz = min(24, max(13, int(min(col_w * 0.52, row_h * 0.64))))
    cell_f_sz = _s(base_cell_sz, fscale, 11, int(min(col_w * 0.72, row_h * 0.82)))
    font_day = T.font(cell_f_sz, bold=True)
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
                rad = int(min(col_w * 0.44, row_h * 0.46))
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
    fscale = _font_scale(el)
    show_border = el.get("show_border") not in (False, "false", 0, "0")
    if show_border:
        d.rounded_rectangle([(x, y), (x + w, y + h)], radius=12, outline=T.BLACK, width=1)

    title = str(el.get("title") or "Upcoming Events").upper()
    hdr_f = T.font(_s(15, fscale, 11, 24), bold=True)
    d.text((x + 14, y + 16), title, font=hdr_f, fill=T.BLACK, anchor="lm")

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
    bf = T.font(_s(11, fscale, 9, 18), bold=True)
    bw = T.text_width(count_badge, bf) + 14
    d.rounded_rectangle([(x + w - bw - 14, y + 6), (x + w - 14, y + 26)], radius=4, fill=T.BLACK)
    d.text((x + w - 14 - bw // 2, y + 16), count_badge, font=bf, fill=T.WHITE, anchor="mm")
    d.line([(x + 10, y + 32), (x + w - 10, y + 32)], fill=T.BLACK, width=1)

    if not events:
        d.text((x + w // 2, y + h // 2), "No upcoming events scheduled", font=T.font(_s(16, fscale, 12, 26), bold=True), fill=T.BLACK, anchor="mm")
        return

    list_y = y + 36
    avail_h = (y + h - 8) - list_y
    max_items = max(1, min(6, int(el.get("max_events", 4))))
    show_sub = el.get("show_sub") not in (False, "false", 0, "0")
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

        df = T.font(_s(12, fscale, 9, 20), bold=True)
        pill_w = max(58, T.text_width(dt_str, df) + 14)
        pill_h = min(item_h - 6, max(20, _s(22, fscale, 18, 32)))
        py0 = iy_mid - pill_h // 2
        d.rounded_rectangle([(x + 12, py0), (x + 12 + pill_w, py0 + pill_h)], radius=4, fill=T.BLACK)
        d.text((x + 12 + pill_w // 2, iy_mid), dt_str, font=df, fill=T.WHITE, anchor="mm")

        # Title
        cal_badge = ev.get("cal_badge")
        title_x = x + 12 + pill_w + 12
        title_w = (x + w - 14) - title_x
        if cal_badge:
            cbf = T.font(_s(10, fscale, 8, 16), bold=True)
            cb_w = max(28, T.text_width(cal_badge, cbf) + 10)
            d.rounded_rectangle([(x + w - 14 - cb_w, iy_mid - 9), (x + w - 14, iy_mid + 9)], radius=3, outline=T.BLACK, width=1)
            d.text((x + w - 14 - cb_w // 2, iy_mid), cal_badge, font=cbf, fill=T.BLACK, anchor="mm")
            title_w -= (cb_w + 8)

        sub_txt = (ev.get("sub") or ev.get("location") or "") if show_sub else ""
        base_tf_sz = min(22, max(14, int(item_h * (0.40 if sub_txt else 0.52))))
        tf = T.font(_s(base_tf_sz, fscale, 12, 34), bold=True)
        summary = ev.get("summary") or ev.get("message") or "Untitled Event"
        title_txt = _fit_text(summary, title_w, tf)

        d.text((title_x, iy_mid - (int(item_h * 0.18) if sub_txt else 0)), title_txt, font=tf, fill=T.BLACK, anchor="lm")

        if sub_txt:
            base_sf_sz = min(16, max(11, int(item_h * 0.28)))
            sf = T.font(_s(base_sf_sz, fscale, 10, 24), bold=False)
            sub_fit = _fit_text(sub_txt, title_w, sf)
            d.text((title_x, iy_mid + int(item_h * 0.22)), sub_fit, font=sf, fill=T.BLACK, anchor="lm")

        if idx < len(display_events) - 1:
            div_y = iy0 + item_h - 1
            d.line([(x + 14, div_y), (x + w - 14, div_y)], fill=T.BLACK, width=1)


_WEATHER_ICON_MAP = {
    "clear-night": "mdi:weather-night",
    "clear_night": "mdi:weather-night",
    "cloudy": "mdi:weather-cloudy",
    "fog": "mdi:weather-fog",
    "hail": "mdi:weather-hail",
    "lightning": "mdi:weather-lightning",
    "lightning-rainy": "mdi:weather-lightning-rainy",
    "lightning_rainy": "mdi:weather-lightning-rainy",
    "partlycloudy": "mdi:weather-partly-cloudy",
    "pouring": "mdi:weather-pouring",
    "rainy": "mdi:weather-rainy",
    "snowy": "mdi:weather-snowy",
    "snowy-rainy": "mdi:weather-snowy-rainy",
    "snowy_rainy": "mdi:weather-snowy-rainy",
    "sunny": "mdi:weather-sunny",
    "windy": "mdi:weather-windy",
    "windy-variant": "mdi:weather-windy-variant",
    "windy_variant": "mdi:weather-windy-variant",
    "exceptional": "mdi:alert-circle-outline",
}

_WEATHER_LABEL_MAP = {
    "clear-night": "Clear Night",
    "clear_night": "Clear Night",
    "cloudy": "Cloudy",
    "fog": "Foggy",
    "hail": "Hail",
    "lightning": "Lightning",
    "lightning-rainy": "Thunderstorm",
    "lightning_rainy": "Thunderstorm",
    "partlycloudy": "Partly Cloudy",
    "pouring": "Heavy Rain",
    "rainy": "Rainy",
    "snowy": "Snowy",
    "snowy-rainy": "Sleet",
    "snowy_rainy": "Sleet",
    "sunny": "Sunny",
    "windy": "Windy",
    "windy-variant": "Windy & Cloudy",
    "windy_variant": "Windy & Cloudy",
    "exceptional": "Severe Alert",
}


def _draw_weather_forecast(img, d, el, raw_val, display=None):
    x, y, w, h = _clamp_box(el, 752, 235, display=display)
    fscale = _font_scale(el)
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
    cond_label = _WEATHER_LABEL_MAP.get(cond, cond.replace("-", " ").replace("_", " ").title())
    temp = data.get("temperature", "--")
    unit = str(data.get("unit") or "°C")
    humidity = data.get("humidity")
    wind = data.get("wind_speed")
    wind_unit = str(data.get("wind_unit") or "km/h")
    forecast = data.get("forecast") or []

    cur_icon = _WEATHER_ICON_MAP.get(cond, "mdi:weather-cloudy")
    show_details = el.get("show_details") not in (False, "false", 0, "0")
    try:
        max_f_days = max(1, min(6, int(el.get("forecast_days") or 4)))
    except (ValueError, TypeError):
        max_f_days = 4
    layout_mode = str(el.get("layout_mode") or "auto").lower()

    # Determine layout mode: split, stacked, hero_only, or forecast_only
    if layout_mode == "hero_only":
        hero_mid_y = y + h // 2 - (16 if show_details else 0)
        isz = min(110, max(56, int(h * 0.48)))
        _draw_icon_glyph(d, cur_icon, x + 32 + isz // 2, hero_mid_y, isz)
        tx = x + 32 + isz + 24
        avail_hero_w = max(80, (x + w - 24) - tx)
        temp_str = f"{temp}{unit}" if str(temp).endswith("°") or unit.startswith("°") else f"{temp}°"
        tf = _fit_font(temp_str, avail_hero_w, _s(min(76, max(36, int(h * 0.36))), fscale, 28, 110), min_sz=24, bold=True)
        d.text((tx, hero_mid_y - int(h * 0.08)), temp_str, font=tf, fill=T.BLACK, anchor="lm")
        cf = _fit_font(cond_label, avail_hero_w, _s(min(28, max(16, int(h * 0.13))), fscale, 14, 42), min_sz=13, bold=True)
        d.text((tx, hero_mid_y + int(h * 0.14)), cond_label, font=cf, fill=T.BLACK, anchor="lm")
        if show_details:
            chip_parts = []
            if humidity is not None:
                chip_parts.append(f"HUM {humidity}%")
            if wind is not None:
                chip_parts.append(f"WIND {wind} {wind_unit}")
            if forecast:
                today_f = forecast[0]
                th, tl = today_f.get("temperature"), today_f.get("templow")
                if th is not None and tl is not None:
                    chip_parts.append(f"H {th:.0f}° · L {tl:.0f}°")
            if chip_parts:
                chip_text = "   •   ".join(chip_parts)
                mf = _fit_font(chip_text, w - 48, _s(16, fscale, 12, 26), min_sz=11, bold=True)
                d.text((x + 24, y + h - 22), chip_text, font=mf, fill=T.BLACK, anchor="lm")
        return

    is_split = (layout_mode == "split") or (layout_mode == "auto" and ((w >= 480) or (w >= 340 and w >= h)))
    if layout_mode == "forecast_only":
        is_split = True

    if is_split:
        if layout_mode == "forecast_only":
            hero_w = 0
            fore_x = x + 8
            fore_w = w - 16
        else:
            hero_w = int(w * 0.42)
            fore_x = x + hero_w
            fore_w = w - hero_w

            hero_mid_y = y + int(h * (0.40 if show_details else 0.50))
            isz = min(84, max(48, int(h * 0.38)))
            _draw_icon_glyph(d, cur_icon, x + 18 + isz // 2, hero_mid_y, isz)

            tx = x + 18 + isz + 14
            avail_hero_w = max(60, fore_x - tx - 12)
            temp_str = f"{temp}{unit}" if str(temp).endswith("°") or unit.startswith("°") else f"{temp}°"
            target_tf_sz = _s(min(56, max(32, int(h * 0.27))), fscale, 24, 88)
            tf = _fit_font(temp_str, avail_hero_w, target_tf_sz, min_sz=22, bold=True)
            d.text((tx, hero_mid_y - int(h * 0.07)), temp_str, font=tf, fill=T.BLACK, anchor="lm")

            target_cf_sz = _s(min(22, max(15, int(h * 0.105))), fscale, 13, 34)
            cf = _fit_font(cond_label, avail_hero_w, target_cf_sz, min_sz=12, bold=True)
            d.text((tx, hero_mid_y + int(h * 0.13)), cond_label, font=cf, fill=T.BLACK, anchor="lm")

            if show_details:
                line1_parts = []
                line2_parts = []
                if humidity is not None:
                    line1_parts.append(f"HUM {humidity}%")
                if wind is not None:
                    line1_parts.append(f"WIND {wind} {wind_unit}")
                if forecast:
                    today_f = forecast[0]
                    th = today_f.get("temperature")
                    tl = today_f.get("templow")
                    if th is not None and tl is not None:
                        line2_parts.append(f"H {th:.0f}° / L {tl:.0f}°")
                    pop = today_f.get("precipitation_probability")
                    precip = today_f.get("precipitation")
                    if pop is not None and float(pop) > 0:
                        line2_parts.append(f"RAIN {float(pop):.0f}%")
                    elif precip is not None and float(precip) > 0:
                        line2_parts.append(f"RAIN {float(precip):.1f}mm")

                avail_chip_w = fore_x - x - 32
                combined = "  •  ".join(line1_parts + line2_parts)
                target_chip_sz = _s(15, fscale, 11, 24)
                if line2_parts and h >= 165:
                    # Two clean, large detail lines instead of 1 squeezed microscopic line
                    l1_txt = "   •   ".join(line1_parts) if line1_parts else "   •   ".join(line2_parts)
                    l2_txt = "   •   ".join(line2_parts) if line1_parts else ""
                    mf1 = _fit_font(l1_txt, avail_chip_w, target_chip_sz, min_sz=11, bold=True)
                    d.text((x + 18, y + h - (36 if l2_txt else 20)), l1_txt, font=mf1, fill=T.BLACK, anchor="lm")
                    if l2_txt:
                        mf2 = _fit_font(l2_txt, avail_chip_w, target_chip_sz, min_sz=11, bold=True)
                        d.text((x + 18, y + h - 16), l2_txt, font=mf2, fill=T.BLACK, anchor="lm")
                elif combined:
                    mf = _fit_font(combined, avail_chip_w, target_chip_sz, min_sz=10, bold=True)
                    d.text((x + 18, y + h - 20), combined, font=mf, fill=T.BLACK, anchor="lm")

            # Vertical divider
            d.line([(fore_x, y + 12), (fore_x, y + h - 12)], fill=T.BLACK, width=1)

        # Forecast strip
        display_forecast = forecast[1:1 + max_f_days] if len(forecast) > max_f_days else forecast[:max_f_days]
        n_days = len(display_forecast)
        if n_days > 0:
            day_w = fore_w / float(n_days)
            for i, fcast in enumerate(display_forecast):
                cx = fore_x + int((i + 0.5) * day_w)
                if i > 0:
                    div_x = fore_x + int(i * day_w)
                    d.line([(div_x, y + 18), (div_x, y + h - 18)], fill=T.BLACK, width=1)
                dt_raw = fcast.get("datetime")
                day_name = f"DAY {i+1}"
                if dt_raw:
                    try:
                        dt = datetime.fromisoformat(str(dt_raw).replace("Z", "+00:00"))
                        day_name = dt.strftime("%a").upper()
                    except Exception:
                        pass

                day_f = _fit_font(day_name, int(day_w - 8), _s(17, fscale, 12, 26), min_sz=11, bold=True)
                d.text((cx, y + int(h * 0.14)), day_name, font=day_f, fill=T.BLACK, anchor="mm")

                f_cond = str(fcast.get("condition") or "cloudy").lower()
                f_icon = _WEATHER_ICON_MAP.get(f_cond, "mdi:weather-cloudy")
                f_isz = min(54, max(34, int(min(day_w * 0.50, h * 0.25))))
                _draw_icon_glyph(d, f_icon, cx, y + int(h * 0.45), f_isz)

                hi = fcast.get("temperature")
                lo = fcast.get("templow")
                hl_str = f"{hi:.0f}°/{lo:.0f}°" if (hi is not None and lo is not None) else f"{hi or lo or '--'}°"
                hl_f = _fit_font(hl_str, int(day_w - 6), _s(19, fscale, 13, 30), min_sz=12, bold=True)
                d.text((cx, y + int(h * 0.76)), hl_str, font=hl_f, fill=T.BLACK, anchor="mm")

                pop = fcast.get("precipitation_probability")
                precip = fcast.get("precipitation")
                rain_str = ""
                if pop is not None and float(pop) > 0:
                    rain_str = f"{float(pop):.0f}% rain"
                elif precip is not None and float(precip) > 0:
                    rain_str = f"{float(precip):.1f} mm"
                if rain_str:
                    rf = _fit_font(rain_str, int(day_w - 6), _s(14, fscale, 10, 22), min_sz=10, bold=True)
                    d.text((cx, y + int(h * 0.90)), rain_str, font=rf, fill=T.BLACK, anchor="mm")
        else:
            d.text((fore_x + fore_w // 2, y + h // 2), "No forecast data", font=T.font(_s(16, fscale, 12, 24), bold=True), fill=T.BLACK, anchor="mm")
    else:
        # Stacked layout (portrait or narrow cards)
        hero_h = int(h * 0.34)
        mid_y = y + hero_h // 2 - (10 if show_details else 0)
        isz = min(64, max(40, int(hero_h * 0.55)))
        _draw_icon_glyph(d, cur_icon, x + 20 + isz // 2, mid_y, isz)
        tx = x + 20 + isz + 16
        temp_str = f"{temp}{unit}" if str(temp).endswith("°") or unit.startswith("°") else f"{temp}°"
        tf = _fit_font(temp_str, w - (tx - x) - 16, _s(min(46, max(28, int(w * 0.12))), fscale, 22, 72), min_sz=20, bold=True)
        d.text((tx, mid_y - 12), temp_str, font=tf, fill=T.BLACK, anchor="lm")
        cf = _fit_font(cond_label, w - (tx - x) - 16, _s(18, fscale, 13, 28), min_sz=12, bold=True)
        d.text((tx, mid_y + 18), cond_label, font=cf, fill=T.BLACK, anchor="lm")

        if show_details:
            parts = []
            if humidity is not None:
                parts.append(f"HUM {humidity}%")
            if wind is not None:
                parts.append(f"WIND {wind} {wind_unit}")
            if parts:
                mf = _fit_font("   •   ".join(parts), w - 36, _s(14, fscale, 10, 22), min_sz=10, bold=True)
                d.text((x + 20, y + hero_h - 14), "   •   ".join(parts), font=mf, fill=T.BLACK, anchor="lm")

        d.line([(x + 10, y + hero_h), (x + w - 10, y + hero_h)], fill=T.BLACK, width=1)

        display_forecast = forecast[1:1 + max_f_days] if len(forecast) > max_f_days else forecast[:max_f_days]
        n_days = min(max_f_days, len(display_forecast))
        if n_days > 0:
            row_h = (h - hero_h - 12) / float(n_days)
            for i, fcast in enumerate(display_forecast[:n_days]):
                ry = y + hero_h + 6 + int(i * row_h)
                ry_mid = ry + int(row_h * 0.5)
                dt_raw = fcast.get("datetime")
                day_name = f"DAY {i+1}"
                if dt_raw:
                    try:
                        dt = datetime.fromisoformat(str(dt_raw).replace("Z", "+00:00"))
                        day_name = dt.strftime("%A").upper()
                    except Exception:
                        pass
                row_f = T.font(_s(16, fscale, 12, 26), bold=True)
                d.text((x + 20, ry_mid), day_name, font=row_f, fill=T.BLACK, anchor="lm")
                f_cond = str(fcast.get("condition") or "cloudy").lower()
                _draw_icon_glyph(d, _WEATHER_ICON_MAP.get(f_cond, "mdi:weather-cloudy"), x + w // 2, ry_mid, min(38, max(26, int(row_h * 0.72))))
                hi = fcast.get("temperature")
                lo = fcast.get("templow")
                hl_str = f"{hi:.0f}° / {lo:.0f}°" if (hi is not None and lo is not None) else f"{hi or lo or '--'}°"
                d.text((x + w - 20, ry_mid), hl_str, font=row_f, fill=T.BLACK, anchor="rm")
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
    cf = T.font(10, bold=True)
    d.text((cx, cy - r_scope + 9), "N", font=cf, fill=T.BLACK, anchor="mm")
    d.text((cx + r_scope - 9, cy), "E", font=cf, fill=T.BLACK, anchor="mm")
    d.text((cx, cy + r_scope - 9), "S", font=cf, fill=T.BLACK, anchor="mm")
    d.text((cx - r_scope + 9, cy), "W", font=cf, fill=T.BLACK, anchor="mm")

    # Range scale label
    rf = T.font(9, bold=True)
    d.text((cx + mid_r + 3, cy - 6), f"{int(max_r_km // 2)}k", font=rf, fill=T.BLACK, anchor="lm")

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
            d.text((lx, py - 6), cs, font=T.font(10, bold=True), fill=T.BLACK, anchor=anchor)


def _draw_flight_tracker(img, d, el, raw_val, display=None):
    x, y, w, h = _clamp_box(el, 752, 235, display=display)
    fscale = _font_scale(el)
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
    loc_name = str(el.get("location_name") or el.get("name") or "").strip()
    show_sub_metrics = el.get("show_sub_metrics") not in (False, "false", 0, "0")

    if not aircraft_list:
        mid_x = x + w // 2
        mid_y = y + h // 2
        _draw_icon_glyph(d, "mdi:radar", mid_x, mid_y - 26, 56)
        d.text((mid_x, mid_y + 16), "AIRSPACE CLEAR", font=T.font(_s(22, fscale, 16, 36), bold=True), fill=T.BLACK, anchor="mm")
        loc_str = f" overhead {loc_name}" if loc_name else " overhead"
        d.text((mid_x, mid_y + 42), f"No aircraft{loc_str} within {radius} km", font=T.font(_s(15, fscale, 11, 24), bold=False), fill=T.BLACK, anchor="mm")
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
        hdr_title = f"{loc_name.upper()} RADAR · {radius} KM" if loc_name else f"AIRSPACE RADAR · {radius} KM"
        rf_hdr = T.font(_s(14, fscale, 10, 22), bold=True)
        d.text((x + 16, y + 18), hdr_title, font=rf_hdr, fill=T.BLACK, anchor="lm")
        target_str = f"TARGET: {callsign} ({dist_km:.1f} KM {bearing})"
        if sub_total > 1:
            target_str = f"[{sub_idx + 1}/{sub_total}] {target_str}"
        d.text((x + w - 16, y + 18), target_str, font=rf_hdr, fill=T.BLACK, anchor="rm")
        return

    loc_suffix = f" · {loc_name}" if loc_name else ""

    if style == "split" and w >= 480:
        # Split mode: Scope on left, telemetry card on right
        scope_w = min(h - 10, int(w * 0.36))
        _draw_radar_scope(d, x + 8, y + 8, scope_w, h - 16, radius, aircraft_list, tracked_cs=callsign)
        d.line([(x + scope_w + 14, y + 14), (x + scope_w + 14, y + h - 14)], fill=T.BLACK, width=1)

        tx0 = x + scope_w + 26
        tw = w - scope_w - 38
        top_y = y + 14

        dist_badge = f"{dist_km:.1f} KM {bearing}{loc_suffix}" if dist_km > 0 else (f"OVERHEAD {loc_name}" if loc_name else "OVERHEAD")
        bf = T.font(_s(12, fscale, 9, 18), bold=True)
        bw = T.text_width(dist_badge, bf) + 16
        bh = 26
        bx1 = x + w - 16
        bx0 = bx1 - bw
        d.rounded_rectangle([(bx0, top_y + 4), (bx1, top_y + 4 + bh)], radius=5, fill=T.BLACK)
        d.text((bx0 + bw // 2, top_y + 4 + bh // 2), dist_badge, font=bf, fill=T.WHITE, anchor="mm")

        avail_cs_w = bx0 - tx0 - 10
        if sub_total > 1:
            pag_str = f"{sub_idx + 1}/{sub_total}"
            pb_w = T.text_width(pag_str, bf) + 12
            pbx1 = bx0 - 6
            pbx0 = pbx1 - pb_w
            avail_cs_w = pbx0 - tx0 - 10
            d.rounded_rectangle([(pbx0, top_y + 4), (pbx1, top_y + 4 + bh)], radius=5, outline=T.BLACK, width=1)
            d.text((pbx0 + pb_w // 2, top_y + 4 + bh // 2), pag_str, font=bf, fill=T.BLACK, anchor="mm")

        cs_f = _fit_font(callsign, max(80, avail_cs_w), _s(34, fscale, 20, 52), min_sz=18, bold=True)
        d.text((tx0, top_y + 16), callsign, font=cs_f, fill=T.BLACK, anchor="lm")

        sub_f = T.font(_s(15, fscale, 11, 22), bold=False)
        sub_title = _fit_text(country, max(60, tw - 16), sub_f)
        d.text((tx0 + 2, top_y + 44), sub_title, font=sub_f, fill=T.BLACK, anchor="lm")

        div_y = y + 78
        d.line([(tx0, div_y), (x + w - 16, div_y)], fill=T.BLACK, width=1)

        cols_y = div_y + 6
        cols_h = y + h - cols_y - 8
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
            lbl_f = T.font(_s(12, fscale, 9, 18), bold=True)
            main_f = _fit_font(val_main, int(cw - 12), _s(23, fscale, 15, 38), min_sz=14, bold=True)
            d.text((mid_col_x, cols_y + int(cols_h * 0.16)), label, font=lbl_f, fill=T.BLACK, anchor="mm")
            d.text((mid_col_x, cols_y + int(cols_h * (0.52 if show_sub_metrics else 0.60))), val_main, font=main_f, fill=T.BLACK, anchor="mm")
            if show_sub_metrics:
                sub_mf = _fit_font(val_sub, int(cw - 12), _s(14, fscale, 10, 22), min_sz=10, bold=False)
                d.text((mid_col_x, cols_y + int(cols_h * 0.84)), val_sub, font=sub_mf, fill=T.BLACK, anchor="mm")
        return

    # Style: "card" (Full-Width Telemetry Card with bold, legible typography)
    top_y = y + 14
    _draw_icon_glyph(d, "mdi:airplane", x + 32, top_y + 22, 48)

    dist_badge = f"{dist_km:.1f} KM {bearing}{loc_suffix}" if dist_km > 0 else (f"OVERHEAD {loc_name}" if loc_name else "OVERHEAD")
    bf = T.font(_s(13, fscale, 10, 20), bold=True)
    bw = T.text_width(dist_badge, bf) + 18
    bh = 28
    bx1 = x + w - 20
    bx0 = bx1 - bw
    d.rounded_rectangle([(bx0, top_y + 4), (bx1, top_y + 4 + bh)], radius=6, fill=T.BLACK)
    d.text((bx0 + bw // 2, top_y + 4 + bh // 2), dist_badge, font=bf, fill=T.WHITE, anchor="mm")

    if sub_total > 1:
        more_txt = f"FLIGHT {sub_idx + 1} OF {sub_total}"
        mf = T.font(_s(12, fscale, 9, 18), bold=True)
        d.text((bx1, top_y + 44), more_txt, font=mf, fill=T.BLACK, anchor="rm")

    cs_f = _fit_font(callsign, max(100, bx0 - (x + 68) - 12), _s(38, fscale, 24, 58), min_sz=20, bold=True)
    d.text((x + 68, top_y + 16), callsign, font=cs_f, fill=T.BLACK, anchor="lm")

    sub_f = T.font(_s(16, fscale, 12, 24), bold=False)
    sub_title = _fit_text(country, max(80, bx0 - (x + 70) - 20), sub_f)
    d.text((x + 70, top_y + 44), sub_title, font=sub_f, fill=T.BLACK, anchor="lm")

    div_y = y + 78
    d.line([(x + 16, div_y), (x + w - 16, div_y)], fill=T.BLACK, width=1)

    cols_y = div_y + 6
    cols_h = y + h - cols_y - 8
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

        lbl_f = _fit_font(label, int(cw - 10), _s(12, fscale, 9, 18), min_sz=9, bold=True)
        main_f = _fit_font(val_main, int(cw - 12), _s(26, fscale, 16, 44), min_sz=15, bold=True)
        d.text((mid_col_x, cols_y + int(cols_h * 0.16)), label, font=lbl_f, fill=T.BLACK, anchor="mm")
        d.text((mid_col_x, cols_y + int(cols_h * (0.52 if show_sub_metrics else 0.60))), val_main, font=main_f, fill=T.BLACK, anchor="mm")
        if show_sub_metrics:
            sub_mf = _fit_font(val_sub, int(cw - 12), _s(15, fscale, 11, 24), min_sz=10, bold=False)
            d.text((mid_col_x, cols_y + int(cols_h * 0.84)), val_sub, font=sub_mf, fill=T.BLACK, anchor="mm")


def _draw_sports_racing(img, d, el, raw_val, display=None):
    x, y, w, h = _clamp_box(el, 752, 235, display=display)
    fscale = _font_scale(el)
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
    default_name = "Formula E World Championship" if series == "FE" else "Formula 1 Grand Prix"
    event_name = str(data.get("event_name") or default_name).upper()
    status = str(data.get("status") or "IN").upper()
    lap = data.get("lap")
    total_laps = data.get("total_laps")
    standings = data.get("standings") or []
    show_teams = el.get("show_teams") not in (False, "false", 0, "0")
    try:
        max_drv = max(4, min(10, int(el.get("max_drivers") or 10)))
    except (ValueError, TypeError):
        max_drv = 10

    # Status badge at top right
    status_txt = f"LAP {lap}/{total_laps}" if (lap and total_laps) else (data.get("clock") or status)
    bf = T.font(_s(13, fscale, 10, 20), bold=True)
    bw = T.text_width(status_txt, bf) + 16
    bx1 = x + w - 16
    bx0 = bx1 - bw
    d.rounded_rectangle([(bx0, y + 8), (bx1, y + 34)], radius=5, fill=T.BLACK)
    d.text((bx0 + bw // 2, y + 21), status_txt, font=bf, fill=T.WHITE, anchor="mm")

    # Header
    hdr_icon = "mdi:car-electric" if series == "FE" else "mdi:flag-checkered"
    _draw_icon_glyph(d, hdr_icon, x + 24, y + 21, 26)
    hf = T.font(_s(16, fscale, 12, 24), bold=True)
    header_txt = _fit_text(f"{series} · {event_name}", max(80, bx0 - (x + 46) - 10), hf)
    d.text((x + 46, y + 21), header_txt, font=hf, fill=T.BLACK, anchor="lm")

    d.line([(x + 14, y + 42), (x + w - 14, y + 42)], fill=T.BLACK, width=1)

    if not standings:
        # Pre-race or schedule view
        mid_x = x + w // 2
        mid_y = y + h // 2
        mid_icon = "mdi:car-electric" if series == "FE" else "mdi:racing-helmet"
        _draw_icon_glyph(d, mid_icon, mid_x, mid_y - 22, 50)
        circ = data.get("circuit") or ("ePrix Circuit" if series == "FE" else "Grand Prix Circuit")
        d.text((mid_x, mid_y + 18), circ, font=T.font(_s(20, fscale, 14, 32), bold=True), fill=T.BLACK, anchor="mm")
        detail = data.get("detail") or "Session scheduled soon"
        d.text((mid_x, mid_y + 44), detail, font=T.font(_s(15, fscale, 11, 24), bold=False), fill=T.BLACK, anchor="mm")
        return

    # Leaderboard (2 columns)
    col_w = (w - 30) // 2
    mid_div = x + col_w + 15
    d.line([(mid_div, y + 46), (mid_div, y + h - 10)], fill=T.BLACK, width=1)

    display_drivers = standings[:max_drv]
    n_rows = max(1, math.ceil(len(display_drivers) / 2))
    row_h = (h - 52) // n_rows

    pos_f = T.font(_s(min(15, max(11, int(row_h * 0.42))), fscale, 10, 22), bold=True)
    drv_f = T.font(_s(min(19, max(13, int(row_h * 0.54))), fscale, 12, 28), bold=True)
    team_f = T.font(_s(min(15, max(11, int(row_h * 0.42))), fscale, 10, 22), bold=False)
    gap_f = T.font(_s(min(15, max(11, int(row_h * 0.44))), fscale, 10, 24), bold=True)
    tyre_f = T.font(_s(11, fscale, 9, 16), bold=True)

    for idx, drv in enumerate(display_drivers):
        is_right = idx >= n_rows
        cx0 = (x + 15) if not is_right else (mid_div + 15)
        r_idx = idx if not is_right else (idx - n_rows)
        ry = y + 46 + r_idx * row_h
        ry_mid = ry + row_h // 2
        rw = (mid_div - 14) if not is_right else (x + w - 15)

        pos_str = f"P{drv.get('pos', idx + 1)}"
        code = str(drv.get("driver") or drv.get("code") or drv.get("name") or "DRV")[:3].upper()
        team = str(drv.get("team") or drv.get("constructor") or "") if show_teams else ""
        gap = str(drv.get("gap") or drv.get("interval") or "")
        tyre = str(drv.get("tyre") or "")[:1].upper()

        d.text((cx0 + 2, ry_mid), pos_str, font=pos_f, fill=T.BLACK, anchor="lm")
        pos_w = max(32, T.text_width("P10", pos_f) + 6)
        d.text((cx0 + pos_w, ry_mid), code, font=drv_f, fill=T.BLACK, anchor="lm")

        off_x = cx0 + pos_w + max(44, T.text_width("VER", drv_f) + 8)
        if tyre in ("S", "M", "H", "I", "W"):
            d.rounded_rectangle([(off_x, ry_mid - 8), (off_x + 16, ry_mid + 8)], radius=3, outline=T.BLACK, width=1)
            d.text((off_x + 8, ry_mid), tyre, font=tyre_f, fill=T.BLACK, anchor="mm")
            off_x += 22

        if team:
            avail_tw = max(24, rw - off_x - (T.text_width(gap, gap_f) + 10 if gap else 0))
            team_fit = _fit_text(team, avail_tw, team_f)
            d.text((off_x, ry_mid), team_fit, font=team_f, fill=T.BLACK, anchor="lm")

        if gap:
            d.text((rw, ry_mid), gap, font=gap_f, fill=T.BLACK, anchor="rm")

        if r_idx < n_rows - 1:
            d.line([(cx0, ry + row_h - 1), (rw, ry + row_h - 1)], fill=T.BLACK, width=1)


def _draw_sports_match(img, d, el, raw_val, display=None):
    x, y, w, h = _clamp_box(el, 752, 235, display=display)
    fscale = _font_scale(el)
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
    show_stats = el.get("show_stats") not in (False, "false", 0, "0")
    show_scorers = el.get("show_scorers") not in (False, "false", 0, "0")

    # Clock / Status badge
    bf = T.font(_s(13, fscale, 10, 20), bold=True)
    bw = T.text_width(clock, bf) + 16
    bx1 = x + w - 16
    bx0 = bx1 - bw
    d.rounded_rectangle([(bx0, y + 8), (bx1, y + 34)], radius=5, fill=T.BLACK)
    d.text((bx0 + bw // 2, y + 21), clock, font=bf, fill=T.WHITE, anchor="mm")

    hdr_max_x = bx0 - 10
    # Sub-item pagination badge (e.g. [ 2 / 5 ])
    if sub_total > 1:
        pag_badge = f"{sub_idx + 1}/{sub_total}"
        pb_f = T.font(_s(12, fscale, 9, 18), bold=True)
        pb_w = T.text_width(pag_badge, pb_f) + 14
        pbx1 = bx0 - 8
        pbx0 = pbx1 - pb_w
        hdr_max_x = pbx0 - 10
        d.rounded_rectangle([(pbx0, y + 8), (pbx1, y + 34)], radius=5, outline=T.BLACK, width=1)
        d.text((pbx0 + pb_w // 2, y + 21), pag_badge, font=pb_f, fill=T.BLACK, anchor="mm")

    hf = T.font(_s(16, fscale, 12, 24), bold=True)
    d.text((x + 20, y + 21), _fit_text(header_title, max(80, hdr_max_x - (x + 20)), hf), font=hf, fill=T.BLACK, anchor="lm")

    d.line([(x + 14, y + 42), (x + w - 14, y + 42)], fill=T.BLACK, width=1)

    ev_h = str(data.get("events_home") or "") if show_scorers else ""
    ev_a = str(data.get("events_away") or "") if show_scorers else ""
    has_scorers = bool(ev_h or ev_a)

    mid_x = x + w // 2
    hero_y = y + int(h * (0.46 if has_scorers else 0.56))

    h_name = str(data.get("home_team") or "HOME").upper()
    a_name = str(data.get("away_team") or "AWAY").upper()
    h_score = str(data.get("home_score") if data.get("home_score") is not None else "-")
    a_score = str(data.get("away_score") if data.get("away_score") is not None else "-")

    score_gap = int(min(136, max(96, w * 0.17)))
    team_avail_w = max(80, (mid_x - score_gap) - (x + 20))
    target_tf_sz = _s(min(36, max(22, w // 21)), fscale, 18, 54)
    tf_h = _fit_font(h_name, team_avail_w, target_tf_sz, min_sz=16, bold=True)
    tf_a = _fit_font(a_name, team_avail_w, target_tf_sz, min_sz=16, bold=True)

    h_stat = str(data.get("home_stats") or "") if show_stats else ""
    a_stat = str(data.get("away_stats") or "") if show_stats else ""
    team_y_off = -16 if (h_stat or a_stat) else -2

    d.text((mid_x - score_gap, hero_y + team_y_off), _fit_text(h_name, team_avail_w, tf_h), font=tf_h, fill=T.BLACK, anchor="rm")
    d.text((mid_x + score_gap, hero_y + team_y_off), _fit_text(a_name, team_avail_w, tf_a), font=tf_a, fill=T.BLACK, anchor="lm")

    # Stats under team names
    sf = T.font(_s(14, fscale, 10, 22), bold=False)
    if h_stat:
        d.text((mid_x - score_gap, hero_y + 18), _fit_text(h_stat, team_avail_w, sf), font=sf, fill=T.BLACK, anchor="rm")
    if a_stat:
        d.text((mid_x + score_gap, hero_y + 18), _fit_text(a_stat, team_avail_w, sf), font=sf, fill=T.BLACK, anchor="lm")

    # Big Scores in center
    sc_f = T.font(_s(min(70, max(46, int(h * 0.32))), fscale, 36, 96), bold=True)
    d.text((mid_x - int(score_gap * 0.44), hero_y - 4), h_score, font=sc_f, fill=T.BLACK, anchor="mm")
    d.text((mid_x, hero_y - 8), "—", font=T.font(_s(34, fscale, 22, 48), bold=True), fill=T.BLACK, anchor="mm")
    d.text((mid_x + int(score_gap * 0.44), hero_y - 4), a_score, font=sc_f, fill=T.BLACK, anchor="mm")

    # Match highlights / scorers
    if has_scorers:
        div_y2 = y + h - 48
        d.line([(x + 20, div_y2), (x + w - 20, div_y2)], fill=T.BLACK, width=1)
        ef = T.font(_s(15, fscale, 11, 24), bold=True)
        if ev_h:
            d.text((mid_x - 24, y + h - 22), _fit_text(ev_h, int(w * 0.44), ef), font=ef, fill=T.BLACK, anchor="rm")
        if ev_a:
            d.text((mid_x + 24, y + h - 22), _fit_text(ev_a, int(w * 0.44), ef), font=ef, fill=T.BLACK, anchor="lm")



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
