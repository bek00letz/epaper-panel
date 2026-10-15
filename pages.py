"""One function per page. Each returns an 8-bit canvas; render.py thresholds it.

Every page is built for a 3 m viewing distance: one fact, set as large as it
will go. The footer is the only small text and is deliberately only legible
up close -- it is there to tell you the panel is alive, not to be read.
"""
import math

from PIL import Image, ImageDraw

import theme as T


# ------------------------------------------------------------------ pieces

def _sun(draw, cx, cy, r=30, rays=8):
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=T.BLACK)
    for i in range(rays):
        a = math.radians(i * (360 / rays))
        ca, sa = math.cos(a), math.sin(a)
        draw.line([(cx + ca * (r + 12), cy + sa * (r + 12)),
                   (cx + ca * (r + 30), cy + sa * (r + 30))],
                  fill=T.BLACK, width=7)


def _cat(draw, dx=0, dy=4):
    """Sitting cat in profile, facing right. Ears sit on the head circle so the
    three shapes merge into one silhouette; the tail is a stroked curve."""
    def P(pts):
        return [(x + dx, y + dy) for x, y in pts]

    # body: chest and front leg on the left, haunch and back on the right
    draw.polygon(P([(124, 96), (112, 130), (106, 170), (104, 202),
                    (176, 202), (206, 198), (222, 176), (224, 146),
                    (210, 116), (188, 96)]), fill=T.BLACK)
    draw.ellipse(P([(114, 24), (198, 108)]), fill=T.BLACK)          # head
    draw.polygon(P([(122, 44), (112, 4), (152, 30)]), fill=T.BLACK)  # left ear
    draw.polygon(P([(160, 30), (200, 4), (190, 44)]), fill=T.BLACK)  # right ear
    draw.line(P([(202, 196), (248, 188), (268, 166), (272, 136),
                 (262, 112), (246, 102)]),
              fill=T.BLACK, width=14, joint="curve")


def _drum(draw, cx, cy, r=46):
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=T.BLACK, width=7)
    ir = r - 16
    draw.ellipse([cx - ir, cy - ir, cx + ir, cy + ir], outline=T.BLACK, width=4)


def _curve(img, draw, pts, box, dot=3):
    """Filled area chart, screened with a dot pattern and a solid top edge."""
    x0, y0, x1, y1 = box
    if not pts or len(pts) < 2:
        return
    peak = max(pts) or 1
    n = len(pts)
    coords = [(x0 + i * (x1 - x0) / (n - 1), y1 - (v / peak) * (y1 - y0))
              for i, v in enumerate(pts)]

    mask = Image.new("1", (T.W, T.H), 0)
    ImageDraw.Draw(mask).polygon(coords + [(x1, y1), (x0, y1)], fill=1)
    pattern = Image.new("L", (T.W, T.H), T.WHITE)
    px = pattern.load()
    for y in range(0, T.H, dot):
        for x in range(0, T.W, dot):
            px[x, y] = T.BLACK
    img.paste(pattern, (0, 0), mask)

    draw.line(coords, fill=T.BLACK, width=3, joint="curve")
    draw.line([(x0, y1), (x1, y1)], fill=T.BLACK, width=1)


def _hero(draw, text, left, region, max_size=160, allow_two=False):
    """Set text as large as it fits in region=(top, bottom). Returns size used."""
    top, bottom = region
    width = T.W - T.MARGIN - left
    size = T.fit_size(text, width, bottom - top, max_size)

    if allow_two and size < 100:
        pair = T.wrap_two(text)
        if pair:
            each = (bottom - top) // 2
            two = min(T.fit_size(pair[0], width, each, max_size),
                      T.fit_size(pair[1], width, each, max_size))
            if two > size:
                f = T.font(two)
                lead = int(two * 1.06)
                mid = (top + bottom) // 2
                draw.text((left, mid - lead // 2), pair[0], font=f,
                          fill=T.BLACK, anchor="lm")
                draw.text((left, mid + lead // 2), pair[1], font=f,
                          fill=T.BLACK, anchor="lm")
                return two

    draw.text((left, (top + bottom) // 2), text, font=T.font(size),
              fill=T.BLACK, anchor="lm")
    return size


def _label(draw, text, xy, size=None, bold=False, anchor="ls"):
    draw.text(xy, text, font=T.font(size or T.LABEL_SIZE, bold=bold),
              fill=T.BLACK, anchor=anchor)


# ------------------------------------------------------------------- pages

def solar(data, ctx):
    img, d = T.new_canvas()
    _sun(d, 90, 100)
    v = data.num("pv_today")
    d.text((156, 152), f"{v:.1f}" if v is not None else "--",
           font=T.font(150), fill=T.BLACK, anchor="ls")
    _label(d, "kWh today", (160, 196))
    _curve(img, d, data.pv_curve, (490, 106, 760, 186))
    T.footer(d, **ctx)
    return img


def solar_month(data, ctx):
    img, d = T.new_canvas()
    _sun(d, 90, 100)
    v = data.month_kwh
    d.text((156, 152), f"{v:.0f}" if v is not None else "--",
           font=T.font(150), fill=T.BLACK, anchor="ls")
    _label(d, "kWh this month", (160, 196))
    pct = data.num("batt_pct")
    if pct is not None:
        _label(d, f"battery {pct:.0f} %", (T.W - T.MARGIN, 196), anchor="rs")
    T.footer(d, **ctx)
    return img


def cat(data, ctx):
    img, d = T.new_canvas()
    _cat(d)
    _hero(d, data.cat_word(), 320, (70, 180), max_size=112)
    since = data.cat_since()
    if since:
        _label(d, since, (322, 212))
    T.footer(d, **ctx)
    return img


def watch(data, ctx, item=None):
    img, d = T.new_canvas()
    _label(d, "new to watch", (T.MARGIN, 48), size=T.BODY_SIZE)

    if item is None:
        size = _hero(d, "nothing new", T.MARGIN, (80, 220), max_size=120)
        T.screen(img, (T.MARGIN - 4, 80, T.W - T.MARGIN, 224))
    else:
        _label(d, item["detail"], (T.W - T.MARGIN, 48),
               size=T.BODY_SIZE, anchor="rs")
        _hero(d, item["title"], T.MARGIN, (74, 226),
              max_size=160, allow_two=True)

    T.footer(d, **ctx)
    return img


def temps(data, ctx):
    img, d = T.new_canvas()
    d.line([(396, 44), (396, 200)], fill=T.BLACK, width=1)
    for label, key, lx, vx in (("yard", "yard", 62, 56), ("inside", "inside", 436, 430)):
        _label(d, label, (lx, 66))
        v = data.num(key)
        d.text((vx, 186), f"{v:.1f}" if v is not None else "--",
               font=T.font(124), fill=T.BLACK, anchor="ls")
    T.footer(d, **ctx)
    return img


def dryer(data, ctx):
    img, d = T.new_canvas()
    _drum(d, 102, 118)
    secs = data.dryer_remaining() or 0
    h, m = divmod(secs // 60, 60)
    d.text((186, 162), f"{h}:{m:02d}", font=T.font(150), fill=T.BLACK, anchor="ls")
    _label(d, "dryer, time left", (190, 206))
    T.footer(d, **ctx)
    return img


ALWAYS = {"solar": solar, "solar_month": solar_month, "cat": cat, "temps": temps}
CONDITIONAL = {"watch": watch, "dryer": dryer}
