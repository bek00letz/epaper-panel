"""Racing series: what's on now or next, and race windows.

One rule for every series. A series lists the calendars it's published in,
most trusted first: the series' own, then community ones (`Series.calendars`).
All of them are read and merged by race day (`_season`): the first calendar
that has a race names it, and the one that knows most of its sessions times
it, so the series' own calendar knows a new season the day it's published
and a community one adds exact session times once it catches up. `_pick`
then says what to show, the same way for every series:

  PRE / IN / POST   a race weekend: before, during, and for a few hours after
                    (`AFTER_HOURS`), while its result is worth showing;
  OFF               the off-season: the next season's first race while it's
                    more than `OFF_SEASON_LEAD` away, or, when no calendar
                    has a race to come, that the calendar isn't out yet.

ESPN's scoreboard adds live status and standings for the series it covers.
"""

import json
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import aiohttp

import health
import runtime
from render import clock
from sources.geo import get_home_timezone


@dataclass(frozen=True)
class Calendar:
    """One place a series' race calendar is published, and how it's read (a key of `_READERS`)."""
    reader: str
    url: str                # "{year}": published a year at a time; this year's and next year's are read


_SPORTSTIMES = "https://raw.githubusercontent.com/sportstimes/f1/main/_db/{db}/{{year}}.json"


def _sportstimes(db: str) -> Calendar:
    """The community session database behind f1calendar.com and its siblings."""
    return Calendar("sessions", _SPORTSTIMES.format(db=db))


ESPN_CALENDAR = Calendar("espn", "")    # the series' ESPN scoreboard (`Series.espn`): its season and this weekend


@dataclass(frozen=True)
class Series:
    """One racing series: every place that needs to know a series asks here."""
    slug: str               # names its sensor, sensor.epaper_racing_<slug>
    code: str               # short, on the page: "F1"
    title: str              # "Formula 1"
    event: str              # what an event is called before we know its name
    venue: str              # what a venue is called before we know its name
    aliases: tuple          # what a page may say for it
    espn: str | None        # ESPN's scoreboard for it (live status, standings)
    calendars: tuple        # where its calendar is published, most trusted first (Calendar)
    icon: str


SERIES = {s.slug: s for s in (
    Series("f1", "F1", "Formula 1", "Formula 1 Grand Prix", "Grand Prix Circuit",
           ("f1", "formula1", "formula_1", "formula-1"), espn="f1",
           calendars=(_sportstimes("f1"), ESPN_CALENDAR), icon="mdi:racing-helmet"),
    # Formula E's own calendar page carries the season as schema.org events (dates only).
    Series("fe", "FE", "Formula E", "Formula E World Championship", "ePrix Circuit",
           ("fe", "formula_e", "formula-e", "formulae"), espn=None,
           calendars=(Calendar("events", "https://www.fiaformulae.com/en/calendar"), _sportstimes("fe"),
                      Calendar("sessions", "https://formulaecal.com/api/year/{year}")),
           icon="mdi:car-electric"),
    Series("nascar", "NASCAR", "NASCAR", "NASCAR Cup Series", "Speedway",
           ("nascar", "nascar-premier", "nascar_cup"), espn="nascar-premier",
           calendars=(ESPN_CALENDAR,), icon="mdi:racing-helmet"),
    Series("indycar", "INDYCAR", "IndyCar", "IndyCar Series", "Circuit",
           ("indycar", "irl"), espn="irl",
           calendars=(ESPN_CALENDAR, _sportstimes("indycar")), icon="mdi:racing-helmet"),
)}
_ALIASES = {a: s for s in SERIES.values() for a in s.aliases}


def series_of(value) -> Series:
    """The series a page names, or Formula 1 for anything it doesn't know (an entity ID, say)."""
    return _ALIASES.get(str(value or "f1").strip().lower(), SERIES["f1"])


# ---------------------------------------------------------------- a season: every calendar, merged

AFTER_HOURS = 4.0                       # a finished race's result stays this long
OFF_SEASON_LEAD = timedelta(days=7)     # a season's first race further off than this: off-season
SEASON_GAP = timedelta(weeks=10)        # a longer gap than this before a race: it opens a season
CALENDAR_EVERY = 3600.0                 # calendars change rarely
RETRY_EVERY = 600.0                     # one that failed is asked again sooner
HEADERS = {"User-Agent": "Crowpanel-Epaper/0.8.23 (HomeAssistant Addon)"}
TIMEOUT = aiohttp.ClientTimeout(total=6)

