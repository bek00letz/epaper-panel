"""AI usage, drawn: each provider's limit windows as calm bars, a few extras, and who's gone quiet.

What it shows comes from usage.py, in the one shape every provider's numbers come in
(docs/ai-usage.md): the page never names a provider. Each window is a cell:

    5-hour session            what it is (and its scope: "Weekly · Sonnet")
    42%                       how much is used, large (an amount: "$314" and "of $500")
    ██████████░░░░░░░░░░      a bar, when there's a limit
    Resets in 2 h 10 min      when it resets

A provider's cells sit under its name, its extras under them ("1.2M tokens today · 3 sessions").
Every way of putting each provider's cells in columns is tried, and the one with the largest
numbers wins, as the world clock does, so one provider or four read well on the wide 5.79", the
2.9", the 4.2", a TRMNL and upright. What doesn't fit goes in this order: extras, the heading of
a lone provider, when each resets, then a provider's windows past its first two, then past its first.

On a screen that sleeps between updates "in 2 h 10 min" would go stale, and would change the
picture at every wake, so it says when instead ("Resets 16:15"; the element is marked `asleep`,
render/clocktime.py).

Before there's anything to show it says what to do: no computer yet (plain steps), one that
hasn't reported, or nothing it could read.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from functools import lru_cache
from datetime import datetime, timedelta, timezone

from . import clock, hero
from . import theme as T
from .todo import now_in
from .words import cap, number, say, language

VMAX = 110              # the largest a number gets, at text size 1
MIN_V = hero.MIN_VALUE  # 18
MIN_C = hero.MIN_CAPTION  # 12
CURRENCY = {"USD": "$", "EUR": "€", "GBP": "£", "JPY": "¥"}


# ---------------------------------------------------------------- what each part says

def _when(raw) -> datetime | None:
    try:
        got = datetime.fromisoformat(str(raw or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    return got if got.tzinfo else got.replace(tzinfo=timezone.utc)


def percent(fraction: float) -> str:
    n = max(0, round(fraction * 100))
    return f"{n} %" if language() in ("de", "fr") else f"{n}%"


def money(amount: float, unit: str) -> str:
    """An amount as people write it: "$314", "$1.20", "12 CHF"."""
    decimals = 0 if amount >= 100 or float(amount).is_integer() else 2
    text = number(amount, decimals, group=True)
    sym = CURRENCY.get(unit)
    if sym:
        return f"{sym}{text}" if language() == "en" else f"{text} {sym}"
    return f"{text} {unit}".strip()


def amount_text(amount: float, unit: str) -> str:
    from usage import CURRENCY_RE
    if CURRENCY_RE.match(unit or ""):
        return money(amount, unit)
    return f"{number(amount, 0 if float(amount).is_integer() else 1, group=True)} {unit}".strip()


def compact(n: int) -> str:
    """A count, short: 950, 12K, 1.2M (the language's decimal sign)."""
    for size, mark in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if n >= size:
            v = round(n / size, 1)
            return (number(v, 1) if v < 10 and v != int(v) else number(round(v), 0)) + mark
    return str(int(n))


def window_label(w: dict) -> str:
    from usage import is_spend
    if is_spend(w):
        base = say(f"ai.spend.{w['window']}")
    elif w["window"] == "session":
        base = say("ai.session", int(w.get("hours") or 5))
    else:
        base = say(f"ai.{w['window']}")
    return f"{base} · {w['scope']}" if w.get("scope") else base


def duration(delta: timedelta) -> str:
    mins = max(1, math.ceil(delta.total_seconds() / 60))
    if mins < 60:
        return say("ago.minutes", mins)
    h, m = divmod(mins, 60)
    if h < 24:
        return say("ago.hours", h) if m == 0 else say("ai.hm", h=h, m=m)
    d, h = divmod(h, 24)
    return say("ai.dh", d=d, h=h)


def at_text(when: datetime, now: datetime, alone: bool = False) -> str:
    """When, as short as it can be said: "16:15" today, "Tue 09:00" this week, "1 Nov" after.
    `alone`: standing on its own, so a weekday the language writes in lowercase starts with a capital."""
    when = when.astimezone(now.tzinfo)
    days = (when.date() - now.date()).days
    if days == 0:
        return clock.hm(when)
    if 0 < days < 7 or -7 < days < 0:
        wd = clock.date(when, "wd")
        return f"{cap(wd) if alone else wd} {clock.hm(when)}"
    return clock.date(when, "date")


def reset_forms(w: dict, now: datetime, asleep: bool) -> list[str]:
    """What it says about resetting, longest first; the drawing takes the first that fits."""
    if w.get("reset"):
        at = _when(w["reset"])
        return [say("ai.reset_at", when=at_text(at, now)), at_text(at, now, alone=True)]
    resets = _when(w.get("resets_at"))
    if resets is None:
        return [""]
    left = resets - now
    if not asleep and timedelta(0) < left < timedelta(hours=24):
        t = duration(left)
        return [say("ai.resets_in", t=t), say("ai.in", t=t), t]
    return [say("ai.resets_at", when=at_text(resets, now)), at_text(resets, now, alone=True)]


def big_text(w: dict) -> tuple[str, str]:
    """(the number, large; what's beside it, small): "42%", or "$314" and "of $500"."""
    from usage import is_spend
    if "amount" in w and ("used" not in w or is_spend(w)):
        unit = w.get("unit") or ""
        beside = say("ai.of", limit=amount_text(w["limit"], unit)) if w.get("limit") else ""
        return amount_text(w["amount"], unit), beside
    return percent(w.get("used") or 0), ""


def bar_share(w: dict) -> float | None:
    if "used" in w:
        return max(0.0, min(1.0, w["used"]))
    if w.get("limit"):
        return max(0.0, min(1.0, w["amount"] / w["limit"]))
    return None


def extras_parts(ex: dict) -> list[str]:
    out = []
    if ex.get("tokens"):
        out.append(say("ai.tokens", n=compact(ex["tokens"])))
    if ex.get("sessions"):
        out.append(say("ai.sessions", ex["sessions"]))
    if ex.get("cost"):
        out.append(say("ai.cost_today", amount=money(ex["cost"]["amount"], ex["cost"]["unit"])))
    if ex.get("streak_days", 0) >= 2:
        out.append(say("ai.streak", ex["streak_days"]))
    if "cache" in ex and ex.get("tokens"):
        out.append(say("ai.cache", share=percent(ex["cache"])))
    return out


def names_said(names: list[str]) -> str:
    names = [n for n in names if n]
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    return say("ai.and", a=", ".join(names[:-1]), b=names[-1])


def reporter_name(r: dict) -> str:
    return r.get("name") or say("ai.your_mac" if r.get("platform") == "macos" else "ai.your_computer")


def quiet_line(reporters: list[dict], now: datetime) -> str:
    quiet = [r for r in reporters if r.get("quiet") and r.get("heard_at")]
    if not quiet:
        return ""
    if len(quiet) > 1:
        return say("ai.heard_many", n=len(quiet))
    r = quiet[0]
    heard = _when(r["heard_at"]).astimezone(now.tzinfo)
    key = "ai.heard_today" if heard.date() == now.date() else "ai.heard_before"
    return say(key, name=reporter_name(r), time=at_text(heard, now))


# ---------------------------------------------------------------- the plan: sizes and places, no pixels drawn

@dataclass
class Cell:
    label: str
    big: str
    beside: str
    share: float | None
    resets: list
    box: tuple = (0, 0, 0, 0)
    reset: str = ""             # the form that fits
    reset_at: tuple = ()        # where it's written: beside the number or under the bar


@dataclass
class Block:
    heading: str
    cells: list
    extras: list
    heading_at: tuple = ()
    extras_at: tuple = ()
    extras_text: str = ""


@dataclass(frozen=True)
class Way:
    """How much it says, and where: the heading on top, at the side or not at all; when it resets
    beside the number, under the bar, or not at all; the extras or not."""
    heading: str = "top"
    resets: str = "beside"
    extras: bool = True


@dataclass
class Plan:
    v: int = 0                  # the numbers' size
    c: int = 0                  # the words' size
    bar: int = 0
    gap: int = 0
    blocks: list = field(default_factory=list)
    quiet: str = ""
    quiet_at: tuple = ()
    way: Way | None = None
    dropped: int = 0            # windows left out
    message: list = field(default_factory=list)  # instead of cells: [(text, bold)], a title then lines


def _sizes(v: int) -> tuple[int, int, int]:
    """(words, bar height, gap) for numbers of size v."""
    return max(MIN_C, round(v * 0.34)), max(14, round(v * 0.28)), max(4, round(v * 0.12))


@lru_cache(maxsize=4096)
def _width(text: str, px: int, bold: bool = False) -> int:
    """A text's width at a size: the plan measures the same words at many sizes while it looks for the best."""
    return T.text_width(text, T.font(px, bold=bold))


@lru_cache(maxsize=256)
def _ink(v: int) -> int:
    f = T.font(v, bold=True)
    asc, _ = f.getmetrics()
    return asc - f.getbbox("0")[1]


@lru_cache(maxsize=256)
def _line(c: int) -> int:
    asc, desc = T.font(c, bold=False).getmetrics()
    return asc + desc


def _layout(blocks, cols_of, box, v: int, way: Way, quiet: str) -> Plan | None:
    """Everything placed at number size v, or None if it doesn't fit the box."""
    x, y, w, h = box
    c, bar, gap = _sizes(v)
    lh = _line(c)
    ink = _ink(v)
    col_gap, row_gap, block_gap = max(12, v // 3), max(gap, v // 4), max(gap * 2, v // 3)
    side = 0
    if way.heading == "side":
        side = max(_width(b.heading, c, True) for b in blocks) + col_gap
        if side > w * 0.34:
            return None
    ch = lh + gap + ink + gap + bar + ((gap + lh) if way.resets == "below" else 0)
    cy = y
    placed = []
    for b, cols in zip(blocks, cols_of):
        cx0, cw_all = x + side, w - side
        cw = (cw_all - col_gap * (cols - 1)) // cols
        if cw < 40:
            return None
        nb = Block(b.heading, [], b.extras)
        if way.heading == "top":
            nb.heading_at = (x, cy)
            cy += lh + gap
        elif way.heading == "side":
            nb.heading_at = (x, cy)
        for k, cell in enumerate(b.cells):
            r, col = divmod(k, cols)
            cx, top = cx0 + col * (cw + col_gap), cy + r * (ch + row_gap)
            if _width(cell.label, c) > cw:
                return None
            big_w = _width(cell.big, v, True) + (_width(cell.beside, c) + round(v * 0.15) if cell.beside else 0)
            if big_w > cw:
                return None
            got = Cell(cell.label, cell.big, cell.beside, cell.share, cell.resets, box=(cx, top, cw, ch))
            if way.resets == "beside":
                room = cw - big_w - round(v * 0.3)
                # Beside the number it says it in full ("in 2 h" alone could be read as anything).
                got.reset = cell.resets[0] if _width(cell.resets[0], c) <= room else None
                if got.reset is None:
                    return None
                got.reset_at = (cx + big_w + round(v * 0.3), top + lh + gap + ink)      # on the number's baseline
            elif way.resets == "below":
                got.reset = next((f for f in cell.resets if _width(f, c) <= cw), None)
                if got.reset is None:
                    return None
                got.reset_at = (cx, top + lh + gap + ink + gap + bar + gap)
            nb.cells.append(got)
        rows = math.ceil(len(b.cells) / cols)
        cy += rows * ch + (rows - 1) * row_gap
        if way.extras and b.extras:
            parts = list(b.extras)
            while parts and _width(" · ".join(parts), c) > cw_all:
                parts.pop()
            if parts:
                nb.extras_text = " · ".join(parts)
                nb.extras_at = (cx0, cy + gap)
                cy += gap + lh
        placed.append(nb)
        cy += block_gap
    cy -= block_gap
    if quiet:
        if _width(quiet, c, True) > w:
            return None
        cy += gap + lh
    if cy - y > h:
        return None
    out = Plan(v=v, c=c, bar=bar, gap=gap, blocks=placed, way=way, quiet=quiet)
    if quiet:
        out.quiet_at = (x, y + h - lh)
    return out


def _largest(blocks, cols_of, box, way, quiet, scale) -> Plan | None:
    """The largest number size this arrangement holds (sizes that fit form a run from the smallest up)."""
    lo, hi = MIN_V, max(MIN_V, min(round(VMAX * scale), round(box[3] * 0.55)))
    best = _layout(blocks, cols_of, box, lo, way, quiet)
    if best is None:
        return None
    while lo < hi:
        mid = (lo + hi + 1) // 2
        got = _layout(blocks, cols_of, box, mid, way, quiet)
        if got is not None:
            best, lo = got, mid
        else:
            hi = mid - 1
    return best


def _columns(blocks) -> list[list[int]]:
    """Each way of putting every provider's cells in columns: one choice of columns for all, up to the most cells."""
    most = max((len(b.cells) for b in blocks), default=1)
    return [[min(n, len(b.cells)) or 1 for b in blocks] for n in range(1, most + 1)]


def _ways(many: bool) -> list[list[Way]]:
    """What it says, most first: each tier keeps more than the next. Within a tier, where things go
    is free (the largest numbers win)."""
    heads = ("top", "side") if many else ("top",)
    tiers = [[Way(hd, r, True) for hd in heads for r in ("beside", "below")],
             [Way(hd, r, False) for hd in heads for r in ("beside", "below")]]
    if not many:
        tiers.append([Way("none", r, False) for r in ("beside", "below")])
    tiers.append([Way(hd, "none", False) for hd in (heads if many else ("none",))])
    return tiers


def _message(lines: list) -> Plan:
    return Plan(message=lines)


def legible(h: int, scale: float = 1.0) -> int:
    """The number size a tier must reach to be kept: a fifth of the box's height (44 px on the 5.79"),
    at least what e-ink can show. Below it, the next tier says less, larger."""
    return max(MIN_V, round(h * 0.2 * min(1.0, scale)))


def plan(box, data, el: dict, now: datetime | None = None, *, scale: float = 1.0) -> Plan:
    """Where everything goes in the box: the one place the layout rules live (the drawing only paints)."""
    x, y, w, h = box
    data = data if isinstance(data, dict) else {}
    now = (now or datetime.now(timezone.utc)).astimezone(now_in(data.get("tz")).tzinfo)
    asleep = bool(el.get("asleep"))
    reporters = data.get("reporters") or []
    provs = data.get("providers") or []
    quiet = quiet_line(reporters, now)
    if not reporters:
        return _message([(say("ai.empty_title"), True), (say("ai.step_open"), False), (say("ai.step_run"), False),
                         (say("ai.step_wait"), False)])
    if not provs:
        if data.get("filtered"):
            return _message([(say("ai.no_match", names=names_said(data["filtered"])), True)])
        if not any(r.get("heard_at") for r in reporters):
            return _message([(say("ai.waiting"), True)])
        skipped = []
        for r in reporters:
            skipped += [s["name"] for s in r.get("skipped") or [] if s.get("reason") == "no_limits" and s["name"] not in skipped]
        tail = say("ai.nothing_use", names=names_said(skipped)) if skipped else say("ai.nothing_apps")
        return _message([(say("ai.nothing_title"), True), (tail, False)] + ([(quiet, True)] if quiet else []))

    show_extras = el.get("extras") is not False
    blocks = []
    for p in provs:
        cells = [Cell(window_label(w_), *big_text(w_), bar_share(w_), reset_forms(w_, now, asleep)) for w_ in p["windows"]]
        if cells:
            heading = p["name"] + (f" · {p['account']}" if p.get("account") else "")
            blocks.append(Block(heading, cells, extras_parts(p.get("extras") or {}) if show_extras else []))
    if not blocks:
        return _message([(say("ai.nothing_title"), True)])

    many = len(blocks) > 1
    enough = legible(h, scale)
    fallback = None
    # The tiers say less and less; past them, a provider's windows after its first two go, then after its first.
    for keep in (None, 2, 1):
        bl = blocks if keep is None else [Block(b.heading, b.cells[:keep], b.extras) for b in blocks]
        if keep is not None and all(len(b.cells) <= keep for b in blocks):
            continue
        for tier in _ways(many):
            best = None
            for way in tier:
                for cols_of in _columns(bl):
                    got = _largest(bl, cols_of, box, way, quiet, scale)
                    if got is not None and (best is None or got.v > best.v):
                        best = got
            if best is None:
                continue
            best.dropped = sum(len(b.cells) for b in blocks) - sum(len(b.cells) for b in bl)
            if best.v >= enough:
                return best
            if fallback is None or best.v > fallback.v:
                fallback = best
    if fallback is not None:
        return fallback
    # Far too small for bars: each provider's first window, a line each ("Claude Code: 42%").
    return _message([(f"{b.heading}: {b.cells[0].big}", True) for b in blocks])


# ---------------------------------------------------------------- painting the plan

def _bar(d, box, share: float) -> None:
    x, y, w, h = box
    r = h // 2
    line = max(4, round(h * 0.18))                    # under ~4 px a stroke vanishes on this glass
    d.rounded_rectangle([(x, y), (x + w - 1, y + h - 1)], radius=r, outline=T.BLACK, width=line)
    # A gap of one outline's width inside it, so the fill reads as filling, not as a thicker outline.
    pad = line * 2 if h >= line * 7 else line
    fill = round((w - 2 * pad) * share)
    if fill > 0:
        inner = max(0, r - pad)                       # concentric: the outline's radius less the gap
        fh = h - 2 * pad
        d.rounded_rectangle([(x + pad, y + pad), (x + pad + fill - 1, y + pad + fh - 1)],
                            radius=min(inner, fill // 2, fh // 2), fill=T.BLACK)


def _draw_message(d, box, lines: list[tuple[str, bool]]) -> None:
    """A title and plain steps, centred, smaller until it fits; steps that don't fit are left out."""
    x, y, w, h = box
    if len(lines) == 1:
        hero.message(d, box, lines[0][0])
        return
    for keep in range(len(lines), 0, -1):
        shown = lines[:keep]
        for px in range(max(MIN_C, min(h // 6, 34)), MIN_C - 1, -1):
            sub = max(MIN_C, round(px * 0.7))
            rows = []
            for k, (text, bold) in enumerate(shown):
                size = px if k == 0 else sub
                f = T.font(size, bold=bold or k == 0, text=text)
                prefix = f"{k}. " if k and len(shown) > 2 and not bold else ""
                wrapped = T.wrap_lines(prefix + text, f, w)
                rows += [(ln, f) for ln in wrapped[:2]]
                if len(wrapped) > 2:
                    rows = None
                    break
            if rows is None:
                continue
            heights = [sum(f.getmetrics()) for _, f in rows]
            gap = round(px * 0.5)
            total = sum(heights) + gap
            if total <= h:
                top = y + (h - total) // 2
                for i, ((ln, f), lh) in enumerate(zip(rows, heights)):
                    d.text((x + w // 2, top), ln, font=f, fill=T.BLACK, anchor="mt")
                    top += lh + (gap if i == 0 else 0)
                return
    hero.message(d, box, lines[0][0])


def draw(img, d, box, el: dict, data, *, scale: float = 1.0, now: datetime | None = None) -> None:
    p = plan(box, data, el, now, scale=scale)
    if p.message:
        _draw_message(d, box, p.message)
        return
    x, y, w, h = box
    bf, sf, hf = T.font(p.v, bold=True), T.font(p.c, bold=False), T.font(p.c, bold=True)
    lh, ink = _line(p.c), _ink(p.v)
    for b in p.blocks:
        if b.heading_at:
            side = p.way.heading == "side"
            d.text(b.heading_at, hero.shorten(b.heading, hf, w if not side else round(w * 0.34)), font=hf, fill=T.BLACK)
        for cell in b.cells:
            cx, cy, cw, _ = cell.box
            d.text((cx, cy), cell.label, font=sf, fill=T.BLACK)
            ty = cy + lh + p.gap
            d.text((cx, ty - bf.getbbox(cell.big or "0")[1]), cell.big, font=bf, fill=T.BLACK)
            if cell.beside:
                bx = cx + T.text_width(cell.big, bf) + round(p.v * 0.15)
                d.text((bx, ty + ink), cell.beside, font=sf, fill=T.BLACK, anchor="ls")
            by = ty + ink + p.gap
            if cell.share is not None:
                _bar(d, (cx, by, cw - max(4, cw // 40), p.bar), cell.share)
            if cell.reset:
                if p.way.resets == "beside":
                    d.text(cell.reset_at, cell.reset, font=sf, fill=T.BLACK, anchor="ls")
                else:
                    d.text(cell.reset_at, cell.reset, font=sf, fill=T.BLACK)
        if b.extras_text:
            d.text(b.extras_at, b.extras_text, font=sf, fill=T.BLACK)
    if p.quiet:
        d.text(p.quiet_at, p.quiet, font=hf, fill=T.BLACK)
