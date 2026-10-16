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
from .binding import template_for

_FONTS = Path(__file__).parent.parent / "fonts"
_MDI_TTF = _FONTS / "mdi.ttf"
_MDI_MAP = _FONTS / "mdi-codepoints.json"

_mdi_codepoints = None

MM_PER_PX = 139.1 / T.W          # ~0.176 mm; the panel is 139mm wide


# Cap height is ~0.7em, and legibility bands come from the 3m measurements
# in ARCHITECTURE.md.
def legibility(size_px):
    mm = size_px * 0.7 * MM_PER_PX
    if mm < 4.4:
        verdict = "too small at 3 m"
    elif mm < 13:
        verdict = "squint at 3 m"
    elif mm < 19:
        verdict = "comfortable"
    else:
        verdict = "effortless"
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


def _clamp_box(el, default_w=200, default_h=60):
    x = max(-T.W, min(T.W * 2, int(el.get("x", 0))))
    y = max(-T.H, min(T.H * 2, int(el.get("y", 0))))
    w = max(1, min(T.W * 2, int(el.get("w", default_w))))
    h = max(1, min(T.H * 2, int(el.get("h", default_h))))
    return x, y, w, h


def _draw_text(img, d, el, text, metrics=None):
    if not text:
        return
    x, y, w, h = _clamp_box(el, 200, 60)
    align = el.get("align", "left")
    bold = el.get("bold", True)

    size = max(8, min(T.H, int(el["size"]))) if el.get("size") else T.fit_size(text, w, h, 200, bold=bold)
    f = T.font(size, bold=bold)
    if metrics is not None:
        mm, verdict = legibility(size)
        t = text.strip()
        metrics.append({"size": size, "mm": mm, "verdict": verdict,
                        "overflow": T.text_width(text, f) > w,
                        # A list or dict rendered as a string is almost always
                        # the wrong attribute picked, not a deliberate choice.
                        "collection": t.startswith(("[", "{")) and t.endswith(("]", "}"))})
    ax = _anchor_x(align, x, w)
    anchor = {"left": "lm", "center": "mm", "right": "rm"}.get(align, "lm")
    d.text((ax, y + h // 2), text, font=f, fill=T.BLACK, anchor=anchor)


def _draw_icon(img, d, el, _text):
    name = str(el.get("icon", ""))
    x, y, w, h = _clamp_box(el, 100, 100)
    if name.startswith("custom:"):
        art = CUSTOM_ICONS.get(name.removeprefix("custom:"))
        if art:
            art(d, x, y, h)
        return
    cp = mdi_codepoint(name)
    if cp is None:
        return
    ch = chr(cp)
    size = max(8, min(T.H, int(el["size"]))) if el.get("size") else _fit_glyph(ch, w, h)
    f = _mdi_font(size)
    d.text((x + w // 2, y + h // 2), ch, font=f, fill=T.BLACK, anchor="mm")


def _draw_line(img, d, el, _text):
    x, y, w, h = _clamp_box(el, 200, 2)
    thick = max(1, min(32, int(el.get("thickness", 2))))
    if h >= w:                                   # taller than wide -> vertical
        d.line([(x + w // 2, y), (x + w // 2, y + h)], fill=T.BLACK, width=thick)
    else:
        d.line([(x, y + h // 2), (x + w, y + h // 2)], fill=T.BLACK, width=thick)


def _draw_curve(img, d, el, _text, series=None):
    """Filled area chart, dot-screened, with a solid top edge."""
    pts = [float(p) for p in (series or el.get("_series") or []) if p is not None]
    if len(pts) < 2:
        return
    x0, y0, w, h = _clamp_box(el, 250, 100)
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


DRAWERS = {
    "text": _draw_text,
    "number": _draw_text,          # same drawing, value formatted first
    "icon": _draw_icon,
    "line": _draw_line,
    "curve": _draw_curve,
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
                metrics=None):
    """Draw one page. `vals` maps element index -> resolved template result."""
    img, d = T.new_canvas()
    for i, el in enumerate(page.get("elements", [])):
        drawer = DRAWERS.get(el.get("type"))
        if drawer is None:
            continue
        try:
            if el["type"] == "curve":
                drawer(img, d, el, "", (series or {}).get(i))
            elif el["type"] in ("text", "number"):
                got = []
                drawer(img, d, el, element_text(el, vals, i), got)
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
            else:
                drawer(img, d, el, element_text(el, vals, i))
        except Exception:
            # One bad element must never cost the whole page.
            continue
    T.footer(d, clock=clock, label=label, battery_pct=battery_pct)
    return img


def collect_templates(page):
    """Every templated string on a page, as {element_index: template}.

    Elements may carry a raw `value` template or a structured entity
    binding; binding.template_for resolves either to Jinja.
    """
    out = {}
    for i, el in enumerate(page.get("elements", [])):
        if el.get("type") not in ("text", "number"):
            continue
        tpl = template_for(el)
        if tpl and "{{" in tpl:
            out[i] = tpl
    return out
