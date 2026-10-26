"""Example values for any page: what a preset's thumbnail shows.

The New page sheet draws every preset with these, never with the person's
own data, and never by asking Home Assistant, the internet or a data
source (POST /api/example). Templates are answered by the offline fixture
(render/fixture.json) without the add-on's own values; widgets get the
samples below, picked to look like a real day: a league's own teams, a
series' own drivers, a sunny afternoon's solar.

The offline add-on (no Home Assistant token) draws the same samples, so
there is one set of examples, here.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta

from fixture import eval_fixture_template, fixture_todo, load_fixture
from render import layout

# ---------------------------------------------------------------- sports

# Every league the add-on offers (sources/sports.LEAGUES) has its own; a test holds both ways.
_TEAMS = {
    "soccer/eng.1": ("ARSENAL", "CHELSEA", "PREMIER LEAGUE", "Emirates Stadium"),
    "soccer/esp.1": ("BARCELONA", "REAL MADRID", "LALIGA", "Spotify Camp Nou"),
    "soccer/ita.1": ("INTER", "MILAN", "SERIE A", "San Siro"),
    "soccer/ger.1": ("BAYERN", "DORTMUND", "BUNDESLIGA", "Allianz Arena"),
    "soccer/uefa.champions": ("REAL MADRID", "BAYERN", "CHAMPIONS LEAGUE", "Santiago Bernabéu"),
    "soccer/usa.1": ("LA GALAXY", "LAFC", "MLS", "Dignity Health Sports Park"),
    "basketball/nba": ("LAKERS", "CELTICS", "NBA", "Crypto.com Arena"),
    "basketball/wnba": ("LIBERTY", "ACES", "WNBA", "Barclays Center"),
    "football/college-football": ("MICHIGAN", "OHIO STATE", "COLLEGE FOOTBALL", "Michigan Stadium"),
    "football/nfl": ("CHIEFS", "EAGLES", "NFL", "Arrowhead Stadium"),
    "baseball/mlb": ("YANKEES", "DODGERS", "MLB", "Yankee Stadium"),
    "hockey/nhl": ("RANGERS", "BRUINS", "NHL", "Madison Square Garden"),
}
# How a game in progress reads, and a plausible score, by sport.
_PLAY = {
    "soccer": ("74' · 2ND HALF", 2, 1, "14 Shots · 58% Poss", "6 Shots · 42% Poss"),
    "basketball": ("Q3 · 4:12", 78, 71, "48% FG · 9 3PT", "44% FG · 7 3PT"),
    "football": ("Q3 · 8:40", 17, 14, "312 Yds · 2 TO", "268 Yds · 1 TO"),
    "baseball": ("TOP 7TH", 4, 2, "9 Hits · 0 Err", "6 Hits · 1 Err"),
    "hockey": ("2ND · 11:05", 3, 2, "24 Shots · 1 PP", "19 Shots · 0 PP"),
}


def match(league: str) -> dict:
    """A match (or game) in progress in this league."""
    key = str(league or "soccer/eng.1").strip().lower()
    sport = key.split("/", 1)[0]
    home, away, name, venue = _TEAMS.get(key) or ("HOME", "AWAY", key.split("/")[-1].upper(), "")
    clock, hs, as_, hstat, astat = _PLAY.get(sport, _PLAY["soccer"])
    out = {"league": name, "venue": venue, "clock": clock, "status": "IN", "home_team": home, "home_score": hs,
           "home_stats": hstat, "away_team": away, "away_score": as_, "away_stats": astat}
    if sport == "soccer":
        out.update({"events_home": "Saka (22'), Havertz (58')" if key == "soccer/eng.1" else "", "events_away": ""})
    return out


_DRIVERS = {
    "f1": [("VER", "Red Bull"), ("NOR", "McLaren"), ("PIA", "McLaren"), ("LEC", "Ferrari"), ("HAM", "Ferrari"),
           ("RUS", "Mercedes"), ("ALO", "Aston Martin"), ("SAI", "Williams"), ("GAS", "Alpine"), ("HUL", "Sauber")],
    "fe": [("WEH", "Porsche"), ("DEN", "Andretti"), ("EVA", "Jaguar"), ("CAS", "Jaguar"), ("ROW", "Nissan")],
    "nascar": [("LAR", "Hendrick"), ("BYR", "Hendrick"), ("HAM", "Gibbs"), ("BEL", "Gibbs"), ("BLA", "Penske")],
    "indycar": [("PAL", "Ganassi"), ("OWA", "McLaren"), ("NEW", "Penske"), ("DIX", "Ganassi"), ("HER", "Andretti")],
}
_RACES = {"f1": ("Italian Grand Prix", "Autodromo Nazionale Monza", 42, 53),
          "fe": ("London E-Prix", "ExCeL London", 21, 33),
          "nascar": ("Cup Series at Martinsville", "Martinsville Speedway", 312, 500),
          "indycar": ("Indianapolis 500", "Indianapolis Motor Speedway", 141, 200)}


def race(series: str) -> dict:
    """A race in progress in this series, its badge as a page says it ("RACE · LAP 42/53")."""
    from sources.racing import badge, series_of
    ser = series_of(series)
    name, circuit, lap, laps = _RACES.get(ser.slug, _RACES["f1"])
    gaps = ["LEADER", "+2.1s", "+4.8s", "+7.3s", "+11.0s", "+14.2s", "+18.9s", "+25.1s", "+32.0s", "+38.4s"]
    words = badge("Race", "IN", lap, laps)
    return {"series": ser.code, "series_name": ser.title, "event_name": name, "circuit": circuit, "status": "IN",
            "session": "Race", "lap": lap, "total_laps": laps, "badge": words, "clock": words[0],
            "standings": [{"pos": k + 1, "driver": code, "team": team, "gap": gaps[k]}
                          for k, (code, team) in enumerate(_DRIVERS.get(ser.slug, _DRIVERS["f1"]))]}


AIRCRAFT = [
    {"callsign": "BAW71LK", "country": "United Kingdom • British Airways", "icao24": "40089A", "distance_km": 8.4,
     "bearing_deg": 225.0, "bearing_cardinal": "SW", "altitude_m": 10370, "velocity_ms": 233.2, "track_deg": 302,
     "vertical_rate": 0.0},
    {"callsign": "THY41Y", "country": "Turkey • Turkish Airlines", "icao24": "4BA982", "distance_km": 19.2,
     "bearing_deg": 45.0, "bearing_cardinal": "NE", "altitude_m": 11887, "velocity_ms": 253.3, "track_deg": 140,
     "vertical_rate": -1.5},
]

# ---------------------------------------------------------------- home and energy


def sun(now: datetime) -> dict:
    rise = now.replace(hour=7, minute=41, second=0, microsecond=0)
    set_ = now.replace(hour=18, minute=22, second=0, microsecond=0)
    if rise <= now:
        rise += timedelta(days=1)
    if set_ <= now:
        set_ += timedelta(days=1)
    return {"rising": rise.isoformat(), "setting": set_.isoformat()}


def bars(period: str, now: datetime, scale: float, signed: bool = False) -> list:
    """A sunny period's bars so far: solar by hour or day, or the grid bought (+) and sold (−)."""
    from sources.energy import _slot, slots
    n, cur = slots(period, now), _slot(period, now)
    out = []
    for k in range(n):
        if k > cur:
            out.append(None)
        elif period == "day":
            light = max(0.0, math.sin(math.pi * (k - 6) / 13)) if 6 <= k <= 19 else 0.0
            out.append(round((0.4 - light * 1.6 if signed else light) * scale, 2))
        else:
            out.append(round(scale * (0.55 + 0.45 * abs(math.sin(k * 1.7))), 2))
    return out


