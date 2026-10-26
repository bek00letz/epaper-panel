"""Each sport's own words: a football match, a basketball game, a race, in the screen's language.

The user's rule (21 Oct): never call a Premier League match a game. Keyed by
the first part of an ESPN league path ("soccer/eng.1" -> soccer), the same
way as the editor's presets.SPORT_WORDS. A sport not listed reads as a match,
with a plain "Starts". The words are render/words.py's, said in the language
being spoken (the editor's catalog asks outside any device: English).

What a Scores page's badge says is here too (`badge`): from the game's facts
(sources/sports.game_view), so the same game says "Anstoß 19:30" on a German
screen and "Kick-off 19:30" on an English one.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from . import clock
from .words import say


@dataclass(frozen=True)
class Words:
    event: str          # one of them: "match"
    start: str          # before its start time: "Kick-off 19:30"
    day: str            # a day with one on: "Matchday"
    events: str         # several of them: "matches"


# Each sport's words, as keys in render/words_table.py: (event, start, day, events).
SPORTS = {
    "soccer": ("match", "kick_off", "matchday", "matches"),
    "rugby": ("match", "kick_off", "matchday", "matches"),
    "tennis": ("match", "starts", "match_day", "matches"),
    "cricket": ("match", "starts", "match_day", "matches"),
    "basketball": ("game", "tip_off", "game_day", "games"),
    "football": ("game", "kickoff", "game_day", "games"),        # American football; ESPN's soccer is "soccer"
    "baseball": ("game", "first_pitch", "game_day", "games"),
    "hockey": ("game", "puck_drop", "game_day", "games"),
    "racing": ("race", "lights_out", "race_day", "races"),
}
OTHER = ("match", "starts", "match_day", "matches")


def _said(keys) -> Words:
    return Words(*(say(f"sport.{k}") for k in keys))


def words(league) -> Words:
    """The words for a league path ("basketball/nba") or a sport ("basketball"), in the language spoken."""
    return _said(SPORTS.get(str(league or "").strip().lower().split("/", 1)[0], OTHER))


def catalog() -> dict:
    """Every sport's words, for the editor's catalog: {sport: Words}, "other" for the rest."""
    return {**{k: _said(v) for k, v in SPORTS.items()}, "other": _said(OTHER)}


# ESPN's states the add-on says in the screen's language (status.type.name); any other keeps ESPN's words.
STATES = {"STATUS_HALFTIME": "half_time", "STATUS_FULL_TIME": "full_time", "STATUS_FINAL": "final",
          "STATUS_POSTPONED": "postponed", "STATUS_CANCELED": "canceled", "STATUS_DELAYED": "delayed",
          "STATUS_FIRST_HALF": "first_half", "STATUS_SECOND_HALF": "second_half"}


def _state_words(game: dict, fallback: str) -> str:
    key = STATES.get(str(game.get("status_name") or "").upper())
    return say(f"sport.{key}") if key else (str(game.get("status_text") or "") or say(fallback))


def badge(game: dict, league="", now: datetime | None = None) -> str:
    """A Scores page's badge from a game's facts: "74' · 2nd half" while it's on, "Sat 19:30" or
    "Kick-off 19:30" before it, "Full time" after. A game whose source gave its own badge
    (a Home Assistant sensor's `clock`) keeps it."""
    if game.get("clock"):
        return str(game["clock"])
    state = str(game.get("status") or "PRE").upper()
    if state == "IN":
        live = _state_words(game, "sport.live")
        tick = str(game.get("clock_val") or "")
        return f"{tick} · {live}" if tick and tick != "0'" else live
    if state == "PRE":
        try:
            ko = datetime.fromisoformat(str(game.get("kickoff_iso") or "").replace("Z", "+00:00"))
            if ko.tzinfo is not None and game.get("tz"):
                ko = ko.astimezone(ZoneInfo(game["tz"]))
        except Exception:
            ko = None
        if ko is not None:
            today = (now or datetime.now(ko.tzinfo)).date()
            if ko.date() != today:
                return clock.day_and_time(ko)
            return f"{words(league).start} {clock.hm(ko)}"
        return _state_words(game, "sport.scheduled")
    return _state_words(game, "sport.final")
