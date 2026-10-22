"""Icons drawn from their outlines: SVG path data, crisp at any size.

An icon is a record: its path data (`d`, the SVG path grammar), and when it
isn't on Material Design Icons' 24 x 24 grid, its view box (`v`: x, y, w, h).
A record is a plain string when it's just a path on the 24 grid (every icon
Home Assistant serves). `e` is a path filled by the even-odd rule, and `s`
lists stroked paths as [d, width] (an icon drawn with lines rather than
shapes): both only in custom icons.

`mask(record, size)` draws one into a size x size picture the way SVG does
(the view box fitted and centred), 4x over and averaged, so the page's
threshold at the end (`theme.to_1bit`) cuts the edge where it's half covered,
as it does for type (8x matched the old icon font best: about 4% of the ink
differs at 24 px, where the font's hinting thins strokes, and under 2% at 48). Filled with the non-zero rule, SVG's default: a winding
number per subpath, added up (a subpath that doesn't cross itself winds +1
or -1 inside it), so a hole is a subpath going the other way round.

`normalize(d, matrix)` rewrites any path as absolute M, L, C and Z with a
transform applied, which is how a custom icon's shapes (circles, rectangles,
transforms) become one path when its set is copied (`iconsets`).
"""
from __future__ import annotations

import math
import re
from functools import lru_cache

from PIL import Image, ImageChops, ImageDraw

GRID = (0.0, 0.0, 24.0, 24.0)

# What one icon may cost to read and draw, about twice the largest real one (a brand icon: 248k
# characters, 14,080 commands, 2,625 shapes, ~47k points; Material Design's are far smaller). An
# icon beyond any of these is refused when its set is copied (`check`) and draws as nothing, so a
# crafted file can't make a render slow.
MAX_CHARS = 512_000
MAX_SEGMENTS = 30_000
MAX_SHAPES = 6_000
MAX_AREA = 16.0                 # its shapes' boxes added up, in squares of its view box (real: under 5)
MAX_POINTS = 120_000            # past this, curves are cut coarser rather than into more points
OVER = 8                                    # drawn this many times larger, then averaged

_TOKEN = re.compile(r"[MmLlHhVvCcSsQqTtAaZz]|[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")
_ARGS = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "S": 4, "Q": 4, "T": 2, "A": 7, "Z": 0}


class PathError(ValueError):
    pass


def _tokens(d: str):
    """Commands and numbers. An arc's two flags may be written run together ("a1 1 0 01 2 2")."""
    out, pos, s = [], 0, str(d or "")
    while pos < len(s):
        c = s[pos]
        if c in " \t\r\n,":
            pos += 1
            continue
        m = _TOKEN.match(s, pos)
        if not m:
            raise PathError(f"can't read {s[pos:pos + 12]!r}")
        out.append(m.group())
        pos = m.end()
    return out


def _split_flags(tokens):
    """Arc flags are single digits; '01' read as one number is two flags."""
    out, cmd, k = [], "", 0
    for t in tokens:
        if t.isalpha():
            cmd, k = t.upper(), 0
            out.append(t)
            continue
        if cmd == "A":
            i = k % 7
            if i in (3, 4) and len(t) > 1 and t[0] in "01" and "." not in t[:1]:
                # one or two flags glued to what follows: "01" or "0120.5"
                out.append(t[0])
                rest = t[1:]
                k += 1
                if i == 3 and rest and rest[0] in "01":
                    out.append(rest[0])
                    rest = rest[1:]
                    k += 1
                if rest:
                    out.append(rest)
                    k += 1
                continue
        out.append(t)
        k += 1
    return out


