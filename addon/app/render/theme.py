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

W, H = 792, 272
WHITE, BLACK = 255, 0

MARGIN       = 40
FOOTER_RULE  = 236   # y of the hairline above the footer
FOOTER_BASE  = 258   # baseline of footer text
FOOTER_SIZE  = 20
BODY_SIZE    = 26    # the "worthwhile when passing by" tier
LABEL_SIZE   = 30

# Fonts live beside the app, not inside the render package. Check both so
# this works whether run as a package or as a loose script.
_FONT_DIRS = [
    Path(__file__).parent.parent / "fonts",
    Path(__file__).parent / "fonts",
]


def _font_file(*names):
    for d in _FONT_DIRS:
        for n in names:
            p = d / n
            if p.exists():
                return str(p)
    raise FileNotFoundError(f"none of {names} in {[str(d) for d in _FONT_DIRS]}")


BOLD    = _font_file("Lato-Bold.ttf", "DejaVuSans-Bold.ttf")
REGULAR = _font_file("Lato-Regular.ttf", "DejaVuSans.ttf")


@lru_cache(maxsize=128)
def _cached_font(path: str, size: int):
    return ImageFont.truetype(path, size)


def font(size, bold=True):
    clamped = max(8, min(360, int(size)))
    return _cached_font(BOLD if bold else REGULAR, clamped)


def canvas_dims(orientation=0):
    """Logical (width, height) for the editor and renderer before panel rotation."""
    if int(orientation or 0) in (90, 270):
        return H, W
    return W, H


def new_canvas(orientation=0):
    """8-bit greyscale working canvas; converted to 1-bit on save."""
    cw, ch = canvas_dims(orientation)
    img = Image.new("L", (cw, ch), WHITE)
    return img, ImageDraw.Draw(img)


def to_1bit(img):
    """Hard threshold, no dithering -- crisp edges are what e-ink wants."""
    return img.convert("1", dither=Image.Dither.NONE)


def orient_for_panel(img, orientation=0):
    """Rotate a rendered logical page into the physical 792x272 panel buffer."""
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


def fit_size(s, max_w, max_h, start, floor=24, bold=True):
    """Largest point size at which s fits max_w x max_h. Binary search."""
    lo, hi, best = floor, max(floor, min(360, int(start))), floor
    while lo <= hi:
        mid = (lo + hi) // 2
        f = font(mid, bold)
        asc, desc = f.getmetrics()
        if text_width(s, f) <= max_w and (asc + desc) <= max_h:
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


def footer(draw, *, clock, label, battery_pct=None, orientation=0):
    cw, ch = canvas_dims(orientation)
    margin = 20 if cw < 400 else MARGIN
    rule_y = ch - 36
    base_y = ch - 14
    f = font(FOOTER_SIZE, bold=False)
    draw.line([(margin, rule_y), (cw - margin, rule_y)], fill=BLACK, width=1)
    draw.text((margin, base_y), clock, font=f, fill=BLACK, anchor="ls")
    draw.text((cw // 2, base_y), label, font=f, fill=BLACK, anchor="ms")
    if battery_pct is not None and battery_pct > 0:
        draw.text((cw - margin, base_y), f"{battery_pct} %", font=f, fill=BLACK, anchor="rs")
