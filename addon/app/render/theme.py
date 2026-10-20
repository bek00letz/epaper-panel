"""Geometry, type and drawing helpers for the CrowPanel 5.79" e-paper panel.

The panel is 792x272 px, 1-bit, about 139 x 48 mm (145 dpi). Everything here
works in panel pixels so the numbers match the design directly.

There is no grey on a 1-bit panel: hierarchy is carried by SIZE, not tone.
Small secondary text is solid black and simply smaller. Only text above
~90 px can be screened (see screen) and still read as a deliberate grey.
"""
from functools import lru_cache
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

DISPLAYS = {
    "crowpanel_579": {
        "kind": "crowpanel",
        "id": "crowpanel_579",
        "name": "CrowPanel 5.79\"",
        "sku": "DIS08792E",
        "w": 792,
        "h": 272,
        "mm_w": 139.1,
        "mm_h": 47.7,
        "margin": 40,
        "esphome_model": "5.79in",
        "esphome_component": "github://ESPBoards/esphome-lvgl-crowpanel-epaper-5.79-4.2",
    },
    "crowpanel_420": {
        "kind": "crowpanel",
        "id": "crowpanel_420",
        "name": "CrowPanel 4.2\"",
        "sku": "DIS08042E",
        "w": 400,
        "h": 300,
        "mm_w": 84.8,
        "mm_h": 63.6,
        "margin": 24,
        "esphome_model": "4.2in",
        "esphome_component": "github://ESPBoards/esphome-lvgl-crowpanel-epaper-5.79-4.2",
    },
    "crowpanel_290": {
        "kind": "crowpanel",
        "id": "crowpanel_290",
        "name": "CrowPanel 2.9\"",
        "sku": "DIS08029E",
        "w": 296,
        "h": 128,
        "mm_w": 66.9,
        "mm_h": 29.1,
        "margin": 16,
        "esphome_model": "2.90inv2",
        "esphome_component": "waveshare_epaper",
    },
    "crowpanel_750": {
        "kind": "crowpanel",
        "id": "crowpanel_750",
        "name": "CrowPanel 7.5\"",
        "sku": "DIS08075E",
        "w": 800,
        "h": 480,
        "mm_w": 163.2,
        "mm_h": 97.9,
        "margin": 40,
        "esphome_model": "7.50inv2",
        "esphome_component": "waveshare_epaper",
    },
    "crowpanel_102": {
        "kind": "crowpanel",
        "id": "crowpanel_102",
        "name": "CrowPanel 10.2\"",
        "sku": "DIS08102E",
        "w": 960,
        "h": 640,
        "mm_w": 215.0,
        "mm_h": 143.4,
        "margin": 48,
        "esphome_model": "10.2in",
        "esphome_component": "waveshare_epaper",
    },
}

DEFAULT_DISPLAY = "crowpanel_579"


def get_display(key=None):
    """Retrieve display profile by model key; defaults to CrowPanel 5.79\"."""
    if not key or str(key).lower() not in DISPLAYS:
        return DISPLAYS[DEFAULT_DISPLAY]
    return DISPLAYS[str(key).lower()]


W, H = 792, 272
WHITE, BLACK = 255, 0

MARGIN       = 40
FOOTER_SIZE  = 20
BODY_SIZE    = 26    # the "worthwhile when passing by" tier
LABEL_SIZE   = 30

import re

# Fonts live beside the app, not inside the render package. Check both so
# this works whether run as a package or as a loose script, and check system font directories.
_FONT_DIRS = [
    Path(__file__).parent.parent / "fonts",
    Path(__file__).parent / "fonts",
    Path("/usr/share/fonts"),
    Path("/usr/share/fonts/noto"),
    Path("/usr/share/fonts/dejavu"),
    Path("/usr/share/fonts/truetype"),
]


def _font_file(*names):
    for d in _FONT_DIRS:
        for n in names:
            p = d / n
            if p.exists():
                return str(p)
            # Check subdirectories
            if d.is_dir():
                for sub in d.glob(f"**/{n}"):
                    if sub.exists():
                        return str(sub)
    raise FileNotFoundError(f"none of {names} in {[str(d) for d in _FONT_DIRS]}")


