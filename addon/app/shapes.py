"""The add-on's own fields for what a widget shows from outside: races, games and planes.

Every reader of an outside service (ESPN's scoreboards, the racing calendars, Flightradar24,
OpenSky) turns its answer into these fields, and the widgets draw only from them. So they're also
what one of your data sources can give instead (a rest source with "fills"), or a Home Assistant sensor
whose attributes carry them: the same fields, in the add-on's form, which never changes because an
outside service did. The editor shows them per
widget (its Data section, `shown`), with an example of the form (`example`).

A shape here says, for one kind of widget:
  fields   what a source gives, each with its key, its label and whether it's needed;
  read     a source's answer -> the add-on's own items, or ValueError saying what's wrong, plainly;
  shown    what a widget draws -> its fields as a person reads them (label, value), for the editor.

Nothing here fetches on its own: `read_own` reads a source through live_data, like any other
outside value, when a page or the editor's preview asks.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from render import sport


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    needed: bool = False
    says: str = ""                  # what goes in it, when the label alone doesn't say


@dataclass(frozen=True)
class Shape:
    kind: str                       # what a source's "fills" says, and the widget's descriptor
    name: str                       # "Racing"
    list_key: str                   # the list in a source's answer: "races"
    item: str                       # what one is called: "race"
    fields: tuple
    read: Callable[[Any], list]
    example: Callable[[], dict]
    shown: Callable[[Any], list]
    more: tuple = ()                # (list key, fields) inside each item: a race's sessions and result

    def describe(self) -> dict:
        """For the editor (/api/catalog): what a source gives, and an example of it."""
        def f(x):
            return {"key": x.key, "label": x.label, "needed": x.needed, "says": x.says}
        return {"kind": self.kind, "name": self.name, "list": self.list_key, "item": self.item,
                "fields": [f(x) for x in self.fields],
                "more": [{"list": k, "fields": [f(x) for x in fs]} for k, fs in self.more],
                "example": self.example()}

    def summary(self, items: list) -> str:
        n = len(items)
        return f"{n} {self.item if n == 1 else self.item + 's'}"


# ---------------------------------------------------------------- reading a source's answer

def _when(value) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _text(value) -> str:
    return "" if value is None else str(value).strip()


def _number(value) -> float | None:
    if value is None or isinstance(value, bool) or (isinstance(value, str) and not value.strip()):
        return None
    try:
        got = float(value)
    except (TypeError, ValueError):
        return None
    return got if got == got and abs(got) != float("inf") else None


def _list(body, key: str, item: str) -> list:
    got = body.get(key) if isinstance(body, dict) else body if isinstance(body, list) else None
    if not isinstance(got, list):
        raise ValueError(f"It has no list of {item}s: the add-on reads {{\"{key}\": [...]}}.")
    if not got:
        raise ValueError(f"Its list of {item}s is empty.")
    return got


def _each(items: list, item: str):
    for i, x in enumerate(items, 1):
        if not isinstance(x, dict):
            raise ValueError(f"Its {item} number {i} isn't a set of fields.")
        yield i, x


def _read_races(body) -> list:
    """{"races": [{"race", "place", "sessions": [{"session", "start"}] or {session: start}, "result": [...],
    "result_session"}]} -> racing.Race, by start. A result is its session's ("result_session"); without
    one, the page shows it as a result whose session it doesn't know."""
    from sources import racing
    out = []
    for i, r in _each(_list(body, "races", "race"), "race"):
        name = _text(r.get("race"))
        if not name:
            raise ValueError(f"Race number {i} has no name (\"race\").")
        raw = r.get("sessions")
        pairs = list(raw.items()) if isinstance(raw, dict) else \
            [(s.get("session"), s.get("start")) for s in raw if isinstance(s, dict)] if isinstance(raw, list) else None
        if not pairs:
            raise ValueError(f"{name} has no sessions: each has a \"session\" and a \"start\".")
        sessions = []
        for label, start in pairs:
            dt = _when(start)
            if not _text(label) or dt is None:
                raise ValueError(f"{name}: a session needs a name and a start the add-on can read, "
                                 f"like \"2026-10-25T20:00:00Z\" (it got {json.dumps(start)[:40]}).")
            sessions.append((racing.session_name(_text(label)), dt, racing._hours(_text(label))))
        result = []
        for j, row in enumerate(r.get("result") or [], 1):
            if isinstance(row, dict) and _text(row.get("driver")):
                result.append({"pos": int(_number(row.get("position")) or j), "driver": _text(row.get("driver"))[:3].upper(),
                               "team": _text(row.get("team")), "gap": _text(row.get("gap"))})
        of = _text(r.get("result_session"))
        race = racing._timed(name, _text(r.get("place")), sessions, _text(r.get("season")))
        out.append(racing.Race(race.name, race.location, race.day, race.sessions, race.season,
                               ((racing.session_name(of) if of else "", "", tuple(result)),) if result else ()))
    return sorted(out, key=lambda x: x.start)


