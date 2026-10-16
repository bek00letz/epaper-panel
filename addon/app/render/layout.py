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
import json
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
    try:
        v = float(str(raw).strip())
    except (TypeError, ValueError):
        return el.get("fallback") or "--"
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
        icon = it.get("icon") or "mdi:power"

        if has_resolved:
            res = info_by_ent.get(ent, {})
            state = str(res.get("state") or "").strip()
            friendly = res.get("name") or ""
            changed = res.get("changed") or ""

            is_active = (state and state not in ("unavailable", "unknown")) if filter_state in ("*", "any") else (state.lower() == filter_state)
            if is_active:
                active_items.append({
                    "entity": ent,
                    "name": name or friendly or ent.split(".")[-1].replace("_", " ").title(),
                    "icon": icon,
                    "state": state,
                    "changed": changed
                })
        else:
            active_items.append({
                "entity": ent,
                "name": name or (ent.split(".")[-1].replace("_", " ").title() if ent else "Active Spot"),
                "icon": icon,
                "state": "on",
                "changed": "25m ago"
            })

    if not configured_items and not active_items:
        active_items = [{
            "entity": "switch.sample_1",
            "name": "Sample Zone",
            "icon": "mdi:radiator",
            "state": "on",
            "changed": "30m ago"
        }]

    sec_mode = el.get("secondary_mode", "runtime")
    def format_sec(item):
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
    if n == 1:
        it = active_items[0]
        sec = format_sec(it)
        d.rounded_rectangle([(x, y), (x + w, y + h)], radius=12, outline=T.BLACK, width=2)
        if is_wide:
            isz = min(88, h - 36)
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
            isz = min(80, w // 3)
            mid_y = y + h // 2
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

    gap = 12
    if n == 2:
        if is_wide:
            cw = (w - gap) // 2
            cards = [(x, y, cw, h), (x + cw + gap, y, cw, h)]
            for it, (cx0, cy0, cw_i, ch_i) in zip(active_items, cards):
                cx1, cy1 = cx0 + cw_i, cy0 + ch_i
                d.rounded_rectangle([(cx0, cy0), (cx1, cy1)], radius=10, outline=T.BLACK, width=2)
                pw, ph = 34, 18
                d.rounded_rectangle([(cx1 - pw - 8, cy0 + 8), (cx1 - 8, cy0 + 8 + ph)], radius=4, fill=T.BLACK)
                d.text((cx1 - 8 - pw // 2, cy0 + 8 + ph // 2), "ON", font=T.font(10, bold=True), fill=T.WHITE, anchor="mm")
                isz = min(56, ch_i - 36)
                _draw_icon_glyph(d, it["icon"], cx0 + 16 + isz // 2, cy0 + ch_i // 2, isz)
                tx = cx0 + 16 + isz + 14
                sec = format_sec(it)
                name_f = T.font(24, bold=True)
                name_txt = _fit_text(it["name"], cw_i - isz - 64, name_f)
                d.text((tx, cy0 + ch_i // 2 - (12 if sec else 0)), name_txt, font=name_f, fill=T.BLACK, anchor="lm")
                if sec:
                    sec_f = T.font(15, bold=False)
                    d.text((tx, cy0 + ch_i // 2 + 16), sec, font=sec_f, fill=T.BLACK, anchor="lm")
        else:
            ch_card = (h - gap) // 2
            cards = [(x, y, w, ch_card), (x, y + ch_card + gap, w, ch_card)]
            for it, (cx0, cy0, cw_i, ch_i) in zip(active_items, cards):
                cx1, cy1 = cx0 + cw_i, cy0 + ch_i
                d.rounded_rectangle([(cx0, cy0), (cx1, cy1)], radius=10, outline=T.BLACK, width=2)
                pw, ph = 34, 18
                d.rounded_rectangle([(cx1 - pw - 8, cy0 + 8), (cx1 - 8, cy0 + 8 + ph)], radius=4, fill=T.BLACK)
                d.text((cx1 - 8 - pw // 2, cy0 + 8 + ph // 2), "ON", font=T.font(10, bold=True), fill=T.WHITE, anchor="mm")
                sec = format_sec(it)
                if ch_i > cw_i * 1.1:
                    isz = min(64, cw_i // 3)
                    mid_y = cy0 + ch_i // 2
                    _draw_icon_glyph(d, it["icon"], cx0 + cw_i // 2, mid_y - (40 if sec else 20), isz)
                    name_f = T.font(24, bold=True)
                    name_txt = _fit_text(it["name"], cw_i - 24, name_f)
                    d.text((cx0 + cw_i // 2, mid_y + (16 if sec else 20)), name_txt, font=name_f, fill=T.BLACK, anchor="mm")
                    if sec:
                        sec_f = T.font(16, bold=False)
                        d.text((cx0 + cw_i // 2, mid_y + 46), sec, font=sec_f, fill=T.BLACK, anchor="mm")
                else:
                    isz = min(50, ch_i - 28)
                    _draw_icon_glyph(d, it["icon"], cx0 + 16 + isz // 2, cy0 + ch_i // 2, isz)
                    tx = cx0 + 16 + isz + 12
                    name_f = T.font(20, bold=True)
                    name_txt = _fit_text(it["name"], cw_i - isz - 60, name_f)
                    d.text((tx, cy0 + ch_i // 2 - (10 if sec else 0)), name_txt, font=name_f, fill=T.BLACK, anchor="lm")
                    if sec:
                        sec_f = T.font(14, bold=False)
                        d.text((tx, cy0 + ch_i // 2 + 14), sec, font=sec_f, fill=T.BLACK, anchor="lm")
        return

    gap = 10
    if n == 3:
        if is_wide:
            cw = (w - 2 * gap) // 3
            cards = [(x + k * (cw + gap), y, cw, h) for k in range(3)]
            for it, (cx0, cy0, cw_i, ch_i) in zip(active_items, cards):
                cx1, cy1 = cx0 + cw_i, cy0 + ch_i
                d.rounded_rectangle([(cx0, cy0), (cx1, cy1)], radius=10, outline=T.BLACK, width=2)
                pw, ph = 30, 16
                d.rounded_rectangle([(cx1 - pw - 6, cy0 + 6), (cx1 - 6, cy0 + 6 + ph)], radius=4, fill=T.BLACK)
                d.text((cx1 - 6 - pw // 2, cy0 + 6 + ph // 2), "ON", font=T.font(9, bold=True), fill=T.WHITE, anchor="mm")
                isz = min(46, ch_i // 3)
                _draw_icon_glyph(d, it["icon"], cx0 + cw_i // 2, cy0 + ch_i * 0.35, isz)
                name_f = T.font(20, bold=True)
                name_txt = _fit_text(it["name"], cw_i - 16, name_f)
                d.text((cx0 + cw_i // 2, cy0 + ch_i * 0.68), name_txt, font=name_f, fill=T.BLACK, anchor="mm")
                sec = format_sec(it)
                if sec:
                    sec_f = T.font(14, bold=False)
                    d.text((cx0 + cw_i // 2, cy0 + ch_i * 0.86), sec, font=sec_f, fill=T.BLACK, anchor="mm")
        else:
            ch_card = (h - 2 * gap) // 3
            cards = [(x, y + k * (ch_card + gap), w, ch_card) for k in range(3)]
            for it, (cx0, cy0, cw_i, ch_i) in zip(active_items, cards):
                cx1, cy1 = cx0 + cw_i, cy0 + ch_i
                d.rounded_rectangle([(cx0, cy0), (cx1, cy1)], radius=10, outline=T.BLACK, width=2)
                pw, ph = 30, 16
                d.rounded_rectangle([(cx1 - pw - 6, cy0 + 6), (cx1 - 6, cy0 + 6 + ph)], radius=4, fill=T.BLACK)
                d.text((cx1 - 6 - pw // 2, cy0 + 6 + ph // 2), "ON", font=T.font(9, bold=True), fill=T.WHITE, anchor="mm")
                isz = min(42, ch_i - 20)
                _draw_icon_glyph(d, it["icon"], cx0 + 14 + isz // 2, cy0 + ch_i // 2, isz)
                tx = cx0 + 14 + isz + 10
                sec = format_sec(it)
                name_f = T.font(19, bold=True)
                name_txt = _fit_text(it["name"], cw_i - isz - 54, name_f)
                d.text((tx, cy0 + ch_i // 2 - (10 if sec else 0)), name_txt, font=name_f, fill=T.BLACK, anchor="lm")
                if sec:
                    sec_f = T.font(13, bold=False)
                    d.text((tx, cy0 + ch_i // 2 + 14), sec, font=sec_f, fill=T.BLACK, anchor="lm")
        return

    layout_4 = el.get("layout_4", "columns").lower()
    if n == 4 and layout_4 == "quadrant":
        gap = 10
        cw = (w - gap) // 2
        ch_card = (h - gap) // 2
        cards = [
            (x, y, cw, ch_card),
            (x + cw + gap, y, cw, ch_card),
            (x, y + ch_card + gap, cw, ch_card),
            (x + cw + gap, y + ch_card + gap, cw, ch_card)
        ]
        for it, (cx0, cy0, cw_i, ch_i) in zip(active_items, cards):
            cx1, cy1 = cx0 + cw_i, cy0 + ch_i
            d.rounded_rectangle([(cx0, cy0), (cx1, cy1)], radius=10, outline=T.BLACK, width=2)
            pw, ph = 30, 16
            d.rounded_rectangle([(cx1 - pw - 6, cy0 + 6), (cx1 - 6, cy0 + 6 + ph)], radius=4, fill=T.BLACK)
            d.text((cx1 - 6 - pw // 2, cy0 + 6 + ph // 2), "ON", font=T.font(9, bold=True), fill=T.WHITE, anchor="mm")
            sec = format_sec(it)

            if ch_i > cw_i * 1.3:
                # Tall card (e.g. portrait 2x2 grid)
                isz = min(48, int(cw_i * 0.45))
                mid_y = cy0 + ch_i // 2
                _draw_icon_glyph(d, it["icon"], cx0 + cw_i // 2, mid_y - (36 if sec else 20), isz)
                name_f = T.font(min(22, max(16, cw_i // 6)), bold=True)
                name_txt = _fit_text(it["name"], cw_i - 16, name_f)
                d.text((cx0 + cw_i // 2, mid_y + (14 if sec else 20)), name_txt, font=name_f, fill=T.BLACK, anchor="mm")
                if sec:
                    sec_f = T.font(13, bold=False)
                    d.text((cx0 + cw_i // 2, mid_y + 40), sec, font=sec_f, fill=T.BLACK, anchor="mm")
            else:
                # Wide card (e.g. landscape 2x2 grid)
                isz = min(40, ch_i - 20)
                _draw_icon_glyph(d, it["icon"], cx0 + 14 + isz // 2, cy0 + ch_i // 2, isz)
                tx = cx0 + 14 + isz + 10
                name_f = T.font(18, bold=True)
                name_txt = _fit_text(it["name"], cw_i - isz - 52, name_f)
                d.text((tx, cy0 + ch_i // 2 - (9 if sec else 0)), name_txt, font=name_f, fill=T.BLACK, anchor="lm")
                if sec:
                    sec_f = T.font(13, bold=False)
                    d.text((tx, cy0 + ch_i // 2 + 13), sec, font=sec_f, fill=T.BLACK, anchor="lm")
        return

    gap = 8
    if is_wide:
        cw = (w - (n - 1) * gap) // n
        cards = [(x + k * (cw + gap), y, cw, h) for k in range(n)]
        for it, (cx0, cy0, cw_i, ch_i) in zip(active_items, cards):
            cx1, cy1 = cx0 + cw_i, cy0 + ch_i
            d.rounded_rectangle([(cx0, cy0), (cx1, cy1)], radius=8, outline=T.BLACK, width=2)
            pw, ph = 28, 15
            d.rounded_rectangle([(cx1 - pw - 5, cy0 + 5), (cx1 - 5, cy0 + 5 + ph)], radius=3, fill=T.BLACK)
            d.text((cx1 - 5 - pw // 2, cy0 + 5 + ph // 2), "ON", font=T.font(9, bold=True), fill=T.WHITE, anchor="mm")
            isz = min(38, ch_i // 3)
            _draw_icon_glyph(d, it["icon"], cx0 + cw_i // 2, cy0 + ch_i * 0.35, isz)
            name_f = T.font(16, bold=True)
            name_txt = _fit_text(it["name"], cw_i - 12, name_f)
            d.text((cx0 + cw_i // 2, cy0 + ch_i * 0.68), name_txt, font=name_f, fill=T.BLACK, anchor="mm")
            sec = format_sec(it)
            if sec:
                sec_f = T.font(12, bold=False)
                d.text((cx0 + cw_i // 2, cy0 + ch_i * 0.86), sec, font=sec_f, fill=T.BLACK, anchor="mm")
    else:
        ch_card = (h - (n - 1) * gap) // n
        cards = [(x, y + k * (ch_card + gap), w, ch_card) for k in range(n)]
        for it, (cx0, cy0, cw_i, ch_i) in zip(active_items, cards):
            cx1, cy1 = cx0 + cw_i, cy0 + ch_i
            d.rounded_rectangle([(cx0, cy0), (cx1, cy1)], radius=8, outline=T.BLACK, width=2)
            pw, ph = 28, 15
            d.rounded_rectangle([(cx1 - pw - 5, cy0 + 5), (cx1 - 5, cy0 + 5 + ph)], radius=3, fill=T.BLACK)
            d.text((cx1 - 5 - pw // 2, cy0 + 5 + ph // 2), "ON", font=T.font(9, bold=True), fill=T.WHITE, anchor="mm")
            isz = min(34, ch_i - 14)
            _draw_icon_glyph(d, it["icon"], cx0 + 12 + isz // 2, cy0 + ch_i // 2, isz)
            tx = cx0 + 12 + isz + 8
            sec = format_sec(it)
            name_f = T.font(16, bold=True)
            name_txt = _fit_text(it["name"], cw_i - isz - 46, name_f)
            d.text((tx, cy0 + ch_i // 2 - (8 if sec else 0)), name_txt, font=name_f, fill=T.BLACK, anchor="lm")
            if sec:
                sec_f = T.font(12, bold=False)
                d.text((tx, cy0 + ch_i // 2 + 12), sec, font=sec_f, fill=T.BLACK, anchor="lm")


DRAWERS = {
    "text": _draw_text,
    "number": _draw_text,          # same drawing, value formatted first
    "icon": _draw_icon,
    "line": _draw_line,
    "curve": _draw_curve,
    "dynamic_grid": _draw_dynamic_grid,
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


def render_page(page, vals, *, clock="", label="", battery_pct=None, series=None,
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
            elif el["type"] == "dynamic_grid":
                drawer(img, d, el, vals.get(i), display=display)
            else:
                drawer(img, d, el, element_text(el, vals, i), display=display)
        except Exception:
            # One bad element must never cost the whole page.
            continue
    T.footer(d, clock=clock, label=label, battery_pct=battery_pct, orientation=orientation, display=display)
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
    return out
