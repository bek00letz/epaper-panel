"""The latest mail, from Home Assistant's IMAP integration. The add-on never holds an email password.

Home Assistant's IMAP integration logs in to the mailbox itself. It gives two things:

- a sensor per mailbox whose state is how many messages match its search (unread, by default);
- an `imap_content` event for each new message, with its sender, subject and date.

The add-on reads the count like any sensor and hears the events (ha_events), only once a mail
page needs them. It keeps the last few it heard per mailbox in /data/mail.json (sender, subject,
date: never a message's text), so a restart doesn't empty the page. A message that came before
the add-on was listening shows from the next one on; the count is always right.

What the page lists: the newest messages it heard, as many as the count says (when three are
unread, the newest three), so a message read elsewhere drops off as the count goes down.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from email.utils import parseaddr

import examples
import config
import ha_events
import runtime
from config import HA_TOKEN
from sources import hass_read

SERVICE = "Home Assistant mail"
EVENT = "imap_content"
KEEP = 30               # per mailbox: more than a page ever shows
_heard: list[dict] | None = None


def _path():
    return config.DATA_DIR / "mail.json"


def _load() -> list[dict]:
    global _heard
    if _heard is None:
        try:
            got = json.loads(_path().read_text())
            _heard = [m for m in got if isinstance(m, dict)] if isinstance(got, list) else []
        except (OSError, ValueError):
            _heard = []
    return _heard


def _save(items: list[dict]) -> None:
    path = _path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(items))
        os.chmod(tmp, 0o600)                    # whose mail it is, so only the add-on reads it
        tmp.replace(path)
    except OSError as exc:
        print(f"mail: couldn't keep what Home Assistant said: {exc.strerror or exc}", flush=True)


def sender_name(raw) -> str:
    """"Ana Pop <ana@example.com>" as "Ana Pop"; an address alone as itself."""
    name, addr = parseaddr(str(raw or ""))
    return (name or addr or str(raw or "")).strip().strip('"')[:80]


_SPACE = re.compile(r"\s+")


def message_from(data: dict) -> dict | None:
    """An `imap_content` event's data as the page keeps it, or None. Only what's shown is kept."""
    if not isinstance(data, dict):
        return None
    subject = _SPACE.sub(" ", str(data.get("subject") or "")).strip()[:200]
    sender = sender_name(data.get("sender"))
    if not subject and not sender:
        return None
    when = data.get("date")
    try:
        when = datetime.fromisoformat(str(when)).isoformat() if when else ""
    except ValueError:
        when = ""
    return {"entry": str(data.get("entry_id") or ""), "uid": str(data.get("uid") or ""), "sender": sender,
            "subject": subject, "date": when or datetime.now(timezone.utc).isoformat()}


def remember(data: dict) -> None:
    """What the IMAP integration said about a new message, kept: newest first, each once, KEEP per mailbox."""
    msg = message_from(data)
    if msg is None:
        return
    items = [m for m in _load() if not (m.get("entry") == msg["entry"] and msg["uid"] and m.get("uid") == msg["uid"])]
    items.insert(0, msg)
    items.sort(key=lambda m: m.get("date") or "", reverse=True)
    kept, per = [], {}
    for m in items:
        per[m.get("entry")] = per.get(m.get("entry"), 0) + 1
        if per[m.get("entry")] <= KEEP:
            kept.append(m)
    global _heard
    _heard = kept
    _save(kept)


def listen() -> None:
    ha_events.listen(EVENT, remember, SERVICE)


def shown(heard: list[dict], entry: str, count: int | None, only_mailbox: bool) -> tuple[list[dict], int]:
    """(the messages a page lists, how many more it knows are there): the newest heard for this
    mailbox, as many as its count; the count beyond what was heard is the "and N more"."""
    mine = [m for m in heard if m.get("entry") == entry or (only_mailbox and not entry)] if entry or only_mailbox else []
    if count is None:
        return mine[:KEEP], 0
    return mine[:count], max(0, count - len(mine[:count]))


@runtime.live(60)
async def fetch_mail(session, entity: str = ""):
    """{"count", "name", "messages", "more"}; {"missing": "integration"} without the IMAP
    integration; {"missing": "unavailable"} when its sensor has no value (a wrong password there)."""
    if not HA_TOKEN:
        return examples.mail()
    listen()
    found = await hass_read.found_by(session, ("imap",))
    ids = hass_read.clean_ids([entity]) or found[:1]
    if not ids:
        return {"messages": [], "missing": "integration"}
    row = (await hass_read.states_of(session, ids))[0]
    if hass_read.no_value(row.get("state")):
        return {"messages": [], "missing": "unavailable", "name": row.get("name") or ""}
    try:
        count = int(float(row["state"]))
    except (TypeError, ValueError):
        count = None
    messages, more = shown(_load(), row.get("entry") or "", count, only_mailbox=len(found) <= 1)
    return {"count": count, "name": row.get("name") or "", "messages": messages, "more": more}
