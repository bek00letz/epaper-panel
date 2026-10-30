"""Claude Code: its limit windows, and the day's tokens, sessions, cache share and streak.

**The limits** are what `/usage` shows. Claude Code hands them to a status line command with each
update, documented (code.claude.com/docs/en/statusline: `rate_limits.five_hour`, `.seven_day` and,
behind a Claude apps gateway, `.spend_limit`; `used_percentage` 0-100, `resets_at` in Unix seconds),
and keeps them nowhere on disk. So the reporter's status line (statusline.py) saves just that part to
`claude-limits.json` in the reporter's folder; this reads it. When the status line isn't set up,
there are no limits, only the extras.

**The extras** come from its session files, `<config>/projects/**/*.jsonl` (`CLAUDE_CONFIG_DIR`, else
`~/.claude`): each answer's `message.usage`. An answer is written as several lines with the same usage,
and a resumed session copies earlier ones, so each is counted once by its message id and request id.
Only files changed in the last LOOK_BACK days are read, each from where the last run stopped.
"""
from __future__ import annotations

import json
from pathlib import Path

from .. import shape
from . import _files

ID = "claude"
NAME = "Claude Code"
LIMITS_FILE = "claude-limits.json"
LOOK_BACK = 60                  # days of files read, so a streak can be up to this long
WINDOWS = {"five_hour": {"window": "session", "hours": 5}, "seven_day": {"window": "week"}}
PERIODS = {"daily": "day", "weekly": "week", "monthly": "month"}


def config_dir(ctx) -> Path:
    own = ctx.env.get("CLAUDE_CONFIG_DIR")
    return Path(own).expanduser() if own else ctx.home / ".claude"


def limits(ctx) -> list:
    """The windows the status line saved, in the report's shape."""
    try:
        saved = json.loads((ctx.state / LIMITS_FILE).read_text())
    except (OSError, ValueError):
        return []
    rl = saved.get("rate_limits") if isinstance(saved, dict) else None
    if not isinstance(rl, dict):
        return []
    out = []
    for key, base in list(WINDOWS.items()) + [("spend_limit", None)]:
        got = rl.get(key)
        if not isinstance(got, dict):
            continue
        read = shape.from_epoch((got.get("saved_at") or saved.get("saved_at")))
        pct = got.get("used_percentage")
        if read is None or not isinstance(pct, (int, float)) or isinstance(pct, bool):
            continue
        w = dict(base) if base else {"window": PERIODS.get(got.get("period"), "month"), "unit": "USD"}
        w["used"] = round(max(0.0, pct) / 100, 4)
        if base is None:
            for src, dst in (("used_usd", "amount"), ("limit_usd", "limit")):
                if isinstance(got.get(src), (int, float)) and not isinstance(got.get(src), bool):
                    w[dst] = got[src]
        resets = shape.from_epoch(got.get("resets_at"))
        if resets:
            w["resets_at"] = resets
        w["read_at"] = read
        out.append(w)
    return out


def _wanted(line: bytes) -> bool:
    return b'"assistant"' in line and b'"usage"' in line


def _entry(obj: dict):
    """(key, day, input, output, cache read, cache write, session) for an answer, or None."""
    if obj.get("type") != "assistant":
        return None
    msg = obj.get("message") if isinstance(obj.get("message"), dict) else {}
    use = msg.get("usage") if isinstance(msg.get("usage"), dict) else None
    at = _files.when(obj.get("timestamp"))
    if use is None or at is None:
        return None

    def n(k):
        v = use.get(k)
        return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0 else 0
    key = f"{msg.get('id') or ''}:{obj.get('requestId') or ''}"
    if key == ":":
        key = str(obj.get("uuid") or "")
    return [key, _files.local_day(at), n("input_tokens"), n("output_tokens"), n("cache_read_input_tokens"),
            n("cache_creation_input_tokens"), str(obj.get("sessionId") or "")]


def extras(ctx) -> dict:
    root = config_dir(ctx) / "projects"
    cache = ctx.cache("claude")
    files = cache.data.setdefault("files", {})
    paths = _files.recent(root.rglob("*.jsonl"), ctx.now, LOOK_BACK) if root.is_dir() else []
    keep = {str(p) for p in paths}
    for gone in [k for k in files if k not in keep]:
        del files[gone]                                 # older than the look back, or deleted
    for p in paths:
        cur = files.get(str(p)) or {}
        prev = cur.get("seen") or {}
        try:
            if p.stat().st_size < prev.get("size", 0):
                cur, prev = {}, {}                        # rewritten: read again from its start
        except OSError:
            continue
        got = []

        def handle(o, got=got):
            e = _entry(o)
            if e:
                got.append(e)
        seen = _files.scan(p, prev, _wanted, handle)
        files[str(p)] = {"seen": seen, "entries": list(cur.get("entries") or []) + got}
    cache.save()

    counted, days, today = set(), {}, ctx.now.astimezone().date().isoformat()
    for f in files.values():
        for key, day, inp, out, cr, cw, sid in f["entries"]:
            if key and key in counted:
                continue
            counted.add(key)
            d = days.setdefault(day, {"in": 0, "out": 0, "cr": 0, "cw": 0, "sessions": set()})
            d["in"] += inp
            d["out"] += out
            d["cr"] += cr
            d["cw"] += cw
            if sid:
                d["sessions"].add(sid)
    run = _files.streak(days, ctx.now.astimezone().date())
    t = days.get(today)
    out = {"day": today, "read_at": shape.iso(ctx.now.astimezone())}
    if t:
        total = t["in"] + t["out"] + t["cr"] + t["cw"]
        out["tokens"] = total
        out["sessions"] = len(t["sessions"])
        fed = t["in"] + t["cr"] + t["cw"]
        if fed:
            out["cache"] = round(t["cr"] / fed, 4)
    if run:
        out["streak_days"] = run
    return out if len(out) > 2 else {}


def read(ctx):
    cdir = config_dir(ctx)
    if not cdir.is_dir():
        return shape.Skipped(ID, NAME, "not_found")
    windows = limits(ctx)
    ex = extras(ctx)
    if not windows and not ex:
        return shape.Skipped(ID, NAME, "no_limits")
    return shape.Provider(ID, NAME, account=str(ctx.settings.get("account") or ""), windows=windows, extras=ex)

