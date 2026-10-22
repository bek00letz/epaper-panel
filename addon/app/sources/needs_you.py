"""What needs you in Home Assistant: its notifications, the updates waiting, and Repairs.

Three readings, each in the background (live_data), so a render never waits
on Home Assistant:

- notifications: the persistent notifications behind its bell, newest first,
  over the websocket (`persistent_notification/get`; they haven't been
  entities since 2023.6). Dismissing one there clears it at the next fetch.
- updates: every `update.*` entity that's on (a skipped version is off, as in
  Home Assistant), grouped the way Settings shows them: Home Assistant itself,
  add-ons, integrations (HACS), devices. One template, so it's one request.
- repairs: how many Repairs issues are open (`repairs/list_issues`), not
  counting the ones you ignored.

A failure raises, so the last reading stays on the page, and reports as its
own service (health), so the problem sensor in Home Assistant says so.
Everything stays between the add-on and Home Assistant; the device only ever
gets the picture.
"""
from __future__ import annotations

import json
import re

import health
import runtime
from config import HA_TOKEN
from ha import ha_template

NOTIFICATIONS = "Home Assistant notifications"
UPDATES = "Home Assistant updates"
REPAIRS = "Home Assistant repairs"

# What each count is called, in the order a badge offers them (widgets.py), and the add-on's own
# sensor for it: what a page's "only when" or an alert reads (entities.publish_needs_you).
COUNTS = ("updates", "notifications", "repairs", "all")
SENSOR = {"notifications": "sensor.epaper_notifications", "updates": "sensor.epaper_updates",
          "repairs": "sensor.epaper_repairs"}

# The groups an update falls in, in the order they're listed, and what each is called.
GROUPS = (("home_assistant", "Home Assistant"), ("addons", "Add-ons"),
          ("integrations", "Integrations"), ("devices", "Devices"))
GROUP_NAMES = dict(GROUPS)
# Home Assistant's own three, by the titles Home Assistant gives them (its frontend sorts them so too).
HOME_ASSISTANT = ("Home Assistant Core", "Home Assistant Operating System", "Home Assistant Supervisor")

MESSAGE_MOST = 600          # a notification's message is cut here: a page never shows more


# ------------------------------------------------------------------ notifications

_LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
_MARKS = re.compile(r"(\*\*|__|\*|`|~~)")
_HEADING = re.compile(r"^\s{0,3}(#{1,6}\s+|>\s?|[-*+]\s+)", re.M)
_TAG = re.compile(r"<[^>]+>")


def plain(markdown: str) -> str:
    """A notification's Markdown as the words it reads as: links as their text, no marks or tags,
    lines joined. Home Assistant writes notifications in Markdown."""
    text = _TAG.sub("", _LINK.sub(r"\1", str(markdown or "")))
    text = _MARKS.sub("", _HEADING.sub("", text))
    return re.sub(r"\s+", " ", text).strip()


def notifications_from(result) -> list[dict]:
    """`persistent_notification/get`'s answer as the page reads it, newest first:
    [{"id", "title", "message", "created"}]. A notification without a title is titled by its message."""
    out = []
    for n in result if isinstance(result, list) else []:
        if not isinstance(n, dict):
            continue
        title, message = plain(n.get("title")), plain(n.get("message"))
        if not title and not message:
            continue
        if not title:
            title, message = message, ""
        out.append({"id": str(n.get("notification_id") or ""), "title": title[:200],
                    "message": message[:MESSAGE_MOST], "created": str(n.get("created_at") or "")})
    out.sort(key=lambda n: n["created"], reverse=True)
    return out


@runtime.live(60)
async def fetch_notifications(session):
    if not HA_TOKEN:
        import examples
        return examples.notifications()
    try:
        got = notifications_from(await runtime.HASS.ws({"type": "persistent_notification/get"}))
    except Exception as exc:
        health.fail(NOTIFICATIONS, exc)
        raise
    health.ok(NOTIFICATIONS)
    return got


# ------------------------------------------------------------------ updates

# Every update that's on, with what says where it's from: one request, answered by Home Assistant.
UPDATES_TEMPLATE = """
{%- set hassio = integration_entities('hassio') -%}
{%- set hacs = integration_entities('hacs') -%}
{%- set ns = namespace(out=[]) -%}
{%- for s in states.update | selectattr('state', 'eq', 'on') -%}
{%- set dev = device_id(s.entity_id) -%}
{%- set ns.out = ns.out + [{
  'entity': s.entity_id, 'name': s.name, 'title': s.attributes.get('title'),
  'device': (device_attr(dev, 'name_by_user') or device_attr(dev, 'name')) if dev else none,
  'version': s.attributes.get('latest_version'), 'class': s.attributes.get('device_class'),
  'busy': s.attributes.get('in_progress'),
  'from': 'hassio' if s.entity_id in hassio else ('hacs' if s.entity_id in hacs else '')}] -%}
{%- endfor -%}
{{ ns.out | to_json }}
"""


