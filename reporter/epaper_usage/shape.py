"""The report's shape, built here and nowhere else (docs/ai-usage.md is the contract; the add-on's
usage.py reads it). Readers give a Provider; this turns them into the one report."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from . import APP, FORMAT, VERSION

KINDS = ("session", "day", "week", "month")
PROVIDER_RE = re.compile(r"^[a-z0-9_]{1,24}$")
SKIP_REASONS = ("not_found", "no_limits", "error")


def iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat(timespec="seconds")


def from_epoch(seconds) -> Optional[str]:
    try:
        return iso(datetime.fromtimestamp(float(seconds), timezone.utc))
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def window_for_minutes(minutes) -> Optional[dict]:
    """A window's kind from its length: 300 minutes is a 5-hour session, 10080 a week."""
    try:
        m = int(minutes)
    except (TypeError, ValueError):
        return None
    if m <= 0:
        return None
    if m == 1440:
        return {"window": "day"}
    if m == 10080:
        return {"window": "week"}
    if 40320 <= m <= 44640:
        return {"window": "month"}
    if m <= 7 * 1440:
        hours = m / 60
        return {"window": "session", "hours": int(hours) if hours.is_integer() else round(hours, 2)}
    return None


@dataclass
class Provider:
    provider: str
    name: str
    account: str = ""
    windows: list = field(default_factory=list)
    extras: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        out = {"provider": self.provider, "name": self.name, "account": self.account, "windows": self.windows}
        if self.extras:
            out["extras"] = self.extras
        return out


@dataclass
class Skipped:
    provider: str
    name: str
    reason: str


def _need(ok, what: str) -> None:
    if not ok:
        raise ValueError(what)


def _aware(text) -> bool:
    try:
        return datetime.fromisoformat(str(text)).tzinfo is not None
    except ValueError:
        return False


def check_window(w: dict) -> None:
    """A reader's window is the contract's, or ValueError says what's wrong (pinned by the tests)."""
    _need(w.get("window") in KINDS, f"window kind {w.get('window')!r}")
    _need(w["window"] != "session" or w.get("hours"), "a session needs its hours")
    _need("used" in w or "amount" in w, "a window needs used or an amount")
    _need("used" not in w or (isinstance(w["used"], (int, float)) and 0 <= w["used"] <= 100), "used is a fraction")
    _need(_aware(w.get("read_at")), "read_at needs its offset")
    _need("resets_at" not in w or _aware(w["resets_at"]), "resets_at needs its offset")


def report(found: list, skipped: list, platform: str, now: Optional[datetime] = None) -> dict:
    now = now or datetime.now(timezone.utc)
    provs = []
    for p in found:
        _need(PROVIDER_RE.match(p.provider), f"provider id {p.provider!r}")
        for w in p.windows:
            check_window(w)
        provs.append(p.as_dict())
    return {"format": FORMAT, "sent_at": iso(now.astimezone()),
            "reporter": {"app": APP, "version": VERSION, "platform": platform},
            "providers": provs,
            "skipped": [{"provider": s.provider, "name": s.name, "reason": s.reason} for s in skipped
                        if s.reason in SKIP_REASONS]}
