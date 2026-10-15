"""Data layer. Reads Home Assistant state and the Jellyfin library.

Home Assistant can come from a JSON fixture (development, no token needed) or
from the REST API (on the box). Jellyfin is always live -- it is reachable and
cheap, and its answer is the one thing HA cannot provide.
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

JELLYFIN_BASE = ""   # set via add-on config
JELLYFIN_USER = ""   # set via add-on config
WATCH_WINDOW_DAYS = 30

ENT = {
    "pv_today":   "sensor.solar_today_production",
    "pv_now":     "sensor.solar_pv_power",
    "batt_pct":   "sensor.home_battery",
    "batt_w":     "sensor.home_battery_power_2",
    "batt_state": "sensor.home_battery_state",
    "load_w":     "sensor.solar_load_power",
    "forecast":   "sensor.solcast_pv_forecast_forecast_today",
    "cat":        "sensor.cat_location",
    "yard":       "sensor.outdoor_temperature",
    "inside":     "sensor.indoor_temperature",
    "dryer":      "timer.dryer_cycle",
}

CAT_WORDS = {
    "outdoor cat": "outside",
    "indoor cat":  "inside",
    "bed":         "in bed",
    "house":       "in the house",
}

DEAD = {"unavailable", "unknown", "none", ""}


def _http_json(url, headers=None, timeout=10):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


# --------------------------------------------------------------- Jellyfin

def human_ago(dt, now=None):
    now = now or datetime.now(timezone.utc)
    days = (now.date() - dt.astimezone(now.tzinfo).date()).days
    if days <= 0:
        return "today"
    if days == 1:
        return "yesterday"
    if days < 14:
        return f"{days} days ago"
    return dt.strftime("%-d %b").lower()


def jellyfin_new(api_key, *, base=JELLYFIN_BASE, user=JELLYFIN_USER,
                 days=WATCH_WINDOW_DAYS, limit=20):
    """Recently added AND unplayed, newest first, series grouped.

    Returns [] on any failure -- a dead Jellyfin must not take the panel down.
    """
    params = {
        "userId": user, "Limit": limit, "IsPlayed": "false",
        "IncludeItemTypes": "Movie,Episode", "GroupItems": "true",
        "Fields": "SeriesName,DateCreated,ChildCount",
    }
    url = f"{base}/Items/Latest?" + urllib.parse.urlencode(params)
    try:
        items = _http_json(url, {"X-Emby-Token": api_key})
    except Exception:
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    out = []
    for it in items:
        raw = it.get("DateCreated")
        if not raw:
            continue
        try:
            added = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            continue
        if added < cutoff:
            continue

        kind = it.get("Type")
        if kind == "Episode":
            title, detail = (it.get("SeriesName") or it.get("Name")), it.get("Name")
        elif kind == "Series":
            n = it.get("ChildCount") or 0
            title = it.get("Name")
            detail = f"{n} new episodes" if n != 1 else "1 new episode"
        else:
            title, detail = it.get("Name"), "film"

        out.append({
            "title": title or "?",
            "detail": f"{detail} · {human_ago(added)}",
            "added": added,
        })
    return out


# --------------------------------------------------------- Home Assistant

class Data:
    def __init__(self, states, pv_curve, month_kwh, panel, watch):
        self._s = states
        self.pv_curve = pv_curve
        self.month_kwh = month_kwh
        self.panel = panel
        self.watch = watch

    # -- raw access -------------------------------------------------
    def state(self, key):
        return (self._s.get(ENT[key], {}) or {}).get("state")

    def attr(self, key, name):
        return (self._s.get(ENT[key], {}) or {}).get(name)

    def num(self, key, default=None):
        v = self.state(key)
        if v is None or str(v).lower() in DEAD:
            return default
        try:
            return float(v)
        except (TypeError, ValueError):
            return default

    def alive(self, key):
        v = self.state(key)
        return v is not None and str(v).lower() not in DEAD

    # -- derived ----------------------------------------------------
    def cat_word(self):
        raw = (self.state("cat") or "").strip()
        return CAT_WORDS.get(raw.lower(), raw.lower() or "unknown")

    def cat_since(self):
        raw = self.attr("cat", "last_changed")
        if not raw:
            return None
        try:
            dt = datetime.fromisoformat(raw)
        except ValueError:
            return None
        now = datetime.now(dt.tzinfo)
        if (now - dt).total_seconds() < 20 * 3600 and now.date() == dt.date():
            return f"since {dt:%H:%M}"
        return f"since {dt:%H:%M} {human_ago(dt, now)}"

    def dryer_remaining(self):
        """Seconds left on the dryer timer, or None when it is not running."""
        if (self.state("dryer") or "").lower() != "active":
            return None
        rem = self.attr("dryer", "remaining")
        if not rem:
            return None
        try:
            h, m, s = (int(float(p)) for p in str(rem).split(":"))
            return h * 3600 + m * 60 + s
        except ValueError:
            return None


def from_fixture(path="fixture.json"):
    raw = json.loads(Path(path).read_text())
    return Data(raw["states"], raw["pv_curve_w"], raw["month_kwh"],
                raw["panel"], watch=[])


def _ha_get(base, token, path):
    return _http_json(f"{base}{path}",
                      {"Authorization": f"Bearer {token}",
                       "Content-Type": "application/json"})


def _pv_curve(base, token, entity, buckets=24):
    """Today's PV power, averaged into hourly buckets, from the REST history API."""
    start = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
    path = (f"/api/history/period/{start.isoformat()}"
            f"?filter_entity_id={entity}&minimal_response&no_attributes")
    try:
        rows = _ha_get(base, token, path)
    except Exception:
        return []
    if not rows or not rows[0]:
        return []

    sums = [0.0] * buckets
    counts = [0] * buckets
    for r in rows[0]:
        try:
            v = float(r["state"])
            t = datetime.fromisoformat(r["last_changed"]).astimezone()
        except (KeyError, TypeError, ValueError):
            continue
        sums[t.hour] += v
        counts[t.hour] += 1

    last = max((i for i, c in enumerate(counts) if c), default=-1)
    return [sums[i] / counts[i] if counts[i] else 0.0 for i in range(last + 1)]