def _read_games(body) -> list:
    """{"games": [{"home", "away", "start", "status", "home_score", "away_score", "clock", ...}]} ->
    the add-on's own game fields (sources/sports.game_view draws them)."""
    out = []
    for i, g in _each(_list(body, "games", "game"), "game"):
        home, away, start = _text(g.get("home")), _text(g.get("away")), _when(g.get("start"))
        if not home or not away:
            raise ValueError(f"Game number {i} needs both teams (\"home\" and \"away\").")
        if start is None:
            raise ValueError(f"{home} v {away} has no start the add-on can read, like \"2026-10-25T15:00:00Z\".")
        status = _text(g.get("status")).lower()
        if status not in ("pre", "in", "post"):
            raise ValueError(f"{home} v {away}: its status is \"pre\", \"in\" or \"post\" (it got {json.dumps(g.get('status'))[:20]}).")
        scorers = lambda k: [_text(x) for x in (g.get(k) or []) if _text(x)] if isinstance(g.get(k), list) else []  # noqa: E731
        out.append({"id": _text(g.get("id")) or f"{home}_{away}_{start.isoformat()}", "home": home, "away": away,
                    "home_score": g.get("home_score"), "away_score": g.get("away_score"), "status": status,
                    "status_text": _text(g.get("status_text")), "clock": _text(g.get("clock")),
                    "start": start.isoformat(), "league": _text(g.get("league")), "venue": _text(g.get("venue")),
                    "home_record": _text(g.get("home_record")), "away_record": _text(g.get("away_record")),
                    "home_scorers": scorers("home_scorers"), "away_scorers": scorers("away_scorers")})
    return out


def _read_planes(body) -> list:
    """{"planes": [{"callsign", "latitude", "longitude", ...}]} -> the add-on's own plane fields
    (sources/flights.plane_near measures each from home)."""
    out = []
    for i, p in _each(_list(body, "planes", "plane"), "plane"):
        lat, lon = _number(p.get("latitude")), _number(p.get("longitude"))
        if lat is None or lon is None or not -90 <= lat <= 90 or not -180 <= lon <= 180:
            raise ValueError(f"Plane number {i} needs a \"latitude\" and a \"longitude\" in degrees.")
        out.append({"callsign": _text(p.get("callsign")).upper() or f"#{i}", "latitude": lat, "longitude": lon,
                    "altitude_m": _number(p.get("altitude_m")) or 0.0, "speed_kmh": _number(p.get("speed_kmh")) or 0.0,
                    "track_deg": _number(p.get("track_deg")) or 0.0, "vertical_rate": _number(p.get("vertical_rate")) or 0.0,
                    "from": _text(p.get("from")), "to": _text(p.get("to")), "aircraft": _text(p.get("aircraft")),
                    "airline": _text(p.get("airline"))})
    return out


# ---------------------------------------------------------------- examples of the form, for the editor

def _soon(days: float, hour: int) -> str:
    d = (datetime.now(timezone.utc) + timedelta(days=days)).replace(hour=hour, minute=0, second=0, microsecond=0)
    return d.isoformat().replace("+00:00", "Z")


