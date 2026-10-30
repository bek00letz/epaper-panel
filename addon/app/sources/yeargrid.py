"""The days a year grid shows, from wherever they come: the grid draws only these.

Each reader gives the same shape, so render/yeargrid.py never knows the source:

    {"days": [["2026-01-01", 3.2], ...], "today": "2026-10-30", "unit": "kWh", "what": "statistic"}

oldest first, a value or None (nothing known that day), or {"missing": ...} saying what's wrong.

- `fetch_statistic`: any daily number Home Assistant keeps long-term statistics of (solar kWh, a
  heating-hours sensor, steps). A counter (it keeps a sum) gives each day's change; anything else
  gives each day's highest, which is a daily total's value at the end of its day. Statistics are
  never purged, so a year is there once the sensor has been recorded that long.
- `fetch_github`: a GitHub user's public contributions, from GitHub's own contribution calendar
  (the page a profile draws, `services.url("github")`), with no token and no account. GitHub is
  asked at most four times a day per user, and the last good answer stays meanwhile.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta

import aiohttp

import examples
import health
import runtime
import services
from config import HA_TOKEN
from sources import hass_read

DAYS = 371                      # 53 weeks: the grid takes what fits
HOWS = ("auto", "change", "max", "mean")
USER = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}$")
GITHUB_EVERY = 6 * 3600


def clean_user(raw) -> str:
    """A GitHub username as GitHub allows them (letters, digits, single hyphens, 39 at most), or ""."""
    user = str(raw or "").strip().lstrip("@")
    return user if USER.match(user) else ""


# ------------------------------------------------------------------ Home Assistant's statistics

def how_for(meta: dict, how: str = "auto") -> str:
    """Which number a day is: what was asked, or by what Home Assistant keeps of the statistic."""
    if how in ("change", "max", "mean"):
        return how
    return "change" if meta.get("has_sum") else "max"


def days_from_rows(rows, how: str, today: date, tz, days: int = DAYS) -> list[list]:
    """Statistics rows (one a day) as the grid's days, oldest first: every day from `days` ago to
    today, None where Home Assistant has no row."""
    by_day = {}
    for row in rows or []:
        start = hass_read.row_start(row, tz)
        value = row.get(how)
        if start is None or value is None:
            continue
        try:
            by_day[start.date()] = round(float(value), 3)
        except (TypeError, ValueError):
            continue
    first = today - timedelta(days=days - 1)
    return [[(first + timedelta(days=k)).isoformat(), by_day.get(first + timedelta(days=k))] for k in range(days)]


@runtime.live(1800)
async def fetch_statistic(session, entity: str, how: str = "auto"):
    entity = str(entity or "").strip()
    now = await hass_read.home_now(session)
    if not HA_TOKEN:
        return examples.year_grid("statistic", now.date())
    if not hass_read.clean_ids([entity]):
        return {"days": [], "missing": "choose"}
    meta = (await hass_read.statistics_meta([entity])).get(entity)
    if not meta:
        name = ((await hass_read.states_of(session, [entity])) or [{}])[0].get("name") or entity
        return {"days": [], "missing": "statistics", "entity": entity, "name": name}
    kind = how_for(meta, how if how in HOWS else "auto")
    if kind == "mean" and not hass_read.mean_kind(meta):
        kind = "max" if not meta.get("has_sum") else "change"
    start = datetime.combine(now.date() - timedelta(days=DAYS - 1), datetime.min.time(), now.tzinfo)
    rows = (await hass_read.statistics([entity], start, "day", (kind,))).get(entity) or []
    return {"days": days_from_rows(rows, kind, now.date(), now.tzinfo), "today": now.date().isoformat(),
            "unit": str(meta.get("statistics_unit_of_measurement") or meta.get("display_unit_of_measurement") or ""),
            "what": "statistic"}


# ------------------------------------------------------------------ GitHub

_CELL = re.compile(r"<td\b[^>]*?\bdata-date=\"(\d{4}-\d{2}-\d{2})\"[^>]*>", re.S)
_ATTR = lambda name: re.compile(r'\b' + name + r'="([^"]*)"')      # noqa: E731
_ID, _LEVEL = _ATTR("id"), _ATTR("data-level")
_TIP = re.compile(r"<tool-tip\b[^>]*?\bfor=\"([^\"]+)\"[^>]*>(.*?)</tool-tip>", re.S)
_COUNT = re.compile(r"^\s*(No|[\d,.]+)\s+contributions?\b", re.I)


def read_github(html: str) -> dict:
    """GitHub's contribution calendar (the page at /users/<name>/contributions) as the grid's days.
    Each day is a cell with its date; its count is in the words beside it ("3 contributions on
    June 2nd."). If GitHub ever drops the words, the cell's level (0-4) still draws the grid, and
    the totals are left out rather than made up (`levels_only`). ValueError: not a calendar."""
    cells = []
    for m in _CELL.finditer(html or ""):
        tag = m.group(0)
        cid, lv = _ID.search(tag), _LEVEL.search(tag)
        cells.append((m.group(1), cid.group(1) if cid else "", int(lv.group(1)) if lv and lv.group(1).isdigit() else None))
    if not cells:
        raise ValueError("GitHub's answer has no contribution calendar in it")
    counts = {}
    for m in _TIP.finditer(html):
        c = _COUNT.match(re.sub(r"<[^>]+>", "", m.group(2)))
        if c:
            counts[m.group(1)] = 0 if c.group(1).lower() == "no" else int(re.sub(r"[,.]", "", c.group(1)))
    levels_only = not any(cid in counts for _, cid, _ in cells)
    days = {}
    for day, cid, lv in cells:
        value = counts.get(cid) if not levels_only else lv
        days[day] = value if value is not None else (lv if levels_only else None)
    ordered = sorted(days.items())
    return {"days": [[d, v] for d, v in ordered], "today": ordered[-1][0], "unit": "", "what": "github",
            **({"levels_only": True} if levels_only else {})}


@runtime.live(GITHUB_EVERY)
async def fetch_github(session, user: str):
    """A GitHub user's contributions for the past year, or {"missing": "user"} for no such user."""
    user = clean_user(user)
    if not user:
        return {"days": [], "missing": "choose"}
    url = f"{services.url('github')}/{user}/contributions"
    async with session.get(url, headers=services.HEADERS, allow_redirects=False,
                           timeout=aiohttp.ClientTimeout(total=20, sock_connect=10),
                           trace_request_ctx=health.Ask(missing_ok=True, judged=True)) as r:
        if r.status == 404:
            health.ok(services.name("github"))
            return {"days": [], "missing": "user", "user": user}
        r.raise_for_status()
        html = await r.text()
    try:
        got = read_github(html)
    except ValueError as exc:
        health.fail(services.name("github"), exc)
        raise
    health.ok(services.name("github"))
    return got


async def fetch(session, el: dict):
    """The days an element shows, from its source."""
    if str(el.get("source") or "statistic") == "github":
        return await fetch_github(session, clean_user(el.get("user")))
    return await fetch_statistic(session, str(el.get("entity") or ""), str(el.get("how") or "auto"))