_SESSION_NAMES = {"practice1": "Practice 1", "practice2": "Practice 2", "practice3": "Practice 3",
                  "fp1": "Practice 1", "fp2": "Practice 2", "fp3": "Practice 3", "qualifying": "Qualifying",
                  "qual": "Qualifying", "sprintqualifying": "Sprint qualifying", "sprint": "Sprint",
                  "gp": "Race", "race": "Race"}


def session_name(key: str) -> str:
    """A session as a page says it: "practice1" and ESPN's "FP1" are both "Practice 1"."""
    k = str(key or "").strip()
    return _SESSION_NAMES.get(k.lower().replace(" ", ""), k[:1].upper() + k[1:])


def _hours(label: str) -> float:
    return 2.5 if session_name(label) == "Race" else 1.5


@dataclass(frozen=True)
class Race:
    """One race weekend, from one calendar or merged from several."""
    name: str
    location: str
    day: date                   # race day, by which calendars are matched
    sessions: tuple = ()        # ((label, start UTC, hours), ...) by start; () when only the day is known
    season: str = ""            # what its calendar calls the season ("Season 13"), when it says

    @property
    def start(self) -> datetime:
        return self.sessions[0][1] if self.sessions else datetime.combine(self.day, datetime.min.time(), timezone.utc)

    @property
    def end(self) -> datetime:
        if self.sessions:
            return max(s + timedelta(hours=h) for _, s, h in self.sessions)
        return self.start + timedelta(days=1)


def _when(value) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _timed(name, location, sessions, season="") -> Race | None:
    """A race from its sessions; its day is its last session's (the race)."""
    sessions = tuple(sorted(sessions, key=lambda s: s[1]))
    if not sessions:
        return None
    return Race(str(name or ""), str(location or ""), sessions[-1][1].date(), sessions, season)


def _read_sessions(body) -> list[Race]:
    """sportstimes' and formulaecal's shape: {"races": [{"name", "location", "sessions": {key: time}}]}."""
    out = []
    for r in (body or {}).get("races") or [] if isinstance(body, dict) else []:
        sessions = [(k, dt, _hours(k)) for k, v in (r.get("sessions") or {}).items() if v and (dt := _when(v))]
        if race := _timed(r.get("name"), r.get("location"), sessions):
            out.append(race)
    return out


