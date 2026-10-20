"""A screen that sleeps between wakes, and the add-on picks its page.

The one mode for every screen that sleeps: a TRMNL always, a CrowPanel in
Low Power Mode. The kind keeps only its protocol (how a wake asks, how the
answer is said); what to show and how long to sleep are worked out here.

- **Drawn ahead** (`draw_ahead`, from the kind's `render` in every render
  cycle). Everything the screen can fetch at its next wakes: every item of
  every live page, the empty page, and the sleep screen. A page says
  "updated" when it last changed, not when the screen woke (`steady`), so an
  unchanged page keeps its picture and the screen neither downloads nor
  flashes. Quiet hours, presence included, come from the cycle.
- **A wake only picks** (`wake`). The cursor steps (`step`: a timer moves
  through every item of every page; a person goes to the next page), and the
  sleep time comes from the clock (`sleep_seconds`): the wake interval, cut
  short to wake just after quiet hours start; through quiet hours, until they
  end. Quiet hours' schedule is checked against the clock at the wake (it's
  only arithmetic), so a wake just after they start or end is right even if
  the last cycle was a minute earlier.
- **Awake time.** A wake can say how long the screen stays awake before it
  sleeps (a CrowPanel: a minute after a press, or ten minutes when asked to
  stay awake for an update). A TRMNL's protocol has no such field.
- **The one exception to "a request never draws"**: a wake that finds
  nothing drawn for the size the screen has now (just after a start, or it
  just said it has a new size) is drawn there and then, and the log says so.
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from datetime import datetime, timedelta

import devices
import frames
import health
import runtime
from render import sleep, theme as T

WAKE_CHOICES = (5, 10, 15, 30, 60, 120, 240)    # minutes
DEFAULT_WAKE = 15
GLANCE_SECONDS = 120                    # a press during quiet hours shows a page this long
FIRST_RENDER_SECONDS = 60               # nothing drawn yet: ask again soon
QUIET_MARGIN = 60                       # wake just after quiet hours start or end, never just before
MAX_SLEEP = 24 * 3600
PERSON_AWAKE_SECONDS = 60               # after the last press, before it sleeps again
STAY_AWAKE_SECONDS = 600                # "stay awake for an update"
KEEP_UPDATED = 64
KEEP_AWAKE_TIMES = 12                   # per screen, for the editor's average

EMPTY_KEY = "\x00empty"


def sleep_key(text: str) -> str:
    return f"\x00sleep:{text}"


def page_key(name: str, item: int) -> str:
    return f"{name}#{item}"


# ---------------------------------------------------------------- the wake interval

def wake_minutes(dev: dict) -> int:
    """How often the screen wakes. One setting for every kind (a TRMNL, a CrowPanel in
    Low Power Mode); a TRMNL paired before it moved here kept it in its setup."""
    raw = dev.get("wake_minutes")
    if raw is None:
        raw = (dev.get("setup") or {}).get("wake_minutes")
    try:
        minutes = int(raw or DEFAULT_WAKE)
    except (TypeError, ValueError):
        minutes = DEFAULT_WAKE
    return minutes if minutes in WAKE_CHOICES else DEFAULT_WAKE


def wake_setting(body: dict) -> dict:
    """The device field an editor change of the wake interval asks for ({} when it asks for none)."""
    if "wake_minutes" not in body:
        return {}
    try:
        minutes = int(body["wake_minutes"])
    except (TypeError, ValueError):
        minutes = 0
    if minutes not in WAKE_CHOICES:
        raise ValueError("Pick one of the intervals offered.")
    return {"wake_minutes": minutes}


# ---------------------------------------------------------------- drawn ahead

class Art:
    """How a kind turns a page into what its screen fetches (a PNG, a frame file).
    Called only from the render cycle, and for the one exception in `wake`."""

    async def page(self, dev: dict, spec: dict, st, plans: list[dict], pos: int, item: int, clock: str) -> bytes:
        raise NotImplementedError

    async def sleep(self, dev: dict, spec: dict, text: str) -> bytes:
        raise NotImplementedError

    async def empty(self, dev: dict, spec: dict, clock: str) -> bytes:
        raise NotImplementedError


@dataclass
class Ahead:
    """What the last render cycle drew for one screen, and what it knew."""
    display: str
    spec: dict
    st: object                      # frames.DesignState
    quiet: bool
    reason: str
    pictures: dict


def ahead_of(dev: dict) -> Ahead | None:
    return runtime.device(dev["id"]).kind.get("ahead")


def forget(dev: dict) -> None:
    runtime.device(dev["id"]).kind.pop("ahead", None)


def _plans(spec: dict, st) -> list[dict]:
    return [p for p in st.plans if p["name"] in spec.get("pages", {})]


def _qh(spec: dict) -> dict:
    return spec.get("quiet_hours") if isinstance(spec.get("quiet_hours"), dict) else {}


def _schedule_text(spec: dict) -> str:
    return sleep.wake_text("schedule", frames.quiet_window(_qh(spec))[1])


async def draw_ahead(dev: dict, spec: dict, st, quiet: bool, reason: str, art: Art,
                     now: datetime | None = None) -> Ahead:
    """Draw every picture the screen can fetch before the next cycle. Called from the cycle only."""
    now = now or datetime.now().astimezone()
    pictures: dict[str, bytes] = {}
    plans = _plans(spec, st)

    async def keep(key, make):
        try:
            pictures[key] = await make()
        except Exception as exc:
            # One picture that can't be drawn must not cost the others: that wake keeps what it shows.
            print(f"{dev.get('name')}: couldn't draw {key.lstrip(chr(0))} ahead: {health.describe(exc)}", flush=True)

    texts = []
    if _qh(spec).get("enabled"):
        texts.append(_schedule_text(spec))
    if quiet:
        texts.append(sleep.wake_text(reason, frames.quiet_window(_qh(spec))[1]))
    for text in dict.fromkeys(texts):
        await keep(sleep_key(text), lambda text=text: art.sleep(dev, spec, text))

    if not st.live or not plans:
        await keep(EMPTY_KEY, lambda: steady(dev, EMPTY_KEY, now, lambda clock: art.empty(dev, spec, clock)))
    for pos, plan in enumerate(plans):
        for item in range(max(1, plan["want"])):
            key = page_key(plan["name"], item)
            if key in pictures:
                continue                              # a page twice in the rotation is one picture
            await keep(key, lambda pos=pos, item=item, key=key: steady(
                dev, key, now, lambda clock: art.page(dev, spec, st, plans, pos, item, clock)))

    ahead = Ahead(T.get_display(spec.get("display"))["id"], spec, st, quiet, reason, pictures)
    runtime.device(dev["id"]).kind["ahead"] = ahead       # whole, at once: a wake never sees half a cycle
    return ahead


# ---------------------------------------------------------------- "updated" is when the page last changed

def updated_label(at: datetime, now: datetime) -> str:
    """The footer's time: when this page last changed, with the day once it's not today."""
    return f"updated {at.strftime('%H:%M') if at.date() == now.date() else at.strftime('%a %H:%M')}"


def digest(data: bytes) -> str:
    return hashlib.blake2s(data, digest_size=8).hexdigest()


async def steady(dev: dict, key: str, now: datetime, draw) -> bytes:
    """A page's picture, with "updated" saying when it last changed rather than when it
    was drawn. Drawn again with the time it had: if that's the same picture, nothing
    changed, so it keeps its bytes (and its name, its ETag) and the screen neither
    downloads nor flashes. `draw(clock)` makes the picture with that footer text."""
    seen = dict(devices.state(dev["id"]).get("updated") or {})
    prev = seen.get(key)
    if isinstance(prev, dict):
        try:
            at = datetime.fromisoformat(prev["at"])
            data = await draw(prev["label"])
        except (KeyError, TypeError, ValueError):
            data = None
        if data is not None and digest(data) == prev.get("hash"):
            label = updated_label(at, now)
            if label == prev["label"]:
                return data
            data = await draw(label)                  # the same page, a day on: the day joins the time
            seen[key] = {"at": prev["at"], "label": label, "hash": digest(data)}
            _keep_updated(dev, seen)
            return data
    label = updated_label(now, now)
    data = await draw(label)
    seen.pop(key, None)
    seen[key] = {"at": now.isoformat(timespec="seconds"), "label": label, "hash": digest(data)}
    _keep_updated(dev, seen)
    return data


def _keep_updated(dev: dict, seen: dict) -> None:
    devices.set_state(dev["id"], updated=dict(list(seen.items())[-KEEP_UPDATED:]))


# ---------------------------------------------------------------- a wake

def seconds_until(hhmm: str, now: datetime) -> int | None:
    try:
        h, m = (int(x) for x in str(hhmm).strip()[:5].split(":"))
        target = now.replace(hour=h, minute=m, second=0, microsecond=0)
    except (TypeError, ValueError):
        return None
    if target <= now:
        target += timedelta(days=1)
    return int((target - now).total_seconds())


def step(plans: list[dict], cursor: dict, by_page: bool) -> tuple[int, int]:
    """The next (page position, item) after the cursor. A timer wake moves through every
    item of every page; a person goes to the next page. A page that has gone is
    looked for by name; failing that, the rotation starts again."""
    n = len(plans)
    pos, name, item = cursor.get("pos", -1), cursor.get("name"), int(cursor.get("item") or 0)
    if not (isinstance(pos, int) and 0 <= pos < n and plans[pos]["name"] == name):
        pos = next((i for i, p in enumerate(plans) if p["name"] == name), None)
        if pos is None:
            return 0, 0
    if not by_page and item + 1 < max(1, plans[pos]["want"]):
        return pos, item + 1
    return (pos + 1) % n, 0


def quiet_now(ahead: Ahead, now: datetime) -> tuple[bool, str]:
    """Quiet hours at this wake: the schedule against the clock, presence as the cycle found it."""
    qh = _qh(ahead.spec)
    if frames.in_quiet_schedule(qh, now):
        start, end = frames.quiet_window(qh)
        return True, f"schedule ({start}–{end})"
    if ahead.quiet and str(ahead.reason).startswith("away"):
        return True, ahead.reason
    return False, "outside quiet window"


def sleep_seconds(dev: dict, ahead: Ahead, now: datetime, person: bool) -> int:
    """How long to sleep after this wake."""
    qh = _qh(ahead.spec)
    wake = wake_minutes(dev) * 60
    quiet, reason = quiet_now(ahead, now)
    alert = bool(ahead.st.alert) and (not quiet or qh.get("allow_alerts", True))
    if quiet and not alert and not person:
        # Until they end, plus a minute. Presence has no end: check again at the interval.
        end = None if str(reason).startswith("away") else seconds_until(frames.quiet_window(qh)[1], now)
        return min(MAX_SLEEP, max(60, end + QUIET_MARGIN)) if end is not None else wake
    seconds = GLANCE_SECONDS if quiet and not alert else wake
    if qh.get("enabled") and not quiet:
        # Asleep through the start of quiet hours would leave a page up all night.
        start = seconds_until(frames.quiet_window(qh)[0], now)
        if start is not None:
            seconds = min(seconds, start + QUIET_MARGIN)
    return int(seconds)


@dataclass
class Wake:
    """What one wake gets: a picture (None: keep what it shows), how long to sleep, and how long to stay awake first."""
    picture: bytes | None
    sleep: int
    awake: int = 0
    key: str = ""


def _choose(dev: dict, ahead: Ahead, now: datetime, person: bool) -> str | None:
    """Which picture this wake shows (None: keep what it shows). Steps the cursor."""
    qh = _qh(ahead.spec)
    quiet, reason = quiet_now(ahead, now)
    alert = bool(ahead.st.alert) and (not quiet or qh.get("allow_alerts", True))
    if quiet and not alert and not person:
        if qh.get("sleep_screen", True) is False:
            return None                               # keeps what it shows: no flash in a dark room
        return sleep_key(sleep.wake_text(reason, frames.quiet_window(qh)[1]))
    plans = _plans(ahead.spec, ahead.st)
    if not ahead.st.live or not plans:
        return EMPTY_KEY
    cursor = devices.state(dev["id"]).get("cursor") or {}
    pos, item = step(plans, cursor, by_page=person)
    plan = plans[pos]
    devices.set_state(dev["id"], cursor={"pos": pos, "name": plan["name"], "item": item})
    return page_key(plan["name"], min(item, max(1, plan["want"]) - 1))


async def _draw_now(dev: dict, ahead: Ahead, key: str, now: datetime, art: Art, why: str) -> bytes | None:
    """The exception: draw one picture during a wake, for the size the screen has now."""
    print(f"{dev.get('name')}: drawing its picture while it waits ({why})", flush=True)
    spec = devices.view(dev["id"])                    # placed for the size it has now
    st = ahead.st
    if key == EMPTY_KEY:
        return await steady(dev, key, now, lambda clock: art.empty(dev, spec, clock))
    if key.startswith("\x00sleep:"):
        return await art.sleep(dev, spec, key[len("\x00sleep:"):])
    plans = _plans(spec, st)
    name, _, item = key.rpartition("#")
    pos = next((i for i, p in enumerate(plans) if p["name"] == name), None)
    if pos is None:
        return None
    return await steady(dev, key, now, lambda clock: art.page(dev, spec, st, plans, pos, int(item), clock))


def awake_seconds(dev: dict, person: bool) -> int:
    """How long to stay awake after this wake: a minute after a person, longer when asked to stay awake."""
    awake = PERSON_AWAKE_SECONDS if person else 0
    stay = devices.state(dev["id"]).get("stay_awake") or {}
    now = time.time()
    if stay.get("asked") and not stay.get("until"):
        stay = {"asked": stay["asked"], "until": now + STAY_AWAKE_SECONDS}
        devices.set_state(dev["id"], stay_awake=stay)  # delivered: it counts from this wake
    until = float(stay.get("until") or 0)
    if until > now:
        awake = max(awake, int(until - now))
    elif until:
        devices.set_state(dev["id"], stay_awake={})   # done
    return awake


def ask_to_stay_awake(dev: dict, on: bool = True) -> dict:
    """Ask the screen to stay awake for an update at its next wake (or stop asking)."""
    stay = {"asked": datetime.now().astimezone().isoformat(timespec="seconds")} if on else {}
    devices.set_state(dev["id"], stay_awake=stay)
    return stay_awake_info(dev)


def stay_awake_info(dev: dict) -> dict:
    stay = devices.state(dev["id"]).get("stay_awake") or {}
    until = float(stay.get("until") or 0)
    if until and until <= time.time():
        return {"asked": False, "until": None}
    return {"asked": bool(stay.get("asked")),
            "until": datetime.fromtimestamp(until).astimezone().isoformat(timespec="seconds") if until else None}


def timing(dev: dict, *, person: bool, now: datetime | None = None) -> Wake:
    """How long to sleep and stay awake after a wake that fetched everything it holds
    (a CrowPanel's frame file after a press): no picture is picked, no cursor moves."""
    now = now or datetime.now().astimezone()
    ahead = ahead_of(dev)
    awake = awake_seconds(dev, person)
    if ahead is None:
        return Wake(None, FIRST_RENDER_SECONDS, awake)
    return Wake(None, sleep_seconds(dev, ahead, now, person), awake)


async def wake(dev: dict, *, person: bool, art: Art, now: datetime | None = None) -> Wake:
    """One wake: pick the picture from what the cycle drew, and say how long to sleep."""
    now = now or datetime.now().astimezone()
    ahead = ahead_of(dev)
    awake = awake_seconds(dev, person)
    if ahead is None:
        return Wake(None, FIRST_RENDER_SECONDS, awake)    # just started: nothing rendered yet
    sleep_for = sleep_seconds(dev, ahead, now, person)
    key = _choose(dev, ahead, now, person)
    rt = runtime.device(dev["id"]).kind
    if key is None:
        return Wake(rt.get("last"), sleep_for, awake)
    display = T.get_display(dev.get("display"))["id"]
    picture = ahead.pictures.get(key) if ahead.display == display else None
    if picture is None:
        why = "it said it has a new size" if ahead.display != display else "nothing was drawn ahead for it"
        try:
            picture = await _draw_now(dev, ahead, key, now, art, why)
        except Exception as exc:
            print(f"{dev.get('name')}: couldn't draw its picture: {health.describe(exc)}", flush=True)
            picture = None
        if picture is None:
            return Wake(rt.get("last"), sleep_for, awake)
    rt["last"] = picture
    return Wake(picture, sleep_for, awake, key)


# ---------------------------------------------------------------- how long it's awake

def note_awake(dev: dict, ms) -> None:
    """Record how long the screen was awake at its last wake (milliseconds), as it reports it."""
    try:
        ms = int(float(str(ms).strip()))
    except (TypeError, ValueError):
        return
    if not 0 < ms < 3_600_000:
        return                                         # not a reading
    times = [int(x) for x in devices.state(dev["id"]).get("awake_ms") or [] if isinstance(x, (int, float))]
    devices.set_state(dev["id"], awake_ms=(times + [ms])[-KEEP_AWAKE_TIMES:])


def awake_average(dev: dict) -> float | None:
    """The recent average awake time per wake, in seconds (one decimal), or None before any reading."""
    times = [x for x in devices.state(dev["id"]).get("awake_ms") or [] if isinstance(x, (int, float))]
    return round(sum(times) / len(times) / 1000, 1) if times else None