def segments(d: str):
    """The path as absolute segments: ("M", p), ("L", p0, p1), ("C", p0, c1, c2, p1), ("Z", p0, p1).
    A path longer than MAX_CHARS or MAX_SEGMENTS isn't read (PathError)."""
    if len(str(d or "")) > MAX_CHARS:
        raise PathError("too long to be an icon")
    toks = _split_flags(_tokens(d))
    segs, i = [], 0
    cur = start = (0.0, 0.0)
    last_c = last_q = None                      # the previous curve's second control point
    cmd = None
    while i < len(toks):
        if len(segs) > MAX_SEGMENTS:
            raise PathError("too many commands to be an icon")
        t = toks[i]
        if t.isalpha():
            cmd = t
            i += 1
            if cmd in "Zz":
                if cur != start:
                    segs.append(("L", cur, start))
                segs.append(("Z", cur, start))
                cur, last_c, last_q = start, None, None
                continue
        elif cmd is None:
            raise PathError("a path starts with a command")
        n = _ARGS[cmd.upper()]
        if i + n > len(toks) or any(x.isalpha() for x in toks[i:i + n]):
            raise PathError(f"{cmd} needs {n} numbers")
        a = [float(x) for x in toks[i:i + n]]
        i += n
        rel = cmd.islower()
        ox, oy = cur if rel else (0.0, 0.0)
        C = cmd.upper()
        if C == "M":
            cur = start = (ox + a[0], oy + a[1])
            segs.append(("M", cur))
            cmd = "l" if rel else "L"            # numbers after a moveto are linetos
            last_c = last_q = None
            continue
        if C in "LHV":
            if C == "L":
                p = (ox + a[0], oy + a[1])
            elif C == "H":
                p = ((ox if rel else 0.0) + a[0], cur[1])
            else:
                p = (cur[0], (oy if rel else 0.0) + a[0])
            segs.append(("L", cur, p))
            cur, last_c, last_q = p, None, None
        elif C == "C":
            c1, c2, p = (ox + a[0], oy + a[1]), (ox + a[2], oy + a[3]), (ox + a[4], oy + a[5])
            segs.append(("C", cur, c1, c2, p))
            cur, last_c, last_q = p, c2, None
        elif C == "S":
            c1 = (2 * cur[0] - last_c[0], 2 * cur[1] - last_c[1]) if last_c else cur
            c2, p = (ox + a[0], oy + a[1]), (ox + a[2], oy + a[3])
            segs.append(("C", cur, c1, c2, p))
            cur, last_c, last_q = p, c2, None
        elif C in "QT":
            if C == "Q":
                q, p = (ox + a[0], oy + a[1]), (ox + a[2], oy + a[3])
            else:
                q = (2 * cur[0] - last_q[0], 2 * cur[1] - last_q[1]) if last_q else cur
                p = (ox + a[0], oy + a[1])
            c1 = (cur[0] + 2 / 3 * (q[0] - cur[0]), cur[1] + 2 / 3 * (q[1] - cur[1]))
            c2 = (p[0] + 2 / 3 * (q[0] - p[0]), p[1] + 2 / 3 * (q[1] - p[1]))
            segs.append(("C", cur, c1, c2, p))
            cur, last_c, last_q = p, None, q
        elif C == "A":
            p = (ox + a[5], oy + a[6])
            segs.extend(_arc(cur, a[0], a[1], a[2], a[3] != 0, a[4] != 0, p))
            cur, last_c, last_q = p, None, None
    return segs


