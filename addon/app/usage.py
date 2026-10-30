"""AI usage: the one shape every provider's numbers come in, kept and read back (docs/ai-usage.md).

A reporter on someone's computer (reporter/, paired through reporters.py) sends a report: per
provider, its limit windows (how much is used, when it resets, when it was read) and a few
extras for the day. This module is the contract's add-on half:

  clean      a report -> its providers in the add-on's form, and what was left out, plainly;
  save/load  each reporter's newest report, on disk, so a restart forgets nothing;
  current    every reporter's providers merged: the newest reading of each window wins, the
             day's extras add up (several computers, one account);
  window_now a window as it stands now: one that has reset since it was read is empty;
  publish    the same numbers as Home Assistant sensors (entities.publish_computed calls it).

Nothing here names a provider: a new reader in the reporter needs nothing here.
"""
from __future__ import annotations

import json
import math
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import config

FORMAT = 1
MAX_BYTES = 64 * 1024
MOST_PROVIDERS = 8
MOST_WINDOWS = 8
KINDS = ("session", "day", "week", "month")
PROVIDER_RE = re.compile(r"^[a-z0-9_]{1,24}$")
SKIP_REASONS = ("not_found", "no_limits", "error")
# A report older than this is let go, with its sensors.
KEEP_FOR = timedelta(days=7)
# A reporter that hasn't reported for this long is said to be quiet on the page (it reports every 5 minutes).
QUIET_AFTER = timedelta(minutes=20)
CURRENCY_RE = re.compile(r"^[A-Z]{3}$")


# ---------------------------------------------------------------- reading a report

def _text(value, most: int) -> str:
    s = "" if value is None else str(value)
    s = re.sub(r"[\x00-\x1f\x7f]", "", s).strip()
    return s[:most]


def _number(value) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        got = float(value)
    except (TypeError, ValueError):
        return None
    return got if math.isfinite(got) and abs(got) < 1e15 else None


def _when(value) -> datetime | None:
    """An ISO 8601 time with its offset; one without is refused (it could be any zone)."""
    if not isinstance(value, str):
        return None
    try:
        got = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return got if got.tzinfo else None


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def slug(text: str) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", str(text or "").lower())).strip("_")[:24]


def _window(raw, who: str) -> tuple[dict | None, str]:
    """One window in the add-on's form, or (None, why it was left out)."""
    if not isinstance(raw, dict):
        return None, f"{who}: a window isn't an object"
    kind = raw.get("window")
    if kind not in KINDS:
        return None, f"{who}: window {_text(kind, 20)!r} isn't one of {', '.join(KINDS)}"
    out = {"window": kind}
    what = f"{who} {kind}"
    if kind == "session":
        hours = _number(raw.get("hours"))
        if hours is None or not 0 < hours <= 24 * 7:
            return None, f"{what}: a session needs its hours"
        out["hours"] = int(hours) if float(hours).is_integer() else round(hours, 2)
    scope = _text(raw.get("scope"), 24)
    if scope:
        out["scope"] = scope
    used, amount, limit = _number(raw.get("used")), _number(raw.get("amount")), _number(raw.get("limit"))
    if raw.get("used") is not None and used is None:
        return None, f"{what}: used isn't a number"
    if used is not None and not 0 <= used <= 100:
        return None, f"{what}: used is a fraction, 0 to 1 (above 1 when over)"
    if amount is not None:
        if amount < 0 or (limit is not None and limit <= 0):
            return None, f"{what}: an amount and its limit are above 0"
        out["amount"] = amount
        if limit is not None:
            out["limit"] = limit
        unit = _text(raw.get("unit"), 12)
        if unit:
            out["unit"] = unit
    if used is None and amount is not None and limit is not None:
        used = amount / limit
    if used is None and amount is None:
        return None, f"{what}: it needs used, or an amount"
    if used is not None:
        out["used"] = round(used, 4)
    read = _when(raw.get("read_at"))
    if read is None:
        return None, f"{what}: read_at is needed, with its offset"
    out["read_at"] = _iso(read)
    if raw.get("resets_at") is not None:
        resets = _when(raw.get("resets_at"))
        if resets is None:
            return None, f"{what}: resets_at needs its offset"
        out["resets_at"] = _iso(resets)
    return out, ""


