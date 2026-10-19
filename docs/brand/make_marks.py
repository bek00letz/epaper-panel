"""Draw the add-on's icon, logo and the editor's favicon from one geometry.

The mark is the panel itself: the dark device frame around warm paper, with
a reading in black ink. The ink is Lato, the font the panel draws with, and
it follows the panel's rules: black only, size carries hierarchy.

    pip install fonttools pillow
    python docs/brand/make_marks.py

Writes addon/icon.png, addon/logo.png, docs/brand/icon.svg, docs/brand/logo.svg
and prints the favicon's data URL for addon/app/web/index.html.
"""
import math
from pathlib import Path
from urllib.parse import quote

from fontTools.pens.basePen import BasePen
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont
from PIL import Image, ImageChops, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
FONTS = ROOT / "addon/app/fonts"

FRAME = "#26262a"
PAPER = "#fbfbf9"
INK = "#111111"

SS = 8  # supersampling for the PNGs


class Font:
    def __init__(self, name):
        self.tt = TTFont(FONTS / name)
        self.glyphs = self.tt.getGlyphSet()
        self.cmap = self.tt.getBestCmap()
        self.upm = self.tt["head"].unitsPerEm
        self.cap = self.tt["OS/2"].sCapHeight

    def runs(self, text, cap, tracking=0.0):
        """(glyph name, x offset in font units) for each character, and the
        run's width in our units for a cap height of `cap`."""
        scale = cap / self.cap
        out, x = [], 0.0
        for ch in text:
            name = self.cmap[ord(ch)]
            out.append((name, x))
            x += self.glyphs[name].width + tracking / scale
        width = (x - tracking / scale) * scale
        return out, scale, width


class FlattenPen(BasePen):
    """Turns a glyph into polygons (one per contour)."""

    def __init__(self, glyphset, xform, steps=24):
        super().__init__(glyphset)
        self.xform, self.steps, self.contours, self.cur = xform, steps, [], []

    def _moveTo(self, p):
        self.cur = [self.xform(p)]

    def _lineTo(self, p):
        self.cur.append(self.xform(p))

    def _qCurveToOne(self, p1, p2):
        p0 = self._getCurrentPoint()
        for i in range(1, self.steps + 1):
            t = i / self.steps
            a, b, c = (1 - t) ** 2, 2 * (1 - t) * t, t * t
            self.cur.append(self.xform((a * p0[0] + b * p1[0] + c * p2[0],
                                        a * p0[1] + b * p1[1] + c * p2[1])))

    def _curveToOne(self, p1, p2, p3):
        p0 = self._getCurrentPoint()
        for i in range(1, self.steps + 1):
            t = i / self.steps
            a, b, c, d = (1 - t) ** 3, 3 * (1 - t) ** 2 * t, 3 * (1 - t) * t * t, t ** 3
            self.cur.append(self.xform((a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0],
                                        a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1])))

    def _closePath(self):
        self.contours.append(self.cur)
        self.cur = []

    _endPath = _closePath


def squircle(x, y, w, h, r, n=5.0, steps=40):
    """A rounded rectangle with continuous (superellipse) corners."""
    e = min(r * 1.28, w / 2, h / 2)
    pts = []
    for cx, cy, a0 in ((x + w - e, y + e, -90), (x + w - e, y + h - e, 0),
                       (x + e, y + h - e, 90), (x + e, y + e, 180)):
        for i in range(steps + 1):
            a = math.radians(a0 + 90 * i / steps)
            c, s = math.cos(a), math.sin(a)
            pts.append((cx + e * math.copysign(abs(c) ** (2 / n), c),
                        cy + e * math.copysign(abs(s) ** (2 / n), s)))
    return pts


