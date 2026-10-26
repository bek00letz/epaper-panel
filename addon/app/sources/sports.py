"""Football and other ESPN leagues: matches and matchday windows."""

import health
import services
import json
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import aiohttp

import runtime
from render import clock, sport
from sources import HOURS_AROUND
from sources.geo import get_home_timezone


_sports_match_cache = {}


@dataclass(frozen=True)
class League:
    """One league the add-on offers: every place that needs to know a league asks here (and the editor,
    through /api/catalog)."""
    path: str                   # ESPN's: "soccer/eng.1"
    slug: str                   # names its sensor, sensor.epaper_sports_<slug>
    name: str                   # "Premier League"
    aliases: tuple = ()         # what a page may say for it
    # The most games its scoreboard lists at once on its busiest day: today's, or with none today the
    # round or week ahead (fetch_sports_match). How the editor knows a page could outgrow an always-on
    # panel before it does (frames.busy_day). From the league's size and calendar, checked against
    # ESPN's scoreboards in Oct 2026.
    busiest_day: int = 1

    @property
    def sensor(self) -> str:
        return f"sensor.epaper_sports_{self.slug}"


# In the order the editor offers them.
LEAGUES = (
    League("soccer/eng.1", "premier_league", "Premier League", ("premier_league", "epl"), 10),       # 20 clubs: a round
    League("soccer/uefa.champions", "champions_league", "Champions League", ("champions_league", "ucl"),
           18),                                                     # 36 clubs, the last league night all at once
    League("soccer/esp.1", "la_liga", "La Liga", ("la_liga",), 10),                                  # 20 clubs
    League("soccer/ger.1", "bundesliga", "Bundesliga", ("bundesliga",), 9),                          # 18 clubs
    League("soccer/ita.1", "serie_a", "Serie A", ("serie_a",), 10),                                  # 20 clubs
    League("soccer/usa.1", "mls", "MLS", ("mls",), 15),                                              # 30 clubs, Decision Day
    League("basketball/nba", "nba", "NBA", ("nba",), 15),                                            # 30 teams
    League("basketball/wnba", "wnba", "WNBA", ("wnba",), 7),                                         # 15 teams in 2026
    League("football/nfl", "nfl", "NFL", ("nfl",), 16),                                              # 32 teams: a week
    League("football/college-football", "college_football", "College football", ("college_football",),
           80),                                                     # ESPN's list of a busy Saturday (80 on 6 Sep 2025)
    League("baseball/mlb", "mlb", "MLB", ("mlb",), 16),                                              # 30 teams and a doubleheader
    League("hockey/nhl", "nhl", "NHL", ("nhl",), 16),                                                # 32 teams, the last day
)
# What a page may say, to the ESPN path; and a path or alias to the slug that names its sensor.
LEAGUE_MAP = {a: lg.path for lg in LEAGUES for a in lg.aliases}
LEAGUE_SLUGS = {**{lg.path: lg.slug for lg in LEAGUES}, **{a: lg.slug for lg in LEAGUES for a in lg.aliases}}


def path_of(raw) -> str:
    """ESPN's path for a league as a page says it: a path or an alias."""
    said = str(raw or "soccer/eng.1").strip()
    return LEAGUE_MAP.get(said.lower().replace("-", "_").replace(" ", "_"), said)


def busiest_day(raw) -> int:
    """The most games a page for this league (a path or an alias, as a page says it) can have at
    once; 1 for a league the add-on doesn't know, which it can't promise anything about."""
    path = path_of(raw)
    return next((lg.busiest_day for lg in LEAGUES if lg.path == path), 1)


