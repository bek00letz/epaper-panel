"""The latest mail, drawn: who it's from, the subject under it, and when it came.

What it shows comes from sources/mail.py: the IMAP integration's count and the messages it
announced. The heading says how many are unread; a device that sleeps between updates says when
each came ("14:05") rather than how long ago, which would go stale while it sleeps.
"""
from __future__ import annotations

from . import hero, listing
from .needs_you import age_label
from .todo import now_in
from .words import say


def draw(img, d, box, el: dict, data, *, scale: float = 1.0) -> None:
    if not isinstance(data, dict):
        return
    if data.get("missing"):
        hero.message(d, box, say("mail.none" if data["missing"] == "integration" else "mail.unavailable",
                                 name=str(data.get("name") or say("mail.title"))))
        return
    title = str(el.get("title") or "").strip() or data.get("name") or say("mail.title")
    count = data.get("count")
    now = now_in(data.get("tz"))
    rows = [listing.Row(m.get("sender") or m.get("subject") or "", sub=m.get("subject") if m.get("sender") else "",
                        note=age_label(m.get("date"), now, bool(el.get("asleep"))))
            for m in data.get("messages") or [] if isinstance(m, dict)]
    more = int(data.get("more") or 0)
    if not rows and more:
        # Unread mail it hasn't heard about yet (it came before the page): the count says it.
        listing.draw(img, d, box, title=title, rows=[], count=say("mail.unread", count) if count else "",
                     empty=say("mail.unread_not_heard", more), scale=scale)
        return
    listing.draw(img, d, box, title=title, rows=rows, count=say("mail.unread", count) if count else "",
                 empty=say("mail.empty"), more=more, scale=scale)
