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
FOOTER_RULE  = 236   # y of the hairline above the footer
FOOTER_BASE  = 258   # baseline of footer text
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


def footer_geometry(*, clock, cat_label="", has_sub=False, battery_pct=None, orientation=0, display=None):
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
    cat_x0 = 96 if cw >= 400 else (margin + text_width(clock, f) + 12)
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


def footer(draw, *, clock, label="", cat_label="", sub_label="", battery_pct=None, orientation=0, display=None):
    g = footer_geometry(clock=clock, cat_label=cat_label, has_sub=bool(sub_label),
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