def _arc(p0, rx, ry, phi_deg, large, sweep, p1):
    """An elliptical arc (SVG's endpoint form) as cubic curves of at most a quarter turn each."""
    if p0 == p1:
        return []
    rx, ry = abs(rx), abs(ry)
    if rx == 0 or ry == 0:
        return [("L", p0, p1)]
    phi = math.radians(phi_deg % 360)
    cos_p, sin_p = math.cos(phi), math.sin(phi)
    dx, dy = (p0[0] - p1[0]) / 2, (p0[1] - p1[1]) / 2
    x1 = cos_p * dx + sin_p * dy
    y1 = -sin_p * dx + cos_p * dy
    lam = (x1 * x1) / (rx * rx) + (y1 * y1) / (ry * ry)
    if lam > 1:
        s = math.sqrt(lam)
        rx, ry = rx * s, ry * s
    num = rx * rx * ry * ry - rx * rx * y1 * y1 - ry * ry * x1 * x1
    den = rx * rx * y1 * y1 + ry * ry * x1 * x1
    co = math.sqrt(max(0.0, num / den)) if den else 0.0
    if large == sweep:
        co = -co
    cx1, cy1 = co * rx * y1 / ry, -co * ry * x1 / rx
    cx = cos_p * cx1 - sin_p * cy1 + (p0[0] + p1[0]) / 2
    cy = sin_p * cx1 + cos_p * cy1 + (p0[1] + p1[1]) / 2

    def angle(ux, uy, vx, vy):
        a = math.atan2(ux * vy - uy * vx, ux * vx + uy * vy)
        return a

    t1 = angle(1, 0, (x1 - cx1) / rx, (y1 - cy1) / ry)
    dt = angle((x1 - cx1) / rx, (y1 - cy1) / ry, (-x1 - cx1) / rx, (-y1 - cy1) / ry)
    if not sweep and dt > 0:
        dt -= 2 * math.pi
    elif sweep and dt < 0:
        dt += 2 * math.pi
    n = max(1, math.ceil(abs(dt) / (math.pi / 2) - 1e-9))
    step = dt / n
    k = 4 / 3 * math.tan(step / 4)

    def pt(t):
        x, y = rx * math.cos(t), ry * math.sin(t)
        return (cos_p * x - sin_p * y + cx, sin_p * x + cos_p * y + cy)

    def deriv(t):
        x, y = -rx * math.sin(t), ry * math.cos(t)
        return (cos_p * x - sin_p * y, sin_p * x + cos_p * y)

    out, t, a = [], t1, p0
    for j in range(n):
        t2 = t + step
        b = p1 if j == n - 1 else pt(t2)
        d1, d2 = deriv(t), deriv(t2)
        out.append(("C", a, (a[0] + k * d1[0], a[1] + k * d1[1]), (b[0] - k * d2[0], b[1] - k * d2[1]), b))
        t, a = t2, b
    return out


