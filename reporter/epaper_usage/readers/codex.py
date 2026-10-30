"""Codex (OpenAI's Codex CLI, and the Codex app, which share its folder): its limit windows and the day's tokens.

Its session files, `<home>/sessions/YYYY/MM/DD/rollout-*.jsonl` (`CODEX_HOME`, else `~/.codex`),
record with each answer a `token_count` event: `rate_limits`, the windows its server sent
(`primary` and `secondary`, each `used_percent`, `window_minutes` and `resets_at` in Unix seconds, or
`resets_in_seconds` in older versions; `limit_id`, `limit_name` and `plan_type`), and `info`, the
session's tokens so far (`total_token_usage`: `input_tokens` with `cached_input_tokens` in it,
`output_tokens`). Read as they are: no key, no network.

The newest reading of each limit wins. "codex" is the plan's own limit; another one (a model's) is
reported only when Codex names it (`limit_name`), since its id is a code name.

Tokens are counted per session: the day's use is its running total at the day's end less at the
end of the day before, so a session that runs past midnight is split where it should be.
"""
from __future__ import annotations

from pathlib import Path

from .. import shape
from . import _files

ID = "codex"
NAME = "Codex"
LOOK_BACK = 60
MAIN = "codex"


def codex_home(ctx) -> Path:
    own = ctx.env.get("CODEX_HOME")
    return Path(own).expanduser() if own else ctx.home / ".codex"


def _wanted(line: bytes) -> bool:
    return b'"token_count"' in line


def _windows(rl: dict, read_at: str, at) -> list:
    out = []
    for slot in ("primary", "secondary"):
        got = rl.get(slot)
        if not isinstance(got, dict):
            continue
        pct = got.get("used_percent")
        base = shape.window_for_minutes(got.get("window_minutes"))
        if base is None or not isinstance(pct, (int, float)) or isinstance(pct, bool):
            continue
        w = {**base, "used": round(max(0.0, float(pct)) / 100, 4)}
        resets = shape.from_epoch(got.get("resets_at"))
        if resets is None and isinstance(got.get("resets_in_seconds"), (int, float)):
            resets = shape.from_epoch(at.timestamp() + got["resets_in_seconds"])
        if resets:
            w["resets_at"] = resets
        w["read_at"] = read_at
        out.append(w)
    return out


def read(ctx):
    root = codex_home(ctx)
    sessions = root / "sessions"
    if not root.is_dir():
        return shape.Skipped(ID, NAME, "not_found")
    cache = ctx.cache("codex")
    files = cache.data.setdefault("files", {})
    paths = _files.recent(sessions.rglob("*.jsonl"), ctx.now, LOOK_BACK) if sessions.is_dir() else []
    keep = {str(p) for p in paths}
    for gone in [k for k in files if k not in keep]:
        del files[gone]
    for p in paths:
        cur = files.get(str(p)) or {}
        prev = cur.get("seen") or {}
        try:
            if p.stat().st_size < prev.get("size", 0):
                cur, prev = {}, {}                        # rewritten: read again from its start
        except OSError:
            continue
        state = {"limits": dict(cur.get("limits") or {}), "days": dict(cur.get("days") or {}), "plan": cur.get("plan") or ""}

        def handle(o, state=state):
            pay = o.get("payload") if isinstance(o.get("payload"), dict) else {}
            if pay.get("type") != "token_count":
                return
            at = _files.when(o.get("timestamp"))
            if at is None:
                return
            rl = pay.get("rate_limits")
            if isinstance(rl, dict):
                lid = str(rl.get("limit_id") or MAIN)
                old = state["limits"].get(lid)
                if old is None or old[0] <= shape.iso(at):
                    state["limits"][lid] = [shape.iso(at), rl]
                if rl.get("plan_type"):
                    state["plan"] = str(rl["plan_type"])
            info = pay.get("info")
            tot = info.get("total_token_usage") if isinstance(info, dict) else None
            if isinstance(tot, dict):
                state["days"][_files.local_day(at)] = {k: int(tot.get(k) or 0) for k in
                                                       ("input_tokens", "cached_input_tokens", "output_tokens")}
        seen = _files.scan(p, prev, _wanted, handle)
        files[str(p)] = {"seen": seen, **state}
    cache.save()

    # The newest reading of each limit, from every file.
    newest, plan = {}, ""
    for f in files.values():
        for lid, (at, rl) in (f.get("limits") or {}).items():
            if lid not in newest or newest[lid][0] < at:
                newest[lid] = (at, rl)
                plan = f.get("plan") or plan
    windows = []
    for lid, (at, rl) in sorted(newest.items(), key=lambda kv: kv[0] != MAIN):
        scope = "" if lid == MAIN else str(rl.get("limit_name") or "").strip()
        if lid != MAIN and not scope:
            continue                                      # a code name, not something to show
        for w in _windows(rl, at, _files.when(at)):
            if scope:
                w["scope"] = scope[:24]
            windows.append(w)

    today = ctx.now.astimezone().date()
    day = today.isoformat()
    used_days, tokens, inp, cached, sessions_today = set(), 0, 0, 0, 0
    for f in files.values():
        days = f.get("days") or {}
        used_days |= set(days)
        if day in days:
            before = [d for d in days if d < day]
            base = days[max(before)] if before else {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0}
            t = days[day]
            d_in = max(0, t["input_tokens"] - base["input_tokens"])
            d_cached = max(0, t["cached_input_tokens"] - base["cached_input_tokens"])
            d_out = max(0, t["output_tokens"] - base["output_tokens"])
            tokens += d_in + d_out
            inp += d_in
            cached += d_cached
            sessions_today += 1
    extras = {"day": day, "read_at": shape.iso(ctx.now.astimezone())}
    if sessions_today:
        extras.update(tokens=tokens, sessions=sessions_today)
        if inp:
            extras["cache"] = round(min(1.0, cached / inp), 4)
    run = _files.streak(used_days, today)
    if run:
        extras["streak_days"] = run
    if len(extras) <= 2:
        extras = {}
    if not windows and not extras:
        return shape.Skipped(ID, NAME, "no_limits")
    account = str(ctx.settings.get("account") or "") or (plan.capitalize() if plan else "")
    return shape.Provider(ID, NAME, account=account, windows=windows, extras=extras)