def _extras(raw) -> dict:
    if not isinstance(raw, dict):
        return {}
    day = raw.get("day")
    try:
        day = date.fromisoformat(day).isoformat() if isinstance(day, str) else None
    except ValueError:
        day = None
    if day is None:
        return {}
    out = {"day": day}
    read = _when(raw.get("read_at"))
    if read is not None:
        out["read_at"] = _iso(read)
    for key in ("tokens", "sessions", "streak_days"):
        n = _number(raw.get(key))
        if n is not None and n >= 0:
            out[key] = int(n)
    cache = _number(raw.get("cache"))
    if cache is not None and 0 <= cache <= 1:
        out["cache"] = round(cache, 4)
    cost = raw.get("cost")
    if isinstance(cost, dict):
        amount, unit = _number(cost.get("amount")), _text(cost.get("unit"), 12)
        if amount is not None and amount >= 0 and unit:
            out["cost"] = {"amount": round(amount, 4), "unit": unit}
    return out if len(out) > 1 or "streak_days" in out else {}


def clean(body) -> tuple[dict, list[str]]:
    """A report as the add-on keeps it: {"providers": [...], "skipped": [...], "platform"}, and what
    was left out, in plain words. Raises ValueError for something that isn't a report at all."""
    if not isinstance(body, dict):
        raise ValueError("A report is a JSON object.")
    if body.get("format") != FORMAT:
        raise ValueError(f"This add-on reads report format {FORMAT}. Update the reporter, or the add-on.")
    provs = body.get("providers")
    if not isinstance(provs, list):
        raise ValueError("A report needs its providers, a list (it may be empty).")
    dropped, out, seen = [], [], set()
    for raw in provs[:MOST_PROVIDERS]:
        if not isinstance(raw, dict) or not PROVIDER_RE.match(str(raw.get("provider") or "")):
            dropped.append("a provider without an id of lowercase letters, digits and _")
            continue
        pid = raw["provider"]
        name = _text(raw.get("name"), 40) or pid
        account = _text(raw.get("account"), 40)
        if "@" in account:
            account = ""                                  # never an email address on a screen or a sensor
        if (pid, account) in seen:
            dropped.append(f"{pid}: sent twice")
            continue
        seen.add((pid, account))
        windows, keys = [], set()
        for w in (raw.get("windows") or [])[:MOST_WINDOWS] if isinstance(raw.get("windows"), list) else []:
            got, why = _window(w, pid)
            if got is None:
                dropped.append(why)
                continue
            if window_key(got) in keys:
                dropped.append(f"{pid}: {window_slug(got)} sent twice")
                continue
            keys.add(window_key(got))
            windows.append(got)
        out.append({"provider": pid, "name": name, "account": account, "windows": windows,
                    "extras": _extras(raw.get("extras"))})
    if len(provs) > MOST_PROVIDERS:
        dropped.append(f"providers after the first {MOST_PROVIDERS}")
    skipped = []
    for s in body.get("skipped") or [] if isinstance(body.get("skipped"), list) else []:
        if isinstance(s, dict) and PROVIDER_RE.match(str(s.get("provider") or "")) and s.get("reason") in SKIP_REASONS:
            skipped.append({"provider": s["provider"], "name": _text(s.get("name"), 40) or s["provider"],
                            "reason": s["reason"]})
    rep = body.get("reporter") if isinstance(body.get("reporter"), dict) else {}
    return {"providers": out, "skipped": skipped[:MOST_PROVIDERS],
            "platform": slug(rep.get("platform")) or "", "version": _text(rep.get("version"), 16)}, dropped


def is_spend(w: dict) -> bool:
    """A window counted in money: its unit is a currency (ISO 4217)."""
    return bool(CURRENCY_RE.match(str(w.get("unit") or "")))


def window_key(w: dict) -> tuple:
    return (w["window"], w.get("hours"), w.get("scope", "").lower(), is_spend(w))


def window_slug(w: dict) -> str:
    """The window's part of its sensor's name: session_5h, week, week_sonnet."""
    base = f"session_{slug(str(w.get('hours')).replace('.', '_'))}h" if w["window"] == "session" else w["window"]
    return base + ("_spend" if is_spend(w) else "") + (f"_{slug(w['scope'])}" if w.get("scope") else "")