def _espn_game(ev) -> dict:
    """ESPN's event as the add-on's own game fields (shapes.py "scores"): what a source of yours can
    give in its place, and all `game_view` draws from."""
    comp = (ev.get("competitions") or [{}])[0]
    competitors = comp.get("competitors") or []
    home = next((c for c in competitors if c.get("homeAway") == "home"), competitors[0] if competitors else {})
    away = next((c for c in competitors if c.get("homeAway") == "away"), competitors[1] if len(competitors) > 1 else {})
    st_type = comp.get("status", {}).get("type", {})
    home_id = str(home.get("team", {}).get("id") or "")
    scorers = {"home": [], "away": []}
    for dt in comp.get("details", []):
        t_txt = dt.get("type", {}).get("text") or ""
        clk = dt.get("clock", {}).get("displayValue") or ""
        athletes = dt.get("athletesInvolved") or []
        p_name = athletes[0].get("displayName") if athletes else ""
        if p_name and ("Goal" in t_txt or "Point" in t_txt or "Touchdown" in t_txt or "Home Run" in t_txt):
            side = "home" if str(dt.get("team", {}).get("id") or "") == home_id else "away"
            scorers[side].append(f"{p_name} ({clk})" if clk else p_name)

    def team(c, fallback):
        t = c.get("team", {})
        return t.get("displayName") or t.get("shortDisplayName") or fallback

    def names(c):
        t = c.get("team") or {}
        return f"{t.get('displayName', '')} {t.get('shortDisplayName', '')} {t.get('abbreviation', '')}"
    return {
        "id": str(ev.get("id") or comp.get("id") or f"{home_id}_{str(away.get('team', {}).get('id') or '')}"),
        "home": team(home, ""), "away": team(away, ""),
        "home_score": home.get("score"), "away_score": away.get("score"),
        "status": st_type.get("state") or "pre",
        "status_name": st_type.get("name") or "",
        "status_text": st_type.get("description") or st_type.get("detail") or "",
        "clock": comp.get("status", {}).get("displayClock") or "",
        "start": ev.get("date") or comp.get("date") or "",
        "venue": comp.get("venue", {}).get("fullName") or "",
        "home_record": (home.get("records") or [{}])[0].get("summary", ""),
        "away_record": (away.get("records") or [{}])[0].get("summary", ""),
        "home_scorers": scorers["home"], "away_scorers": scorers["away"],
        "names": f"{names(home)} {names(away)}",
    }


def game_view(g: dict, league_title="", tz_name=None, league="soccer") -> dict:
    """A game in the add-on's own fields, as a Scores page draws it: the same for ESPN's and yours.
    Its badge is said when it's drawn (render/sport.badge), in the screen's language; here are its facts."""
    st_state = g.get("status") or "pre"
    date_str = g.get("start") or ""
    kickoff_time_str = ""
    if date_str:
        try:
            kickoff_dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            if tz_name:
                try:
                    kickoff_dt = kickoff_dt.astimezone(ZoneInfo(tz_name))
                except Exception:
                    pass
            kickoff_time_str = clock.hm(kickoff_dt)
        except Exception:
            pass
    return {
        "id": g.get("id") or "",
        "league": g.get("league") or league_title or "",
        "venue": g.get("venue") or "",
        "status": st_state.upper(),
        "status_name": g.get("status_name") or "",
        "status_text": g.get("status_text") or "",
        "clock_val": g.get("clock") or "",
        "tz": tz_name or "",
        "is_live": st_state == "in",
        "kickoff_iso": date_str,
        "kickoff_time": kickoff_time_str,
        "home_team": g.get("home") or "",
        "home_score": g.get("home_score") if g.get("home_score") is not None else "-",
        "home_stats": g.get("home_record") or "",
        "away_team": g.get("away") or "",
        "away_score": g.get("away_score") if g.get("away_score") is not None else "-",
        "away_stats": g.get("away_record") or "",
        "events_home": ", ".join((g.get("home_scorers") or [])[:3]),
        "events_away": ", ".join((g.get("away_scorers") or [])[:3]),
    }


def _parse_espn_event(ev, league_title="", tz_name=None, league="soccer"):
    return game_view(_espn_game(ev), league_title, tz_name, league)


