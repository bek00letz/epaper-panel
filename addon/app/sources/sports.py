"""Football and other ESPN leagues: matches and matchday windows."""

import health
import json
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import aiohttp

import runtime
from sources.geo import get_home_timezone


_sports_match_cache = {}


LEAGUE_MAP = {
    "premier_league": "soccer/eng.1",
    "epl": "soccer/eng.1",
    "champions_league": "soccer/uefa.champions",
    "ucl": "soccer/uefa.champions",
    "la_liga": "soccer/esp.1",
    "bundesliga": "soccer/ger.1",
    "serie_a": "soccer/ita.1",
    "mls": "soccer/usa.1",
    "nba": "basketball/nba",
    "wnba": "basketball/wnba",
    "nfl": "football/nfl",
    "college_football": "football/college-football",
    "mlb": "baseball/mlb",
    "nhl": "hockey/nhl"
}

LEAGUE_SLUGS = {
    "soccer/eng.1": "premier_league",
    "premier_league": "premier_league",
    "epl": "premier_league",
    "soccer/uefa.champions": "champions_league",
    "champions_league": "champions_league",
    "ucl": "champions_league",
    "soccer/esp.1": "la_liga",
    "la_liga": "la_liga",
    "soccer/ger.1": "bundesliga",
    "bundesliga": "bundesliga",
    "soccer/ita.1": "serie_a",
    "serie_a": "serie_a",
    "soccer/usa.1": "mls",
    "mls": "mls",
    "basketball/nba": "nba",
    "nba": "nba",
    "basketball/wnba": "wnba",
    "wnba": "wnba",
    "football/nfl": "nfl",
    "nfl": "nfl",
    "football/college-football": "college_football",
    "baseball/mlb": "mlb",
    "mlb": "mlb",
    "hockey/nhl": "nhl",
    "nhl": "nhl"
}


def _parse_espn_event(ev, league_title="MATCH", tz_name=None):
    comp = (ev.get("competitions") or [{}])[0]
    competitors = comp.get("competitors") or []
    home = next((c for c in competitors if c.get("homeAway") == "home"), competitors[0] if competitors else {})
    away = next((c for c in competitors if c.get("homeAway") == "away"), competitors[1] if len(competitors) > 1 else {})

    st_type = comp.get("status", {}).get("type", {})
    st_state = st_type.get("state") or "pre"
    st_desc = st_type.get("description") or st_type.get("detail") or "Scheduled"
    clock_val = comp.get("status", {}).get("displayClock")
    is_live = (st_state == "in")

    date_str = ev.get("date") or comp.get("date") or ""
    kickoff_time_str = ""
    kickoff_day_str = ""
    if date_str:
        try:
            kickoff_dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            if tz_name:
                try:
                    local_tz = ZoneInfo(tz_name)
                    kickoff_dt = kickoff_dt.astimezone(local_tz)
                except Exception:
                    pass
            kickoff_time_str = kickoff_dt.strftime("%H:%M")
            now_local = datetime.now(kickoff_dt.tzinfo)
            if kickoff_dt.date() != now_local.date():
                kickoff_day_str = kickoff_dt.strftime("%a ")
        except Exception:
            pass

    if is_live:
        clock_badge = f"{clock_val} · {st_desc}" if (clock_val and clock_val != "0'") else st_desc
    elif st_state == "pre":
        if kickoff_day_str:
            clock_badge = f"{kickoff_day_str}{kickoff_time_str}"
        elif kickoff_time_str:
            clock_badge = f"Kickoff {kickoff_time_str}"
        else:
            clock_badge = st_desc
    else:
        clock_badge = st_desc

    venue_title = comp.get("venue", {}).get("fullName") or ""

    home_id = str(home.get("team", {}).get("id") or "")
    events_home = []
    events_away = []
    for dt in comp.get("details", []):
        t_txt = dt.get("type", {}).get("text") or ""
        clk = dt.get("clock", {}).get("displayValue") or ""
        athletes = dt.get("athletesInvolved") or []
        p_name = athletes[0].get("displayName") if athletes else ""
        if p_name and ("Goal" in t_txt or "Point" in t_txt or "Touchdown" in t_txt or "Home Run" in t_txt):
            entry_str = f"{p_name} ({clk})" if clk else p_name
            if str(dt.get("team", {}).get("id") or "") == home_id:
                events_home.append(entry_str)
            else:
                events_away.append(entry_str)

    return {
        "id": str(ev.get("id") or comp.get("id") or f"{home_id}_{str(away.get('team', {}).get('id') or '')}"),
        "league": league_title,
        "venue": venue_title,
        "clock": clock_badge,
        "status": st_state.upper(),
        "is_live": is_live,
        "kickoff_iso": date_str,
        "kickoff_time": kickoff_time_str,
        "home_team": home.get("team", {}).get("displayName") or home.get("team", {}).get("shortDisplayName") or "HOME",
        "home_score": home.get("score") if home.get("score") is not None else "-",
        "home_stats": (home.get("records") or [{}])[0].get("summary", ""),
        "away_team": away.get("team", {}).get("displayName") or away.get("team", {}).get("shortDisplayName") or "AWAY",
        "away_score": away.get("score") if away.get("score") is not None else "-",
        "away_stats": (away.get("records") or [{}])[0].get("summary", ""),
        "events_home": ", ".join(events_home[:3]),
        "events_away": ", ".join(events_away[:3])
    }


