"""Formula 1 and Formula E sessions and race windows."""

import json
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import aiohttp

import runtime
from sources.geo import get_home_timezone


_racing_cache = {}


@runtime.live(30)
async def fetch_racing_data(session, entity_or_series="f1", fallback=None, tz_name=None):
    if not tz_name:
        tz_name = await get_home_timezone(session)
    now = time.time()
    raw_key = str(entity_or_series or "f1").strip().lower()
    cache_key = f"{raw_key}:{tz_name}"

    # 1. Approach A: Check if fallback is a resolved template from HA entity (e.g. sensor.f1)
    base_data = None
    if isinstance(fallback, dict):
        base_data = fallback
    elif isinstance(fallback, str) and fallback.strip():
        try:
            base_data = json.loads(fallback)
        except Exception:
            pass

    ha_event_name = ""
    ha_status = ""
    ha_circuit = ""
    ha_date = ""
    if isinstance(base_data, dict) and "attributes" in base_data:
        attrs = base_data.get("attributes") or {}
        ha_status = str(base_data.get("state") or "").upper()
        ha_event_name = attrs.get("event_name") or attrs.get("event") or ""
        ha_circuit = attrs.get("venue") or attrs.get("circuit") or ""
        ha_date = attrs.get("date") or ""
        if attrs.get("standings"):
            ser_name = "FE" if raw_key in ("fe", "formula_e", "formula-e", "formulae") else "F1"
            return {
                "series": ser_name,
                "event_name": ha_event_name or ("Formula E World Championship" if ser_name == "FE" else "Formula 1 Grand Prix"),
                "circuit": ha_circuit or "Grand Prix Circuit",
                "status": ha_status or "IN",
                "lap": attrs.get("lap"),
                "total_laps": attrs.get("total_laps"),
                "clock": attrs.get("clock") or ha_status,
                "standings": attrs.get("standings")
            }

    # 2. Formula E support
    if raw_key in ("fe", "formula_e", "formula-e", "formulae"):
        cached = _racing_cache.get(cache_key)
        if cached and (now - cached["at"] < (60.0 if cached.get("is_live") else 600.0)):
            return cached["data"]

        fe_event = {
            "series": "FE",
            "event_name": ha_event_name or "Formula E World Championship",
            "circuit": ha_circuit or "ePrix Circuit",
            "detail": "Upcoming Formula E Session",
            "status": ha_status or "PRE",
            "clock": "PRE",
            "standings": []
        }
        is_live = False
        now_utc = datetime.now(timezone.utc)
        cur_year = now_utc.year
        headers = {"User-Agent": "Crowpanel-Epaper/0.8.23 (HomeAssistant Addon)"}
        timeout = aiohttp.ClientTimeout(total=6)

        try:
            races = []
            for yr in (cur_year, cur_year + 1):
                fe_url = f"https://raw.githubusercontent.com/sportstimes/f1/main/_db/fe/{yr}.json"
                try:
                    async with session.get(fe_url, headers=headers, timeout=timeout) as r:
                        if r.status == 200:
                            fdata = await r.json(content_type=None)
                            yr_races = fdata.get("races") or []
                            if yr_races:
                                races.extend(yr_races)
                except Exception:
                    pass

            if not races:
                try:
                    async with session.get(f"https://formulaecal.com/api/year/{cur_year}", headers=headers, timeout=timeout) as r:
                        if r.status == 200:
                            fdata = await r.json(content_type=None)
                            races = fdata.get("races") or []
                except Exception:
                    pass

            if races:
                candidate_race = None
                active_session_name = "Race"
                active_session_dt = None
                session_st = "PRE"

                for r in races:
                    sess_dict = r.get("sessions") or {}
                    s_items = []
                    for s_k, s_v in sess_dict.items():
                        if not s_v:
                            continue
                        try:
                            s_dt = datetime.fromisoformat(str(s_v).replace("Z", "+00:00"))
                            s_items.append((s_k, s_dt))
                        except Exception:
                            pass
                    s_items.sort(key=lambda x: x[1])
                    if not s_items:
                        continue

                    if s_items[-1][1] + timedelta(hours=4) >= now_utc:
                        candidate_race = r
                        for s_k, s_dt in s_items:
                            if s_dt <= now_utc <= s_dt + timedelta(hours=2):
                                active_session_name = s_k
                                active_session_dt = s_dt
                                session_st = "IN"
                                is_live = True
                                break
                            elif s_dt > now_utc:
                                active_session_name = s_k
                                active_session_dt = s_dt
                                session_st = "PRE"
                                break
                        if not active_session_dt:
                            active_session_name = s_items[-1][0]
                            active_session_dt = s_items[-1][1]
                            session_st = "POST"
                        break

                if not candidate_race:
                    candidate_race = races[-1]
                    session_st = "POST"
                    s_items = [(k, datetime.fromisoformat(str(v).replace("Z", "+00:00")))
                               for k, v in candidate_race.get("sessions", {}).items() if v]
                    s_items.sort(key=lambda x: x[1])
                    active_session_name = s_items[-1][0] if s_items else "Race"
                    active_session_dt = s_items[-1][1] if s_items else now_utc

                friendly_session_map = {
                    "practice1": "Practice 1",
                    "practice2": "Practice 2",
                    "qualifying": "Qualifying",
                    "race": "ePrix Race"
                }
                session_title = friendly_session_map.get(active_session_name.lower(), active_session_name.capitalize())
                circ_name = candidate_race.get("location") or "ePrix Circuit"
                if "circuit" not in circ_name.lower():
                    circ_name = f"{circ_name} ePrix Circuit"

                detail_str = ""
                if active_session_dt:
                    try:
                        dt_loc = active_session_dt.astimezone(ZoneInfo(tz_name))
                        tz_abbr = dt_loc.tzname() or ""
                        detail_str = f"{session_title} · {dt_loc.strftime('%a %b %d · %H:%M')} {tz_abbr}".strip()
                    except Exception:
                        detail_str = f"{session_title} · {active_session_dt.strftime('%a %b %d · %H:%M UTC')}"

                fe_event = {
                    "series": "FE",
                    "event_name": candidate_race.get("name") or ha_event_name or "Formula E World Championship",
                    "circuit": circ_name,
                    "detail": detail_str or f"Status: {session_st}",
                    "status": session_st,
                    "clock": f"{session_title} runtime.LIVE" if session_st == "IN" else ("SCHEDULED" if session_st == "PRE" else "FINAL"),
                    "standings": []
                }

            _racing_cache[cache_key] = {"at": now, "data": fe_event, "is_live": is_live}
            return fe_event
        except Exception as exc:
            print(f"fetch_formula_e_data error: {exc!r}", flush=True)
            return _racing_cache.get(cache_key, {}).get("data") or fe_event

    # 3. Check in-memory cache for F1 / other series
    cached = _racing_cache.get(cache_key)
    if cached and (now - cached["at"] < (60.0 if cached.get("is_live") else 600.0)):
        return cached["data"]

    # 4. Approach B: Query ESPN F1 scoreboard
    f1_url = "https://site.api.espn.com/apis/site/v2/sports/racing/f1/scoreboard"
    headers = {"User-Agent": "Crowpanel-Epaper/0.8.23 (HomeAssistant Addon)"}
    timeout = aiohttp.ClientTimeout(total=6)

    event_data = {
        "series": "F1",
        "event_name": ha_event_name or "Formula 1 Grand Prix",
        "circuit": ha_circuit or "Grand Prix Circuit",
        "detail": "Upcoming Grand Prix Session",
        "status": ha_status or "PRE",
        "standings": []
    }
    is_live = False

    try:
        async with session.get(f1_url, headers=headers, timeout=timeout) as r:
            if r.status == 200:
                data = await r.json()
                events = data.get("events") or []
                if events:
                    ev = events[0]
                    ev_name = ev.get("name") or ha_event_name or "Formula 1 Grand Prix"
                    circuit_info = ev.get("circuit") or {}
                    c_name = circuit_info.get("fullName") or ha_circuit or "Grand Prix Circuit"
                    c_addr = circuit_info.get("address", {})
                    c_city = c_addr.get("city") or ""
                    circuit_str = f"{c_name} · {c_city}" if c_city else c_name
                    st_desc = ev.get("status", {}).get("type", {}).get("description") or "Scheduled"
                    st_state = ev.get("status", {}).get("type", {}).get("state") or "pre"
                    is_live = (st_state == "in" or "progress" in st_desc.lower())

                    date_iso = ev.get("date") or ha_date
                    detail_str = f"Status: {st_desc}"
                    if date_iso:
                        try:
                            dt = datetime.fromisoformat(date_iso.replace("Z", "+00:00"))
                            if tz_name:
                                dt_loc = dt.astimezone(ZoneInfo(tz_name))
                                tz_abbr = dt_loc.tzname() or ""
                                detail_str = f"{dt_loc.strftime('%a %b %d · %H:%M')} {tz_abbr}".strip()
                            else:
                                detail_str = dt.strftime("%a %b %d · %H:%M UTC")
                        except Exception:
                            detail_str = f"{st_desc} · {str(date_iso)[:10]}"

                    event_data = {
                        "series": "F1",
                        "event_name": ev_name,
                        "circuit": circuit_str,
                        "detail": detail_str,
                        "status": "IN" if is_live else ("POST" if st_state == "post" else "PRE"),
                        "clock": st_desc,
                        "standings": []
                    }

                    comps = (ev.get("competitions") or [{}])[0].get("competitors") or []
                    if comps:
                        parsed_standings = []
                        for idx, c in enumerate(comps[:10]):
                            ath = c.get("athlete") or {}
                            tm = c.get("team") or {}
                            code = ath.get("abbreviation") or ath.get("shortName") or "DRV"
                            team_name = tm.get("displayName") or tm.get("shortDisplayName") or ""
                            gap_val = c.get("status", {}).get("displayValue") or ("LEADER" if idx == 0 else "")
                            parsed_standings.append({
                                "pos": idx + 1,
                                "driver": str(code)[:3].upper(),
                                "team": team_name,
                                "gap": gap_val,
                                "tyre": "M"
                            })
                        if parsed_standings:
                            event_data["standings"] = parsed_standings

        _racing_cache[cache_key] = {"at": now, "data": event_data, "is_live": is_live}
        return event_data
    except Exception as exc:
        print(f"fetch_racing_data error: {exc!r}", flush=True)
        return _racing_cache.get(cache_key, {}).get("data") or event_data