_LD_JSON = re.compile(r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', re.S | re.I)


def _read_events(page: str) -> list[Race]:
    """schema.org SportsEvents in a page's structured data (JSON-LD): a season's races, by day."""
    found = []

    def walk(node):
        if isinstance(node, list):
            for n in node:
                walk(n)
        elif isinstance(node, dict):
            if node.get("@type") == "SportsEvent":
                found.append(node)
            for k in ("@graph", "itemListElement", "item"):
                walk(node.get(k))
    for block in _LD_JSON.findall(page or ""):
        try:
            walk(json.loads(block))
        except ValueError:
            continue
    out = []
    for ev in found:
        try:
            day = date.fromisoformat(str(ev.get("endDate") or ev.get("startDate"))[:10])
        except ValueError:
            continue
        place = ev.get("location") or {}
        place = place[0] if isinstance(place, list) and place else place
        where = (place.get("address") or {}).get("addressLocality") or place.get("name") or "" if isinstance(place, dict) else ""
        name = re.sub(r"^R\d+\s+", "", str(ev.get("name") or "")).strip()    # "R01 Jeddah E-Prix"
        out.append(Race(name, str(where), day, (), str((ev.get("superEvent") or {}).get("name") or "")))
    return out


def _read_board(board) -> list[Race]:
    """ESPN's scoreboard: its season calendar (one time per race), and this weekend's sessions in full."""
    if not isinstance(board, dict):
        return []
    out = []
    for ev in board.get("events") or []:
        circuit = ev.get("circuit") or {}
        city = (circuit.get("address") or {}).get("city") or ""
        where = " · ".join(p for p in (circuit.get("fullName"), city) if p)
        sessions = []
        for comp in ev.get("competitions") or []:
            label = (comp.get("type") or {}).get("abbreviation") or (comp.get("type") or {}).get("text") or "Race"
            if dt := _when(comp.get("date") or ev.get("date")):
                sessions.append((label, dt, _hours(label)))
        if not sessions and (dt := _when(ev.get("date"))):
            sessions.append(("Race", dt, 2.5))
        if race := _timed(ev.get("name"), where, sessions):
            out.append(race)
    for item in ((board.get("leagues") or [{}])[0] or {}).get("calendar") or []:
        start, end = _when(item.get("startDate")), _when(item.get("endDate"))
        if not start:
            continue
        if end and end > start:        # a weekend: from its first session to the end of the race
            out.append(Race(str(item.get("label") or ""), "", end.date(),
                            (("Race weekend", start, (end - start).total_seconds() / 3600),)))
        else:
            out.append(_timed(item.get("label"), "", [("Race", start, 2.5)]))
    return out


def _merge(lists: list[list[Race]]) -> list[Race]:
    """Races from every calendar, most trusted first, as one season by race day: the first calendar
    that has a race names it, the one with most sessions times it."""
    season: list[Race] = []
    for races in lists:
        for r in races:
            i = next((i for i, have in enumerate(season) if _same(have, r)), None)
            if i is None:
                season.append(r)
                continue
            have = season[i]
            season[i] = Race(have.name or r.name, have.location or r.location, have.day,
                             r.sessions if len(r.sessions) > len(have.sessions) else have.sessions,
                             have.season or r.season)
    return sorted(season, key=lambda r: r.start)


def _same(a: Race, b: Race) -> bool:
    """One race in two calendars: the same race day, or (both timed) weekends that overlap."""
    if a.day == b.day:
        return True
    return bool(a.sessions and b.sessions) and a.start < b.end and b.start < a.end


_calendar_cache: dict[str, dict] = {}


async def _read_calendar(session, cal: Calendar, url: str, missing_ok: bool) -> list[Race] | None:
    """One calendar's races; [] when it isn't published (yet), None when it couldn't be read."""
    try:
        async with session.get(url, headers=HEADERS, timeout=TIMEOUT,
                               trace_request_ctx=health.MISSING_OK if missing_ok else None) as r:
            if r.status == 404 and missing_ok:
                return []
            if r.status != 200:
                return None             # health's trace has said so
            if cal.reader == "events":
                races = _read_events(await r.text())
                if not races:           # the page is there but no longer says its season: say so
                    health.fail(_service(url), "its calendar page has no races in it")
                    return None
                return races
            return _read_sessions(await r.json(content_type=None))
    except ValueError as exc:           # an answer that isn't the calendar it was
        health.fail(_service(url), exc)
        return None
    except Exception:
        return None                     # unreachable: health's trace has said so


def _service(url: str) -> str:
    from urllib.parse import urlparse
    host = urlparse(url).hostname or url
    return health.SERVICES.get(host, host)


async def _calendar(session, cal: Calendar, ser: Series, now: datetime) -> list[Race] | None:
    """A calendar's races, read again every hour (sooner after a failure), its last good ones kept."""
    if cal.reader == "espn":
        return _read_board(await _board(session, ser))
    lists = []
    years = (now.year, now.year + 1) if "{year}" in cal.url else (None,)
    for year in years:
        url = cal.url.format(year=year) if year else cal.url
        cached = _calendar_cache.get(url)
        t = time.time()
        if cached and t - cached["at"] < (CALENDAR_EVERY if cached["ok"] else RETRY_EVERY):
            got = cached["races"]
        else:
            # Next year's calendar may not be published yet: a 404 there is normal.
            got = await _read_calendar(session, cal, url, missing_ok=bool(year and year > now.year))
            if got is None:
                _calendar_cache[url] = {"at": t, "ok": False, "races": cached["races"] if cached else None}
                got = cached["races"] if cached else None
            else:
                _calendar_cache[url] = {"at": t, "ok": True, "races": got}
        lists.append(got)
    known = [x for x in lists if x is not None]
    return [r for x in known for r in x] if known else None


async def _season(session, ser: Series, now: datetime) -> list[Race] | None:
    """The series' season as every calendar it's published in knows it; None when none could be read."""
    lists = [await _calendar(session, cal, ser, now) for cal in ser.calendars]
    known = [x for x in lists if x is not None]
    return _merge(known) if known else None


_board_cache: dict[str, dict] = {}


async def _board(session, ser: Series) -> dict | None:
    """The series' ESPN scoreboard: every 10 minutes, every minute while a session is live."""
    if not ser.espn:
        return None
    cached = _board_cache.get(ser.slug)
    t = time.time()
    if cached and t - cached["at"] < (60.0 if cached["live"] else 600.0):
        return cached["data"]
    url = f"https://site.api.espn.com/apis/site/v2/sports/racing/{ser.espn}/scoreboard"
    data = None
    try:
        async with session.get(url, headers=HEADERS, timeout=TIMEOUT) as r:
            if r.status == 200:
                data = await r.json()
    except Exception as exc:
        print(f"fetch_racing_data error ({ser.slug}): {health.describe(exc)}", flush=True)
    if data is None:
        return cached["data"] if cached else None
    live = any(((ev.get("status") or {}).get("type") or {}).get("state") == "in" for ev in data.get("events") or [])
    _board_cache[ser.slug] = {"at": t, "data": data, "live": live}
    runtime.prune(_board_cache)
    return data


@dataclass
class Pick:
    """What a series has on: a race and where its weekend is (PRE / IN / POST), or the off-season (OFF)."""
    status: str
    race: Race | None = None
    session: tuple | None = None        # the session it's about: (label, start, hours)
    last: Race | None = None            # the last race before now, when one is known


def _pick(races: list[Race], now: datetime) -> Pick:
    """The one rule: the race weekend on now (or until its result is old), else the next race,
    else the off-season. A season's first race further off than OFF_SEASON_LEAD is the off-season."""
    after = timedelta(hours=AFTER_HOURS)
    past = [r for r in races if r.end + after < now]
    last = past[-1] if past else None
    nxt = next((r for r in races if r.end + after >= now), None)
    if nxt is None:
        return Pick("OFF", last=last)
    if nxt.start - now > OFF_SEASON_LEAD and (last is None or nxt.start - last.end > SEASON_GAP):
        return Pick("OFF", nxt, last=last)
    if not nxt.sessions:                # only its day is known
        return Pick("PRE", nxt, last=last)
    for s in nxt.sessions:
        if s[1] <= now <= s[1] + timedelta(hours=s[2]):
            return Pick("IN", nxt, s, last)
    upcoming = next((s for s in nxt.sessions if s[1] > now), None)
    if upcoming:
        return Pick("PRE", nxt, upcoming, last)
    return Pick("POST", nxt, nxt.sessions[-1], last)


def _day(d) -> str:
    """A day as the panel says it: "Fri 18 Dec"."""
    return clock.strftime(d if isinstance(d, datetime) else datetime.combine(d, datetime.min.time()), "%a %-d %b")


def _local(dt: datetime, tz_name: str | None) -> datetime:
    try:
        return dt.astimezone(ZoneInfo(tz_name)) if tz_name else dt
    except Exception:
        return dt


def _at(dt: datetime, tz_name: str | None) -> str:
    """When a session starts, in the home's time: "Fri 18 Dec · 13:30 GMT"."""
    loc = _local(dt, tz_name)
    return f"{_day(loc)} · {clock.hm(loc)} {loc.tzname() or ''}".strip()


def _describe(ser: Series, pick: Pick, tz_name: str | None) -> dict:
    """The race data a page draws, from what `_pick` found."""
    race = pick.race
    data = {"series": ser.code, "series_name": ser.title, "event_name": race.name if race else "",
            "circuit": race.location if race else "", "status": pick.status, "standings": []}
    if race and race.season:
        data["season"] = race.season
    if pick.last:
        data["last_race_end"] = pick.last.end.isoformat()
    if pick.status == "OFF":
        data["clock"] = "OFF SEASON"
        if race:
            data["next_start"] = race.start.isoformat() if race.sessions else race.day.isoformat()
            data["detail"] = "Season starts " + (_day(_local(race.sessions[0][1], tz_name)) if race.sessions else _day(race.day))
        else:
            data["detail"] = "Next season's calendar isn't out yet"
        return data
    if pick.session is None:            # only the race day is known
        data.update(clock="SCHEDULED", detail=f"Race day · {_day(race.day)}")
        return data
    label = session_name(pick.session[0])
    data["detail"] = f"{label} · {_at(pick.session[1], tz_name)}"
    data["clock"] = {"IN": f"{label} LIVE", "PRE": "SCHEDULED"}.get(pick.status, "FINAL")
    return data


def _board_event(board, race: Race | None):
    """ESPN's event for this race, when its scoreboard is on it."""
    if not race or not isinstance(board, dict):
        return None
    for ev in board.get("events") or []:
        r = _read_board({"events": [ev]})
        if r and (r[0].day == race.day or r[0].name == race.name):
            return ev
    return None


@runtime.live(30)
async def fetch_racing_data(session, entity_or_series="f1", fallback=None, tz_name=None):
    if not tz_name:
        tz_name = await get_home_timezone(session)
    ser = series_of(str(entity_or_series or "f1").strip().lower())

    # 1. A Home Assistant entity of its own with standings (the fallback is its state): shown as it is
    base_data = None
    if isinstance(fallback, dict):
        base_data = fallback
    elif isinstance(fallback, str) and fallback.strip():
        try:
            base_data = json.loads(fallback)
        except Exception:
            pass
    if isinstance(base_data, dict) and "attributes" in base_data:
        attrs = base_data.get("attributes") or {}
        if attrs.get("standings"):
            status = str(base_data.get("state") or "").upper()
            return {
                "series": ser.code,
                "series_name": ser.title,
                "event_name": attrs.get("event_name") or attrs.get("event") or ser.event,
                "circuit": attrs.get("venue") or attrs.get("circuit") or ser.venue,
                "status": status or "IN",
                "lap": attrs.get("lap"),
                "total_laps": attrs.get("total_laps"),
                "clock": attrs.get("clock") or status,
                "standings": attrs.get("standings")
            }

    # 2. The season, every calendar merged, and the one rule
    now = datetime.now(timezone.utc)
    races = await _season(session, ser, now)
    if races is None:
        return None                     # no calendar could be read: nothing yet, never a made-up race
    pick = _pick(races, now)
    data = _describe(ser, pick, tz_name)

    # 3. ESPN's scoreboard on this race: its live status, names and standings
    board = await _board(session, ser)
    ev = _board_event(board, pick.race) if pick.status != "OFF" else None
    if ev is not None:
        st = (ev.get("status") or {}).get("type") or {}
        st_state = st.get("state") or "pre"
        data["status"] = {"in": "IN", "post": "POST"}.get(st_state, "PRE")
        data["event_name"] = ev.get("name") or data["event_name"]
        data["circuit"] = _read_board({"events": [ev]})[0].location or data["circuit"]
        data["clock"] = st.get("description") or data.get("clock")
        standings = []
        for idx, c in enumerate(_session_on(ev).get("competitors") or []):
            if idx >= 10:
                break
            ath = c.get("athlete") or {}
            tm = c.get("team") or {}
            standings.append({
                "pos": idx + 1,
                "driver": str(_driver_code(ath))[:3].upper(),
                "team": tm.get("displayName") or tm.get("shortDisplayName") or "",
                "gap": (c.get("status") or {}).get("displayValue") or ("LEADER" if idx == 0 else ""),
                "tyre": "M"
            })
        data["standings"] = standings
    return data


def _driver_code(athlete: dict) -> str:
    """Three letters for a driver: ESPN's code where it has one (F1), else from the surname."""
    code = athlete.get("abbreviation")
    if code:
        return str(code)
    name = str(athlete.get("lastName") or athlete.get("displayName") or athlete.get("shortName") or "").strip()
    return name.split()[-1] if name else "DRV"


def _session_on(ev: dict) -> dict:
    """The session of an ESPN event whose order to show: the one running, else the last one run."""
    comps = [c for c in ev.get("competitions") or [] if isinstance(c, dict)]
    state = lambda c: ((c.get("status") or {}).get("type") or {}).get("state")  # noqa: E731
    return (next((c for c in comps if state(c) == "in"), None)
            or next((c for c in reversed(comps) if state(c) == "post"), None)
            or (comps[0] if comps else {}))


_racing_window_cache: dict[str, dict] = {}


def series_slug(series) -> tuple[str, str]:
    """A racing series as (slug, title): the slug names its sensor, sensor.epaper_racing_<slug>."""
    ser = series_of(series)
    return ser.slug, ser.title


@runtime.live(60)
async def compute_racing_active_window(session, series="f1", pre_buffer_hours=2.0, post_buffer_hours=2.0, window_mode="session", tz_name=None):
    """Compute whether a Motorsport series (F1, Formula E, NASCAR, IndyCar) is in an active session/race-weekend window."""
    if not tz_name:
        tz_name = await get_home_timezone(session)
    ser = series_of(series)
    slug, series_title = ser.slug, ser.title

    w_mode = "weekend" if str(window_mode).strip().lower() == "weekend" else "session"
    cache_key = f"{slug}:{pre_buffer_hours}:{post_buffer_hours}:{w_mode}:{tz_name}"
    now_ts = time.time()
    cached = _racing_window_cache.get(cache_key)
    if cached and (now_ts - cached["at"] < 60.0):
        return cached["data"]

    now_utc = datetime.now(timezone.utc)
    event_name = f"{series_title} Championship"
    circuit_name = ""
    is_live = False
    sessions_list: list[tuple[str, datetime, float]] = []  # (session_label, start_utc, duration_hours)

    # The race weekend on now or next, from the same season the page shows
    races = await _season(session, ser, now_utc)
    if races is None:
        return None                                           # no calendar could be read yet
    race = next((r for r in races if r.end + timedelta(hours=max(post_buffer_hours, AFTER_HOURS)) >= now_utc), None)
    if race is not None:
        event_name = race.name or event_name
        circuit_name = race.location
        # A race known only by its day: the whole day (UTC), until a calendar has its sessions
        sessions_list = list(race.sessions) or [("Race day", race.start, 24.0)]
        ev = _board_event(await _board(session, ser), race)
        if ev is not None and (((ev.get("status") or {}).get("type") or {}).get("state") == "in"
                               or any(((c.get("status") or {}).get("type") or {}).get("state") == "in"
                                      for c in ev.get("competitions") or [])):
            is_live = True

    active_win_start = None
    active_win_end = None
    active_session_label = ""
    is_active = is_live

    if sessions_list:
        for s_label, s_dt, s_dur in (race.sessions if race else ()):     # a race day alone is never "live"
            if s_dt <= now_utc <= s_dt + timedelta(hours=s_dur):
                is_live = True
                is_active = True

        if w_mode == "weekend":
            first_label, first_dt, _ = sessions_list[0]
            last_label, last_dt, last_dur = sessions_list[-1]
            w_start = first_dt - timedelta(hours=pre_buffer_hours)
            w_end = last_dt + timedelta(hours=last_dur + post_buffer_hours)
            active_win_start = w_start
            active_win_end = w_end
            active_session_label = f"{first_label} – {last_label}"
            if w_start <= now_utc <= w_end:
                is_active = True
        else:
            # Session-by-session mode: find the currently active session window, or the next upcoming one
            chosen = None
            for s_label, s_dt, s_dur in sessions_list:
                w_start = s_dt - timedelta(hours=pre_buffer_hours)
                w_end = s_dt + timedelta(hours=s_dur + post_buffer_hours)
                if w_start <= now_utc <= w_end:
                    is_active = True
                    chosen = (s_label, w_start, w_end)
                    break
                elif w_start > now_utc and chosen is None:
                    chosen = (s_label, w_start, w_end)
            if chosen is None:
                s_label, s_dt, s_dur = sessions_list[-1]
                chosen = (s_label, s_dt - timedelta(hours=pre_buffer_hours), s_dt + timedelta(hours=s_dur + post_buffer_hours))
            active_session_label, active_win_start, active_win_end = chosen

    try:
        local_tz = ZoneInfo(tz_name)
    except Exception:
        local_tz = timezone.utc

    win_start_local = active_win_start.astimezone(local_tz).strftime("%a %H:%M") if active_win_start else None
    win_end_local = active_win_end.astimezone(local_tz).strftime("%a %H:%M") if active_win_end else None

    result = {
        "slug": slug,
        "sensor_id": f"sensor.epaper_racing_{slug}",
        "series_name": series_title,
        "event_name": event_name,
        "circuit": circuit_name,
        "session_name": active_session_label,
        "is_active": is_active,
        "state": "active" if is_active else "idle",
        "is_live": is_live,
        "window_mode": w_mode,
        "window_start": active_win_start.isoformat() if active_win_start else None,
        "window_start_local": win_start_local,
        "window_end": active_win_end.isoformat() if active_win_end else None,
        "window_end_local": win_end_local,
        "time_zone": tz_name,
        "pre_buffer_hours": pre_buffer_hours,
        "post_buffer_hours": post_buffer_hours,
    }
    _racing_window_cache[cache_key] = {"at": now_ts, "data": result}
    runtime.prune(_racing_window_cache)
    return result