def group_of(row: dict) -> str:
    if row.get("from") == "hassio":
        return "home_assistant" if row.get("title") in HOME_ASSISTANT else "addons"
    if row.get("from") == "hacs":
        return "integrations"
    return "devices"          # device firmware, and a device's own software (a NAS, a camera)


def name_of(row: dict, group: str) -> str:
    """What an update is called: Home Assistant's own title, an add-on's name, the device or the
    integration it's for ("Kitchen light", not "Kitchen light Firmware"), or else Home Assistant's own name."""
    title = str(row.get("title") or "").strip()
    if group in ("home_assistant", "addons") and title:
        return title
    device = str(row.get("device") or "").strip()
    return device or title or str(row.get("name") or "").strip() or str(row.get("entity") or "")


def short_name(item: dict) -> str:
    """Its name under its group's heading: "Core" under Home Assistant."""
    name = item["name"]
    if item["group"] == "home_assistant" and name.startswith("Home Assistant "):
        return name[len("Home Assistant "):]
    return name


def updates_from(rows) -> list[dict]:
    """The template's rows as the page reads them, grouped and in order:
    [{"entity", "group", "name", "version", "installing"}]."""
    order = {g: k for k, (g, _) in enumerate(GROUPS)}
    out = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict) or not row.get("entity"):
            continue
        group = group_of(row)
        out.append({"entity": str(row["entity"]), "group": group, "name": name_of(row, group)[:120],
                    "version": str(row.get("version") or "")[:40],
                    "installing": row.get("busy") not in (None, False, 0, "", "false", "False")})

    def key(u):
        own = HOME_ASSISTANT.index(u["name"]) if u["name"] in HOME_ASSISTANT else len(HOME_ASSISTANT)
        return order[u["group"]], own, u["name"].casefold()
    return sorted(out, key=key)


def by_group(items) -> dict[str, int]:
    """How many updates in each group, every group named."""
    return {g: sum(1 for u in items or [] if u.get("group") == g) for g, _ in GROUPS}


@runtime.live(120)
async def fetch_updates(session):
    if not HA_TOKEN:
        import examples
        return examples.updates()
    raw = await ha_template(session, UPDATES_TEMPLATE)
    try:
        if raw is None:
            raise ValueError("Home Assistant didn't answer the updates template")
        got = updates_from(json.loads(raw))
    except Exception as exc:
        health.fail(UPDATES, exc)
        raise
    health.ok(UPDATES)
    return got


# ------------------------------------------------------------------ repairs

def repairs_from(result) -> int:
    """How many Repairs issues are open: the ones you ignored don't count, as in Home Assistant."""
    issues = (result or {}).get("issues") if isinstance(result, dict) else None
    return sum(1 for i in issues or [] if isinstance(i, dict) and not i.get("ignored"))


@runtime.live(300)
async def fetch_repairs(session):
    if not HA_TOKEN:
        import examples
        return examples.REPAIRS
    try:
        got = repairs_from(await runtime.HASS.ws({"type": "repairs/list_issues"}))
    except Exception as exc:
        health.fail(REPAIRS, exc)
        raise
    health.ok(REPAIRS)
    return got


# ------------------------------------------------------------------ counts

async def counts(session, wanted=COUNTS) -> dict[str, int | None]:
    """{"updates", "notifications", "repairs", "all"}: each None until it has been read.
    "all" is the three together, of those read so far (one that fails says so as its service)."""
    out: dict[str, int | None] = {}
    if {"updates", "all"} & set(wanted):
        got = await fetch_updates(session)
        out["updates"] = None if got is None else len(got)
    if {"notifications", "all"} & set(wanted):
        got = await fetch_notifications(session)
        out["notifications"] = None if got is None else len(got)
    if {"repairs", "all"} & set(wanted):
        got = await fetch_repairs(session)
        out["repairs"] = None if got is None else int(got)
    if "all" in wanted:
        parts = [out.get(k) for k in ("updates", "notifications", "repairs")]
        out["all"] = None if all(p is None for p in parts) else sum(p or 0 for p in parts)
    return out


# What a page's elements show (widgets.py): which counts each needs.
SHOWS = {"notifications": ("notifications",), "updates": ("updates",)}


def counts_in(spec: dict) -> set[str]:
    """The counts the pages use: their widgets', a badge's, and any of the add-on's sensors a page's
    "only when" or an alert names. What entities.publish_needs_you keeps up to date."""
    out: set[str] = set()
    for page in (spec.get("pages") or {}).values():
        for el in page.get("elements") or []:
            if not isinstance(el, dict):
                continue
            out |= set(SHOWS.get(el.get("type"), ()))
            if el.get("type") == "badge":
                c = badge_counts(el)
                out |= {"updates", "notifications", "repairs"} if c == "all" else {c}
    text = json.dumps(spec)
    out |= {k for k, sensor in SENSOR.items() if sensor in text}
    return out


def badge_counts(el: dict) -> str:
    c = str((el or {}).get("counts") or "updates")
    return c if c in COUNTS else "updates"