class Mark:
    """Shapes in drawing units; rendered to PNG at any pixel size and to SVG."""

    def __init__(self, w, h):
        self.w, self.h, self.layers = w, h, []  # (colour, kind, data)

    def rect(self, colour, x, y, w, h, r):
        self.layers.append((colour, "poly", [squircle(x, y, w, h, r)], (x, y, w, h, r)))

    def text(self, colour, font, text, x, baseline, cap, tracking=0.0):
        runs, scale, width = font.runs(text, cap, tracking)
        polys, svg = [], []
        for name, gx in runs:
            xform = lambda p, gx=gx: (x + (p[0] + gx) * scale, baseline - p[1] * scale)
            pen = FlattenPen(font.glyphs, xform)
            font.glyphs[name].draw(pen)
            polys += pen.contours
            sp = SVGPathPen(font.glyphs, lambda v: f"{v:.2f}".rstrip("0").rstrip("."))
            font.glyphs[name].draw(TransformPen(sp, (scale, 0, 0, -scale, x + gx * scale, baseline)))
            svg.append(sp.getCommands())
        self.layers.append((colour, "glyphs", polys, "".join(svg)))
        return width

    def png(self, px_w, path):
        k = px_w / self.w * SS
        size = (round(self.w * k), round(self.h * k))
        out = Image.new("RGBA", (px_w, round(px_w * self.h / self.w)), (0, 0, 0, 0))
        for colour, _kind, polys, _ in self.layers:
            mask = Image.new("1", size, 0)
            for poly in polys:  # even-odd: counters punch through
                one = Image.new("1", size, 0)
                ImageDraw.Draw(one).polygon([(px * k, py * k) for px, py in poly], fill=1)
                mask = ImageChops.logical_xor(mask, one)
            alpha = mask.convert("L").resize(out.size, Image.BOX)
            layer = Image.new("RGBA", out.size, colour)
            layer.putalpha(alpha)
            out = Image.alpha_composite(out, layer)
        out.save(path, optimize=True)

    def svg(self, compact=False):
        body = []
        for colour, kind, polys, data in self.layers:
            fill = colour.replace("#111111", "#111")
            if kind == "poly" and compact:
                x, y, w, h, r = data
                body.append(f"<rect x='{x:g}' y='{y:g}' width='{w:g}' height='{h:g}' rx='{r:g}' fill='{fill}'/>")
            elif kind == "poly":
                d = "M" + "L".join(f"{px:.2f} {py:.2f}" for px, py in polys[0]) + "Z"
                body.append(f'<path d="{d}" fill="{fill}"/>')
            else:
                q = "'" if compact else '"'
                body.append(f"<path d={q}{data}{q} fill={q}{fill}{q}/>")
        q = "'" if compact else '"'
        return (f"<svg xmlns={q}http://www.w3.org/2000/svg{q} viewBox={q}0 0 {self.w:g} {self.h:g}{q}>"
                + "".join(body) + "</svg>")


def reading(m, bold, x, cx_top, cap):
    """The '21°' reading; returns where it ends."""
    return x + m.text(INK, bold, "21°", x, cx_top + cap, cap, tracking=-cap * 0.04)


def icon(bold):
    """Square: the panel with a reading and three lines of smaller text."""
    m = Mark(128, 128)
    m.rect(FRAME, 6, 30, 116, 68, 16)
    m.rect(PAPER, 14, 38, 100, 52, 8)        # concentric: 16 - 8
    cap, top = 25, 51.5
    end = reading(m, bold, 23, top, cap)
    x0, x1 = end + 9, 106                   # lines of smaller text, ragged right
    for y, frac in ((top + 1, 1.0), (top + 10.75, 0.86), (top + 20.5, 0.5)):
        m.rect(INK, x0, y, (x1 - x0) * frac, 4.5, 2.25)
    return m


def favicon(bold):
    """Optical size for 16-32 px: the reading alone, larger."""
    m = Mark(32, 32)
    m.rect(FRAME, 0.5, 6, 31, 20, 5)
    m.rect(PAPER, 3, 8.5, 26, 15, 2.5)       # concentric: 5 - 2.5
    cap = 9
    _, _, w = bold.runs("21°", cap, -cap * 0.04)
    reading(m, bold, 16 - w / 2, 16 - cap / 2, cap)
    return m


def logo(bold, regular):
    """Wide: the panel at its real proportions with the name on it."""
    m = Mark(250, 100)
    m.rect(FRAME, 2, 2, 246, 96, 20)
    m.rect(PAPER, 10, 10, 230, 80, 12)       # 230 x 80, the panel's 792 x 272
    cap, gap, name, sub = 30, 13, 14, 10
    _, _, w_read = bold.runs("21°", cap, -cap * 0.04)
    _, _, w_name = bold.runs("e-Paper Panel", name, -0.2)
    x = 125 - (w_read + gap + w_name) / 2    # centred on the paper
    x = reading(m, bold, x, 50 - cap / 2, cap) + gap
    m.text(INK, bold, "e-Paper Panel", x, 50 - cap / 2 + name, name, tracking=-0.2)
    m.text(INK, regular, "for CrowPanel", x, 50 + cap / 2, sub)
    return m


def main():
    bold, regular = Font("Lato-Bold.ttf"), Font("Lato-Regular.ttf")
    out = ROOT / "docs/brand"
    i, l, f = icon(bold), logo(bold, regular), favicon(bold)
    i.png(256, ROOT / "addon/icon.png")
    l.png(500, ROOT / "addon/logo.png")
    (out / "icon.svg").write_text(i.svg() + "\n")
    (out / "logo.svg").write_text(l.svg() + "\n")
    print("data:image/svg+xml," + quote(f.svg(compact=True), safe=" '=:/,.-"))
    return f


if __name__ == "__main__":
    main()
