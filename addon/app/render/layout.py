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
from datetime import datetime, date, timedelta
import json
import math
import re
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from . import theme as T
from . import binding
from . import energy
from . import media
from . import needs_you
from . import sport
from . import race
from . import sun
from . import clock
from . import words
from .words import say
from . import clocktime
from . import countdown
from . import todo
from . import units
from . import worldclock
from . import states as state_words
from . import icons
from . import vector
from .binding import template_for
from .qr import encode_qr_matrix

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
    """Largest font size at which the glyph's ink fits the box (the old font path, icons.FROM_FONT)."""
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


# Where the old icon font's baseline sat in its square: it measured an icon from the top of its ink
# down to the lower of its ink and this line, and across by the whole square (_fit_glyph).
_FONT_BASELINE = 0.875


def _fit_outline(record, box_w, box_h, most=200):
    """Largest size at which an icon fits the box, measured as the old font measured it: its whole
    square across, its ink top to bottom (down to the font's baseline at least). So an icon is the
    size it always was in a box drawn before icons came from outlines."""
    ink = vector.ink_box(record)
    if not ink:
        return 8
    vx, vy, vw, vh = vector.parts(record)[2]
    unit = max(vw, vh)
    off = (unit - vh) / 2                                   # a wide view box sits in the middle
    top = (ink[1] - vy + off) / unit
    bottom = max((ink[3] - vy + off) / unit, _FONT_BASELINE)
    tall = max(1e-6, bottom - top)
    return max(8, min(most, int(box_w), int(box_h / tall)))


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
    bold = el.get("bold") not in (False, "false", 0, "0") and str(el.get("weight", "bold")).lower() != "regular"
    family = str(el.get("font") or "lato").lower()
    invert = el.get("invert") in (True, "true", 1, "1")
    pill = el.get("pill") in (True, "true", 1, "1")
    has_bg = invert or pill

    pad_x = 12 if has_bg else 0
    inner_w = max(8, w - pad_x * 2)
    inner_h = h - (8 if has_bg else 0)
    wrap = el.get("wrap") in (True, "true", 1, "1")
    # A size of its own, or as large as fits the box: at most `max_size` (what a preset gives a word
    # that's longer in some languages, "Geschlossen" where English says "Closed").
    most = max(8, min(360, int(el.get("max_size") or 200)))
    if el.get("size"):
        size = max(8, min(360, int(el["size"])))
    elif wrap:
        size = T.fit_wrapped(text, inner_w, inner_h, most, bold=bold, family=family)
    else:
        size = T.fit_size(text, inner_w, inner_h, most, bold=bold, family=family)
    f = T.font(size, bold=bold, family=family, text=text)
    asc, desc = f.getmetrics()
    lines = T.wrap_lines(text, f, inner_w) if wrap else [text]
    if metrics is not None:
        mm, verdict = legibility(size, distance_m=distance_m, display=display)
        t = text.strip()
        too_wide = any(T.text_width(l, f) > inner_w for l in lines)
        metrics.append({"size": size, "mm": mm, "verdict": verdict, "lines": len(lines),
                        "overflow": too_wide or (wrap and len(lines) * (asc + desc) > inner_h),
                        "collection": t.startswith(("[", "{")) and t.endswith(("]", "}"))})

    if has_bg:
        try:
            rad = max(0, min(h // 2, int(el.get("radius", 10))))
        except (ValueError, TypeError):
            rad = min(14, h // 2)
        if invert:
            d.rounded_rectangle([(x, y), (x + w, y + h)], radius=rad, fill=T.BLACK)
        else:
            d.rounded_rectangle([(x, y), (x + w, y + h)], radius=rad, fill=T.WHITE, outline=T.BLACK, width=2)

    fg = T.WHITE if invert else T.BLACK
    ax = _anchor_x(align, x + pad_x, inner_w)
    if wrap:
        # Lines stacked and centred as a block, each aligned like a single line.
        lh = asc + desc
        top = y + (h - lh * len(lines)) // 2
        anchor = {"left": "la", "center": "ma", "right": "ra"}.get(align, "la")
        for n, line in enumerate(lines):
            d.text((ax, top + n * lh), line, font=f, fill=fg, anchor=anchor)
        return
    anchor = {"left": "lm", "center": "mm", "right": "rm"}.get(align, "lm")
    d.text((ax, y + h // 2), text, font=f, fill=fg, anchor=anchor)


@lru_cache(maxsize=256)
def _render_mdi_1bit_crop(ch: str, size: int):
    """Render an MDI glyph at `size` and return its tight 1-bit cropped mask ('L', 255=ink, 0=bg)."""
    f = _mdi_font(size)
    l, t, r, b = f.getbbox(ch)
    gw, gh = max(1, r - l + 6), max(1, b - t + 6)
    tmp = Image.new("L", (gw, gh), T.WHITE)
    ImageDraw.Draw(tmp).text((-l + 3, -t + 3), ch, font=f, fill=T.BLACK)
    bw = T.to_1bit(tmp)
    inv = bw.point(lambda p: 255 if p == 0 else 0, mode="L")
    ibbox = inv.getbbox()
    if not ibbox:
        return None
    return inv.crop(ibbox)


def _render_outline_crop(name: str, size: int):
    """An icon's outline at `size`, cut to 1 bit, tight crop ('L', 255=ink, 0=bg), or None. Cached
    by the outline itself (vector.cut), so a set copied in later is drawn from at once."""
    rec = icons.get(name)
    return vector.cut(rec, size, crop=True) if rec is not None else None


def _glyph_crop(name: str, size: int):
    """The tight 1-bit crop of a Material Design or custom-set icon at `size`, from outlines (or
    the old font while icons.FROM_FONT is on)."""
    if icons.FROM_FONT:
        cp = mdi_codepoint(name)
        return _render_mdi_1bit_crop(chr(cp), size) if cp is not None and icons.split(name)[0] == "mdi" else None
    return _render_outline_crop(str(name), size)


def _mask_symmetry_error(mask, target_parity: int) -> float:
    iw, ih = mask.size
    parity_pen = 0.0 if (iw % 2) == target_parity else 1.0
    mid = iw / 2.0
    px = mask.load()
    errs = []
    for y in (2, ih // 4, ih // 2, (3 * ih) // 4, max(0, ih - 3)):
        if 0 <= y < ih:
            xs = [x for x in range(iw) if px[x, y] > 0]
            if xs:
                rc = (xs[0] + xs[-1] + 1) / 2.0
                errs.append(abs(rc - mid))
    return parity_pen + (max(errs) if errs else 0.0)


def _draw_icon(img, d, el, _text, display=None):
    name = str(el.get("icon", ""))
    x, y, w, h = _clamp_box(el, 100, 100, display=display)
    invert = el.get("invert") in (True, "true", 1, "1")
    pill = el.get("pill") in (True, "true", 1, "1")
    has_bg = invert or pill
    if has_bg:
        try:
            rad = max(0, min(min(w, h) // 2, int(el.get("radius", 14))))
        except (ValueError, TypeError):
            rad = min(14, min(w, h) // 4)
        if invert:
            d.rounded_rectangle([(x, y), (x + w, y + h)], radius=rad, fill=T.BLACK)
        else:
            d.rounded_rectangle([(x, y), (x + w, y + h)], radius=rad, fill=T.WHITE, outline=T.BLACK, width=2)
    if name.startswith("custom:"):
        art = CUSTOM_ICONS.get(name.removeprefix("custom:"))
        if art:
            art(d, x, y, h)
        return
    if not can_draw_icon(name):
        return
    pad = 10 if has_bg else 0
    max_iw, max_ih = max(8, w - pad * 2), max(8, h - pad * 2)
    if el.get("size"):
        size = max(8, min(360, int(el["size"])))
        mask = _glyph_crop(name, size)
    else:
        if icons.FROM_FONT:
            base_size = _fit_glyph(chr(mdi_codepoint(name)), max_iw, max_ih)
        else:
            base_size = _fit_outline(icons.get(name), max_iw, max_ih)
        mask = _glyph_crop(name, base_size)
        while mask is not None and base_size > 8 and (mask.size[0] > max_iw or mask.size[1] > max_ih):
            base_size -= 1                       # rounding at the edge: one size down until it fits
            mask = _glyph_crop(name, base_size)
        best_score = _mask_symmetry_error(mask, w % 2) if mask is not None else 999.0
        if best_score > 0.0:
            for delta in (-1, 1, -2, 2, -3, 3):
                cand_sz = max(8, min(360, base_size + delta))
                cand_mask = _glyph_crop(name, cand_sz)
                if cand_mask is not None and cand_mask.size[0] <= max_iw and cand_mask.size[1] <= max_ih:
                    sc = _mask_symmetry_error(cand_mask, w % 2) + abs(delta) * 0.01
                    if sc < best_score:
                        best_score = sc
                        mask = cand_mask
    if mask is None:
        return
    ink_w, ink_h = mask.size
    px_x = int(round(x + (w - ink_w) / 2.0))
    px_y = int(round(y + (h - ink_h) / 2.0))
    img.paste(T.WHITE if invert else T.BLACK, (px_x, px_y, px_x + ink_w, px_y + ink_h), mask)


def _draw_line(img, d, el, _text, display=None):
    x, y, w, h = _clamp_box(el, 200, 2, display=display)
    thick = max(1, min(32, int(el.get("thickness") or el.get("stroke") or 2)))
    if h >= w:                                   # taller than wide -> vertical
        x0 = int(round(x + (w - thick) / 2.0))
        d.rectangle([(x0, y), (x0 + thick - 1, y + h - 1)], fill=T.BLACK)
    else:
        y0 = int(round(y + (h - thick) / 2.0))
        d.rectangle([(x, y0), (x + w - 1, y0 + thick - 1)], fill=T.BLACK)


def _draw_box(img, d, el, _text, display=None):
    """1-bit container / card / pill / shaded block primitive."""
    x, y, w, h = _clamp_box(el, 220, 120, display=display)
    try:
        rad = max(0, min(min(w, h) // 2, int(el.get("radius", 10))))
    except (ValueError, TypeError):
        rad = 10
    try:
        thick = max(0, min(24, int(el.get("thickness") if el.get("thickness") is not None else el.get("stroke", 2))))
    except (ValueError, TypeError):
        thick = 2
    fill_mode = str(el.get("fill") or "outline").lower()

    if fill_mode in ("solid", "black"):
        d.rounded_rectangle([(x, y), (x + w, y + h)], radius=rad, fill=T.BLACK)
    elif fill_mode == "white":
        d.rounded_rectangle([(x, y), (x + w, y + h)], radius=rad, fill=T.WHITE, outline=T.BLACK if thick > 0 else None, width=max(1, thick))
    elif fill_mode in ("checker", "screen"):
        mask = Image.new("1", img.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle([(x, y), (x + w, y + h)], radius=rad, fill=1)
        pattern = Image.new("L", img.size, T.WHITE)
        px = pattern.load()
        for yy in range(max(0, y), min(img.size[1], y + h + 1)):
            for xx in range(max(0, x), min(img.size[0], x + w + 1)):
                if (xx + yy) % 2 == 0:
                    px[xx, yy] = T.BLACK
        img.paste(pattern, (0, 0), mask)
        if thick > 0:
            d.rounded_rectangle([(x, y), (x + w, y + h)], radius=rad, outline=T.BLACK, width=thick)
    else:
        # "outline" default: transparent interior, crisp border
        d.rounded_rectangle([(x, y), (x + w, y + h)], radius=rad, outline=T.BLACK, width=max(1, thick))


def _draw_bar(img, d, el, raw_val, display=None):
    """1-bit horizontal, segmented, or vertical progress/gauge bar."""
    x, y, w, h = _clamp_box(el, 260, 44, display=display)
    try:
        lo = float(el.get("min_val") if el.get("min_val") not in (None, "") else 0.0)
    except (ValueError, TypeError):
        lo = 0.0
    try:
        hi = float(el.get("max_val") if el.get("max_val") not in (None, "") else 100.0)
    except (ValueError, TypeError):
        hi = 100.0
    span = (hi - lo) or 100.0

    # No value (no sensor yet, or none from it) draws an empty gauge and no number:
    # never a made-up one (it used to read 68).
    raw_str = str(raw_val if raw_val is not None else el.get("value", "")).strip()
    try:
        cleaned = "".join(ch for ch in raw_str if ch in "0123456789.-")
        val = float(cleaned) if cleaned not in ("", "-", ".") else None
    except (ValueError, TypeError):
        val = None
    pct = max(0.0, min(1.0, (val - lo) / span)) if val is not None else 0.0
    try:
        places = max(0, min(4, int(el.get("decimals") or 0)))
    except (TypeError, ValueError):
        places = 0

    style = str(el.get("bar_style") or ("vertical" if h > w * 1.3 else "solid")).lower()
    show_label = el.get("show_label") not in (False, "false", 0, "0")
    title = str(el.get("title") or "").strip()
    suffix = str(el.get("suffix") if el.get("suffix") is not None else "%")

    bar_x, bar_y, bar_w, bar_h = x, y, w, h
    if title and style != "vertical" and h >= 38:
        tf = T.font(max(11, min(20, int(h * 0.30))), bold=True)
        d.text((x + 2, y + 2), title.upper(), font=tf, fill=T.BLACK, anchor="lt")
        if show_label:
            if val is not None:
                lbl = f"{words.number(val, places)}{suffix}"
                d.text((x + w - 2, y + 2), lbl, font=tf, fill=T.BLACK, anchor="rt")
        hdr_off = max(16, int(h * 0.42))
        bar_y += hdr_off
        bar_h = max(12, h - hdr_off)
        show_label = False  # already drawn in header row

    rad = min(8, min(bar_w, bar_h) // 4)
    if style == "segmented":
        segs = max(4, min(20, int(el.get("segments") or 10)))
        gap = 4
        seg_w = max(4, (bar_w - gap * (segs - 1)) / float(segs))
        lit = int(round(pct * segs))
        for s_i in range(segs):
            sx0 = int(bar_x + s_i * (seg_w + gap))
            sx1 = int(sx0 + seg_w)
            if s_i < lit:
                d.rounded_rectangle([(sx0, bar_y), (sx1, bar_y + bar_h)], radius=min(4, rad), fill=T.BLACK)
            else:
                d.rounded_rectangle([(sx0, bar_y), (sx1, bar_y + bar_h)], radius=min(4, rad), outline=T.BLACK, width=2)
    elif style == "vertical":
        d.rounded_rectangle([(bar_x, bar_y), (bar_x + bar_w, bar_y + bar_h)], radius=rad, outline=T.BLACK, width=2)
        fill_h = int(round((bar_h - 6) * pct))
        if fill_h > 2:
            d.rounded_rectangle([(bar_x + 3, bar_y + bar_h - 3 - fill_h), (bar_x + bar_w - 3, bar_y + bar_h - 3)], radius=max(2, rad - 2), fill=T.BLACK)
    else:
        d.rounded_rectangle([(bar_x, bar_y), (bar_x + bar_w, bar_y + bar_h)], radius=rad, outline=T.BLACK, width=2)
        fill_w = int(round((bar_w - 6) * pct))
        if fill_w > 2:
            d.rounded_rectangle([(bar_x + 3, bar_y + 3), (bar_x + 3 + fill_w, bar_y + bar_h - 3)], radius=max(2, rad - 2), fill=T.BLACK)
        if show_label and bar_h >= 20:
            lbl = f"{title + ' · ' if title else ''}{'' if val is None else f'{val:.{places}f}{suffix}'}"
            lf = T.font(max(11, min(24, int(bar_h * 0.56))), bold=True)
            cx = bar_x + bar_w // 2
            cy = bar_y + bar_h // 2
            # High-contrast pill behind center label so it reads over both black and white regions
            tw = T.text_width(lbl, lf) + 14
            th = max(16, int(bar_h * 0.72))
            d.rounded_rectangle([(cx - tw // 2, cy - th // 2), (cx + tw // 2, cy + th // 2)], radius=4, fill=T.WHITE, outline=T.BLACK, width=1)
            d.text((cx, cy), lbl, font=lf, fill=T.BLACK, anchor="mm")


def _draw_bar_chart(img, d, el, _text, series=None, display=None):
    """Crisp 1-bit vertical bar chart from entity history series."""
    raw_pts = [float(p) for p in (series or el.get("_series") or []) if p is not None]
    if len(raw_pts) < 2:
        # Clean sample wave for visual design preview when no live history yet
        raw_pts = [18, 24, 32, 48, 65, 82, 95, 88, 74, 52, 36, 22]
    x0, y0, w, h = _clamp_box(el, 280, 120, display=display)
    show_border = el.get("show_border") in (True, "true", 1, "1")
    if show_border:
        d.rounded_rectangle([(x0, y0), (x0 + w, y0 + h)], radius=14, outline=T.BLACK, width=3)
        x0 += 14
        y0 += 12
        w = max(24, w - 28)
        h = max(24, h - 24)
    try:
        num_bars = max(4, min(32, int(el.get("bars") or 12)))
    except (ValueError, TypeError):
        num_bars = 12
    show_labels = el.get("show_labels") not in (False, "false", 0, "0")
    title = str(el.get("title") or "").strip()

    # Downsample/bucket raw_pts into num_bars buckets
    buckets = []
    n = len(raw_pts)
    for b_i in range(num_bars):
        i0 = int(b_i * n / num_bars)
        i1 = max(i0 + 1, int((b_i + 1) * n / num_bars))
        chunk = raw_pts[i0:i1]
        buckets.append(sum(chunk) / len(chunk) if chunk else 0.0)

    top_pad = 24 if (title or show_labels) else 4
    chart_y0 = y0 + top_pad
    chart_y1 = y0 + h - 2
    chart_h = max(16, chart_y1 - chart_y0)

    lo = min(0.0, min(buckets))
    hi = max(buckets)
    span = (hi - lo) or 1.0

    if title or show_labels:
        hf = T.font(14, bold=True)
        if title:
            d.text((x0 + 2, y0 + 2), title.upper(), font=hf, fill=T.BLACK, anchor="lt")
        if show_labels:
            hi_lbl = f"MAX {hi:.1f}" if abs(hi) < 10 and hi != int(hi) else f"MAX {hi:.0f}"
            d.text((x0 + w - 2, y0 + 2), hi_lbl, font=hf, fill=T.BLACK, anchor="rt")

    gap = max(2, min(6, w // (num_bars * 4)))
    bar_w = max(3, (w - gap * (num_bars - 1)) / float(num_bars))
    for i, v in enumerate(buckets):
        bx0 = int(x0 + i * (bar_w + gap))
        bx1 = int(bx0 + bar_w)
        bh = max(3, int(round(((v - lo) / span) * (chart_h - 4))))
        by0 = chart_y1 - bh
        d.rounded_rectangle([(bx0, by0), (bx1, chart_y1)], radius=min(3, int(bar_w // 2)), fill=T.BLACK)

    d.line([(x0, chart_y1), (x0 + w, chart_y1)], fill=T.BLACK, width=2)


def _draw_qr(img, d, el, raw_val, display=None):
    """1-bit QR code element (supports literal URL/text, entity value, or Wi-Fi credentials)."""
    x, y, w, h = _clamp_box(el, 150, 150, display=display)
    show_border = el.get("show_border") in (True, "true", 1, "1")
    if show_border:
        d.rounded_rectangle([(x, y), (x + w, y + h)], radius=12, outline=T.BLACK, width=2)
        x += 6
        y += 6
        w = max(32, w - 12)
        h = max(32, h - 12)
    wifi_ssid = str(el.get("wifi_ssid") or "").strip()
    if wifi_ssid:
        wifi_pass = str(el.get("wifi_password") or "")
        wifi_enc = str(el.get("wifi_auth") or ("WPA" if wifi_pass else "nopass"))
        payload = f"WIFI:S:{wifi_ssid};T:{wifi_enc};P:{wifi_pass};;"
    else:
        payload = str(raw_val if (raw_val is not None and str(raw_val).strip()) else (el.get("value") or "https://home-assistant.io")).strip()

    title = str(el.get("title") or "").strip()
    matrix = encode_qr_matrix(payload)
    m_size = len(matrix)
    quiet = 2  # 2-module quiet zone around QR
    total_mods = m_size + quiet * 2

    label_h = 22 if title and h >= 90 else 0
    avail_box = min(w, max(40, h - label_h))
    mod_px = max(1, avail_box // total_mods)
    qr_px = mod_px * total_mods
    ox = x + (w - qr_px) // 2
    oy = y + (h - label_h - qr_px) // 2

    d.rectangle([(ox, oy), (ox + qr_px, oy + qr_px)], fill=T.WHITE)
    for r_i, row in enumerate(matrix):
        for c_i, cell in enumerate(row):
            if cell:
                px0 = ox + (c_i + quiet) * mod_px
                py0 = oy + (r_i + quiet) * mod_px
                d.rectangle([(px0, py0), (px0 + mod_px - 1, py0 + mod_px - 1)], fill=T.BLACK)

    if label_h and title:
        tf = _fit_font(title, w - 8, 15, min_sz=10, bold=True)
        d.text((x + w // 2, oy + qr_px + label_h // 2 + 2), title, font=tf, fill=T.BLACK, anchor="mm")


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
    if isinstance(el.get("units"), dict) and el["units"].get("base"):
        formatted = units.format_value(v, el)          # picks its own unit: 1234 W -> 1.23 kW
    else:
        dec = max(0, min(6, int(el.get("decimals", 0))))
        formatted = words.number(v, dec)
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


def can_draw_icon(name) -> bool:
    """Whether the panel draws this icon: one of its own (custom:), or one in a set it has
    (render/icons: Material Design, copied from Home Assistant or shipped, and custom sets). An icon
    no set has draws as nothing, so it's never offered."""
    name = str(name or "")
    if name.startswith(icons.BUILT_IN + ":"):
        return name.removeprefix(icons.BUILT_IN + ":") in CUSTOM_ICONS
    if icons.FROM_FONT:
        return icons.split(name)[0] == "mdi" and mdi_codepoint(name) is not None
    return icons.get(name) is not None


def _draw_icon_glyph(d, name, cx, cy, sz):
    name = str(name or "")
    if name.startswith("custom:"):
        art = CUSTOM_ICONS.get(name.removeprefix("custom:"))
        if art:
            art(d, cx, cy - sz // 2, sz)
        return
    if icons.FROM_FONT:
        cp = mdi_codepoint(name)
        if cp is not None:
            f = _mdi_font(sz)
            d.text((cx, cy), chr(cp), font=f, fill=T.BLACK, anchor="mm")
        return
    rec = icons.get(name)
    if rec is not None:
        sz = max(1, int(sz))
        d.bitmap((int(round(cx - sz / 2)), int(round(cy - sz / 2))), vector.cut(rec, sz), fill=T.BLACK)


ICON_LOOKS = ("plain", "invert", "pill")      # an icon's Style: Plain, Inverted, Outlined


def _state_entry(state_icons, state) -> dict:
    """What a state_icons map says for a state: {"icon", "look"}, {} when nothing. Matched as Home
    Assistant's state reads, ignoring case and spaces around it ("outdoor cat" is "Outdoor Cat").
    An entry is an icon ("mdi:cat", the first shape) or {"icon", "look"}, look one of ICON_LOOKS;
    without a look, the element's own Style."""
    st = str(state or "").strip().lower()
    if not st or not isinstance(state_icons, dict):
        return {}
    for k, v in state_icons.items():
        if str(k).strip().lower() != st:
            continue
        if isinstance(v, dict):
            look = str(v.get("look") or "")
            return {"icon": str(v.get("icon") or ""), "look": look if look in ICON_LOOKS else ""}
        return {"icon": str(v or ""), "look": ""}
    return {}


def icon_for_state(state_icons, state) -> str:
    """The icon a state_icons map gives a state, or "" when none does: the one lookup for an icon
    element and a Dynamic status spot."""
    return _state_entry(state_icons, state).get("icon", "")


def icon_in_state(el: dict, state) -> dict:
    """An icon that follows its entity, as drawn in this state: the state's icon and look, else its
    own (what "Anything else" is in the editor)."""
    got = _state_entry(el.get("state_icons"), state)
    out = {**el, "icon": got.get("icon") or el.get("icon", "")}
    if got.get("look"):
        out["invert"], out["pill"] = got["look"] == "invert", got["look"] == "pill"
    return out


def _resolve_spot_icon(it, state):
    st = str(state or "").strip().lower()
    # 1. Custom state-to-icon mapping
    mapped = icon_for_state(it.get("state_icons"), st)
    if mapped:
        return mapped
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


def _number_or_none(state):
    try:
        v = float(str(state).strip())
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _past(level, rule, own, page_value):
    """Whether a level is past its threshold: an item's own, else the grid's. "below" is strictly
    below (Home Assistant's numeric_state); "at_least" includes it, so 100 % reads charged at 100."""
    t = _number_or_none(own) if own not in (None, "") else _number_or_none(page_value)
    if t is None:
        return False
    return level < t if rule == "below" else level >= t


def _level_text(level, unit):
    if level is None:
        return ""
    unit = str(unit or "").strip()
    num = words.number(level, 0 if abs(level - round(level)) < 0.05 or unit == "%" else 1)
    return f"{num}{unit}" if unit in ("%", "") else f"{num} {unit}"


# A list of Dynamic status items (the user's call, 22 Oct, for Batteries): a row each, with its icon,
# its name and, on the right, its level or detail; two columns when wide; "and 3 more" when they
# don't all fit. Rows never get smaller than reads on e-ink.
LIST_ROW_MIN, LIST_ROW_MAX, LIST_GAP = 30, 60, 4
LIST_TEXT_MIN = 14                      # the smallest a name gets on e-ink before it's shortened


def _fit_middle(text, max_w, f):
    """`text` as it fits in max_w: whole, or its start and its end around an ellipsis."""
    if T.text_width(text, f) <= max_w:
        return text
    for keep in range(len(text) - 1, 1, -1):
        head = text[:(keep + 1) // 2]
        tail = text[len(text) - keep // 2:] if keep // 2 else ""
        out = f"{head}…{tail}"
        if T.text_width(out, f) <= max_w:
            return out
    return text[:1] + "…"


def _draw_grid_list(d, x, y, w, h, items, detail, by_number, fscale=1.0, icons_only=False, icon_px=None):
    n = len(items)
    cols = 2 if w >= 480 and n >= 4 else 1
    per_col = max(1, (h + LIST_GAP) // (LIST_ROW_MIN + LIST_GAP))
    room = per_col * cols
    shown = items if n <= room else items[:room - 1]
    more = n - len(shown)
    slots = len(shown) + (1 if more else 0)
    rows = max(1, math.ceil(slots / cols))
    rh = max(LIST_ROW_MIN, min(LIST_ROW_MAX, (h - LIST_GAP * (rows - 1)) // rows))
    col_gap = 24
    cw = (w - col_gap * (cols - 1)) // cols
    text_px = max(14, min(36, int(rh * 0.5 * fscale), cw // 8))
    name_f, level_f = T.font(text_px, bold=True), T.font(text_px, bold=by_number)
    isz = 0 if cw < 180 else min(icon_px or int(rh * 0.78), rh)     # a sliver of a column keeps the room for the name
    pad = 10 if isz else 0

    for k in range(slots):
        col, row = divmod(k, rows)                      # down the first column, then the next
        cx, cy = x + col * (cw + col_gap), y + row * (rh + LIST_GAP)
        mid = cy + rh // 2
        if k < len(shown) and row < rows - 1 and k + 1 < slots:
            d.line([(cx, cy + rh + LIST_GAP // 2), (cx + cw, cy + rh + LIST_GAP // 2)], fill=T.BLACK, width=1)
        if k >= len(shown):
            d.text((cx + isz + pad, mid), say("and_more", more), font=T.font(text_px, bold=False), fill=T.BLACK, anchor="lm")
            continue
        it = shown[k]
        if isz:
            _draw_icon_glyph(d, it["icon"], cx + isz // 2, mid, isz)
        if icons_only:
            continue
        right = detail(it)
        rw = T.text_width(right, level_f) if right else 0
        if right:
            d.text((cx + cw, mid), right, font=level_f, fill=T.BLACK, anchor="rm")
        tx = cx + isz + pad
        avail = max(20, cx + cw - rw - 12 - tx)
        name = it["name"]
        f = name_f
        for px in range(text_px, LIST_TEXT_MIN - 1, -1):                  # smaller, down to what still reads, before it's cut
            f = T.font(px, bold=True)
            if T.text_width(name, f) <= avail:
                break
        words = name.split()
        if T.text_width(name, f) > avail and len(words) > 1 and rh >= f.size * 2.3:
            # Still too long, and the row has room: two lines, split where both fit best.
            cut = min(range(1, len(words)), key=lambda j: max(T.text_width(" ".join(words[:j]), f), T.text_width(" ".join(words[j:]), f)))
            for line, dy in ((" ".join(words[:cut]), -0.55), (" ".join(words[cut:]), 0.55)):
                d.text((tx, mid + int(dy * f.size)), _fit_text(line, avail, f), font=f, fill=T.BLACK, anchor="lm")
        elif len(words) == 1:
            # One word that won't fit even at the smallest: its start and its end ("Ther…stat"), never cut mid-letter.
            d.text((tx, mid), _fit_middle(name, avail, f), font=f, fill=T.BLACK, anchor="lm")
        else:
            d.text((tx, mid), _fit_text(name, avail, f), font=f, fill=T.BLACK, anchor="lm")


def _no_answer_text(res: dict, now: datetime | None = None) -> str:
    """A battery that hasn't answered: "No answer since Tue 14:02" (12- or 24-hour, as set); one older than
    six days by its date, "No answer since 12 Oct", since a weekday would be last week's. Several from one
    integration that went quiet together are one line: "4 not answering" (its name is the integration's)."""
    if res.get("no_answer_count"):
        return say("status.not_answering", res["no_answer_count"])
    try:
        at = datetime.fromisoformat(str(res.get("no_answer")).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return say("status.no_answer")
    now = now or datetime.now(at.tzinfo)
    if (now - at).days > 6:
        return say("status.no_answer_since", when=clock.date(at, "date"))
    return say("status.no_answer_since", when=clock.day_and_time(at))


def _fit_line(text, max_w, px, bold=False, floor=11):
    """A line of words as it fits max_w: smaller first, down to what still reads, then shortened."""
    f = _fit_font(text, max_w, px, min_sz=min(px, floor), bold=bold)
    return _fit_text(text, max_w, f), f


def _active_badge_w() -> int:
    """How wide a lone item's "ACTIVE" badge is: its word's, never under 90."""
    return max(90, T.text_width(say("status.ACTIVE"), T.font(14, bold=True)) + 24)


def _on_for(changed, now: datetime | None = None) -> str:
    """How long an item has been in its state, short ("25m"): from when it changed (an ISO time) or a
    number of seconds; "" when not known."""
    if isinstance(changed, (int, float)) and not isinstance(changed, bool):
        return clock.span_short(changed)
    try:
        at = datetime.fromisoformat(str(changed or "").strip().replace("Z", "+00:00"))
    except ValueError:
        return ""
    now = now or (datetime.now(at.tzinfo) if at.tzinfo else datetime.now())
    return clock.span_short((now - at).total_seconds())


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
    if el.get("batteries"):
        # Batteries by rule (review 2 #5): which ones come with the value; `items` are each one's own settings.
        own = {it.get("entity"): it for it in configured_items if isinstance(it, dict)}
        configured_items = [own.get(ent) or {"entity": ent, "name": "", "icon": ""} for ent in info_by_ent] if has_resolved else []
    filter_state = str(el.get("filter_state") or "on").strip().lower()
    # A number rule instead of a state (a battery below 40 %, or charged to at least 90 %): each item
    # shows while its level is past the grid's value, or its own `threshold`; the level is its second line.
    rule = str(el.get("filter_rule") or "state")
    by_number = rule in ("below", "at_least")

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

            level = _number_or_none(state) if by_number else None
            low_sensor = by_number and ent.startswith("binary_sensor.") and res.get("device_class") == "battery"
            silent = rule == "below" and bool(res.get("no_answer"))
            if silent:
                # Hasn't answered for its wait (sources/batteries.shown): it shows, after the low ones.
                is_active = True
            elif low_sensor:
                # A "battery low" sensor: below whenever it's on, never charged; it shows "Low", no level.
                is_active = rule == "below" and state.lower() == "on"
            elif by_number:
                is_active = level is not None and _past(level, rule, it.get("threshold"), el.get("filter_value"))
            else:
                is_active = (state and state not in ("unavailable", "unknown")) if filter_state in ("*", "any") else (state.lower() == filter_state)
            if is_active:
                chosen_icon = _resolve_spot_icon(it, state)
                if by_number and not it.get("icon") and res.get("device_class") == "battery":
                    chosen_icon = state_words.battery_icon(None if silent else 0 if low_sensor else level)   # Home Assistant's own glyph for its level
                if by_number and res.get("device_class") == "battery":
                    # On a page of batteries, "Door Sensor Battery" is the Door Sensor.
                    friendly = re.sub(r"\s+battery(\s+level)?$", "", friendly, flags=re.I) or friendly
                active_items.append({
                    "level": None if silent else 0 if low_sensor else level,
                    "silent": silent,
                    "level_text": (_no_answer_text(res) if silent else say("status.low") if low_sensor
                                   else _level_text(level, res.get("unit")) if by_number else ""),
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
                "name": name or (ent.split(".")[-1].replace("_", " ").title() if ent else say("status.active_spot")),
                "icon": chosen_icon,
                "state": state,
                "changed": 25 * 60,
                "hide_name": hide_name,
                "raw_item": it
            })

    if by_number:
        # The most urgent first: the emptiest battery when it's "below", the fullest when "at least".
        # Ones that haven't answered come after the low ones.
        active_items.sort(key=lambda it: it.get("level") if it.get("level") is not None else 0, reverse=rule == "at_least")
        active_items.sort(key=lambda it: bool(it.get("silent")))

    if not configured_items and not active_items:
        active_items = [{
            "entity": "switch.sample_1",
            "name": say("status.sample_zone"),
            "icon": "mdi:radiator",
            "state": "on",
            "changed": 30 * 60,
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
        if by_number:
            return item.get("level_text", "")
        if sec_mode == "state":
            return item.get("state", "")
        span = _on_for(item.get("changed"))
        return say("status.on_for", span=span) if span else say("status.active")

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

        if by_number:
            badge_str = say("of", a=len(active_items), b=len(configured_items))
        else:
            badge_str = say("status.n_on", a=len(active_items), b=len(configured_items)) if configured_items \
                else say("status.n_active", len(active_items))
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
        d.text((x + w // 2, y + h // 2 + 18), _fit_text(say("status.all_idle"), w - 16, f_idle1), font=f_idle1, fill=T.BLACK, anchor="mm")
        f_idle2 = T.font(13, bold=False)
        d.text((x + w // 2, y + h // 2 + 38), _fit_text(say("status.all_idle_hint"), w - 16, f_idle2), font=f_idle2, fill=T.BLACK, anchor="mm")
        return

    is_wide = (w >= h)

    try:
        fscale = max(0.6, min(1.8, float(el.get("font_scale") or el.get("scale") or 1.0)))
    except (ValueError, TypeError):
        fscale = 1.0

    if el.get("layout_mode") == "list":
        _draw_grid_list(d, x, y, w, h, active_items, format_sec, by_number, fscale,
                        icons_only=show_labels == "icons_only", icon_px=req_icon_sz)
        return

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
                if by_number and sec:
                    # One battery alone: its level large on the right, where a state's pill would be.
                    lvl_f = T.font(max(24, min(72, int(56 * fscale), h - 40)), bold=True)
                    d.text((x + w - 24, y + h // 2), sec, font=lvl_f, fill=T.BLACK, anchor="rm")
                    room = x + w - 24 - T.text_width(sec, lvl_f) - 24 - tx
                    sec = ""
                else:
                    room = (x + w - _active_badge_w() - 24 - 12) - tx          # up to the badge
                name_txt = _fit_text(it["name"], room, name_f)
                d.text((tx, y + h // 2 - (int(16 * fscale) if sec else 0)), name_txt, font=name_f, fill=T.BLACK, anchor="lm")
                if sec:
                    sec_txt, sec_f = _fit_line(sec, room, max(13, min(32, int(20 * fscale))))
                    d.text((tx, y + h // 2 + int(20 * fscale)), sec_txt, font=sec_f, fill=T.BLACK, anchor="lm")
            if not by_number:                    # a level says it all; "ACTIVE" is for a state
                act, act_f = say("status.ACTIVE"), T.font(14, bold=True)
                bw, bh = _active_badge_w(), 32
                bx0 = x + w - bw - 24
                by0 = y + (h - bh) // 2
                d.rounded_rectangle([(bx0, by0), (bx0 + bw, by0 + bh)], radius=6, fill=T.BLACK)
                d.text((bx0 + bw // 2, by0 + bh // 2), act, font=act_f, fill=T.WHITE, anchor="mm")
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
                    sec_txt, sec_f = _fit_line(sec, w - 32, max(13, min(28, int(19 * fscale))))
                    d.text((x + w // 2, mid_y + 54), sec_txt, font=sec_f, fill=T.BLACK, anchor="mm")
            if not by_number:
                on, on_f = say("status.ON"), T.font(11, bold=True)
                pw, ph = max(40, T.text_width(on, on_f) + 14), 20
                d.rounded_rectangle([(x + w - pw - 10, y + 10), (x + w - 10, y + 10 + ph)], radius=4, fill=T.BLACK)
                d.text((x + w - 10 - pw // 2, y + 10 + ph // 2), on, font=on_f, fill=T.WHITE, anchor="mm")
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

        sec = format_sec(it)
        if by_number:
            bx0 = cx1 - 6                        # no state badge: the level is drawn large instead
        else:
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
                d.text((tx, cy0 + ch_i // 2 - (int((14 if by_number else 11) * fscale) if sec else 0)), name_txt, font=name_f, fill=T.BLACK, anchor="lm")
                if sec and by_number:
                    # The level under the name, bold and a size larger ("21%"), so the name keeps the width.
                    lvl_f = T.font(max(14, min(40, int(base_name_sz * 1.2 * fscale))), bold=True)
                    d.text((tx, cy0 + ch_i // 2 + int(17 * fscale)), sec, font=lvl_f, fill=T.BLACK, anchor="lm")
                elif sec:
                    base_sec_sz = min(16, max(12, cw_i // 16))
                    sec_txt, sec_f = _fit_line(sec, max(30, cx1 - 8 - tx), max(10, min(24, int(base_sec_sz * fscale))))
                    d.text((tx, cy0 + ch_i // 2 + int(14 * fscale)), sec_txt, font=sec_f, fill=T.BLACK, anchor="lm")
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
                    sec_px, bold = max(10, min(22, int(base_sec_sz * fscale))), False
                    if by_number:                    # the level reads as large as the name
                        sec_px, bold = max(12, min(32, int(base_name_sz * fscale))), True
                    sec_txt, sec_f = _fit_line(sec, cw_i - 14, sec_px, bold=bold)
                    d.text((mid_x, cy0 + ch_i * 0.86), sec_txt, font=sec_f, fill=T.BLACK, anchor="mm")


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
        header_text = clock.date(datetime(year, month, 1), "month_year").upper()
        header_sz = _s(min(24, max(15, int(header_h * 0.76))), fscale, 13, 36)
        header_f = _fit_font(header_text, w - 20, header_sz, min_sz=12, bold=True)
        d.text((x + w // 2, y + header_h // 2), header_text, font=header_f, fill=T.BLACK, anchor="mm")

    show_weekdays = el.get("show_weekdays") not in (False, "false", 0, "0")
    col_w = w / 7.0

    if show_weekdays:
        weekday_h = min(24, max(16, int(header_h * 0.65 if header_h else 20)))
        order = [(first_weekday + k) % 7 for k in range(7)]       # Monday is 0; Sunday first is 6
        day_names_long = [words.name("wd", k).rstrip(".").upper() for k in order]
        day_names_short = [words.name("wdn", k) for k in order]
        wf_sz = _s(min(16, max(11, int(col_w * 0.34))), fscale, 9, 22)
        wf = T.font(wf_sz, bold=True)
        # The day's short name where every one fits its column ("MIÉ", "DO"), its letter where not
        use_long = col_w >= 34 and all(T.text_width(n, wf) <= col_w - 4 for n in day_names_long)
        day_labels = day_names_long if use_long else day_names_short
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


# A to-do list (render/todo.py says what it shows). Sizes are the 5.79"'s and
# scale with the element's text size; hierarchy is size and weight, no grey.
TODO_ITEM_PX = 30
TODO_HEAD_PX = 22


def _shorten(s, f, max_w):
    return T._ellipsize(s, f, max_w) or T._ellipsize(s, f, max_w, min_chars=1) or ""


def _draw_todo_list(img, d, el, raw_val, metrics=None, distance_m=3.0, display=None):
    x, y, w, h = _clamp_box(el, 712, 220, display=display)
    fscale = _font_scale(el)
    show = el.get("show") if el.get("show") in todo.SHOWS else "open"
    data = raw_val if isinstance(raw_val, dict) else None
    now = todo.now_in((data or {}).get("tz"))

    item_px = _s(TODO_ITEM_PX, fscale, 12, 96)
    head_px = _s(TODO_HEAD_PX, fscale, 11, 64)
    if metrics is not None:
        mm, verdict = legibility(item_px, distance_m=distance_m, display=display)
        metrics.append({"size": item_px, "mm": mm, "verdict": verdict, "lines": 1, "overflow": False})

    head_f, item_f = T.font(head_px, bold=True), T.font(item_px, bold=False)
    head_mid = y + head_px // 2 + 2
    title = str(el.get("title") or (data or {}).get("name") or "").strip()
    if not str(el.get("entity") or "").strip():
        d.text((x + w // 2, y + h // 2), _fit_text(say("todo.choose"), w, T.font(item_px, bold=True)), font=T.font(item_px, bold=True), fill=T.BLACK, anchor="mm")
        return
    if data is None:                                   # not fetched yet: the name, nothing else
        d.text((x, head_mid), _shorten(title, head_f, w), font=head_f, fill=T.BLACK, anchor="lm")
        return

    items = todo.items_for(data.get("items"), show, now)
    count = todo.count_label(len(items), show) if items else ""   # empty says so below
    count_w = T.text_width(count, head_f) if count else 0
    if count:
        d.text((x + w, head_mid), count, font=head_f, fill=T.BLACK, anchor="rm")
    if title:
        d.text((x, head_mid), _shorten(title, head_f, max(1, w - count_w - 16)), font=head_f, fill=T.BLACK, anchor="lm")

    top = y + head_px + max(8, item_px // 3)
    if not items:
        d.text((x + w // 2, (top + y + h) // 2), _fit_text(todo.empty_text(show), w, T.font(item_px, bold=True)), font=T.font(item_px, bold=True), fill=T.BLACK, anchor="mm")
        return

    style = todo.style_of(el)
    row_h, pitch = todo.rows(style, item_px)
    n_shown, more = todo.fit(len(items), y + h - top, row_h, pitch)

    box = round(item_px * 0.72)                        # the empty square before each item
    stroke = max(4, round(box / 6))                    # thinner disappears on e-ink
    # Inside a pill: content starts where the pill's curve allows, and the
    # label pill sits concentric with the row (its radius = the row's - inset),
    # just clear of the outline.
    pad = 0 if style == "plain" else round(row_h * 0.42)
    line = max(4, round(row_h / 10))                   # a pill's outline; thinner disappears on e-ink
    inset = line + max(3, round(row_h / 13))
    label_px = max(10, round(item_px * (0.8 if style == "plain" else 0.72)))
    label_f = T.font(label_px, bold=True)
    text_x = x + pad + box + max(10, item_px // 2)
    for k, item in enumerate(items[:n_shown]):
        r0 = top + k * pitch
        mid = r0 + row_h // 2
        label, urgency = todo.due_label(item, now)
        look = todo.row_look(style, urgency)
        ink, paper = (T.WHITE, T.BLACK) if look == "invert" else (T.BLACK, T.WHITE)
        if look == "invert":
            d.rounded_rectangle([(x, r0), (x + w, r0 + row_h)], radius=row_h // 2, fill=T.BLACK)
        elif look == "outline":
            d.rounded_rectangle([(x, r0), (x + w, r0 + row_h)], radius=row_h // 2, outline=T.BLACK, width=line)
        d.rounded_rectangle([(x + pad, mid - box // 2), (x + pad + box, mid + box // 2)], radius=max(2, box // 5),
                            outline=ink, width=stroke)
        right = x + w - (inset if look != "plain" else 0)
        if label:
            lw = T.text_width(label, label_f)
            if urgency:                                # overdue or today: a pill of the other colour
                lh = min(row_h - 2 * inset, label_px + 10) if look != "plain" else label_px + 8
                lp = 8 if look == "plain" else max(6, lh * 2 // 5)
                d.rounded_rectangle([(right - lw - lp * 2, mid - lh // 2), (right, mid + lh // 2)],
                                    radius=lh // 2, fill=ink)
                d.text((right - lp, mid), label, font=label_f, fill=paper, anchor="rm")
                right -= lw + lp * 2 + 12
            else:
                if look != "plain":
                    right -= max(6, item_px // 4)      # clear of the pill's curve
                d.text((right, mid), label, font=label_f, fill=ink, anchor="rm")
                right -= lw + 12
        elif look != "plain":
            right -= max(6, item_px // 4)
        d.text((text_x, mid), _shorten(str(item.get("summary") or ""), item_f, max(1, right - text_x)),
               font=item_f, fill=ink, anchor="lm")
    if more:
        mid = top + n_shown * pitch + row_h // 2
        d.text((text_x, mid), say("and_more", more), font=item_f, fill=T.BLACK, anchor="lm")


def sample_agenda(now: datetime) -> list[dict]:
    """The made-up agenda the editor shows before a calendar is chosen (and New page's thumbnail), in
    the screen's language: today, and three days ahead."""
    at = lambda days, hour, minute=0: (now + timedelta(days=days)).replace(hour=hour, minute=minute, second=0, microsecond=0)
    return [
        {"start": at(0, 19, 30).isoformat(), "summary": say("calendar.sample1"), "sub": say("calendar.sample1_sub")},
        {"start": at(1, 9).isoformat(), "summary": say("calendar.sample2"),
         "sub": f"{clock.hm(at(1, 9))} • {say('calendar.sample2_sub')}"},
        {"start": at(3, 7).date().isoformat(), "summary": say("calendar.sample3"),
         "sub": say("calendar.sample3_sub", time=clock.hm(at(3, 7)))},
        {"start": at(11, 8).date().isoformat(), "summary": say("calendar.sample4"), "sub": say("calendar.sample4_sub")},
    ]


def _draw_calendar_agenda(img, d, el, raw_val, display=None):
    x, y, w, h = _clamp_box(el, 375, 250, display=display)
    fscale = _font_scale(el)
    show_border = el.get("show_border") not in (False, "false", 0, "0")
    if show_border:
        d.rounded_rectangle([(x, y), (x + w, y + h)], radius=12, outline=T.BLACK, width=1)

    title = str(el.get("title") or say("calendar.upcoming")).upper()
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
        events = sample_agenda(datetime.now())         # the editor's preview, before a calendar is chosen

    count_badge = say("calendar.events", len(events)) if events else say("calendar.none")
    bf = T.font(_s(11, fscale, 9, 18), bold=True)
    bw = T.text_width(count_badge, bf) + 14
    d.rounded_rectangle([(x + w - bw - 14, y + 6), (x + w - 14, y + 26)], radius=4, fill=T.BLACK)
    d.text((x + w - 14 - bw // 2, y + 16), count_badge, font=bf, fill=T.WHITE, anchor="mm")
    d.line([(x + 10, y + 32), (x + w - 10, y + 32)], fill=T.BLACK, width=1)

    if not events:
        ef = T.font(_s(16, fscale, 12, 26), bold=True)
        d.text((x + w // 2, y + h // 2), _fit_text(say("calendar.empty"), w - 24, ef), font=ef, fill=T.BLACK, anchor="mm")
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
                    edt = datetime.fromisoformat(s_clean)
                    if edt.strftime("%Y-%m-%d") != today_ymd:
                        dt_str = clock.date(edt, "short_day_date").upper()
                    elif len(s_clean) == 10:  # all day "YYYY-MM-DD"
                        dt_str = say("day.today").upper()
                    else:
                        dt_str = say("day.today_at", time=clock.hm(edt)).upper()
                except Exception:
                    dt_str = say("calendar.soon")
            else:
                dt_str = say("calendar.event")

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
        summary = ev.get("summary") or ev.get("message") or say("calendar.untitled")
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

def _weather_label(cond: str) -> str:
    """Home Assistant's weather condition in the screen's words ("partlycloudy" -> "Partly Cloudy")."""
    key = f"weather.{cond.replace('_', '-')}"
    return say(key) if words.has(key) else cond.replace("-", " ").replace("_", " ").title()


def _weather_details(humidity, wind, wind_unit, pressure_trend) -> list[str]:
    """The current weather's details, most useful first: humidity, wind, the pressure's way."""
    parts = []
    if humidity is not None:
        parts.append(say("weather.humidity", v=words.number(humidity)))
    if wind is not None:
        parts.append(say("weather.wind", v=f"{words.number(wind)} {wind_unit}"))
    if pressure_trend in ("rising", "falling"):
        parts.append(say(f"weather.pressure_{pressure_trend}"))
    return parts


def _high_low(hi, lo, sep) -> str:
    return f"{say('weather.high')} {hi:.0f}°{sep}{say('weather.low')} {lo:.0f}°"


def _fit_parts(parts, max_w, size, sep, min_sz=11):
    """As many of the parts as fit max_w at a readable size, in order, and the font: never text running on."""
    parts = list(parts)
    while parts:
        txt = sep.join(parts)
        f = _fit_font(txt, max_w, size, min_sz=min_sz, bold=True)
        if T.text_width(txt, f) <= max_w:
            return txt, f
        parts.pop()
    return "", T.font(min_sz, bold=True)


def _draw_weather_forecast(img, d, el, raw_val, display=None):
    x, y, w, h = _clamp_box(el, 752, 235, display=display)
    fscale = _font_scale(el)
    show_border = el.get("show_border") not in (False, "false", 0, "0")
    if show_border:
        d.rounded_rectangle([(x, y), (x + w, y + h)], radius=12, outline=T.BLACK, width=1)

    data = _parse_val_json(raw_val)
    if not isinstance(data, dict):
        # No weather from Home Assistant (it's restarting, say): blank says so. Made-up weather wouldn't.
        return

    cond = str(data.get("condition") or "partlycloudy").lower()
    cond_label = _weather_label(cond)
    temp = data.get("temperature", "--")
    unit = str(data.get("unit") or "°C")
    humidity = data.get("humidity")
    wind = data.get("wind_speed")
    wind_unit = str(data.get("wind_unit") or "km/h")
    pressure_trend = str(data.get("pressure_trend") or "")         # from your own station (sources/station.py)
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
            chip_parts = _weather_details(humidity, wind, wind_unit, pressure_trend)
            if forecast:
                today_f = forecast[0]
                th, tl = today_f.get("temperature"), today_f.get("templow")
                if th is not None and tl is not None:
                    chip_parts.append(_high_low(th, tl, " · "))
            chip_text, mf = _fit_parts(chip_parts, w - 48, _s(16, fscale, 12, 26), "   •   ")
            if chip_text:
                d.text((x + 24, y + h - 22), chip_text, font=mf, fill=T.BLACK, anchor="lm")
        return

    # Any landscape box splits (a 2.9" screen's is 285 x 80); stacked is for portrait cards.
    is_split = (layout_mode == "split") or (layout_mode == "auto" and ((w >= 480) or (w >= 340 and w >= h) or w >= h * 1.3))
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

            hero_mid_y = y + int(h * (0.40 if show_details and h >= 110 else 0.50))
            isz = min(84, max(28, int(h * 0.38)))
            pad = max(6, min(18, w // 40))
            _draw_icon_glyph(d, cur_icon, x + pad + isz // 2, hero_mid_y, isz)

            tx = x + pad + isz + max(6, min(14, isz // 4))
            avail_hero_w = max(60, fore_x - tx - 12)
            temp_str = f"{temp}{unit}" if str(temp).endswith("°") or unit.startswith("°") else f"{temp}°"
            target_tf_sz = _s(min(56, max(32, int(h * 0.27))), fscale, 24, 88)
            tf = _fit_font(temp_str, avail_hero_w, target_tf_sz, min_sz=22, bold=True)
            d.text((tx, hero_mid_y - int(h * 0.07)), temp_str, font=tf, fill=T.BLACK, anchor="lm")

            target_cf_sz = _s(min(22, max(15, int(h * 0.105))), fscale, 13, 34)
            cf = _fit_font(cond_label, avail_hero_w, target_cf_sz, min_sz=12, bold=True)
            d.text((tx, hero_mid_y + int(h * 0.13)), cond_label, font=cf, fill=T.BLACK, anchor="lm")

            if show_details:
                line1_parts = _weather_details(humidity, wind, wind_unit, pressure_trend)
                line2_parts = []
                if forecast:
                    today_f = forecast[0]
                    th = today_f.get("temperature")
                    tl = today_f.get("templow")
                    if th is not None and tl is not None:
                        line2_parts.append(_high_low(th, tl, " / "))
                    pop = today_f.get("precipitation_probability")
                    precip = today_f.get("precipitation")
                    if pop is not None and float(pop) > 0:
                        line2_parts.append(say("weather.rain", v=f"{float(pop):.0f}%"))
                    elif precip is not None and float(precip) > 0:
                        line2_parts.append(say("weather.rain", v=f"{words.number(float(precip), 1)}mm"))

                avail_chip_w = fore_x - x - 32
                target_chip_sz = _s(15, fscale, 11, 24)
                if line2_parts and h >= 165:
                    # Two clean, large detail lines instead of 1 squeezed microscopic line
                    l1_txt, mf1 = _fit_parts(line1_parts or line2_parts, avail_chip_w, target_chip_sz, "   •   ")
                    l2_txt, mf2 = _fit_parts(line2_parts if line1_parts else [], avail_chip_w, target_chip_sz, "   •   ")
                    d.text((x + 18, y + h - (36 if l2_txt else 20)), l1_txt, font=mf1, fill=T.BLACK, anchor="lm")
                    if l2_txt:
                        d.text((x + 18, y + h - 16), l2_txt, font=mf2, fill=T.BLACK, anchor="lm")
                elif h >= 110:
                    # One line: as many details as fit, most useful first, rather than text running into the days
                    txt, mf = _fit_parts(line2_parts[:1] + line1_parts + line2_parts[1:], avail_chip_w, target_chip_sz, "  •  ")
                    if txt:
                        d.text((x + 18, y + h - 20), txt, font=mf, fill=T.BLACK, anchor="lm")

            # Vertical divider
            d.line([(fore_x, y + 12), (fore_x, y + h - 12)], fill=T.BLACK, width=1)

        # Forecast strip
        fit_days = max(1, min(max_f_days, int(fore_w // 56)))     # a day narrower than this can't be read
        display_forecast = forecast[1:1 + fit_days] if len(forecast) > fit_days else forecast[:fit_days]
        n_days = len(display_forecast)
        if n_days > 0:
            day_w = fore_w / float(n_days)
            for i, fcast in enumerate(display_forecast):
                cx = fore_x + int((i + 0.5) * day_w)
                if i > 0:
                    div_x = fore_x + int(i * day_w)
                    d.line([(div_x, y + 18), (div_x, y + h - 18)], fill=T.BLACK, width=1)
                dt_raw = fcast.get("datetime")
                day_name = say("weather.day_n", n=i + 1)
                if dt_raw:
                    try:
                        dt = datetime.fromisoformat(str(dt_raw).replace("Z", "+00:00"))
                        day_name = clock.date(dt, "wd").rstrip(".").upper()
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
                    rain_str = say("weather.rain_chance", v=f"{float(pop):.0f}")
                elif precip is not None and float(precip) > 0:
                    rain_str = f"{words.number(float(precip), 1)} mm"
                if rain_str and h >= 100:                 # below that it would sit on the temperatures
                    rf = _fit_font(rain_str, int(day_w - 6), _s(14, fscale, 10, 22), min_sz=10, bold=True)
                    d.text((cx, y + int(h * 0.90)), rain_str, font=rf, fill=T.BLACK, anchor="mm")
        else:
            nf = T.font(_s(16, fscale, 12, 24), bold=True)
            d.text((fore_x + fore_w // 2, y + h // 2), _fit_text(say("weather.no_forecast"), fore_w - 12, nf), font=nf, fill=T.BLACK, anchor="mm")
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
            parts = _weather_details(humidity, wind, wind_unit, pressure_trend)
            txt, mf = _fit_parts(parts, w - 36, _s(14, fscale, 10, 22), "   •   ")
            if txt:
                d.text((x + 20, y + hero_h - 14), txt, font=mf, fill=T.BLACK, anchor="lm")

        d.line([(x + 10, y + hero_h), (x + w - 10, y + hero_h)], fill=T.BLACK, width=1)

        display_forecast = forecast[1:1 + max_f_days] if len(forecast) > max_f_days else forecast[:max_f_days]
        n_days = min(max_f_days, len(display_forecast))
        if n_days > 0:
            row_h = (h - hero_h - 12) / float(n_days)
            for i, fcast in enumerate(display_forecast[:n_days]):
                ry = y + hero_h + 6 + int(i * row_h)
                ry_mid = ry + int(row_h * 0.5)
                dt_raw = fcast.get("datetime")
                day_name = say("weather.day_n", n=i + 1)
                if dt_raw:
                    try:
                        dt = datetime.fromisoformat(str(dt_raw).replace("Z", "+00:00"))
                        day_name = clock.date(dt, "weekday").upper()
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
    d.text((cx, cy - r_scope + 9), say("compass.N"), font=cf, fill=T.BLACK, anchor="mm")
    d.text((cx + r_scope - 9, cy), say("compass.E"), font=cf, fill=T.BLACK, anchor="mm")
    d.text((cx, cy + r_scope - 9), say("compass.S"), font=cf, fill=T.BLACK, anchor="mm")
    d.text((cx - r_scope + 9, cy), say("compass.W"), font=cf, fill=T.BLACK, anchor="mm")

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


def _compass(cardinal: str) -> str:
    """A compass point in the screen's letters ("SW" is "SO" in French)."""
    return "".join(say(f"compass.{c}") if c in "NESW" else c for c in str(cardinal or ""))


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
        return                        # not fetched yet: never made-up aircraft (examples.py has them)

    style = str(el.get("style") or "card").lower()
    loc_name = str(el.get("location_name") or el.get("name") or "").strip()
    show_sub_metrics = el.get("show_sub_metrics") not in (False, "false", 0, "0")

    if not aircraft_list:
        mid_x = x + w // 2
        mid_y = y + h // 2
        _draw_icon_glyph(d, "mdi:radar", mid_x, mid_y - 26, 56)
        cf = T.font(_s(22, fscale, 16, 36), bold=True)
        d.text((mid_x, mid_y + 16), _fit_text(say("flight.clear"), w - 16, cf), font=cf, fill=T.BLACK, anchor="mm")
        none = say("flight.none_near", place=loc_name, r=radius) if loc_name else say("flight.none", r=radius)
        nf = T.font(_s(15, fscale, 11, 24), bold=False)
        d.text((mid_x, mid_y + 42), _fit_text(none, w - 16, nf), font=nf, fill=T.BLACK, anchor="mm")
        return

    sub_idx = int(el.get("sub_index", 0))
    sub_total = len(aircraft_list) if aircraft_list else 1
    if sub_idx >= sub_total:
        sub_idx = 0

    ac = aircraft_list[sub_idx]
    callsign = str(ac.get("callsign") or ac.get("icao24") or say("flight.unknown")).strip().upper()
    country = ac.get("country") or say("flight.commercial")
    dist_km = float(ac.get("distance_km") or 0.0)
    bearing = _compass(ac.get("bearing_cardinal")) or say("flight.overhead")
    km = lambda v: words.number(v, 1)
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
        hdr_title = say("flight.radar_at", place=loc_name.upper(), r=radius) if loc_name else say("flight.radar", r=radius)
        rf_hdr = T.font(_s(14, fscale, 10, 22), bold=True)
        d.text((x + 16, y + 18), hdr_title, font=rf_hdr, fill=T.BLACK, anchor="lm")
        target_str = say("flight.target", plane=f"{callsign} ({km(dist_km)} KM {bearing})")
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

        dist_badge = f"{km(dist_km)} KM {bearing}{loc_suffix}" if dist_km > 0 else (say("flight.overhead_at", place=loc_name) if loc_name else say("flight.overhead"))
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
            (say("flight.altitude"), f"{words.number(alt_ft, 0, group=True)} ft{climb_arrow}", f"{words.number(int(alt_m), 0, group=True)} m"),
            (say("flight.speed"), f"{speed_kts} kts", f"{speed_kmh} km/h"),
            (say("flight.heading"), f"{track}°", str(ac.get("icao24", "")).upper() or "--")
        ]

        for i, (label, val_main, val_sub) in enumerate(metrics_list):
            col_x = tx0 + int(i * cw)
            mid_col_x = col_x + int(cw * 0.5)
            if i > 0:
                d.line([(col_x, cols_y + 6), (col_x, cols_y + cols_h - 6)], fill=T.BLACK, width=1)
            lbl_f = _fit_font(label, int(cw - 10), _s(12, fscale, 9, 18), min_sz=9, bold=True)
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

    dist_badge = f"{km(dist_km)} KM {bearing}{loc_suffix}" if dist_km > 0 else (say("flight.overhead_at", place=loc_name) if loc_name else say("flight.overhead"))
    bf = T.font(_s(13, fscale, 10, 20), bold=True)
    bw = T.text_width(dist_badge, bf) + 18
    bh = 28
    bx1 = x + w - 20
    bx0 = bx1 - bw
    d.rounded_rectangle([(bx0, top_y + 4), (bx1, top_y + 4 + bh)], radius=6, fill=T.BLACK)
    d.text((bx0 + bw // 2, top_y + 4 + bh // 2), dist_badge, font=bf, fill=T.WHITE, anchor="mm")

    if sub_total > 1:
        more_txt = say("flight.n_of", i=sub_idx + 1, n=sub_total)
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
        (say("flight.altitude"), f"{words.number(alt_ft, 0, group=True)} ft{climb_arrow}", f"{words.number(int(alt_m), 0, group=True)} m"),
        (say("flight.ground_speed"), f"{speed_kts} kts", f"{speed_kmh} km/h"),
        (say("flight.heading"), f"{track}°", bearing),
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


def _draw_race_card(d, x, y, w, h, icon, name, detail, fscale):
    """A race's (or a season's) card in the box x, y, w, h: icon, name, detail, as one centred stack."""
    max_w = max(20, w - 24)
    gap = 6
    for name_px, detail_px, icon_px in ((20, 15, 50), (17, 13, 36), (15, 12, 0), (13, 11, 0)):
        nf = _fit_font(name, max_w, _s(name_px, fscale, 12, 32), min_sz=_s(name_px - 3, fscale, 11, 28))
        df = _fit_font(detail, max_w, _s(detail_px, fscale, 10, 24), min_sz=_s(detail_px - 2, fscale, 10, 22), bold=False)
        name_h, detail_h = nf.size + 2, (df.size + 2 if detail else 0)
        total = (icon_px + gap if icon_px else 0) + name_h + (gap // 2 + detail_h if detail else 0)
        if total <= h - 8:
            break
    else:
        return                          # no room for even a name: nothing outside the box
    cy = y + max(4, (h - total) // 2)
    mid_x = x + w // 2
    if icon_px:
        _draw_icon_glyph(d, icon, mid_x, cy + icon_px // 2, icon_px)
        cy += icon_px + gap
    d.text((mid_x, cy + name_h // 2), _fit_text(name, max_w, nf), font=nf, fill=T.BLACK, anchor="mm")
    cy += name_h + gap // 2
    if detail:
        d.text((mid_x, cy + detail_h // 2), _fit_text(detail, max_w, df), font=df, fill=T.BLACK, anchor="mm")


def _draw_sports_racing(img, d, el, raw_val, display=None):
    x, y, w, h = _clamp_box(el, 752, 235, display=display)
    fscale = _font_scale(el)
    show_border = el.get("show_border") not in (False, "false", 0, "0")
    if show_border:
        d.rounded_rectangle([(x, y), (x + w, y + h)], radius=12, outline=T.BLACK, width=1)

    data = _parse_val_json(raw_val)
    if not isinstance(data, dict):
        return                        # nothing yet (or ESPN is down): never a made-up race

    series = str(data.get("series") or "F1").upper()
    default_name = data.get("series_name") or series
    event_name = str(data.get("event_name") or default_name).upper()
    status = str(data.get("status") or "IN").upper()
    standings = data.get("standings") or []
    show_teams = el.get("show_teams") not in (False, "false", 0, "0")
    try:
        max_drv = max(4, min(10, int(el.get("max_drivers") or 10)))
    except (ValueError, TypeError):
        max_drv = 10

    # The badge at top right: the session and its state (racing.badge), its shorter words where the
    # longer don't fit ("QUALIFYING"); it steps aside where even those would leave the header no room
    forms = race.forms(data)
    bf = T.font(_s(13, fscale, 10, 20), bold=True)
    bx1 = x + w - 16
    badged = False
    for status_txt in forms:
        bw = T.text_width(status_txt, bf) + 16
        bx0 = bx1 - bw
        if bx0 - (x + 46) - 10 >= 56:
            d.rounded_rectangle([(bx0, y + 8), (bx1, y + 34)], radius=5, fill=T.BLACK)
            d.text((bx0 + bw // 2, y + 21), status_txt, font=bf, fill=T.WHITE, anchor="mm")
            badged = True
            break
    if not badged:
        bx0 = x + w - 4

    # Header: the series and the race; off-season, the series and its season. The middle names
    # what the header doesn't: before a race its circuit (or the race, when no calendar says where).
    off = status == "OFF"
    circuit = str(data.get("circuit") or "")
    if off:
        hero = str(data.get("event_name") or say("race.season_over"))
        named = str(data.get("season") or default_name).upper()
    elif circuit:
        hero, named = circuit, event_name
    else:
        hero, named = str(data.get("event_name") or default_name), str(default_name).upper()
    hdr_icon = "mdi:car-electric" if series == "FE" else "mdi:flag-checkered"
    _draw_icon_glyph(d, hdr_icon, x + 24, y + 21, 26)
    hf = T.font(_s(16, fscale, 12, 24), bold=True)
    room = max(20, bx0 - (x + 46) - 10)
    says = [series if named == series else f"{series} · {named}"]
    if standings and not badged:        # a leaderboard always says whose it is: the header does
        says = [f"{series} · {forms[0]}", f"{series} · {forms[-1]}", forms[-1]]
    header_txt = next((t for t in says if T.text_width(t, hf) <= room), None) or _fit_text(says[-1], room, hf)
    d.text((x + 46, y + 21), header_txt, font=hf, fill=T.BLACK, anchor="lm")

    d.line([(x + 14, y + 42), (x + w - 14, y + 42)], fill=T.BLACK, width=1)

    if not standings:
        # Before a race, or the off-season: an icon, a name and one line, centred under the header,
        # smaller where the box is, the icon left out where there's no room for it
        mid_icon = "mdi:car-electric" if series == "FE" else "mdi:racing-helmet"
        detail = race.detail(data)
        _draw_race_card(d, x, y + 42, w, h - 42, mid_icon, hero, detail, fscale)
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

    # The code column is as wide as the widest code shown ("HAM" is wider than "VER").
    code_w = max([T.text_width(str(dd.get("driver") or dd.get("code") or dd.get("name") or "DRV")[:3].upper(), drv_f)
                  for dd in display_drivers] + [T.text_width("VER", drv_f)])
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
        gap = race.gap(drv.get("gap") or drv.get("interval") or "")
        tyre = str(drv.get("tyre") or "")[:1].upper()

        d.text((cx0 + 2, ry_mid), pos_str, font=pos_f, fill=T.BLACK, anchor="lm")
        pos_w = max(32, T.text_width("P10", pos_f) + 6)
        d.text((cx0 + pos_w, ry_mid), code, font=drv_f, fill=T.BLACK, anchor="lm")

        off_x = cx0 + pos_w + max(44, code_w + 8)
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
        return                        # nothing yet, or no matches: never a made-up match

    league = str(data.get("league") or sport.words(el.get("league")).event).upper()
    venue = str(data.get("venue") or "").upper()
    header_title = f"{league} · {venue}" if venue else league
    clock = sport.badge(data, el.get("league")).upper()
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

    h_name = str(data.get("home_team") or say("sport.home")).upper()
    a_name = str(data.get("away_team") or say("sport.away")).upper()
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
    "box": _draw_box,
    "bar": _draw_bar,
    "bar_chart": _draw_bar_chart,
    "qr": _draw_qr,
    "curve": _draw_curve,
    "dynamic_grid": _draw_dynamic_grid,
    "calendar_month": _draw_calendar_month,
    "calendar_agenda": _draw_calendar_agenda,
    "todo_list": _draw_todo_list,
    "weather_forecast": _draw_weather_forecast,
    "flight_tracker": _draw_flight_tracker,
    "sports_racing": _draw_sports_racing,
    "sports_match": _draw_sports_match,
}


def _widget(draw):
    """A widget that draws itself from its box and the value the render cycle fetched for it."""
    def drawer(img, d, el, raw_val, display=None):
        return draw(img, d, _clamp_box(el, 712, 200, display=display), el, raw_val, scale=_font_scale(el))
    return drawer


# The widgets that size everything from their own box (render/hero.py).
WIDGETS = {
    "sun_times": sun.draw,
    "countdown": countdown.draw,
    "energy_total": energy.draw_total,
    "grid_now": energy.draw_grid,
    "energy_cost": energy.draw_cost,
    "now_playing": media.draw_now_playing,
    "tv_week": media.draw_tv_week,
    "world_clock": worldclock.draw,
    "notifications": needs_you.draw_notifications,
    "updates": needs_you.draw_updates,
    "badge": needs_you.draw_badge,
}
DRAWERS.update({t: _widget(fn) for t, fn in WIDGETS.items()})


def element_text(el, vals, idx):
    """The string an element should display, after template resolution."""
    if el["type"] == "number":
        return _fmt_number(vals.get(idx, el.get("value", "")), el)
    if el["type"] == "text":
        got = vals.get(idx)
        if binding.clock_pattern(el) is not None:
            base = binding.now_text(el, got)         # the add-on's clock, written in the screen's language
        elif binding.shows_time(el):
            base = binding.shown(el, got)            # the time Home Assistant gave, in the screen's language
        else:
            base = str(got) if got is not None else str(el.get("value", "") or "")
        if el.get("show") == "unit" and not (isinstance(el.get("value"), str) and el.get("value").strip()):
            # The unit the value is shown in right now, in the user's words.
            word = units.unit_for(base, el)
            for find, repl in (el.get("replace") or {}).items():
                if word == str(find):
                    word = str(repl)
                    break
            return f"{el.get('prefix', '')}{word}{el.get('suffix', '')}"
        if not (isinstance(el.get("value"), str) and el.get("value").strip()):
            return f"{el.get('prefix', '')}{base}{el.get('suffix', '')}"
        return base
    return ""


GROUP_STYLES = ("outline", "pill", "invert")
GROUP_PAD = 10


def group_box(group: dict, members: list[dict], canvas: tuple[int, int]) -> tuple[int, int, int, int] | None:
    """A group's shape: around its members' boxes, `pad` out, kept on the canvas. None without members."""
    boxes = [(e["x"], e["y"], e["x"] + e["w"], e["y"] + e["h"]) for e in members
             if all(isinstance(e.get(k), (int, float)) for k in ("x", "y", "w", "h"))]
    if not boxes:
        return None
    try:
        pad = max(0, min(60, int(group.get("pad", GROUP_PAD))))
    except (TypeError, ValueError):
        pad = GROUP_PAD
    cw, ch = canvas
    x0 = max(0, min(b[0] for b in boxes) - pad)
    y0 = max(0, min(b[1] for b in boxes) - pad)
    x1 = min(cw - 1, max(b[2] for b in boxes) + pad)
    y1 = min(ch - 1, max(b[3] for b in boxes) + pad)
    return (int(x0), int(y0), int(x1 - x0), int(y1 - y0)) if x1 > x0 and y1 > y0 else None


def _group_radius(group: dict, w: int, h: int) -> int:
    if group.get("style") == "pill":
        return min(w, h) // 2
    try:
        return max(0, min(min(w, h) // 2, int(group.get("radius", 14))))
    except (TypeError, ValueError):
        return 14


def _hidden(vals, i) -> bool:
    vis_key = f"__vis_{i}"
    if vis_key not in (vals or {}):
        return False
    return str(vals.get(vis_key) or "").strip().lower() in ("false", "0", "no", "off", "none", "unavailable", "unknown", "")


def render_page(page, vals, *, clock="", label="", footer=None, page_no=None, item_no=0, items=1, series=None,
                metrics=None, orientation=0, distance_m=3.0, display=None, date_for_time=None):
    """Draw one page. `vals` maps element index -> resolved template result.

    `footer` is the screen's theme.footer_plan(); page_no/item_no/items say
    which pills this page shows. Without one, the footer has the clock and `label`.
    `date_for_time`: now, in Home Assistant's time zone, for a device that sleeps
    between updates: it draws the date where the page shows the time (clocktime.py)."""
    swapped = set()
    if date_for_time is not None:
        page, vals, swapped = clocktime.date_for_time(page, vals, date_for_time)
    img, d = T.new_canvas(orientation=orientation, display=display)
    els = page.get("elements", [])
    # Groups: a style around several elements, shaped by the ones showing now.
    shown = {e.get("id"): e for i, e in enumerate(els) if isinstance(e, dict) and e.get("id")
             and e.get("type") != "group" and not _hidden(vals, i)}
    inverts = []
    for i, el in enumerate(els):
        if el.get("type") == "group":
            if el.get("style") not in GROUP_STYLES or _hidden(vals, i):
                continue
            box = group_box(el, [shown[m] for m in el.get("members") or [] if m in shown], img.size)
            if box is None:
                continue
            x, y, w, h = box
            rad = _group_radius(el, w, h)
            if el["style"] == "invert":
                inverts.append((x, y, w, h, rad))          # after everything inside is drawn
            else:
                d.rounded_rectangle([(x, y), (x + w, y + h)], radius=rad, outline=T.BLACK, width=2)
            continue
        drawer = DRAWERS.get(el.get("type"))
        if drawer is None:
            continue
        # Per-element conditional visibility (show_if)
        if _hidden(vals, i):
            continue
        if units.follows(el):
            # The unit after it is its sensor's now, whatever it was when the page was made.
            el = {**el, "suffix": units.suffix_for((vals or {}).get(f"__unit_{i}"))}
        try:
            if el["type"] == "icon" and isinstance(el.get("state_icons"), dict):
                # Drawn by its entity's state, with its own icon when no state matches (or none yet).
                el = icon_in_state(el, vals.get(i))
            if el["type"] in ("curve", "bar_chart"):
                drawer(img, d, el, "", (series or {}).get(i), display=display)
            elif el["type"] == "todo_list":
                got = []
                drawer(img, d, el, vals.get(i), got, distance_m=distance_m, display=display)
                if metrics is not None and got:
                    metrics.append({"i": i, **got[0]})
            elif el["type"] in ("text", "number"):
                got = []
                drawer(img, d, el, element_text(el, vals, i), got, distance_m=distance_m, display=display)
                if metrics is not None and got:
                    entry = {"i": i, **got[0]}
                    if i in swapped:
                        entry["date_for_time"] = True      # the editor says so on the element
                    if el["type"] == "text" and clocktime.shows_time(el):
                        entry["shows_time"] = True          # the editor asks here, never its own string match
                    if el["type"] == "number":
                        raw = vals.get(i, el.get("value", ""))
                        try:
                            float(str(raw).strip())
                        except (TypeError, ValueError):
                            # "--" on the panel means exactly this and nothing
                            # else, so say so rather than let it look broken.
                            entry["not_a_number"] = str(raw)[:60]
                    metrics.append(entry)
            elif el["type"] in WIDGETS:
                size = drawer(img, d, el, vals.get(i), display=display)
                if isinstance(size, int) and metrics is not None:
                    # A widget that says how big its text is gets the legibility note (the badge's number).
                    mm, verdict = legibility(size, distance_m=distance_m, display=display)
                    metrics.append({"i": i, "size": size, "mm": mm, "verdict": verdict, "lines": 1, "overflow": False})
                if i in swapped and metrics is not None:
                    # A sleeping device: the editor says what it shows instead. Only a world clock is a widget
                    # that shows the time, and it shows each city's hours ahead or behind, not the date.
                    metrics.append({"i": i, "hours_apart": True} if el["type"] == "world_clock" else {"i": i, "date_for_time": True})
                if el["type"] == "countdown" and metrics is not None:
                    # What its page does now (showing, waiting, passed), for the editor to say.
                    data = vals.get(i) if isinstance(vals.get(i), dict) else {}
                    metrics.append({"i": i, "countdown": countdown.status(el, todo.now_in(data.get("tz")))})
            elif el["type"] in ("bar", "qr", "dynamic_grid", "calendar_month", "calendar_agenda", "weather_forecast", "flight_tracker", "sports_racing", "sports_match"):
                drawer(img, d, el, vals.get(i), display=display)
            else:
                drawer(img, d, el, element_text(el, vals, i), display=display)
        except Exception:
            # One bad element must never cost the whole page.
            continue
    for x, y, w, h, rad in inverts:
        mask = Image.new("L", img.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle([(x, y), (x + w, y + h)], radius=rad, fill=255)
        img.paste(ImageOps.invert(img), (0, 0), mask)
    if footer is None:
        footer = T.footer_plan(clock=clock, orientation=orientation, display=display)
    T.footer(d, footer, page=page_no, item=item_no, items=items, label=label)
    return img


def collect_templates(page):
    """Every templated string on a page, as {element_index: template}.

    Elements may carry a raw `value` template or a structured entity
    binding; binding.template_for resolves either to Jinja.
    """
    out = {}
    for i, el in enumerate(page.get("elements", [])):
        show_if = str(el.get("show_if") or "").strip()
        if show_if:
            out[f"__vis_{i}"] = show_if
        if el.get("type") in ("text", "number", "bar", "qr"):
            tpl = template_for(el)
            if tpl and "{{" in tpl:
                out[i] = tpl
            if units.follows(el):              # its sensor's unit, asked at each render (review 2 #3)
                out[f"__unit_{i}"] = "{{ state_attr('%s', 'unit_of_measurement') or '' }}" % binding._quote(el["entity"].strip())
        elif el.get("type") == "icon" and isinstance(el.get("state_icons"), dict) and str(el.get("entity") or "").strip():
            # An icon that follows its entity: the state picks one of its state_icons.
            tpl = template_for({"entity": el["entity"], "show": "state"})
            if tpl:
                out[i] = tpl
        elif el.get("type") == "dynamic_grid" and not el.get("batteries"):    # batteries by rule: fetched (widgets.py)
            items = el.get("items", [])
            ents = [it.get("entity", "").strip() for it in items if isinstance(it, dict) and it.get("entity", "").strip()]
            if ents:
                ents_quoted = ", ".join(f"'{binding._quote(e)}'" for e in ents)
                tpl = (
                    "[{% for e in [" + ents_quoted + "] %}"
                    '{"entity": {{ e | to_json }}, '
                    '"state": {{ states(e) | to_json }}, '
                    '"name": {{ (state_attr(e, "friendly_name") or "") | to_json }}, '
                    '"unit": {{ (state_attr(e, "unit_of_measurement") or "") | to_json }}, '
                    '"device_class": {{ (state_attr(e, "device_class") or "") | to_json }}, '
                    '"changed": {{ ((as_timestamp(states[e].last_changed) | timestamp_local) if (states[e] is defined and states[e] is not none and states[e].last_changed is defined) else "") | to_json }}}'
                    "{% if not loop.last %},{% endif %}{% endfor %}]"
                )
                out[i] = tpl
        elif el.get("type") == "weather_forecast" and str(el.get("entity") or "").strip():
            # No entity: the render cycle picks the first Home Assistant has (widgets.py); never a guessed ID.
            ent = str(el.get("entity") or "").strip()
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