def _race_example() -> dict:
    return {"races": [{"race": "Example Grand Prix", "place": "Example Circuit",
                       "sessions": [{"session": "Qualifying", "start": _soon(2, 14)}, {"session": "Race", "start": _soon(3, 13)}],
                       "result_session": "Qualifying",
                       "result": [{"position": 1, "driver": "ABC", "team": "Team One", "gap": ""},
                                  {"position": 2, "driver": "DEF", "team": "Team Two", "gap": "+1.2s"}]}]}


def _game_example() -> dict:
    return {"games": [{"home": "Home Team", "away": "Away Team", "start": _soon(1, 15), "status": "pre",
                       "home_score": None, "away_score": None, "league": "Example League"}]}


def _plane_example() -> dict:
    return {"planes": [{"callsign": "ABC123", "latitude": 0.1, "longitude": 0.1, "altitude_m": 9000,
                        "speed_kmh": 820, "track_deg": 90, "from": "AAA", "to": "BBB", "aircraft": "A320"}]}


# ---------------------------------------------------------------- what a widget draws, as its fields

def _shown_race(v) -> list:
    v = v if isinstance(v, dict) else {}
    result = " · ".join(f"{r.get('pos')} {r.get('driver')}" for r in (v.get("standings") or [])[:3])
    return [("Series", v.get("series_name") or ""), ("Race", v.get("event_name") or ""), ("Place", v.get("circuit") or ""),
            ("Session", v.get("session") or ""), ("Start", v.get("session_start") or v.get("next_start") or ""),
            ("Result", result)]


def _shown_game(v) -> list:
    g = (v[0] if isinstance(v, list) and v else v) if v else {}
    g = g if isinstance(g, dict) else {}
    score = f"{g.get('home_score', '-')}–{g.get('away_score', '-')}" if g else ""
    return [("League", g.get("league") or ""), ("Home", g.get("home_team") or ""), ("Away", g.get("away_team") or ""),
            ("Score", score), ("Status", {"PRE": "Not started", "IN": "Playing", "POST": "Finished"}.get(g.get("status"), "")),
            ("Start", g.get("kickoff_iso") or ""), ("Clock", sport.badge(g) if g else "")]


def _shown_plane(v) -> list:
    p = (v[0] if isinstance(v, list) and v else {}) or {}
    return [("Callsign", p.get("callsign") or ""), ("From", p.get("origin") or ""), ("To", p.get("destination") or ""),
            ("Aircraft", p.get("model") or ""), ("Altitude", f"{round(p['altitude_m'])} m" if p.get("altitude_m") else ""),
            ("Speed", f"{p['speed_kmh']} km/h" if p.get("speed_kmh") else ""),
            ("Distance", f"{p['distance_km']} km" if p.get("distance_km") is not None and p else ""),
            ("Direction", p.get("bearing_cardinal") or "")]


SHAPES = {s.kind: s for s in (
    Shape("racing", "Racing", "races", "race",
          (Field("race", "Race", True), Field("place", "Place"), Field("season", "Season", says="what its calendar calls it"),
           Field("result_session", "Result of", says="the session its result is from, like Qualifying: the page names it")),
          _read_races, _race_example, _shown_race,
          more=(("sessions", (Field("session", "Session", True, "Practice 1, Qualifying, Race…"),
                              Field("start", "Start", True, "date and time, like 2026-10-25T20:00:00Z"))),
                ("result", (Field("position", "Position"), Field("driver", "Driver", True, "three letters"),
                            Field("team", "Team"), Field("gap", "Gap"))))),
    Shape("scores", "Scores", "games", "game",
          (Field("home", "Home", True), Field("away", "Away", True),
           Field("start", "Start", True, "date and time, like 2026-10-25T15:00:00Z"),
           Field("status", "Status", True, "pre, in or post"), Field("home_score", "Home score"),
           Field("away_score", "Away score"), Field("clock", "Clock", says="what the game's clock says, like 67'"),
           Field("league", "League"), Field("venue", "Venue")),
          _read_games, _game_example, _shown_game),
    Shape("flights", "Flights", "planes", "plane",
          (Field("callsign", "Callsign", True), Field("latitude", "Latitude", True), Field("longitude", "Longitude", True),
           Field("altitude_m", "Altitude", says="metres"), Field("speed_kmh", "Speed", says="km/h"),
           Field("track_deg", "Heading", says="degrees"), Field("from", "From"), Field("to", "To"),
           Field("aircraft", "Aircraft")),
          _read_planes, _plane_example, _shown_plane),
)}


