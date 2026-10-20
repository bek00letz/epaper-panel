"""A screen's two timers: how often it updates, and how often it moves to the next page.

Every screen has two settings, set in the editor (Settings › Screen, or the
cards when it's added) and nowhere else. They're the one source of truth for
when a screen fetches and when it sleeps.

- **Update every** (`update_minutes`). 1 minute is always on: a CrowPanel
  stays connected and checks every minute, its buttons answer at once, and
  alerts and Home Assistant reach it straight away. 2 minutes or more, it
  sleeps between updates (paging.py), and longer is lower power. A kind that
  can't stay connected (a TRMNL: `Kind.stays_on`) has no always-on choice and
  starts at 5 minutes.
- **Rotate every**. Always on, it's seconds (`rotate_seconds`) and the panel
  turns its pages itself. Asleep, it's a whole number of updates
  (`rotate_updates`): each wake refreshes the page on screen, and every Nth
  moves on. Each mode keeps its own, so switching back finds what you had.

Before 0.13 a screen had a Low Power Mode switch (`low_power`), a wake
interval (`wake_minutes`) and, for a CrowPanel, the panel's own refresh
interval (Panel setup's `refresh_interval`). They're read only as what a
screen that hasn't been set since means, and never written or removed, so
going back to 0.12 finds them as they were: Low Power Mode off is always on,
on keeps its wake interval.
"""
from __future__ import annotations

ALWAYS_ON = 1
UPDATE_CHOICES = (1, 2, 5, 10, 15, 30, 60, 120, 240, 480, 720, 1440)     # minutes
ASLEEP_FROM = 5                         # the shortest for a screen that can't stay connected
ASLEEP_DEFAULT = 15                     # what "sleeps between updates" starts at
ROTATE_SECONDS = (15, 30, 45, 60, 120, 300)
ROTATE_DEFAULT = 30
ROTATE_UPDATES = (1, 2, 3, 4, 6, 8, 12, 24)
LONGEST_ROTATION = 1440                 # minutes: a page moves on at least once a day
UPDATE_KEYS = ("update_minutes", "rotate_seconds", "rotate_updates")


def update_choices(stays_on: bool) -> list[int]:
    return [m for m in UPDATE_CHOICES if stays_on or m >= ASLEEP_FROM]


def update_minutes(dev: dict, stays_on: bool = True) -> int:
    """Update every, in minutes. A screen set before 0.13 means what it meant then."""
    raw = dev.get("update_minutes")
    if raw is None:
        if stays_on and not dev.get("low_power"):
            raw = ALWAYS_ON
        else:
            # A TRMNL paired before 0.12 kept its interval in its setup.
            raw = dev.get("wake_minutes") or (dev.get("setup") or {}).get("wake_minutes") or ASLEEP_DEFAULT
    try:
        minutes = int(raw)
    except (TypeError, ValueError):
        minutes = 0
    choices = update_choices(stays_on)
    if minutes in choices:
        return minutes
    return ALWAYS_ON if stays_on else ASLEEP_DEFAULT


def sleeps(dev: dict, stays_on: bool = True) -> bool:
    """Whether the screen sleeps between updates: anything but always on."""
    return update_minutes(dev, stays_on) != ALWAYS_ON


def rotate_seconds(dev: dict) -> int:
    """Always on: how long each page shows, in seconds."""
    try:
        return max(5, min(3600, int(dev.get("rotate_seconds") or ROTATE_DEFAULT)))
    except (TypeError, ValueError):
        return ROTATE_DEFAULT


def rotate_update_choices(minutes: int) -> list[int]:
    return [n for n in ROTATE_UPDATES if n == 1 or n * minutes <= LONGEST_ROTATION]


def rotate_updates(dev: dict, stays_on: bool = True) -> int:
    """Asleep: every how many updates it moves to the next page (1: every one)."""
    try:
        n = int(dev.get("rotate_updates") or 1)
    except (TypeError, ValueError):
        n = 1
    allowed = rotate_update_choices(update_minutes(dev, stays_on))
    return max([c for c in allowed if c <= n] or [1])


def settings(dev: dict, body: dict, stays_on: bool = True) -> dict:
    """The device fields an editor change of the timers asks for ({} when it asks for none).
    Raises ValueError, with what to fix, for a value it can't take."""
    fields = {}

    def number(key):
        try:
            return int(body[key])
        except (TypeError, ValueError):
            return None

    if "update_minutes" in body:
        minutes = number("update_minutes")
        if minutes not in update_choices(stays_on):
            raise ValueError("Pick one of the update times offered.")
        fields["update_minutes"] = minutes
    if "rotate_seconds" in body:
        seconds = number("rotate_seconds")
        if seconds not in ROTATE_SECONDS:
            raise ValueError("Pick one of the rotation times offered.")
        fields["rotate_seconds"] = seconds
    if "rotate_updates" in body:
        n = number("rotate_updates")
        minutes = fields.get("update_minutes") or update_minutes(dev, stays_on)
        if n not in rotate_update_choices(minutes):
            raise ValueError("Pick one of the rotation times offered.")
        fields["rotate_updates"] = n
    return fields


def describe(dev: dict, stays_on: bool = True) -> dict:
    """What the editor shows and offers."""
    minutes = update_minutes(dev, stays_on)
    return {
        "update_minutes": minutes,
        "update_choices": update_choices(stays_on),
        "always_on": minutes == ALWAYS_ON,
        "can_stay_on": stays_on,
        "rotate_seconds": rotate_seconds(dev),
        "rotate_seconds_choices": list(ROTATE_SECONDS),
        "rotate_updates": rotate_updates(dev, stays_on),
        "rotate_update_choices": rotate_update_choices(minutes),
        "asleep_default": ASLEEP_DEFAULT,
    }