_sports_window_cache: dict[str, dict] = {}


def league_slug(entity_or_league) -> tuple[str, str]:
    """A league as (ESPN path, slug): the slug names its sensor, sensor.epaper_sports_<slug>."""
    raw_input = str(entity_or_league or "soccer/eng.1").strip()
    slug_in = raw_input.lower().replace("-", "_").replace(" ", "_")
    endpoint_path = LEAGUE_MAP.get(slug_in, raw_input)
    if "/" not in endpoint_path:
        endpoint_path = f"soccer/{endpoint_path}"
    return endpoint_path, LEAGUE_SLUGS.get(endpoint_path, LEAGUE_SLUGS.get(slug_in, slug_in.replace("/", "_")))


@runtime.live(60)
async def compute_sports_active_window(session, entity_or_league="soccer/eng.1", pre_buffer_hours=2.0, post_buffer_hours=2.0, tz_name=None, team=None):
    if not tz_name:
        tz_name = await get_home_timezone(session)
    endpoint_path, slug = league_slug(entity_or_league)
    team_q = str(team or "").strip().lower()

    cache_key = f"{endpoint_path}:{pre_buffer_hours}:{post_buffer_hours}:{tz_name}:{team_q}"
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

    today_url = f"https://site.api.espn.com/apis/site/v2/sports/{endpoint_path}/scoreboard?dates={today_str}"
    events = []
    league_title = "MATCH"
    try:
        async with session.get(today_url, headers=headers, timeout=timeout) as r:
            if r.status == 200:
                data = await r.json()
                events = data.get("events") or []
                league_title = (data.get("leagues") or [{}])[0].get("name") or "MATCH"
    except Exception as exc:
        print(f"compute_sports_active_window error: {health.describe(exc)}", flush=True)

    yesterday_events = []
    if not events or now_utc.hour < 12:
        yest_url = f"https://site.api.espn.com/apis/site/v2/sports/{endpoint_path}/scoreboard?dates={yesterday_str}"
        try:
            async with session.get(yest_url, headers=headers, timeout=timeout) as r:
                if r.status == 200:
                    ydata = await r.json()
                    yesterday_events = ydata.get("events") or []
                    if not events:
                        league_title = (ydata.get("leagues") or [{}])[0].get("name") or league_title
        except Exception:
            pass

    def _matches_team_filter(ev_obj):
        if not team_q:
            return True
        comp = (ev_obj.get("competitions") or [{}])[0]
        for c in (comp.get("competitors") or []):
            t_info = c.get("team") or {}
            names = f"{t_info.get('displayName', '')} {t_info.get('shortDisplayName', '')} {t_info.get('abbreviation', '')}".lower()
            if team_q in names:
                return True
        return False

    filtered_today = [ev for ev in events if _matches_team_filter(ev)]
    filtered_yesterday = [ev for ev in yesterday_events if _matches_team_filter(ev)]
    all_candidate_events = filtered_today + filtered_yesterday

    game_times = []
    is_live = False
    today_parsed = []

    for ev in filtered_today:
        parsed = _parse_espn_event(ev, league_title, tz_name=tz_name)
        today_parsed.append(parsed)

    for ev in all_candidate_events:
        st_state = ev.get("status", {}).get("type", {}).get("state")
        if st_state == "in":
            is_live = True
        d_str = ev.get("date")
        if d_str:
            try:
                dt = datetime.fromisoformat(d_str.replace("Z", "+00:00"))
                if ev in filtered_today or st_state == "in":
                    game_times.append(dt)
            except Exception:
                pass

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
    return result