def _subpaths(segs, scale):
    """Flattened subpaths (lists of points), curves cut finer the larger they're drawn, within
    MAX_POINTS for the path."""
    out, cur = [], None
    most = max(2, min(96, MAX_POINTS // max(1, sum(1 for s in segs if s[0] == "C"))))
    for s in segs:
        if s[0] == "M":
            if cur and len(cur) > 2:
                out.append(cur)
            cur = [s[1]]
        elif s[0] == "L":
            if cur is None:
                cur = [s[1]]
            cur.append(s[2])
        elif s[0] == "C":
            if cur is None:
                cur = [s[1]]
            p0, c1, c2, p1 = s[1:]
            length = (math.dist(p0, c1) + math.dist(c1, c2) + math.dist(c2, p1)) * scale
            n = max(2, min(most, int(math.sqrt(length) * 1.6) + 1))
            for j in range(1, n + 1):
                t = j / n
                u = 1 - t
                cur.append((u * u * u * p0[0] + 3 * u * u * t * c1[0] + 3 * u * t * t * c2[0] + t * t * t * p1[0],
                            u * u * u * p0[1] + 3 * u * u * t * c1[1] + 3 * u * t * t * c2[1] + t * t * t * p1[1]))
        elif s[0] == "Z":
            if cur and len(cur) > 2:
                out.append(cur)
            cur = [s[2]]
    if cur and len(cur) > 2:
        out.append(cur)
    return out


def _area2(pts):
    return sum(pts[i][0] * pts[i - 1][1] - pts[i - 1][0] * pts[i][1] for i in range(len(pts)))


def parts(record):
    """(d, e, view, strokes) of a record, whichever shape it's in: `d` filled by the non-zero rule,
    `e` by the even-odd rule (a custom icon that asks for it), each "" when it has none."""
    if isinstance(record, str):
        return record, "", GRID, ()
    if isinstance(record, dict):
        v = record.get("v") or GRID
        strokes = tuple((str(sd), float(w)) for sd, w in (record.get("s") or ()))
        return str(record.get("d") or ""), str(record.get("e") or ""), tuple(float(x) for x in v), strokes
    raise PathError("not an icon")


def budget(d, e, v, strokes) -> None:
    """Raise PathError when an icon costs more than any real one could (MAX_*): too many commands,
    shapes, or shapes covering too much (each is drawn over its own box)."""
    unit = max(v[2], v[3])
    shapes, area = 0, 0.0
    paths = [x for x in (d, e) if x] + [sd for sd, _ in strokes]
    if sum(len(x) for x in paths) > MAX_CHARS:
        raise PathError("too long to be an icon")
    for x in paths:
        segs = segments(x)
        for sp in _subpaths(segs, 1.0) + _open_runs(segs, 1.0):
            shapes += 1
            xs, ys = [p[0] for p in sp], [p[1] for p in sp]
            area += (max(xs) - min(xs) + unit / 64) * (max(ys) - min(ys) + unit / 64) / (unit * unit)
        if shapes > MAX_SHAPES or area > MAX_AREA:
            raise PathError("too many shapes to be an icon")


def check(record) -> bool:
    """Whether a record is one this draws: its paths read, its view box has a size, it has ink, and
    it costs no more than a real icon could (`budget`)."""
    try:
        d, e, v, strokes = parts(record)
        if len(v) != 4 or v[2] <= 0 or v[3] <= 0:
            return False
        # Every number is a real one: an infinite view box or stroke would be written as JSON no
        # browser reads, and the editor would lose every outline asked for with it.
        if not all(math.isfinite(x) for x in v) or not all(math.isfinite(w) for _, w in strokes):
            return False
        budget(d, e, v, strokes)
        any_ink = any(bool(x) and bool(_subpaths(segments(x), 1.0)) for x in (d, e))
        for sd, w in strokes:
            any_ink = (bool(segments(sd)) and w > 0) or any_ink
        return any_ink
    except (PathError, ValueError, TypeError, ZeroDivisionError):
        return False


@lru_cache(maxsize=512)
def _mask_cached(key, size: int):
    return _draw(*key, size)


def mask(record, size: int):
    """The icon at size x size: an 'L' picture, 255 where it's ink, edges averaged (not yet cut)."""
    return _mask_cached(parts(record), max(1, int(size)))


def cut(record, size: int, crop: bool = False):
    """The icon at `size` cut to 1 bit as the page will be ('L', 255 ink, 0 none); with `crop`, cut
    to its ink (None when it has none). Cached by the outline, like `mask`."""
    return _cut_cached(parts(record), max(1, int(size)), crop)


@lru_cache(maxsize=512)
def _cut_cached(key, size, crop):
    m = _mask_cached(key, size).point(lambda p: 255 if p >= 128 else 0)
    if not crop:
        return m
    box = m.getbbox()
    return m.crop(box) if box else None


def _draw(d, e, v, strokes, size):
    try:
        budget(d, e, v, strokes)
    except (PathError, ValueError, ZeroDivisionError):
        return Image.new("L", (size, size), 0)          # refused: nothing, and quickly
    big = size * OVER
    vx, vy, vw, vh = v
    scale = big / max(vw, vh)                           # fitted and centred, as SVG's "meet"
    ox = (big - vw * scale) / 2 - vx * scale
    oy = (big - vh * scale) / 2 - vy * scale
    tf = lambda p: (ox + p[0] * scale, oy + p[1] * scale)  # noqa: E731
    base = Image.new("L", (big, big), 128)               # winding number, 128 is zero
    if d:
        for pts in _subpaths(segments(d), scale):
            q = [tf(p) for p in pts]
            x0, y0 = max(0, int(min(x for x, _ in q)) - 1), max(0, int(min(y for _, y in q)) - 1)
            x1, y1 = min(big, int(max(x for x, _ in q)) + 2), min(big, int(max(y for _, y in q)) + 2)
            if x1 <= x0 or y1 <= y0:
                continue
            one = Image.new("L", (x1 - x0, y1 - y0), 0)       # only where this subpath is
            ImageDraw.Draw(one).polygon([(x - x0, y - y0) for x, y in q], fill=1)
            box = (x0, y0, x1, y1)
            base.paste((ImageChops.add if _area2(pts) > 0 else ImageChops.subtract)(base.crop(box), one), box)
    ink = base.point(lambda p: 0 if p == 128 else 255)
    if e:                                                # even-odd: each subpath flips what's under it
        odd = Image.new("1", (big, big), 0)
        for pts in _subpaths(segments(e), scale):
            q = [tf(p) for p in pts]
            x0, y0 = max(0, int(min(x for x, _ in q)) - 1), max(0, int(min(y for _, y in q)) - 1)
            x1, y1 = min(big, int(max(x for x, _ in q)) + 2), min(big, int(max(y for _, y in q)) + 2)
            if x1 <= x0 or y1 <= y0:
                continue
            one = Image.new("1", (x1 - x0, y1 - y0), 0)       # only where this subpath is
            ImageDraw.Draw(one).polygon([(x - x0, y - y0) for x, y in q], fill=1)
            box = (x0, y0, x1, y1)
            odd.paste(ImageChops.logical_xor(odd.crop(box), one), box)
        ink = ImageChops.lighter(ink, odd.convert("L"))
    if strokes:
        dr = ImageDraw.Draw(ink)
        for sd, w in strokes:
            width = max(1, int(round(float(w) * scale)))
            for pts in _subpaths(segments(sd), scale) + _open_runs(segments(sd), scale):
                dr.line([tf(p) for p in pts], fill=255, width=width, joint="curve")
                r = width / 2
                for p in (pts[0], pts[-1]):
                    q = tf(p)
                    dr.ellipse([q[0] - r, q[1] - r, q[0] + r, q[1] + r], fill=255)
    return ink.resize((size, size), Image.Resampling.BOX)


def _open_runs(segs, scale):
    """Stroked lines that aren't closed shapes (two points are enough for a line)."""
    out, cur = [], None
    for s in segs:
        if s[0] == "M":
            if cur and len(cur) == 2:
                out.append(cur)
            cur = [s[1]]
        elif s[0] == "L" and cur is not None:
            cur.append(s[2])
        else:
            if cur and len(cur) == 2:
                out.append(cur)
            cur = None
    if cur and len(cur) == 2:
        out.append(cur)
    return out


def ink_box(record):
    """Where its ink is, in its own units (x0, y0, x1, y1), or None: for fitting it into a box."""
    d, e, v, strokes = parts(record)
    pts = [p for x in (d, e) if x for sp in _subpaths(segments(x), 8.0) for p in sp]
    pad = 0.0
    for sd, w in strokes:
        pts += [p for sp in _subpaths(segments(sd), 8.0) + _open_runs(segments(sd), 8.0) for p in sp]
        pad = max(pad, float(w) / 2)
    if not pts:
        return None
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return (min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad)


def _fmt(x: float) -> str:
    s = f"{x:.3f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def normalize(d: str, matrix=(1, 0, 0, 1, 0, 0)) -> str:
    """The path as absolute M, L, C and Z, with an SVG transform matrix (a, b, c, d, e, f) applied."""
    a, b, c, dd, e, f = matrix

    def t(p):
        return f"{_fmt(a * p[0] + c * p[1] + e)} {_fmt(b * p[0] + dd * p[1] + f)}"
    out = []
    for s in segments(d):
        if s[0] == "M":
            out.append("M" + t(s[1]))
        elif s[0] == "L":
            out.append("L" + t(s[2]))
        elif s[0] == "C":
            out.append("C" + " ".join(t(p) for p in s[2:]))
        elif s[0] == "Z":
            if out and out[-1].startswith("L") and out[-1] == "L" + t(s[2]):
                out.pop()                    # the closing line Z draws anyway
            out.append("Z")
    return "".join(out)
