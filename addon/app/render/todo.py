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


def due_label(item: dict, now: datetime) -> tuple[str, bool]:
    """The short label for an item's due date, and whether it's urgent
    (overdue or today), which the page draws inverted. ("", False) for none."""
    due = due_of(item, now)
    if due is None:
        return "", False
    if _overdue(due, now):
        return "Overdue", True
    day = _day(due)
    if day == now.date():
        return (f"Today {due:%H:%M}" if isinstance(due, datetime) else "Today"), True
    if day == now.date() + timedelta(days=1):
        return "Tomorrow", False
    if day < now.date() + timedelta(days=7):
        return f"{day:%a}", False
    return f"{day.day} {day:%b}", False


def fit(count: int, avail_h: int, item_px: int) -> tuple[int, int, int]:
    """How a list of `count` items fills `avail_h`: (row height, items shown,
    how many more). When they don't all fit, "and 4 more" takes the last
    row; with room for only one row, the count in the header says it."""
    row_h = item_px + max(8, round(item_px * 0.36))
    rows = max(1, (avail_h - item_px) // row_h + 1)   # the last row needs no space under it
    if count <= rows:
        return row_h, count, 0
    if rows == 1:
        return row_h, 1, 0
    return row_h, rows - 1, count - (rows - 1)


def due_sensor(entity_id: str) -> str:
    """The add-on's count of what's due today or overdue on a list."""
    return f"sensor.epaper_todo_{entity_id.split('.', 1)[1]}_due"


def count_label(n: int, show: str) -> str:
    if show == "due":
        return f"{n} due"
    return f"{n} to do"


def empty_text(show: str) -> str:
    return "Nothing due today" if show == "due" else "Nothing to do"