# ---------------------------------------------------------------- kept on disk, per reporter

def _dir() -> Path:
    return config.DATA_DIR / "usage"


def _path(reporter_id: str) -> Path:
    if not re.fullmatch(r"[0-9]{1,6}", str(reporter_id)):
        raise KeyError(f"no reporter {str(reporter_id)[:12]!r}")
    return _dir() / f"{reporter_id}.json"


def save(reporter_id: str, report: dict, now: datetime | None = None) -> None:
    now = now or datetime.now(timezone.utc)
    path = _path(reporter_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps({**report, "received_at": _iso(now)}))
    tmp.replace(path)


def load(reporter_id: str) -> dict | None:
    try:
        got = json.loads(_path(reporter_id).read_text())
    except (OSError, ValueError, KeyError):
        return None
    return got if isinstance(got, dict) else None


def forget(reporter_id: str) -> None:
    try:
        _path(reporter_id).unlink()
    except (OSError, KeyError):
        pass


# ---------------------------------------------------------------- now

def window_now(w: dict, now: datetime) -> dict:
    """The window as it stands now. One that has reset since it was read is empty (`reset`: when);
    a week or a day resets again at the same time, so its next reset is known."""
    resets = _when(w.get("resets_at"))
    if resets is None or resets > now:
        return dict(w)
    out = {k: v for k, v in w.items() if k not in ("used", "amount", "resets_at")}
    out["reset"] = _iso(resets)
    if "used" in w or "limit" in w:
        out["used"] = 0.0
    if "amount" in w:
        out["amount"] = 0.0
    step = {"day": timedelta(days=1), "week": timedelta(days=7)}.get(w["window"])
    if step:
        nxt = resets
        while nxt <= now:
            nxt += step
        out["resets_at"] = _iso(nxt)
    return out


def _add_extras(a: dict, b: dict) -> dict:
    """Two computers' extras for the same day: counts add up, the streak is the longest,
    the cache share is weighted by tokens."""
    if not a:
        return dict(b)
    if not b:
        return dict(a)
    if a.get("day") != b.get("day"):
        return dict(a if a.get("day", "") > b.get("day", "") else b)
    out = {"day": a["day"], "read_at": max(a.get("read_at", ""), b.get("read_at", ""))}
    for key in ("tokens", "sessions"):
        if key in a or key in b:
            out[key] = a.get(key, 0) + b.get(key, 0)
    if "streak_days" in a or "streak_days" in b:
        out["streak_days"] = max(a.get("streak_days", 0), b.get("streak_days", 0))
    if "cache" in a or "cache" in b:
        wa, wb = (a.get("tokens", 0) if "cache" in a else 0), (b.get("tokens", 0) if "cache" in b else 0)
        if wa + wb:
            out["cache"] = round((a.get("cache", 0) * wa + b.get("cache", 0) * wb) / (wa + wb), 4)
        else:
            out["cache"] = a.get("cache", b.get("cache"))
    ca, cb = a.get("cost"), b.get("cost")
    if ca and cb and ca["unit"] == cb["unit"]:
        out["cost"] = {"amount": round(ca["amount"] + cb["amount"], 4), "unit": ca["unit"]}
    elif ca or cb:
        out["cost"] = ca or cb
    return {k: v for k, v in out.items() if v not in ("", None)}


def merge(reports: list[tuple[dict, dict]]) -> list[dict]:
    """Every reporter's providers as one list: (reporter, report) pairs -> providers, each with its
    windows (the newest reading of each) and its extras added up, in the order first reported."""
    by: dict[tuple, dict] = {}
    for rep, report in reports:
        for p in report.get("providers") or []:
            key = (p["provider"], p.get("account", ""))
            cur = by.setdefault(key, {"provider": p["provider"], "name": p["name"], "account": p.get("account", ""),
                                      "windows": {}, "extras": {}, "reporters": []})
            if rep["id"] not in cur["reporters"]:
                cur["reporters"].append(rep["id"])
            for w in p.get("windows") or []:
                k = window_key(w)
                if k not in cur["windows"] or w["read_at"] > cur["windows"][k]["read_at"]:
                    cur["windows"][k] = w
            cur["extras"] = _add_extras(cur["extras"], p.get("extras") or {})
    order = {"session": 0, "day": 1, "week": 2, "month": 3}
    out = []
    for p in by.values():
        ws = sorted(p["windows"].values(), key=lambda w: ("amount" in w and "used" not in w, order[w["window"]],
                                                          w.get("hours") or 0, w.get("scope", "")))
        out.append({**p, "windows": ws})
    return out