def _font_file_opt(*names, fallback_path=None):
    try:
        return _font_file(*names)
    except FileNotFoundError:
        return fallback_path


FONTS = {
    "lato": {
        "bold": _font_file("Lato-Bold.ttf", "DejaVuSans-Bold.ttf"),
        "regular": _font_file("Lato-Regular.ttf", "DejaVuSans.ttf"),
    },
    "dejavu": {
        "bold": _font_file("DejaVuSans-Bold.ttf", "Lato-Bold.ttf"),
        "regular": _font_file("DejaVuSans.ttf", "Lato-Regular.ttf"),
    },
    "mono": {
        "bold": _font_file("RobotoMono-Variable.ttf", "DejaVuSans-Bold.ttf"),
        "regular": _font_file("RobotoMono-Variable.ttf", "DejaVuSans.ttf"),
    },
    "cjk": {
        "bold": _font_file_opt("NotoSansCJK-Bold.ttc", "NotoSansCJK-Bold.otf", "NotoSansSC-Bold.ttf", fallback_path=_font_file("DejaVuSans-Bold.ttf")),
        "regular": _font_file_opt("NotoSansCJK-Regular.ttc", "NotoSansCJK-Regular.otf", "NotoSansSC-Regular.ttf", fallback_path=_font_file("DejaVuSans.ttf")),
    },
    "arabic": {
        "bold": _font_file_opt("NotoSansArabic-Bold.ttf", fallback_path=_font_file("DejaVuSans-Bold.ttf")),
        "regular": _font_file_opt("NotoSansArabic-Regular.ttf", fallback_path=_font_file("DejaVuSans.ttf")),
    },
    "hebrew": {
        "bold": _font_file_opt("NotoSansHebrew-Bold.ttf", fallback_path=_font_file("DejaVuSans-Bold.ttf")),
        "regular": _font_file_opt("NotoSansHebrew-Regular.ttf", fallback_path=_font_file("DejaVuSans.ttf")),
    },
}

BOLD    = FONTS["lato"]["bold"]
REGULAR = FONTS["lato"]["regular"]


def detect_script(text: str) -> str:
    """Detect script to route font fallback cleanly without rendering missing glyph boxes."""
    if not text:
        return "latin"
    # CJK (Chinese, Japanese, Korean)
    if re.search(r"[\u3000-\u9fff\uac00-\ud7af\uff00-\uffef]", text):
        return "cjk"
    # Hebrew
    if re.search(r"[\u0590-\u05ff]", text):
        return "hebrew"
    # Arabic
    if re.search(r"[\u0600-\u06ff\u0750-\u077f]", text):
        return "arabic"
    # Cyrillic
    if re.search(r"[\u0400-\u04ff]", text):
        return "cyrillic"
    # Greek
    if re.search(r"[\u0370-\u03ff]", text):
        return "greek"
    return "latin"


@lru_cache(maxsize=128)
def _cached_font(path: str, size: int):
    return ImageFont.truetype(path, size)


def font(size, bold=True, family="lato", text=None):
    clamped = max(8, min(360, int(size)))
    fam_key = str(family or "lato").lower()
    
    # Auto-resolve font family by detecting characters in text if present
    if text and fam_key in ("lato", "mono", "auto"):
        script = detect_script(str(text))
        if script in ("cyrillic", "greek"):
            fam_key = "dejavu"
        elif script in FONTS:
            fam_key = script

    fam = FONTS.get(fam_key, FONTS["lato"])
    path = fam["bold"] if bold else fam["regular"]
    return _cached_font(path, clamped)


def canvas_dims(orientation=0, display=None):
    """Logical (width, height) for the editor and renderer before panel rotation."""
    disp = get_display(display)
    dw, dh = disp["w"], disp["h"]
    if int(orientation or 0) in (90, 270):
        return dh, dw
    return dw, dh


def new_canvas(orientation=0, display=None):
    """8-bit greyscale working canvas; converted to 1-bit on save."""
    cw, ch = canvas_dims(orientation, display)
    img = Image.new("L", (cw, ch), WHITE)
    return img, ImageDraw.Draw(img)


def to_1bit(img):
    """Hard threshold, no dithering -- crisp edges are what e-ink wants."""
    return img.convert("1", dither=Image.Dither.NONE)


