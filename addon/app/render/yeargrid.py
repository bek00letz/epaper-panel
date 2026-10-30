"""A square per day, more ink for more, with a few totals beside it.

The grid never knows where its numbers came from: a GitHub user's contributions, any daily Home
Assistant number from long-term statistics, or one of your data sources all arrive as the same
days (sources/yeargrid.py): {"days": [[date, value or None], ...], "unit", "what"}. None is a day
with nothing known (before a sensor existed), drawn as nothing; 0 is a day with nothing in it,
drawn as a small dot so the grid still reads.

No grey on e-ink, so "more" is a larger square, not a darker one: four sizes from the day's
quartile among the days with something, then a full square. A week is a column, as on GitHub;
the span is a year, or the most weeks that keep a square large enough to see. A tall box wraps
the weeks into bands rather than leaving most of it empty (`plan`).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from . import clock, hero, words
from . import theme as T
from .words import say

SPANS = {"year": 53, "half": 26, "quarter": 13, "month": 5}
MIN_PITCH = 9           # smaller and a day is a speck at arm's length
MAX_PITCH = 44          # larger and a day stops reading as part of a year
LEVELS = (0.42, 0.62, 0.82, 1.0)   # a day's square, by its level, as a share of a cell
LABEL_FROM = 15         # month names above the weeks from this pitch up
MOST_BANDS = 4
FEWEST_WEEKS = 8      # with totals beside, at least this many weeks, or they give way


# ------------------------------------------------------------------ the days, as facts

def days_of(data) -> list[tuple[date, float | None]]:
    """The data's days, oldest first, each once; anything unreadable left out."""
    out = {}
    for item in (data or {}).get("days") or []:
        try:
            raw, value = item if isinstance(item, (list, tuple)) else (item.get("date"), item.get("value"))
            day = date.fromisoformat(str(raw)[:10])
        except (TypeError, ValueError, AttributeError):
            continue
        try:
            out[day] = None if value is None else float(value)
        except (TypeError, ValueError):
            out[day] = None
    return sorted(out.items())


def thresholds(values) -> tuple[float, float, float]:
    """The quartiles of the days with something: a day above the third is a full square. Quartiles,
    not the busiest day, so one huge day doesn't shrink every other one to a dot."""
    xs = sorted(v for v in values if v is not None and v > 0)
    if not xs:
        return (0.0, 0.0, 0.0)

    def q(p):
        k = (len(xs) - 1) * p
        lo, hi = math.floor(k), math.ceil(k)
        return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)
    return q(0.25), q(0.5), q(0.75)


def level(value, cuts) -> int:
    """0 for nothing (or less), else 1-4 by the quartiles."""
    if value is None or value <= 0:
        return 0
    return 1 + sum(1 for c in cuts if value > c)


@dataclass
class Summary:
    total: float
    days: int                   # days with something known
    busiest: tuple[date, float] | None
    longest: int                # the longest run of days with something
    current: int                # the run ending today (or yesterday: today isn't over)
    average: float | None


def summary(days: list[tuple[date, float | None]], today: date) -> Summary:
    known = [(d, v) for d, v in days if v is not None and d <= today]
    total = sum(v for _, v in known)
    busiest = max(((d, v) for d, v in known if v > 0), key=lambda p: (p[1], p[0]), default=None)
    longest = run = 0
    last = None                                 # the last day with something, while a run goes on
    for d, v in known:
        if v > 0:
            run = run + 1 if last is not None and (d - last).days == 1 else 1
            last = d
        else:
            run, last = 0, None
        longest = max(longest, run)
    by_day = dict(known)
    current, k = 0, today if (by_day.get(today) or 0) > 0 else today - timedelta(days=1)
    while (by_day.get(k) or 0) > 0:
        current += 1
        k -= timedelta(days=1)
    return Summary(total, len(known), busiest, longest, current, total / len(known) if known else None)