def total(period: str, now: datetime) -> dict:
    b = bars(period, now, {"day": 1.2, "month": 9.0, "year": 260.0}.get(period, 9.0))
    return {"total": round(sum(v for v in b if v), 1), "bars": b, "unit": "kWh"}


def grid(now: datetime) -> dict:
    b = bars("day", now, 1.0, signed=True)
    return {"watts": -1830.0, "bars": b, "today": round(sum(v for v in b if v), 2), "unit": "kWh"}


COST = {"today": 4.2, "month": 38.9, "currency": "EUR", "sells": True}

PLAYING = [{"entity": "media_player.living_room", "key": "media_player.living_room", "player": "Living room",
            "title": "Clair de lune", "artist": "Debussy", "series": "", "season": "", "episode": "", "kind": "music",
            "app": "", "since": "2026-10-21T10:00:00+00:00"}]


def episodes(now: datetime) -> list[dict]:
    hour = now.replace(minute=0, second=0, microsecond=0)
    shows = [("Severance - S02E05 - Trojan's Horse", 0, 21), ("The Bear - S04E01 - Groundhog", 2, 9),
             ("Slow Horses - S05E03 - Tall Tales", 4, 3)]
    return [{"summary": s, "start": (hour.replace(hour=h) + timedelta(days=d)).isoformat()} for s, d, h in shows]