def current(reporters: list[dict], now: datetime | None = None) -> dict:
    """What the page and the sensors show: {"providers", "reporters": [{id, name, platform, heard_at, quiet,
    skipped}]}, reports older than a week let go."""
    now = now or datetime.now(timezone.utc)
    pairs, heard = [], []
    for rep in reporters:
        report = load(rep["id"])
        at = _when((report or {}).get("received_at"))
        if report is not None and at is not None and now - at > KEEP_FOR:
            report, at = None, at
        if report is not None:
            pairs.append((rep, report))
        heard.append({"id": rep["id"], "name": rep.get("name") or "", "platform": rep.get("platform") or
                      (report or {}).get("platform") or "", "heard_at": _iso(at) if at else "",
                      "quiet": bool(at and now - at > QUIET_AFTER), "skipped": (report or {}).get("skipped") or []})
    provs = merge(pairs)
    for p in provs:
        p["windows"] = [window_now(w, now) for w in p["windows"]]
    return {"providers": provs, "reporters": heard}


# ---------------------------------------------------------------- in Home Assistant

def _today(home_tz: str | None, now: datetime) -> date:
    from zoneinfo import ZoneInfo
    try:
        return now.astimezone(ZoneInfo(home_tz)).date() if home_tz else now.astimezone().date()
    except Exception:
        return now.astimezone().date()


def extras_now(extras: dict, home_tz: str | None, now: datetime) -> dict:
    """The extras that are still today's (Home Assistant's today); a streak ending yesterday still counts."""
    day = extras.get("day")
    if not day:
        return {}
    today = _today(home_tz, now)
    if day == today.isoformat():
        return dict(extras)
    if day == (today - timedelta(days=1)).isoformat() and extras.get("streak_days"):
        return {"day": day, "streak_days": extras["streak_days"]}
    return {}


def base_id(p: dict) -> str:
    return f"sensor.epaper_ai_{p['provider']}" + (f"_{slug(p['account'])}" if p.get("account") and slug(p["account"]) else "")


def sensors(view: dict, home_tz: str | None, now: datetime | None = None) -> list[tuple[str, object, dict]]:
    """Every sensor the usage makes: (entity id, state, attributes), the contract's names."""
    now = now or datetime.now(timezone.utc)
    names = {r["id"]: r.get("name") or r["id"] for r in view.get("reporters") or []}
    out = []
    for p in view.get("providers") or []:
        base = base_id(p)
        who = {"provider": p["provider"], "provider_name": p["name"], "account": p.get("account", ""),
               "reporter": ", ".join(names.get(r, r) for r in p.get("reporters") or [])}
        label = p["name"] + (f" ({p['account']})" if p.get("account") else "")
        for w in p["windows"]:
            words = window_words_en(w)
            attrs = {**who, **{k: w[k] for k in ("window", "hours", "scope", "used", "amount", "limit", "unit",
                                                   "resets_at", "read_at") if k in w},
                     "reset": "reset" in w, "friendly_name": f"AI {label} {words}", "icon": "mdi:gauge"}
            if "used" in w:
                state, attrs["unit_of_measurement"] = round(w["used"] * 100, 1), "%"
            else:
                state = round(w["amount"], 2)
                if w.get("unit"):
                    attrs["unit_of_measurement"] = w["unit"]
            out.append((f"{base}_{window_slug(w)}", state, attrs))
        ex = extras_now(p.get("extras") or {}, home_tz, now)
        for key, suffix, name, icon, unit in (("tokens", "tokens_today", "tokens today", "mdi:counter", "tokens"),
                                              ("sessions", "sessions_today", "sessions today", "mdi:forum-outline", ""),
                                              ("cache", "cache_today", "cache today", "mdi:cached", "%"),
                                              ("streak_days", "streak", "streak", "mdi:fire", "days")):
            if key in ex:
                val = round(ex[key] * 100, 1) if key == "cache" else ex[key]
                out.append((f"{base}_{suffix}", val, {**who, "day": ex["day"], "friendly_name": f"AI {label} {name}",
                                                      "icon": icon, **({"unit_of_measurement": unit} if unit else {})}))
        if "cost" in ex:
            out.append((f"{base}_cost_today", ex["cost"]["amount"], {**who, "day": ex["day"], "friendly_name": f"AI {label} cost today",
                                                                     "icon": "mdi:cash", "unit_of_measurement": ex["cost"]["unit"]}))
    for r in view.get("reporters") or []:
        out.append((f"sensor.epaper_ai_reporter_{r['id']}", r["heard_at"] or None,
                    {"friendly_name": f"AI usage reporter {r.get('name') or r['id']}", "device_class": "timestamp",
                     "icon": "mdi:laptop", "platform": r.get("platform") or "", "quiet": r["quiet"]}))
    return out


