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


def mdi_codepoint(name):
    """Map 'mdi:washing-machine' (or bare 'washing-machine') to a codepoint."""
    global _mdi_codepoints
    if _mdi_codepoints is None:
        try:
            _mdi_codepoints = json.loads(_MDI_MAP.read_text())
        except Exception:
            _mdi_codepoints = {}
    return _mdi_codepoints.get(str(name).removeprefix("mdi:"))


def _fit_glyph(ch, box_w, box_h, start=200):
    """Largest font size at which the glyph's ink fits the box."""
    lo, hi, best = 8, start, 8
    while lo <= hi:
        mid = (lo + hi) // 2
        f = ImageFont.truetype(str(_MDI_TTF), mid)
        l, t, r, b = f.getbbox(ch)
        if (r - l) <= box_w and (b - t) <= box_h:
            best, lo = mid, mid + 1
        else:
            hi = mid - 1
    return best


def _anchor_x(align, x, w):
    return {"left": x, "center": x + w // 2, "right": x + w}.get(align, x)


def _draw_text(img, d, el, text, metrics=None):
    if not text:
        return
    w, h = int(el.get("w", 200)), int(el.get("h", 60))
    align = el.get("align", "left")
    bold = el.get("bold", True)

    size = int(el["size"]) if el.get("size") else T.fit_size(text, w, h, 200, bold=bold)
    f = T.font(size, bold=bold)
    if metrics is not None:
        mm, verdict = legibility(size)
        metrics.append({"size": size, "mm": mm, "verdict": verdict,
                        "overflow": T.text_width(text, f) > w})
    ax = _anchor_x(align, int(el["x"]), w)
    anchor = {"left": "lm", "center": "mm", "right": "rm"}.get(align, "lm")
    d.text((ax, int(el["y"]) + h // 2), text, font=f, fill=T.BLACK, anchor=anchor)


def _draw_icon(img, d, el, _text):
    name = str(el.get("icon", ""))
    if name.startswith("custom:"):
        # Hand-drawn art that beats any icon-font equivalent.
        from . import pages
        art = {"cat-sitting": pages.draw_cat}.get(name.removeprefix("custom:"))
        if art:
            art(d, int(el["x"]), int(el["y"]), int(el.get("h", 200)))
        return
    cp = mdi_codepoint(name)
    if cp is None:
        return
    ch = chr(cp)
    w, h = int(el.get("w", 100)), int(el.get("h", 100))
    size = int(el["size"]) if el.get("size") else _fit_glyph(ch, w, h)
    f = ImageFont.truetype(str(_MDI_TTF), size)
    d.text((int(el["x"]) + w // 2, int(el["y"]) + h // 2), ch,
           font=f, fill=T.BLACK, anchor="mm")


def _draw_line(img, d, el, _text):
    x, y = int(el["x"]), int(el["y"])
    w, h = int(el.get("w", 200)), int(el.get("h", 2))
    thick = max(1, int(el.get("thickness", 2)))
    if h >= w:                                   # taller than wide -> vertical
        d.line([(x + w // 2, y), (x + w // 2, y + h)], fill=T.BLACK, width=thick)
    else:
        d.line([(x, y + h // 2), (x + w, y + h // 2)], fill=T.BLACK, width=thick)


def _draw_curve(img, d, el, _text, series=None):
    """Filled area chart, dot-screened, with a solid top edge."""
    pts = series or el.get("_series") or []
    if len(pts) < 2:
        return
    x0, y0 = int(el["x"]), int(el["y"])
    w, h = int(el.get("w", 250)), int(el.get("h", 100))
    x1, y1 = x0 + w, y0 + h
    peak = max(pts) or 1
    n = len(pts)
    coords = [(x0 + i * w / (n - 1), y1 - (v / peak) * h) for i, v in enumerate(pts)]

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
        return el.get("fallback", "--")
    dec = int(el.get("decimals", 0))
    return f"{v:.{dec}f}"


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
        if got is not None:
            return str(got)
        return str(el.get("value", "") or "")
    return ""


def render_page(page, vals, *, clock="", label="", battery_pct=0, series=None,
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
                    metrics.append({"i": i, **got[0]})
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