def get(kind) -> Shape | None:
    return SHAPES.get(str(kind or ""))


def read(kind: str, body) -> list:
    """A source's answer as the add-on's own items, or ValueError saying plainly what's wrong."""
    shape = SHAPES[kind]
    try:
        return shape.read(body)
    except ValueError:
        raise
    except (TypeError, AttributeError, KeyError, IndexError):
        raise ValueError(f"It isn't in the form the add-on reads for {shape.name} pages.") from None


# ---------------------------------------------------------------- a widget's own data

# How often a Home Assistant sensor that gives a widget's fields is read again, in seconds.
ENTITY_EVERY = 30.0
ENTITY = "entity:"


def own_source(el: dict) -> str:
    """Where an element reads in place of the add-on's services, or "": one of your data sources (its
    id), or a Home Assistant sensor whose attributes carry the fields ("entity:<entity_id>")."""
    data = el.get("data") if isinstance(el, dict) else None
    if not isinstance(data, dict):
        return ""
    if _text(data.get("entity")):
        return ENTITY + _text(data.get("entity"))
    return _text(data.get("source"))


def fills(kind: str) -> list[dict]:
    """Your data sources that give what a kind of widget shows."""
    from layouts_store import load_sources
    return [s for s in load_sources() if isinstance(s, dict) and s.get("fills") == kind and s.get("id")]


# What went wrong the last time a Home Assistant sensor was read for a widget's fields, by entity:
# shown in the inspector ("Its data"). A sensor is Home Assistant's, not a service: it gets no
# problem sensor of its own.
_entity_errors: dict[str, str] = {}


def problem(own: str) -> str:
    """Why the last read of an element's own data failed, in plain words, or ""."""
    return _entity_errors.get(own[len(ENTITY):], "") if own.startswith(ENTITY) else ""


async def read_own(session, own: str, kind: str) -> list | None:
    """The add-on's own items from where an element reads in place of the services (`own_source`):
    fetched in the background (live_data), the last good answer kept; None until there is one, or
    once the source is gone."""
    import runtime
    if own.startswith(ENTITY):
        return await _read_entity(session, own[len(ENTITY):], kind)
    import feeds
    import health
    from layouts_store import load_sources
    src = next((s for s in load_sources() if isinstance(s, dict) and s.get("id") == own), None)
    if src is None or src.get("fills") != kind:
        return None
    import services
    name = services.source_name(src)

    async def fetch():
        try:
            items = read(kind, await feeds.fetch_json(src, runtime.SESSION or session))
        except Exception as exc:
            health.fail(name, exc if not isinstance(exc, ValueError) else str(exc), kind="source")
            raise
        health.ok(name, kind="source")
        return items

    return await runtime.LIVE.read(("fills", kind, json.dumps(src, sort_keys=True, default=str)), fetch, feeds.interval_of(src))


async def _read_entity(session, entity_id: str, kind: str) -> list | None:
    """The fields from a Home Assistant sensor's attributes ({"races": [...]}, in the add-on's form)."""
    import runtime
    from config import valid_entity_id

    if not valid_entity_id(entity_id):
        return None

    async def fetch():
        import health
        from ha import ha_json
        try:
            state = await ha_json(runtime.SESSION or session, f"/states/{entity_id}")
            items = read(kind, (state or {}).get("attributes") or {})
        except ValueError as exc:
            said = f"Its attributes aren't in the add-on's form: {exc}"
            _entity_errors[entity_id] = said
            print(f"{entity_id}: {said}", flush=True)
            raise
        except Exception as exc:                # noqa: BLE001 -- said plainly in the inspector
            import services
            _entity_errors[entity_id] = "Home Assistant didn't give it: " + services.plain(health.describe(exc))
            raise
        _entity_errors.pop(entity_id, None)
        return items

    return await runtime.LIVE.read(("fills", kind, ENTITY + entity_id), fetch, ENTITY_EVERY)