def window_words_en(w: dict) -> str:
    """A window's name in English, for a sensor's name (Home Assistant names its own entities)."""
    base = (f"{w['hours']:g}-hour session" if w["window"] == "session"
            else {"day": "daily", "week": "weekly", "month": "monthly"}[w["window"]])
    if is_spend(w):
        base += " spend"
    return base + (f" {w['scope']}" if w.get("scope") else "")


async def publish(session, reporters: list[dict], home_tz: str | None) -> set[str]:
    """The usage as Home Assistant sensors; returns their ids, so none is withdrawn while it's reported."""
    from entities import publish_entity                 # entities imports a lot; it calls this
    wanted = set()
    for eid, state, attrs in sensors(current(reporters), home_tz):
        await publish_entity(session, eid, state, attrs)
        wanted.add(eid)
    return wanted


# ---------------------------------------------------------------- for a page

def wanted(el: dict) -> list[str]:
    """The providers an element asks for ("Providers": names or ids, by commas); [] is every one."""
    return [x.strip().lower() for x in str(el.get("providers") or "").split(",") if x.strip()]


def for_page(view: dict, el: dict, home_tz: str | None, now: datetime | None = None) -> dict:
    """What an AI usage element draws: the providers it asks for, their extras still today's, who reports."""
    now = now or datetime.now(timezone.utc)
    want = wanted(el)
    provs = [p for p in view.get("providers") or []
             if not want or p["provider"] in want or p["name"].lower() in want]
    provs = [{**p, "extras": extras_now(p.get("extras") or {}, home_tz, now)} for p in provs]
    out = {"providers": provs, "reporters": view.get("reporters") or [], "tz": home_tz}
    if want and not provs:
        out["filtered"] = [x for x in str(el.get("providers")).split(",") if x.strip()]
    return out


def example(now: datetime) -> dict:
    """The page's example (thumbnails, the editor's preview without a reporter): two providers, as a
    reporter on a Mac would send them. Never anyone's real numbers."""
    def at(**kw):
        return _iso(now + timedelta(**kw))
    read = _iso(now - timedelta(minutes=3))
    day = now.astimezone().date().isoformat()
    return {"providers": [
        {"provider": "claude", "name": "Claude Code", "account": "", "reporters": ["1"],
         "windows": [{"window": "session", "hours": 5, "used": 0.42, "resets_at": at(hours=2, minutes=10), "read_at": read},
                     {"window": "week", "used": 0.18, "resets_at": at(days=4, hours=19), "read_at": read}],
         "extras": {"day": day, "tokens": 1_240_000, "sessions": 3, "streak_days": 12, "cache": 0.91}},
        {"provider": "codex", "name": "Codex", "account": "Plus", "reporters": ["1"],
         "windows": [{"window": "session", "hours": 5, "used": 0.07, "resets_at": at(hours=4, minutes=5), "read_at": read},
                     {"window": "week", "used": 0.31, "resets_at": at(days=2, hours=3), "read_at": read}],
         "extras": {"day": day, "tokens": 86_000, "sessions": 1}}],
        "reporters": [{"id": "1", "name": "", "platform": "macos", "heard_at": read, "quiet": False, "skipped": []}],
        "tz": None}