@runtime.live(30)
async def fetch_sports_match(session, entity_or_league="soccer/eng.1", team=None, fallback=None, tz_name=None):
    if not tz_name:
        tz_name = await get_home_timezone(session)
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
        home = attrs.get("team_name") or attrs.get("team_abbr") or "HOME"
        away = attrs.get("opponent_name") or attrs.get("opponent_abbr") or "AWAY"
        h_score = attrs.get("team_score")
        a_score = attrs.get("opponent_score")
        st = str(base_data.get("state") or "PRE").upper()
        clock_str = attrs.get("clock") or attrs.get("quarter") or attrs.get("period") or st
        last_play = attrs.get("last_play") or ""
        down_dist = attrs.get("down_distance_text") or ""
        venue = attrs.get("venue") or ""
        league_name = attrs.get("league") or "MATCH"
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

    url_today = f"https://site.api.espn.com/apis/site/v2/sports/{endpoint_path}/scoreboard?dates={today_str}"
    url_default = f"https://site.api.espn.com/apis/site/v2/sports/{endpoint_path}/scoreboard"
    headers = {"User-Agent": "Crowpanel-Epaper/0.8.27 (HomeAssistant Addon)"}
    timeout = aiohttp.ClientTimeout(total=6)

    try:
        events = []
        league_title = "MATCH"
        # First try today's games so today's upcoming/live matches take precedence
        async with session.get(url_today, headers=headers, timeout=timeout) as r:
            if r.status == 200:
                data = await r.json()
                events = data.get("events") or []
                league_title = (data.get("leagues") or [{}])[0].get("name") or "MATCH"

        # If no games today, fall back to default scoreboard (upcoming or current round)
        if not events:
            async with session.get(url_default, headers=headers, timeout=timeout) as r:
                if r.status == 200:
                    data = await r.json()
                    events = data.get("events") or []
                    league_title = (data.get("leagues") or [{}])[0].get("name") or league_title

        if not events:
            return cached["data"] if cached else None

        parsed_matches = [_parse_espn_event(ev, league_title, tz_name=tz_name) for ev in events]

        if team:
            query = str(team).lower().strip()
            matched, others = [], []
            for m in parsed_matches:
                if (query in m["home_team"].lower() or query in m["away_team"].lower()):
                    matched.append(m)
                else:
                    others.append(m)
            parsed_matches = matched + others
        else:
            def _st_sort(m):
                st = m.get("status", "")
                if st == "IN": return 0
                if st == "PRE": return 1
                return 2
            parsed_matches.sort(key=_st_sort)

        is_any_live = any(m.get("is_live") for m in parsed_matches)
        _sports_match_cache[cache_key] = {"at": now, "data": parsed_matches, "is_live": is_any_live}
        return parsed_matches
    except Exception as exc:
        print(f"fetch_sports_match error: {health.describe(exc)}", flush=True)
        return cached["data"] if cached else None
