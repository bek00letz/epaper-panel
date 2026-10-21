"""12- or 24-hour time on the panels: Home Assistant's way by default, or the person's choice.

Home Assistant keeps the time format in each person's profile, which an
add-on can't read, so "auto" follows Home Assistant's country (and, in
Canada, its language): the way clocks read there. One setting overrides it
for every device (the user's call, 21 Oct). render/clock.py applies it.
"""
from __future__ import annotations

import json

import config
from render import clock

FILE = "time.json"
FORMATS = ("auto", "12h", "24h")
# Where clocks read 12-hour (on phones, ovens and signs, not only in speech).
TWELVE_HOUR_COUNTRIES = {"US", "CA", "AU", "NZ", "IN", "PH", "PK", "BD", "EG", "SA", "MY", "CO", "JO", "SV", "HN", "NI"}


def settings() -> dict:
    try:
        found = json.loads((config.DATA_DIR / FILE).read_text())
    except (OSError, ValueError):
        found = {}
    return {"format": found.get("format") if found.get("format") in FORMATS else "auto"}


def save(fmt: str) -> dict:
    if fmt not in FORMATS:
        raise ValueError("Pick Automatic, 12-hour or 24-hour.")
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = config.DATA_DIR / (FILE + ".tmp")
    tmp.write_text(json.dumps({"format": fmt}))
    tmp.replace(config.DATA_DIR / FILE)
    return settings()


def by_country(country: str | None, language: str | None = None) -> bool:
    """Whether clocks read 12-hour in Home Assistant's country (and language)."""
    c = str(country or "").upper()
    if c == "CA" and str(language or "").lower().startswith("fr"):
        return False
    return c in TWELVE_HOUR_COUNTRIES


def twelve_hour(country: str | None = None, language: str | None = None) -> bool:
    fmt = settings()["format"]
    if fmt != "auto":
        return fmt == "12h"
    return by_country(country, language)


def describe(country: str | None = None, language: str | None = None) -> dict:
    """What the editor shows: the setting, and what it means now."""
    return {"format": settings()["format"], "resolved": "12h" if twelve_hour(country, language) else "24h",
            "country": str(country or "")}


def apply(country: str | None = None, language: str | None = None) -> bool:
    """Set the panel's time format for this render cycle; returns whether it's 12-hour."""
    clock.use(twelve_hour(country, language))
    return clock.twelve_hour()
