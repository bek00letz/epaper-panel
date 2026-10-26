"""The sleep screen: what the panel shows while quiet hours last.

Large closed eyes, so it reads as "asleep" from across the room, and when it
will wake. Strokes stay at 8 px or more: anything under ~4 px disappears on
this panel at a distance.
"""
from __future__ import annotations

import math
from datetime import datetime

from . import clock
from . import theme as T
from .words import say


def manual_text() -> str:
    """What the sleep screen says when it was put to sleep by hand."""
    return say("sleep.press")


def wake_text(reason: str, end: str) -> str:
    """When it wakes: "back at 07:00" (quiet hours' end, "HH:MM", as the clock shows times), or
    "back when someone's home"."""
    if str(reason).startswith("away"):
        return say("sleep.back_home")
    try:
        hour, minute = (int(part) for part in str(end).strip()[:5].split(":"))
        at = datetime(2000, 1, 1, hour, minute)
    except ValueError:
        return say("sleep.back_at", time=str(end))
    hour = at.hour % 12 or 12 if clock.twelve_hour() else at.hour
    return say("sleep.back_at", hour, time=clock.hm(at))


def render_sleep_page(text: str, orientation: int = 0, display=None):
    img, d = T.new_canvas(orientation, display=display)
    cw, ch = img.size
    portrait = ch > cw

    eye_w = int(min(140, cw * (0.30 if portrait else 0.16)))
    eye_h = int(eye_w * 0.55)
    gap = int(eye_w * (0.45 if portrait else 0.75))
    stroke = max(8, eye_w // 14)
    cy = int(ch * (0.40 if portrait else 0.36))
    left = (cw - (2 * eye_w + gap)) // 2

    for x0 in (left, left + eye_w + gap):
        box = [x0, cy - eye_h // 2, x0 + eye_w, cy + eye_h // 2]
        d.arc(box, start=15, end=165, fill=T.BLACK, width=stroke)
        # Three short lashes hanging from the lid.
        rx, ry = eye_w / 2, eye_h / 2
        cx = x0 + rx
        for deg in (55, 90, 125):
            a = math.radians(deg)
            px, py = cx + rx * math.cos(a), cy + ry * math.sin(a)
            dx, dy = math.cos(a), math.sin(a)
            length = stroke * 1.8
            d.line([(px, py), (px + dx * length, py + dy * length)], fill=T.BLACK, width=max(6, stroke - 2))

    margin = 24
    max_w = cw - 2 * margin
    max_h = int(ch * (0.10 if portrait else 0.22))
    ty = int(ch * (0.62 if portrait else 0.76))
    size = T.fit_size(text, max_w, max_h, start=48, floor=22, bold=False)
    lines = T.wrap_two(text) if size < 32 else None
    if lines:
        # Too long for one comfortable line (portrait): two balanced lines.
        size = min(T.fit_size(line, max_w, max_h, start=48, floor=22, bold=False) for line in lines)
        f = T.font(size, bold=False, text=text)
        step = int(size * 1.25)
        for i, line in enumerate(lines):
            d.text((cw // 2, ty + (i * 2 - 1) * step // 2), line, font=f, fill=T.BLACK, anchor="mm")
    else:
        d.text((cw // 2, ty), text, font=T.font(size, bold=False, text=text), fill=T.BLACK, anchor="mm")
    return img
