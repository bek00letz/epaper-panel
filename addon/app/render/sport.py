"""Each sport's own words: a football match, a basketball game, a race.

The user's rule (21 Oct): never call a Premier League match a game. Keyed by
the first part of an ESPN league path ("soccer/eng.1" -> soccer), the same
way as the editor's presets.SPORT_WORDS. A sport not listed reads as a match,
with a plain "Starts".
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Words:
    event: str          # one of them: "match"
    start: str          # before its start time: "Kick-off 19:30"
    day: str            # a day with one on: "Matchday"
    events: str         # several of them: "matches"


SPORTS = {
    "soccer": Words("match", "Kick-off", "Matchday", "matches"),
    "rugby": Words("match", "Kick-off", "Matchday", "matches"),
    "tennis": Words("match", "Starts", "Match day", "matches"),
    "cricket": Words("match", "Starts", "Match day", "matches"),
    "basketball": Words("game", "Tip-off", "Game day", "games"),
    "football": Words("game", "Kickoff", "Game day", "games"),        # American football; ESPN's soccer is "soccer"
    "baseball": Words("game", "First pitch", "Game day", "games"),
    "hockey": Words("game", "Puck drop", "Game day", "games"),
    "racing": Words("race", "Lights out", "Race day", "races"),
}
OTHER = Words("match", "Starts", "Match day", "matches")


def words(league) -> Words:
    """The words for a league path ("basketball/nba") or a sport ("basketball")."""
    return SPORTS.get(str(league or "").strip().lower().split("/", 1)[0], OTHER)