# ---------------------------------------------------------------- a whole page


def page_values(page: dict, now: datetime | None = None) -> tuple[dict, dict]:
    """(vals, series) for render_page: every element answered from examples, nothing fetched."""
    now = now or datetime.now().astimezone()
    tz = None                                   # the add-on's own zone: never asks Home Assistant
    # Every element shows, whatever its "only when": a thumbnail shows what the page looks like.
    vals = {k: eval_fixture_template(tpl, own=False) for k, tpl in layout.collect_templates(page).items()
            if not str(k).startswith("__vis_")}
    series = {}
    curve = list(load_fixture().get("pv_curve_w") or [])
    for i, el in enumerate(page.get("elements") or []):
        if not isinstance(el, dict):
            continue
        t = el.get("type")
        if el.get("show") == "change_today":                      # a running total's day: the fixture's value
            vals[i] = eval_fixture_template("{{ states('%s') }}" % el.get("entity", ""), own=False)
            continue
        if t in ("curve", "bar_chart"):
            series[i] = curve
            continue
        import widgets                              # widgets.py describes each widget with its example
        w = widgets.get(t)
        got = w.example(el, now) if w and w.example else None
        if got is not None:                         # None: the fixture's answer stands (a Devices grid of states)
            vals[i] = got
    return vals, series


# ---------------------------------------------------------------- what needs you (sources/needs_you.py)

def notifications(now: datetime | None = None) -> list[dict]:
    """Three notifications of the kind Home Assistant sends, newest first."""
    now = now or datetime.now().astimezone()
    rows = [("New devices discovered", "Two new devices were found. Set them up in Settings, Devices and services.", 12),
            ("Backup failed", "The automatic backup couldn't reach its location.", 135),
            ("Low battery", "The front door sensor is at 8%.", 26 * 60)]
    return [{"id": f"example_{k}", "title": t, "message": m, "created": (now - timedelta(minutes=ago)).isoformat()}
            for k, (t, m, ago) in enumerate(rows)]


def updates() -> list[dict]:
    """One update in each group, as needs_you.updates_from gives them."""
    return [{"entity": "update.home_assistant_core_update", "group": "home_assistant", "name": "Home Assistant Core",
             "version": "2026.11.0", "installing": False},
            {"entity": "update.mosquitto_broker_update", "group": "addons", "name": "Mosquitto broker",
             "version": "7.2.0", "installing": False},
            {"entity": "update.mushroom_update", "group": "integrations", "name": "Mushroom",
             "version": "5.3.0", "installing": False},
            {"entity": "update.kitchen_light_firmware", "group": "devices", "name": "Kitchen light",
             "version": "1.4.2", "installing": False}]


REPAIRS = 1


def badge(counts: str) -> int:
    """What a badge counts, from the samples above: 4 updates, 3 notifications, 1 repair, 8 in all."""
    n = {"updates": len(updates()), "notifications": len(notifications()), "repairs": REPAIRS}
    return sum(n.values()) if counts == "all" else n.get(counts, n["updates"])