def orient_for_panel(img, orientation=0, display=None):
    """Rotate a rendered logical page into the physical panel buffer."""
    deg = int(orientation or 0) % 360
    if deg == 180:
        return img.transpose(Image.Transpose.ROTATE_180)
    if deg == 90:
        return img.transpose(Image.Transpose.ROTATE_270)
    if deg == 270:
        return img.transpose(Image.Transpose.ROTATE_90)
    return img


def text_width(s, f):
    b = f.getbbox(s)
    return b[2] - b[0]


def fit_size(s, max_w, max_h, start, floor=24, bold=True, family="lato"):
    """Largest point size at which s fits max_w x max_h. Binary search."""
    lo, hi, best = floor, max(floor, min(360, int(start))), floor
    while lo <= hi:
        mid = (lo + hi) // 2
        f = font(mid, bold, family=family, text=s)
        asc, desc = f.getmetrics()
        if text_width(s, f) <= max_w and (asc + desc) <= max_h:
            best, lo = mid, mid + 1
        else:
            hi = mid - 1
    return best


def wrap_lines(s, f, max_w):
    """Greedy word wrap of s into lines no wider than max_w at font f.

    A word longer than the line keeps its own line (and overflows), rather
    than being cut mid-word. Line breaks already in s are kept.
    """
    out = []
    for para in str(s).split("\n"):
        words, line = para.split(), ""
        if not words:
            out.append("")
            continue
        for w in words:
            trial = f"{line} {w}" if line else w
            if line and text_width(trial, f) > max_w:
                out.append(line)
                line = w
            else:
                line = trial
        out.append(line)
    return out


def fit_wrapped(s, max_w, max_h, start, floor=12, bold=True, family="lato"):
    """Largest size at which s, wrapped onto lines, fits max_w x max_h."""
    lo, hi, best = floor, max(floor, min(360, int(start))), floor
    while lo <= hi:
        mid = (lo + hi) // 2
        f = font(mid, bold, family=family, text=s)
        asc, desc = f.getmetrics()
        lines = wrap_lines(s, f, max_w)
        if len(lines) * (asc + desc) <= max_h and all(text_width(l, f) <= max_w for l in lines):
            best, lo = mid, mid + 1
        else:
            hi = mid - 1
    return best


def wrap_two(s):
    """Split s into two balanced lines on a word boundary. None if impossible."""
    words = s.split()
    if len(words) < 2:
        return None
    best, score = None, None
    for i in range(1, len(words)):
        a, b = " ".join(words[:i]), " ".join(words[i:])
        d = abs(len(a) - len(b))
        if score is None or d < score:
            best, score = (a, b), d
    return best


def screen(img, box):
    """Knock a 50% checkerboard through everything inside box.

    Only legible as 'grey' at large sizes; used for the empty state so it
    reads quieter than a real title without needing a second colour.
    """
    x0, y0, x1, y1 = box
    cw, ch = img.size
    px = img.load()
    for y in range(max(0, y0), min(ch, y1)):
        for x in range(max(0, x0) + (y % 2), min(cw, x1), 2):
            px[x, y] = WHITE


# The footer before footer_plan(). Disabled: nothing calls it. Kept until the
# planned footer has run on real panels, then removed (ask first).
def footer_geometry_v1(*, clock, cat_label="", has_sub=False, battery_pct=None, orientation=0, display=None):
    """Where the footer pills sit, in logical (pre-rotation) pixels.

    The one source for this geometry: footer() draws with it, build_frames sends
    it to the panel in the frame file, and the panel draws its highlight and
    padlocks on top using exactly these numbers.
    """
    cw, ch = canvas_dims(orientation, display=display)
    disp = get_display(display)
    margin = disp["margin"] if cw >= 400 else min(disp["margin"], 16)
    footer_size = 14 if ch < 200 else (18 if ch < 400 else FOOTER_SIZE)
    f = font(footer_size, bold=False)
    cat_f = font(13, bold=True)
    pill_y0, pill_y1 = ch - 28, ch - 4
    # The pill starts after the clock's real width, with a gap that scales with the
    # clock's size (11 px at 18, 12 at 20). Lato's digits all share one width, so
    # the pill stays put as the minutes change.
    cat_x0 = margin + text_width(clock, f) + round(footer_size * 0.6)
    bat_w = text_width(f"{battery_pct} %", f) + 12 if (battery_pct is not None and battery_pct > 0) else 0
    sub_w = 48
    sub_x1 = cw - margin - bat_w
    sub_x0 = sub_x1 - sub_w
    cat_w = text_width(cat_label, cat_f) + 20 if cat_label else 0
    max_cat_w = max(40, (sub_x0 - cat_x0 - 8) if has_sub else (sub_x1 - cat_x0 - 8))
    cat_w = min(cat_w, max_cat_w)
    return {
        "canvas": (cw, ch), "margin": margin, "footer_size": footer_size,
        "pill_y0": pill_y0, "pill_y1": pill_y1,
        "cat_x0": cat_x0, "cat_x1": cat_x0 + cat_w, "cat_w": cat_w,
        "sub_x0": sub_x0, "sub_x1": sub_x1,
    }


