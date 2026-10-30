"""What the readers share: reading a JSON-lines file a piece at a time, and the day of a time.

The apps' session files only grow, and there can be gigabytes of them, so each is read from where
the last run stopped (`scan`): a run every 5 minutes reads only what's new. A file that got
smaller was rewritten, and is read again from its start.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterable, Optional

CHUNK = 1 << 20


def when(text) -> Optional[datetime]:
    """An ISO 8601 time as the apps write it ("2026-10-30T12:34:56.789Z"), any number of decimals."""
    if not isinstance(text, str) or not text:
        return None
    s = text.strip().replace("Z", "+00:00")
    if "." in s:                                   # Python 3.9 takes 3 or 6 decimals only
        head, _, rest = s.partition(".")
        n = 0
        while n < len(rest) and rest[n].isdigit():
            n += 1
        digits, tail = rest[:n], rest[n:]
        s = f"{head}.{(digits + '000000')[:6]}{tail}"
    try:
        got = datetime.fromisoformat(s)
    except ValueError:
        return None
    return got if got.tzinfo else got.replace(tzinfo=timezone.utc)


def local_day(dt: datetime) -> str:
    return dt.astimezone().date().isoformat()


def recent(paths: Iterable[Path], now: datetime, days: int) -> list:
    """The files changed in the last `days`, newest first."""
    edge = (now - timedelta(days=days)).timestamp()
    out = []
    for p in paths:
        try:
            m = p.stat().st_mtime
        except OSError:
            continue
        if m >= edge:
            out.append((m, p))
    return [p for _, p in sorted(out, key=lambda x: x[0], reverse=True)]


def scan(path: Path, seen: dict, wanted: Callable[[bytes], bool], handle: Callable[[dict], None]) -> dict:
    """Read a JSON-lines file from where `seen` says the last run stopped, calling `handle` with each
    new line that `wanted` (a quick look at its bytes) says is worth parsing. Returns where it stopped,
    to keep for next time (the same dict when nothing changed). A line still being written (no newline
    yet) waits for the next run. A file that got smaller is read from its start: its reader forgets
    what it had read of it first."""
    try:
        st = path.stat()
    except OSError:
        return seen
    start = int(seen.get("offset", 0)) if seen.get("size", 0) <= st.st_size else 0
    if start == st.st_size and seen.get("mtime") == st.st_mtime:
        return seen
    with open(path, "rb") as f:
        f.seek(start)
        pos, rest = start, b""
        while True:
            chunk = f.read(CHUNK)
            if not chunk:
                break
            lines = (rest + chunk).split(b"\n")
            rest = lines.pop()
            for line in lines:
                pos += len(line) + 1
                if line and wanted(line):
                    try:
                        obj = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(obj, dict):
                        handle(obj)
    return {"offset": pos, "size": st.st_size, "mtime": st.st_mtime}


def streak(days: Iterable[str], today: date) -> int:
    """Days in a row with any use, ending today or, if nothing yet today, yesterday."""
    have = set(days)
    d = today if today.isoformat() in have else today - timedelta(days=1)
    n = 0
    while d.isoformat() in have:
        n += 1
        d -= timedelta(days=1)
    return n