def amount(value: float, data: dict) -> str:
    """A value as the source counts it: "12.5 kWh"; a count of contributions as its number, the word
    being in its caption ("1,204", "contributions since 3 Nov"), so it stays large."""
    v = abs(value)
    if (data or {}).get("what") == "github":
        return words.number(round(value), 0, group=True)
    text = words.number(value, 0 if v >= 100 or float(value).is_integer() else 1, group=True)
    unit = str((data or {}).get("unit") or "").strip()
    return f"{text} {unit}" if unit else text


def facts(days, data, today: date, first_shown: date) -> list[hero.Fact]:
    """The totals, most telling first: as many as fit are shown."""
    s = summary([(d, v) for d, v in days if d >= first_shown], today)
    if not s.days or data.get("levels_only"):
        return []               # GitHub gave levels, not counts: totals would be made up
    since = clock.date(datetime.combine(first_shown, datetime.min.time()), "date")
    total_words = "yeargrid.contributions_since" if data.get("what") == "github" else "yeargrid.since"
    out = [hero.Fact(amount(s.total, data), say(total_words, date=since)),
           hero.Fact(say("day.days", s.current), say("yeargrid.current")),
           hero.Fact(say("day.days", s.longest), say("yeargrid.longest"))]
    if s.busiest:
        when = clock.date(datetime.combine(s.busiest[0], datetime.min.time()), "date")
        out.append(hero.Fact(amount(s.busiest[1], data), say("yeargrid.busiest", date=when)))
    if s.average is not None:
        out.append(hero.Fact(amount(s.average, data), say("yeargrid.average")))
    return out


# ------------------------------------------------------------------ the layout

@dataclass
class Plan:
    weeks: int
    bands: int
    pitch: int
    grid: tuple[int, int, int, int]
    facts: tuple[int, int, int, int] | None     # where the totals go
    beside: bool
    labels: int                                 # the month names' height above each band, or 0


def _label_h(pitch: int) -> int:
    return max(hero.MIN_CAPTION, round(pitch * 0.62)) if pitch >= LABEL_FROM else 0


def _try(gw, gh, weeks, bands, gap):
    cols = math.ceil(weeks / bands)
    p = min(gw / cols, (gh - (bands - 1) * gap) / (7 * bands))
    lab = _label_h(int(p))
    if lab:
        p = min(gw / cols, (gh - (bands - 1) * gap - bands * lab) / (7 * bands))
        lab = _label_h(int(p))
    return int(min(p, MAX_PITCH)), lab


FACT_PX = 30           # a total's value, as large as a list's row words
MIN_FACT = 16          # smaller and a total stops reading


def _type(scale: float, px: int | None = None) -> tuple[int, int]:
    """(value, caption) sizes for the totals."""
    v = px or max(MIN_FACT, min(48, round(FACT_PX * scale)))
    return v, max(hero.MIN_CAPTION, round(v * 0.5))


def room(fs: list[hero.Fact], w: int, h: int, scale: float = 1.0) -> tuple[int, int]:
    """(width beside, height below) the totals ask for: beside, the widest at their size (at most
    two fifths of the box); below, a row of them. 0 where even the smallest size can't fit."""
    if not fs:
        return 0, 0
    vpx, cpx = _type(scale)
    vf, cf, small = T.font(vpx, bold=True), T.font(cpx, bold=False), T.font(MIN_FACT, bold=True)
    widest = max(max(T.text_width(f.value, vf), T.text_width(f.caption, cf)) for f in fs)
    least = max(T.text_width(f.value, small) for f in fs)
    side = min(widest + 8, round(w * 0.42))
    block = lambda v, c: v + round(c * 0.4) + c + 8              # noqa: E731
    return (side if side >= least + 8 else 0), (block(vpx, cpx) if least + 12 <= w else 0)


