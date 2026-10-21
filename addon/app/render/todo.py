"""A Home Assistant to-do list as a page: which items, in what order, and
the short due label each one gets.

One source of truth for what a list shows: the page (`layout`) and the
add-on's due count (`entities.publish_computed`) both read it from here.

Items come as Home Assistant's `todo.get_items` gives them, in the list's
own stored order (not by due date): `summary`, `uid`, `status`
(`needs_action` or `completed`), and `due` where the list has due dates,
either a date (`2026-10-21`) or a date and time with its zone.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

# What the page shows: everything still to do, or only what's due by today.
SHOWS = ("open", "due")


def now_in(tz_name) -> datetime:
    """Now in Home Assistant's time zone (its "today"), or the add-on's own."""
    try:
        return datetime.now(ZoneInfo(tz_name)) if tz_name else datetime.now().astimezone()
    except Exception:
        return datetime.now().astimezone()


def due_of(item: dict, now: datetime):
    """The item's due date or time (in `now`'s zone), or None."""
    raw = str((item or {}).get("due") or "").strip()
    if not raw:
        return None
    try:
        if len(raw) == 10:
            return date.fromisoformat(raw)
        when = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if when.tzinfo is not None and now.tzinfo is not None:
        when = when.astimezone(now.tzinfo)
    elif when.tzinfo is not None:
        when = when.replace(tzinfo=None)
    return when


def _day(due) -> date:
    return due.date() if isinstance(due, datetime) else due


def is_due(item: dict, now: datetime) -> bool:
    """Due today or overdue."""
    due = due_of(item, now)
    return due is not None and _day(due) <= now.date()


def _overdue(due, now: datetime) -> bool:
    if isinstance(due, datetime):
        # due_of gives a time in now's zone, or one with no zone ("local").
        return due < (now.replace(tzinfo=None) if due.tzinfo is None else now)
    return due < now.date()


def items_for(items, show: str, now: datetime) -> list[dict]:
    """What the page lists: open items, those with a due date first (soonest
    first, overdue at the top), then the rest in the list's own order."""
    open_items = [i for i in (items or []) if isinstance(i, dict) and str(i.get("summary") or "").strip()
                  and i.get("status", "needs_action") == "needs_action"]
    if show == "due":
        open_items = [i for i in open_items if is_due(i, now)]
    dated = [(i, due_of(i, now)) for i in open_items]

    def key(pair):
        due = pair[1]
        # An all-day item is due by the end of its day, so after that day's timed ones.
        return (_day(due), due.time() if isinstance(due, datetime) else time.max)

    with_due = sorted((p for p in dated if p[1] is not None), key=key)
    return [i for i, _ in with_due] + [i for i, due in dated if due is None]


def due_label(item: dict, now: datetime) -> tuple[str, str]:
    """The short label for an item's due date, and how urgent it is:
    "overdue", "today" or "" (later, or no date). ("", "") for none."""
    due = due_of(item, now)
    if due is None:
        return "", ""
    if _overdue(due, now):
        return "Overdue", "overdue"
    day = _day(due)
    if day == now.date():
        return (f"Today {due:%H:%M}" if isinstance(due, datetime) else "Today"), "today"
    if day == now.date() + timedelta(days=1):
        return "Tomorrow", ""
    if day < now.date() + timedelta(days=7):
        return f"{day:%a}", ""
    return f"{day.day} {day:%b}", ""


# How rows look (the user's call, 21 Oct). Each row is "invert" (a solid
# pill, white inside), "outline" (a pill drawn round it) or "plain".
#   urgency:  overdue inverted, today outlined, the rest plain: loud only where it matters
#   due:      overdue and today inverted, the rest outlined
#   outlined: every row outlined
#   plain:    no pills, labels at the right edge: the first look, kept as the
#             way back until the pill styles have proven themselves on a panel;
#             the editor doesn't offer it (the user's call, 21 Oct)
STYLES = ("urgency", "due", "outlined", "plain")
DEFAULT_STYLE = "urgency"


def style_of(el: dict) -> str:
    return el.get("style") if el.get("style") in STYLES else DEFAULT_STYLE


def row_look(style: str, urgency: str) -> str:
    if style == "urgency":
        return {"overdue": "invert", "today": "outline"}.get(urgency, "plain")
    if style == "due":
        return "invert" if urgency else "outline"
    if style == "outlined":
        return "outline"
    return "plain"


def rows(style: str, item_px: int) -> tuple[int, int]:
    """(row height, pitch) for a style. Pill rows (every style but plain) are
    drawn 4/3 of the text tall with a gap, so a row never touches the next;
    every row keeps that pitch, so nothing moves when an item falls due."""
    if style == "plain":
        row_h = item_px + max(8, round(item_px * 0.36))
        return row_h, row_h
    row_h = round(item_px * 4 / 3)
    return row_h, row_h + max(4, round(item_px / 5))


def fit(count: int, avail_h: int, row_h: int, pitch: int) -> tuple[int, int]:
    """How a list of `count` items fills `avail_h`: (items shown, how many
    more). When they don't all fit, "and 4 more" takes the last row; with
    room for only one row, the count in the header says it."""
    n = max(1, (avail_h - row_h) // pitch + 1)         # the last row needs no gap under it
    if count <= n:
        return count, 0
    if n == 1:
        return 1, 0
    return n - 1, count - (n - 1)


def due_sensor(entity_id: str) -> str:
    """The add-on's count of what's due today or overdue on a list."""
    return f"sensor.epaper_todo_{entity_id.split('.', 1)[1]}_due"


def count_label(n: int, show: str) -> str:
    if show == "due":
        return f"{n} due"
    return f"{n} to do"


def empty_text(show: str) -> str:
    return "Nothing due today" if show == "due" else "Nothing to do"