def footer_v1(draw, *, clock, label="", cat_label="", sub_label="", battery_pct=None, orientation=0, display=None):
    g = footer_geometry_v1(clock=clock, cat_label=cat_label, has_sub=bool(sub_label),
                        battery_pct=battery_pct, orientation=orientation, display=display)
    cw, ch = g["canvas"]
    margin, footer_size = g["margin"], g["footer_size"]
    rule_y = ch - int(footer_size * 1.8)
    base_y = ch - int(footer_size * 0.7)
    f = font(footer_size, bold=False)
    draw.line([(margin, rule_y), (cw - margin, rule_y)], fill=BLACK, width=1)
    draw.text((margin, base_y), clock, font=f, fill=BLACK, anchor="ls")

    if cat_label:
        cat_f = font(13, bold=True)
        pill_y0, pill_y1 = g["pill_y0"], g["pill_y1"]
        cat_x0, cat_x1 = g["cat_x0"], g["cat_x1"]
        sub_x0, sub_x1 = g["sub_x0"], g["sub_x1"]

        draw.rounded_rectangle([cat_x0, pill_y0, cat_x1, pill_y1], radius=4, outline=BLACK, width=1)
        draw.text(((cat_x0 + cat_x1) // 2, (pill_y0 + pill_y1) // 2), cat_label, font=cat_f, fill=BLACK, anchor="mm")

        if sub_label:
            draw.rounded_rectangle([sub_x0, pill_y0, sub_x1, pill_y1], radius=4, outline=BLACK, width=1)
            draw.text(((sub_x0 + sub_x1) // 2, (pill_y0 + pill_y1) // 2), sub_label, font=cat_f, fill=BLACK, anchor="mm")
    elif label:
        draw.text((cw // 2, base_y), label, font=f, fill=BLACK, anchor="ms")

    if battery_pct is not None and battery_pct > 0:
        draw.text((cw - margin, base_y), f"{battery_pct} %", font=f, fill=BLACK, anchor="rs")


# ---------------------------------------------------------------- the footer
#
# One plan per screen and strip of pages, from footer_plan(). footer() draws
# with it, build_frames sends its numbers to the panel, and the panel draws its
# highlight and padlocks on top of them (components/epf/epf_core.h):
#   - the page pill's padlock at cat_x1 + 8, the screen's padlock at
#     sub_x0 - 30 (or sub_x1 - 22 on a page with one item); both 22 x 20 at
#     pill_y0 + 2;
#   - the highlight inverts the page pill or the item pill.
# What matters most keeps its place longest: the clock (it says when the panel
# last heard from us), then the counts (they're how you find your way), then
# room for the padlocks (they say why the panel isn't paging), then the name.

PILL_FONT = 13
LOCK_W, LOCK_GAP = 22, 8        # the panel's padlock badge, and its gap from the pill
LOCK_SLOT = LOCK_GAP + LOCK_W + LOCK_GAP
ELLIPSIS = "…"

# What gives way, in order, when a footer doesn't fit. Each step keeps the
# ones before it. The name gives way before all of these, page by page.
FOOTER_STEPS = (
    {},
    {"pad": 6},                                  # tighter pills
    {"pad": 6, "shared_lock": True},             # both padlocks in one spot between the pills
    {"pad": 6, "shared_lock": True, "short": True},   # "2" for "2/5", "1" for "1/3"
    {"pad": 4, "shared_lock": True, "short": True, "margin": 8},
    {"pad": 4, "shared_lock": True, "short": True, "margin": 8, "pill_font": 11},   # smaller pill text
)
CLOCK_FLOOR = 11                 # smallest clock, the last thing to give way


def _footer_size(ch):
    return 14 if ch < 200 else (18 if ch < 400 else FOOTER_SIZE)


def band_height(ch):
    """Height of the footer band on a canvas `ch` px tall, hairline included.

    The one place this is decided: arrange.py and the editor (through
    canvas_geometry()) ask here."""
    return round(_footer_size(ch) * 1.8)


def footer_band(orientation=0, display=None):
    """Height of the footer band at the bottom of the canvas, hairline included."""
    return band_height(canvas_dims(orientation, display=display)[1])


def side_margin(cw, display=None):
    """The margin at the left and right of a canvas `cw` px wide: the footer's, and the editor's guides."""
    m = get_display(display)["margin"]
    return m if cw >= 400 else min(m, 16)


def canvas_geometry(orientation=0, display=None):
    """What the editor needs about a canvas: its size, the footer band and the side margin."""
    cw, ch = canvas_dims(orientation, display=display)
    return {"w": cw, "h": ch, "band": band_height(ch), "margin": side_margin(cw, display)}


def _ellipsize(s, f, max_w, min_chars=3):
    """s, cut with an ellipsis to fit max_w; None if fewer than min_chars would show."""
    if text_width(s, f) <= max_w:
        return s
    for k in range(len(s) - 1, min_chars - 1, -1):
        t = s[:k].rstrip() + ELLIPSIS
        if text_width(t, f) <= max_w:
            return t
    return None


def _count(i, n, short):
    return f"{i}" if short else f"{i}/{n}"


def footer_plan(*, clock, pages=(), orientation=0, display=None):
    """The footer for one screen: the same for every page in its strip.

    `pages` is [(name, item_count), ...] in the order the panel shows them, or
    empty for a page without pills (the editor's preview, the empty screen).
    """
    cw, ch = canvas_dims(orientation, display=display)
    base_margin = side_margin(cw, display)
    size = _footer_size(ch)
    band = band_height(ch)
    pill_h = min(24, band - 4)                       # the padlock needs 22: 2 above it, 20 of it
    pill_y1 = ch - min(4, band - pill_h - 2)
    pill_y0 = pill_y1 - pill_h
    n = len(pages)
    max_items = max([c for _, c in pages] + [1])

    def attempt(step, clock_size):
        margin = step.get("margin", base_margin)
        pad, short, shared = step.get("pad", 10), step.get("short", False), step.get("shared_lock", False)
        pf = font(step.get("pill_font", PILL_FONT), bold=True)
        cf = font(clock_size, bold=False)
        cat_x0 = margin + text_width(clock, cf) + round(clock_size * 0.6)
        right = cw - margin
        sub_w = (text_width(_count(max_items, max_items, short), pf) + 2 * pad) if max_items > 1 else 0
        sub_x1, sub_x0 = right, right - sub_w
        # Where the screen's padlock goes on a page with several items; it's
        # further right on a page with one.
        panel_lock = (sub_x0 - LOCK_GAP - LOCK_W) if sub_w else (sub_x1 - LOCK_W)
        counts = [_count(i + 1, n, short) for i in range(n)]
        need = max([text_width(c, pf) + 2 * pad for c in counts] + [0])
        # The furthest right a page pill may end and still leave its padlock room.
        cat_end = (panel_lock - LOCK_GAP) if shared else (panel_lock - LOCK_SLOT)
        if n and cat_x0 + need > cat_end and step.get("fit", True):
            return None
        cats = []
        for i, (name, _) in enumerate(pages):
            if shared:                      # one width for all, so both padlocks land on the same spot
                label, w = counts[i], cat_end - cat_x0
            else:
                name = str(name).replace("_", " ").upper()
                head = counts[i] + "  "
                fitted = _ellipsize(name, pf, cat_end - cat_x0 - 2 * pad - text_width(head, pf)) if name else None
                label = head + fitted if fitted else counts[i]
                w = text_width(label, pf) + 2 * pad
            cats.append({"label": label, "w": w})
        return {
            "canvas": (cw, ch), "margin": margin, "band": band, "rule_y": ch - band,
            "clock": clock, "clock_size": clock_size, "clock_end": margin + text_width(clock, cf),
            "pill_y0": pill_y0, "pill_y1": pill_y1, "cat_x0": cat_x0, "sub_x0": sub_x0, "sub_x1": sub_x1,
            "pages": cats, "short": short, "shared_lock": shared, "pill_font": step.get("pill_font", PILL_FONT),
        }

    for clock_size in range(size, CLOCK_FLOOR - 1, -1):
        for step in (FOOTER_STEPS if clock_size == size else FOOTER_STEPS[-1:]):
            plan = attempt(step, clock_size)
            if plan:
                return plan
    # Narrower than any screen we make: the smallest version, even if it crowds.
    return attempt({**FOOTER_STEPS[-1], "fit": False}, CLOCK_FLOOR)


def item_label(plan, item, items):
    """The item pill's text for item `item` (0-based) of `items`; '' with one item."""
    return _count(item + 1, items, plan["short"]) if items > 1 else ""


def _text_mid(draw, x, cy, s, f, anchor):
    """Draw s with its capitals and digits centred on cy, which is what reads as centred."""
    top = f.getbbox("0", anchor="ls")[1]
    draw.text((x, round(cy - top / 2)), s, font=f, fill=BLACK, anchor=anchor)


PILL_RADIUS = 4


def in_pill(x, y, x0, y0, x1, y1, r=PILL_RADIUS):
    """Whether (x, y) is inside the pill: the same shape the panel inverts (in_rounded_box in epf_core.h)."""
    if x < x0 or x > x1 or y < y0 or y > y1:
        return False
    cx = x0 + r if x < x0 + r else (x1 - r if x > x1 - r else x)
    cy = y0 + r if y < y0 + r else (y1 - r if y > y1 - r else y)
    return (x - cx) ** 2 + (y - cy) ** 2 <= r * r


def _pill(draw, x0, x1, y0, y1, s, f):
    # The outline is the edge of the panel's own shape, so its highlight covers
    # it exactly: no corner pixels left outside, no ring left inside.
    edge = [(x, y) for y in range(y0, y1 + 1) for x in range(x0, x1 + 1)
            if in_pill(x, y, x0, y0, x1, y1)
            and not all(in_pill(x + dx, y + dy, x0, y0, x1, y1) for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)))]
    draw.point(edge, fill=BLACK)
    _text_mid(draw, (x0 + x1 + 1) // 2, (y0 + y1 + 1) / 2, s, f, "ms")


def footer(draw, plan, *, page=None, item=0, items=1, label=""):
    """Draw the footer from footer_plan().

    page/item are 0-based; `items` is how many items this page has. `label`
    stands in for the pills where there are none (the editor's preview)."""
    cw, ch = plan["canvas"]
    margin, y0, y1 = plan["margin"], plan["pill_y0"], plan["pill_y1"]
    cy = (y0 + y1 + 1) / 2
    draw.line([(margin, plan["rule_y"]), (cw - margin, plan["rule_y"])], fill=BLACK, width=1)
    _text_mid(draw, margin, cy, plan["clock"], font(plan["clock_size"], bold=False), "ls")
    pf = font(plan["pill_font"], bold=True)
    if page is not None and 0 <= page < len(plan["pages"]):
        p = plan["pages"][page]
        _pill(draw, plan["cat_x0"], plan["cat_x0"] + p["w"], y0, y1, p["label"], pf)
        sub = item_label(plan, item, items)
        if sub:
            _pill(draw, plan["sub_x0"], plan["sub_x1"], y0, y1, sub, pf)
    elif label:
        f = font(_footer_size(ch), bold=False)
        # Centred on the screen, clear of the clock on both sides.
        room = 2 * (cw // 2 - plan["cat_x0"])
        fitted = _ellipsize(str(label), f, room)
        if fitted:
            _text_mid(draw, cw // 2, cy, fitted, f, "ms")