def plan(w: int, h: int, weeks: int, with_facts: bool | tuple, scale: float = 1.0) -> Plan:
    """The largest squares for `weeks` weeks in a w x h box: totals beside or below, the weeks in one
    band or wrapped into several. Fewer weeks when even the best can't keep a square of MIN_PITCH.
    The totals stay as long as at least FEWEST_WEEKS (or all asked for) still fit beside them; only
    then do they give way to the grid."""
    gap = max(8, round(min(w, h) / 24))
    with_totals = []
    side, low = with_facts if isinstance(with_facts, tuple) else ((max(110, round(w * 0.3)), max(44, round(h * 0.26)))
                                                                   if with_facts else (0, 0))
    if side or low:
        if side and w - side - gap > 7 * MIN_PITCH:
            with_totals.append((True, (w - side - gap, h), (w - side, 0, side, h)))
        if low and h - low - gap > 7 * MIN_PITCH:
            with_totals.append((False, (w, h - low - gap), (0, h - low, w, low)))
    alone = [(True, (w, h), None)]

    def best(n, options):
        found = None
        for beside, (gw, gh), fbox in options:
            for bands in range(1, min(MOST_BANDS, n) + 1):
                p, lab = _try(gw, gh, n, bands, gap)
                score = (p, -bands, beside)
                if found is None or score > found[0]:
                    found = (score, Plan(n, bands, p, (0, 0, gw, gh), fbox, beside, lab))
        return found[1]

    for options, fewest in ((with_totals, min(weeks, FEWEST_WEEKS)), (alone, 1)):
        for n in range(weeks, fewest - 1, -1) if options else ():
            got = best(n, options)
            if got.pitch >= MIN_PITCH:
                return got
    return best(1, alone)


# ------------------------------------------------------------------ drawing

def _week_start(day: date, first_weekday: int) -> date:
    return day - timedelta(days=(day.weekday() - first_weekday) % 7)


