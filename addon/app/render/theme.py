"""Geometry, type and drawing helpers for the CrowPanel 5.79" e-paper panel.

The panel is 792x272 px, 1-bit, about 139 x 48 mm (145 dpi). Everything here
works in panel pixels so the numbers match the design directly.

There is no grey on a 1-bit panel: hierarchy is carried by SIZE, not tone.
Small secondary text is solid black and simply smaller. Only text above
~90 px can be screened (see screen) and still read as a deliberate grey.
"""
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


def font(size, bold=True):
    return ImageFont.truetype(BOLD if bold else REGULAR, size)


def new_canvas():
    """8-bit greyscale working canvas; converted to 1-bit on save."""
    img = Image.new("L", (W, H), WHITE)
    return img, ImageDraw.Draw(img)


def to_1bit(img):
    """Hard threshold, no dithering -- crisp edges are what e-ink wants."""
    return img.convert("1", dither=Image.Dither.NONE)


def text_width(s, f):
    b = f.getbbox(s)
    return b[2] - b[0]


def fit_size(s, max_w, max_h, start, floor=24, bold=True):
    """Largest point size at which s fits max_w x max_h. Binary search."""
    lo, hi, best = floor, start, floor
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
    px = img.load()
    for y in range(max(0, y0), min(H, y1)):
        for x in range(max(0, x0) + (y % 2), min(W, x1), 2):
            px[x, y] = WHITE


def footer(draw, *, clock, label, battery_pct):
    f = font(FOOTER_SIZE, bold=False)
    draw.line([(MARGIN, FOOTER_RULE), (W - MARGIN, FOOTER_RULE)], fill=BLACK, width=1)
    draw.text((MARGIN, FOOTER_BASE), clock, font=f, fill=BLACK, anchor="ls")
    draw.text((W // 2, FOOTER_BASE), label, font=f, fill=BLACK, anchor="ms")
    draw.text((W - MARGIN, FOOTER_BASE), f"{battery_pct} %", font=f, fill=BLACK, anchor="rs")