def _month_kwh(db_path, entity):
    """This month's production, straight out of the recorder's long-term stats.

    Same numbers the Energy dashboard shows, with history already behind them --
    no utility_meter helper needed. Returns None if the schema has moved.
    """
    import sqlite3
    first = datetime.now().astimezone().replace(
        day=1, hour=0, minute=0, second=0, microsecond=0)
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
        try:
            row = con.execute(
                "SELECT MAX(sum) - MIN(sum) FROM statistics "
                "WHERE metadata_id = (SELECT id FROM statistics_meta "
                "                     WHERE statistic_id = ?) "
                "AND start_ts >= ?",
                (entity, first.timestamp())).fetchone()
        finally:
            con.close()
        return float(row[0]) if row and row[0] is not None else None
    except Exception:
        return None


def from_ha(base, token, *, db_path="/config/home-assistant_v2.db",
            total_entity="sensor.solar_total_production", panel=None):
    """Live Home Assistant: states over REST, curve from history, month from the DB."""
    states = {}
    for eid in ENT.values():
        try:
            s = _ha_get(base, token, f"/api/states/{eid}")
            states[eid] = {
                "state": s.get("state"),
                "last_changed": s.get("last_changed"),
                **(s.get("attributes") or {}),
            }
        except Exception:
            states[eid] = {"state": "unavailable"}

    return Data(
        states,
        pv_curve=_pv_curve(base, token, ENT["pv_now"]),
        month_kwh=_month_kwh(db_path, total_entity),
        panel=panel or {"battery_pct": 0, "rssi": 0},
        watch=[],
    )