def draw_facts(d, box, fs: list[hero.Fact], beside: bool, scale: float) -> int:
    """As many totals as fit, stacked (beside the grid) or in a row (below it), one size for all,
    the most telling first. Returns how many."""
    x, y, w, h = box
    for n in range(len(fs), 0, -1):
        shown = fs[:n]
        slot = h / n if beside else w / n
        width = w if beside else slot - 12
        vpx, _ = _type(scale)
        for _ in range(64):
            cpx = _type(scale, vpx)[1]
            vf, cf = T.font(vpx, bold=True), T.font(cpx, bold=False)
            block = vf.getmetrics()[0] + round(cpx * 0.4) + sum(cf.getmetrics())
            # Its words whole too, unless one total is all there's room for.
            if (block <= (slot if beside else h)) and all(T.text_width(f.value, vf) <= width for f in shown) \
                    and (n == 1 or all(T.text_width(f.caption, cf) <= width for f in shown)):
                break
            vpx -= 1
            if vpx < MIN_FACT:
                break
        if vpx >= MIN_FACT:
            break
    else:
        return 0
    asc = vf.getmetrics()[0]
    for k, f in enumerate(shown):
        if beside:
            cx, cy, cw = x, round(y + k * slot + (slot - block) / 2), w
        else:
            cx, cy, cw = round(x + k * slot), y + max(0, (h - block) // 2), round(slot) - 12
        d.text((cx, cy), hero.shorten(f.value, vf, cw), font=vf, fill=T.BLACK, anchor="la")
        d.text((cx, cy + asc + round(cpx * 0.4)), hero.shorten(f.caption, cf, cw), font=cf, fill=T.BLACK, anchor="la")
    return len(shown)


def draw(img, d, box, el: dict, data, *, scale: float = 1.0) -> None:
    if not isinstance(data, dict):
        return                                  # not read yet: nothing, rather than a grid of made-up days
    x, y, w, h = box
    if data.get("missing"):
        hero.message(d, box, problem(data))
        return
    days = days_of(data)
    if not days or all(v is None for _, v in days):
        hero.message(d, box, say("yeargrid.no_data"))
        return
    today = _today(data, days)
    first_weekday = 6 if str(el.get("first_weekday")) == "6" else 0
    wanted = SPANS.get(str(el.get("span") or "year"), SPANS["year"])
    with_facts = el.get("show_totals") is not False
    year_ago = _week_start(today, first_weekday) - timedelta(weeks=wanted - 1)
    need = room(facts(days, data, today, year_ago), w, h, scale) if with_facts else (0, 0)
    p = plan(w, h, wanted, need, scale)
    start = _week_start(today, first_weekday) - timedelta(weeks=p.weeks - 1)
    cuts = thresholds(v for d_, v in days if d_ >= start)
    by_day = dict(days)

    gx, gy, gw, gh = p.grid
    cols = math.ceil(p.weeks / p.bands)
    gap_b = max(8, round(min(w, h) / 24))
    band_h = p.labels + 7 * p.pitch
    used_w, used_h = cols * p.pitch, p.bands * band_h + (p.bands - 1) * gap_b
    # The grid sits at the left, centred up and down in its part; the totals start where its ink ends.
    ox, oy = x + gx, y + gy + max(0, (gh - used_h) // 2)
    cell = p.pitch - max(2, round(p.pitch * 0.18))
    lab_f = T.font(p.labels, bold=False) if p.labels else None
    label_end = ox
    for week in range(p.weeks):
        band, col = divmod(week, cols)
        wx = ox + col * p.pitch
        top = oy + band * (band_h + gap_b) + p.labels
        monday = start + timedelta(weeks=week)
        if lab_f:
            # A month's name over the week its 1st is in; the first week of a band says its own month,
            # unless the next week starts one. Never over the name before it.
            firsts = [monday + timedelta(days=k) for k in range(7) if (monday + timedelta(days=k)).day == 1]
            nxt = any((monday + timedelta(days=7 + k)).day == 1 for k in range(7))
            month = firsts[0].month if firsts else (monday.month if col == 0 and not nxt else 0)
            if col == 0:
                label_end = ox
            if month:
                name = words.name("mon", month).rstrip(".")
                if wx >= label_end and wx + T.text_width(name, lab_f) <= ox + used_w:
                    d.text((wx, top - 2), name, font=lab_f, fill=T.BLACK, anchor="ld")
                    label_end = wx + T.text_width(name, lab_f) + max(4, p.pitch // 3)
        for k in range(7):
            day = monday + timedelta(days=k)
            if day > today:
                break
            value = by_day.get(day)
            cx, cy = wx + (p.pitch - cell) // 2, top + k * p.pitch + (p.pitch - cell) // 2
            if value is None:
                continue
            lv = level(value, cuts)
            side = max(3, round(cell * (LEVELS[lv - 1] if lv else 0.2)))
            off = (cell - side) // 2
            rad = max(0, side // 5) if side >= 8 else 0
            d.rounded_rectangle([(cx + off, cy + off), (cx + off + side - 1, cy + off + side - 1)], radius=rad, fill=T.BLACK)
    if p.facts and with_facts:
        fx, fy, fw, fh = p.facts
        if p.beside:
            # Beside the grid: from where its squares end, so a narrow span doesn't leave a gap.
            left = min(x + fx, ox + used_w + gap_b * 2)
            draw_facts(d, (left, y + fy, x + w - left, fh), facts(days, data, today, start), True, scale)
        else:
            top = min(y + fy, oy + used_h + gap_b)
            draw_facts(d, (x + fx, top, fw, y + h - top), facts(days, data, today, start), False, scale)


def _today(data: dict, days) -> date:
    raw = data.get("today")
    try:
        return date.fromisoformat(str(raw)[:10])
    except (TypeError, ValueError):
        return days[-1][0]


def problem(data: dict) -> str:
    """What the grid says instead of its days, plainly, with what to do."""
    what = data.get("missing")
    if what == "user":
        return say("yeargrid.no_user", user=str(data.get("user") or ""))
    if what == "statistics":
        return say("yeargrid.no_statistics", name=str(data.get("name") or data.get("entity") or ""))
    if what == "unavailable":
        return say("yeargrid.unavailable")
    return say("yeargrid.choose")