_racing_window_cache: dict[str, dict] = {}


@runtime.live(60)
async def compute_racing_active_window(session, series="f1", pre_buffer_hours=2.0, post_buffer_hours=2.0, window_mode="session", tz_name=None):
    """Compute whether a Motorsport series (F1, Formula E, NASCAR, IndyCar) is in an active session/race-weekend window."""
    if not tz_name:
        tz_name = await get_home_timezone(session)
    raw_s = str(series or "f1").strip().lower()
    if raw_s in ("fe", "formula_e", "formula-e", "formulae"):
        slug = "fe"
        series_title = "Formula E"
    elif raw_s in ("nascar", "nascar-premier"):
        slug = "nascar"
        series_title = "NASCAR"
    elif raw_s in ("indycar", "irl"):
        slug = "indycar"
        series_title = "IndyCar"
    else:
        slug = "f1"
        series_title = "Formula 1"

    w_mode = "weekend" if str(window_mode).strip().lower() == "weekend" else "session"
    cache_key = f"{slug}:{pre_buffer_hours}:{post_buffer_hours}:{w_mode}:{tz_name}"
    now_ts = time.time()
    cached = _racing_window_cache.get(cache_key)
    if cached and (now_ts - cached["at"] < 60.0):
        return cached["data"]

    now_utc = datetime.now(timezone.utc)
    cur_year = now_utc.year
    headers = {"User-Agent": "Crowpanel-Epaper/0.8.27 (HomeAssistant Addon)"}
    timeout = aiohttp.ClientTimeout(total=6)

    sessions_list: list[tuple[str, datetime, float]] = []  # (session_label, start_utc, duration_hours)
    event_name = f"{series_title} Championship"
    circuit_name = ""
    is_live = False

    # 1. For F1 and Formula E, check sportstimes session database for exact FP1/FP2/FP3/Quali/Sprint/Race UTC timestamps
    if slug in ("f1", "fe"):
        for yr in (cur_year, cur_year + 1):
            db_url = f"https://raw.githubusercontent.com/sportstimes/f1/main/_db/{slug}/{yr}.json"
            try:
                async with session.get(db_url, headers=headers, timeout=timeout) as r:
                    if r.status == 200:
                        fdata = await r.json(content_type=None)
                        races = fdata.get("races") or []
                        for race in races:
                            sess_dict = race.get("sessions") or {}
                            r_sessions = []
                            for sk, sv in sess_dict.items():
                                if not sv:
                                    continue
                                try:
                                    sdt = datetime.fromisoformat(str(sv).replace("Z", "+00:00"))
                                    dur = 2.5 if sk.lower() in ("gp", "race") else 1.5
                                    r_sessions.append((sk, sdt, dur))
                                except Exception:
                                    pass
                            r_sessions.sort(key=lambda x: x[1])
                            if not r_sessions:
                                continue
                            # Pick the race weekend whose final session + post_buffer + 12h hasn't long passed
                            if r_sessions[-1][1] + timedelta(hours=r_sessions[-1][2] + max(post_buffer_hours, 6.0)) >= now_utc:
                                event_name = race.get("name") or event_name
                                circuit_name = race.get("location") or ""
                                sessions_list = r_sessions
                                break
                        if sessions_list:
                            break
            except Exception:
                pass

    # 2. Also check ESPN racing scoreboard (for live status and NASCAR/IndyCar/F1 fallback)
    espn_map = {"f1": "f1", "nascar": "nascar-premier", "indycar": "irl"}
    if slug in espn_map:
        espn_url = f"https://site.api.espn.com/apis/site/v2/sports/racing/{espn_map[slug]}/scoreboard"
        try:
            async with session.get(espn_url, headers=headers, timeout=timeout) as r:
                if r.status == 200:
                    data = await r.json()
                    events = data.get("events") or []
                    if events:
                        ev = events[0]
                        event_name = ev.get("name") or event_name
                        circuit_name = (ev.get("circuit") or {}).get("fullName") or circuit_name
                        st_state = ev.get("status", {}).get("type", {}).get("state") or "pre"
                        if st_state == "in":
                            is_live = True
                        if not sessions_list:
                            for comp in (ev.get("competitions") or []):
                                c_date = comp.get("date") or ev.get("date")
                                c_type = (comp.get("type") or {}).get("text") or "Session"
                                c_state = (comp.get("status") or {}).get("type", {}).get("state")
                                if c_state == "in":
                                    is_live = True
                                if c_date:
                                    try:
                                        cdt = datetime.fromisoformat(str(c_date).replace("Z", "+00:00"))
                                        dur = 2.5 if "race" in c_type.lower() else 1.5
                                        sessions_list.append((c_type, cdt, dur))
                                    except Exception:
                                        pass
                            if not sessions_list and ev.get("date"):
                                try:
                                    edt = datetime.fromisoformat(str(ev["date"]).replace("Z", "+00:00"))
                                    sessions_list.append(("Race", edt, 2.5))
                                except Exception:
                                    pass
                            sessions_list.sort(key=lambda x: x[1])
        except Exception:
            pass

    active_win_start = None
    active_win_end = None
    active_session_label = ""
    is_active = is_live

    if sessions_list:
        for s_label, s_dt, s_dur in sessions_list:
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
    return result