async def _own_games(session, own: str) -> list[dict] | None:
    import shapes
    return await shapes.read_own(session, own, "scores")


_sports_window_cache: dict[str, dict] = {}


def _start_of(g: dict) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(g.get("start") or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def preferred_teams(team) -> list[str]:
    """Your teams, lower-case: "Arsenal, Lakers" is two. Empty means any team."""
    return [t.strip().lower() for t in str(team or "").split(",") if t.strip()]


_STATUS_RANK = {"IN": 0, "PRE": 1}


def match_priority(m: dict, team=None) -> tuple:
    """Your teams first, then games being played, then upcoming, then finished."""
    teams = preferred_teams(team)
    names = f"{m.get('home_team', '')} {m.get('away_team', '')}".lower()
    mine = any(t in names for t in teams)
    return (0 if mine else 1, _STATUS_RANK.get(str(m.get("status", "")).upper(), 2))


def league_slug(entity_or_league) -> tuple[str, str]:
    """A league as (ESPN path, slug): the slug names its sensor, sensor.epaper_sports_<slug>."""
    raw_input = str(entity_or_league or "soccer/eng.1").strip()
    slug_in = raw_input.lower().replace("-", "_").replace(" ", "_")
    endpoint_path = LEAGUE_MAP.get(slug_in, raw_input)
    if "/" not in endpoint_path:
        endpoint_path = f"soccer/{endpoint_path}"
    return endpoint_path, LEAGUE_SLUGS.get(endpoint_path, LEAGUE_SLUGS.get(slug_in, slug_in.replace("/", "_")))


@runtime.live(60)
async def compute_sports_active_window(session, entity_or_league="soccer/eng.1", pre_buffer_hours=HOURS_AROUND,
                                       post_buffer_hours=HOURS_AROUND, tz_name=None, team=None, own=""):
    if not tz_name:
        tz_name = await get_home_timezone(session)
    endpoint_path, slug = league_slug(entity_or_league)
    team_q = str(team or "").strip().lower()
    teams_q = preferred_teams(team)

    cache_key = f"{endpoint_path}:{pre_buffer_hours}:{post_buffer_hours}:{tz_name}:{team_q}:{own}"
    now_ts = time.time()
    cached = _sports_window_cache.get(cache_key)
    if cached and (now_ts - cached["at"] < 60.0):
        return cached["data"]

    sport_key = endpoint_path.split("/")[0]
    durations = {"soccer": 2.0, "basketball": 2.5, "football": 3.25, "baseball": 2.75, "hockey": 2.5}
    est_duration_hours = durations.get(sport_key, 2.0)

    now_utc = datetime.now(timezone.utc)
    today_str = now_utc.strftime("%Y%m%d")
    yesterday_str = (now_utc - timedelta(days=1)).strftime("%Y%m%d")

    headers = {"User-Agent": "Crowpanel-Epaper/0.8.27 (HomeAssistant Addon)"}
    timeout = aiohttp.ClientTimeout(total=6)

    events = []
    league_title = ""
    yesterday_events = []
    if own:
        games = await _own_games(session, own)
        if games is None:
            return None                     # your source hasn't answered yet
        day = now_utc.date()
        events = [g for g in games if (_start_of(g) or now_utc).date() == day]
        yesterday_events = [g for g in games if (_start_of(g) or now_utc).date() == day - timedelta(days=1)]
        league_title = next((g["league"] for g in games if g.get("league")), "")
    else:
        today_url = f"{services.url('espn')}/{endpoint_path}/scoreboard?dates={today_str}"
        try:
            async with session.get(today_url, headers=headers, timeout=timeout) as r:
                if r.status == 200:
                    data = await r.json()
                    events = [_espn_game(ev) for ev in data.get("events") or []]
                    league_title = (data.get("leagues") or [{}])[0].get("name") or ""
        except Exception as exc:
            print(f"compute_sports_active_window error: {health.describe(exc)}", flush=True)

        if not events or now_utc.hour < 12:
            yest_url = f"{services.url('espn')}/{endpoint_path}/scoreboard?dates={yesterday_str}"
            try:
                async with session.get(yest_url, headers=headers, timeout=timeout) as r:
                    if r.status == 200:
                        ydata = await r.json()
                        yesterday_events = [_espn_game(ev) for ev in ydata.get("events") or []]
                        if not events:
                            league_title = (ydata.get("leagues") or [{}])[0].get("name") or league_title
            except Exception:
                pass

    def _matches_team_filter(g):
        names = str(g.get("names") or f"{g.get('home', '')} {g.get('away', '')}").lower()
        return not teams_q or any(t in names for t in teams_q)

    filtered_today = [g for g in events if _matches_team_filter(g)]
    filtered_yesterday = [g for g in yesterday_events if _matches_team_filter(g)]
    all_candidate_events = filtered_today + filtered_yesterday

    game_times = []
    is_live = False
    today_parsed = [game_view(g, league_title, tz_name=tz_name, league=endpoint_path) for g in filtered_today]

    for g in all_candidate_events:
        if g.get("status") == "in":
            is_live = True
        dt = _start_of(g)
        if dt is not None and (g in filtered_today or g.get("status") == "in"):
            game_times.append(dt)

    first_ko = min(game_times) if game_times else None
    last_ko = max(game_times) if game_times else None

    win_start = (first_ko - timedelta(hours=pre_buffer_hours)) if first_ko else None
    win_end = (last_ko + timedelta(hours=est_duration_hours + post_buffer_hours)) if last_ko else None

    is_active = is_live or (bool(win_start and win_end and (win_start <= now_utc <= win_end)))

    summaries = []
    for m in today_parsed:
        summaries.append(f"{m['away_team']} at {m['home_team']}")

    try:
        local_tz = ZoneInfo(tz_name)
    except Exception:
        local_tz = timezone.utc

    first_ko_local = first_ko.astimezone(local_tz).strftime("%H:%M") if first_ko else None
    last_ko_local = last_ko.astimezone(local_tz).strftime("%H:%M") if last_ko else None
    win_start_local = win_start.astimezone(local_tz).strftime("%H:%M") if win_start else None
    win_end_local = win_end.astimezone(local_tz).strftime("%H:%M") if win_end else None

    result = {
        "slug": slug,
        "sensor_id": f"sensor.epaper_sports_{slug}",
        "league_name": league_title,
        "is_active": is_active,
        "state": "active" if is_active else "idle",
        "is_live": is_live,
        "matches_today": len(filtered_today),
        "first_kickoff": first_ko.isoformat() if first_ko else None,
        "first_kickoff_local": first_ko_local,
        "last_kickoff": last_ko.isoformat() if last_ko else None,
        "last_kickoff_local": last_ko_local,
        "window_start": win_start.isoformat() if win_start else None,
        "window_start_local": win_start_local,
        "window_end": win_end.isoformat() if win_end else None,
        "window_end_local": win_end_local,
        "time_zone": tz_name,
        "pre_buffer_hours": pre_buffer_hours,
        "post_buffer_hours": post_buffer_hours,
        "team_filter": team or "",
        "matches_summary": ", ".join(summaries[:6]),
        "today_matches": today_parsed,
    }
    _sports_window_cache[cache_key] = {"at": now_ts, "data": result}
    runtime.prune(_sports_window_cache)
    return result


@runtime.live(30)
async def fetch_sports_match(session, entity_or_league="soccer/eng.1", team=None, fallback=None, tz_name=None, own=""):
    """What a Scores page draws. `own`: the id of your data source that gives its games in the add-on's
    own fields, in place of ESPN."""
    if not tz_name:
        tz_name = await get_home_timezone(session)
    if own:
        games = await _own_games(session, own)
        if games is None:
            return None
        title = next((g["league"] for g in games if g.get("league")), "")
        league = path_of(entity_or_league)
        return sorted((game_view(g, title, tz_name=tz_name, league=league) for g in games),
                      key=lambda m: match_priority(m, team))
    now = time.time()
    raw_input = str(entity_or_league or "soccer/eng.1").strip()
    cache_key = f"{raw_input}:{str(team or '').lower()}:{tz_name}"

    # 1. Approach A: Check if fallback is a resolved HA entity from ha-teamtracker
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
        home = attrs.get("team_name") or attrs.get("team_abbr") or ""
        away = attrs.get("opponent_name") or attrs.get("opponent_abbr") or ""
        h_score = attrs.get("team_score")
        a_score = attrs.get("opponent_score")
        st = str(base_data.get("state") or "PRE").upper()
        clock_str = attrs.get("clock") or attrs.get("quarter") or attrs.get("period") or st
        last_play = attrs.get("last_play") or ""
        down_dist = attrs.get("down_distance_text") or ""
        venue = attrs.get("venue") or ""
        league_name = attrs.get("league") or ""
        return [{
            "id": str(attrs.get("event_id") or attrs.get("id") or f"{home}_{away}"),
            "league": league_name,
            "venue": venue,
            "clock": clock_str,
            "status": st,
            "home_team": home,
            "home_score": h_score if h_score is not None else "-",
            "home_stats": down_dist,
            "away_team": away,
            "away_score": a_score if a_score is not None else "-",
            "away_stats": "",
            "events_home": last_play,
            "events_away": ""
        }]

    # 2. Check in-memory cache
    cached = _sports_match_cache.get(cache_key)
    if cached and (now - cached["at"] < (30.0 if cached.get("is_live") else 300.0)):
        return cached["data"]

    # 3. Approach B: Map friendly league names to ESPN endpoint
    slug = raw_input.lower().replace("-", "_").replace(" ", "_")
    endpoint_path = LEAGUE_MAP.get(slug, raw_input)
    if "/" not in endpoint_path:
        endpoint_path = f"soccer/{endpoint_path}"

    now_utc = datetime.now(timezone.utc)
    today_str = now_utc.strftime("%Y%m%d")

    url_today = f"{services.url('espn')}/{endpoint_path}/scoreboard?dates={today_str}"
    url_default = f"{services.url('espn')}/{endpoint_path}/scoreboard"
    headers = {"User-Agent": "Crowpanel-Epaper/0.8.27 (HomeAssistant Addon)"}
    timeout = aiohttp.ClientTimeout(total=6)

    try:
        events = []
        league_title = ""
        # First try today's games so today's upcoming/live matches take precedence
        async with session.get(url_today, headers=headers, timeout=timeout) as r:
            if r.status == 200:
                data = await r.json()
                events = data.get("events") or []
                league_title = (data.get("leagues") or [{}])[0].get("name") or ""

        # If no games today, fall back to default scoreboard (upcoming or current round)
        if not events:
            async with session.get(url_default, headers=headers, timeout=timeout) as r:
                if r.status == 200:
                    data = await r.json()
                    events = data.get("events") or []
                    league_title = (data.get("leagues") or [{}])[0].get("name") or league_title

        if not events:
            return cached["data"] if cached else None

        parsed_matches = [_parse_espn_event(ev, league_title, tz_name=tz_name, league=endpoint_path) for ev in events]

        # Most important first: when the panel can't hold every match, the
        # ones at the end are the ones left out (frames.fit_counts).
        parsed_matches.sort(key=lambda m: match_priority(m, team))

        is_any_live = any(m.get("is_live") for m in parsed_matches)
        _sports_match_cache[cache_key] = {"at": now, "data": parsed_matches, "is_live": is_any_live}
        runtime.prune(_sports_match_cache)
        return parsed_matches
    except Exception as exc:
        print(f"fetch_sports_match error: {health.describe(exc)}", flush=True)
        return cached["data"] if cached else None
