"""The words the add-on puts on a screen, in the screen's language: the one way to look them up.

Every word the add-on draws itself (dates, "updated", the sleep screen, empty states, status
words, labels) comes from one table, `render/words_table.py`, through `say()`. Words the person
typed are theirs and never pass through here. A word missing in a language is said in English
(tests/test_words.py lists any).

The language is the device's, set around each device's drawing with `speaking()`: the one
chosen for it in Settings › Device, else Home Assistant's (`for_device`), English for one we
don't have yet. It's a context
variable, not a global, so two devices drawn at once (the render cycle and an editor preview)
each speak their own. Outside `speaking()` it's English: what the editor and the log read.

Numbers follow the language too (`number`: "2,5" in German), and dates are written from the
table's patterns with its month and day names (`clock.strftime` asks `name()` here), so no date
depends on the system's locale.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar

from .words_table import WORDS

LANGUAGES = ("en", "ro", "es", "de", "fr")
NAMES = {"en": "English", "ro": "Română", "es": "Español", "de": "Deutsch", "fr": "Français"}
DEFAULT = "en"

_speaking: ContextVar[tuple[str, str]] = ContextVar("speaking", default=(DEFAULT, ""))


def resolve(tag) -> str:
    """The language we speak for a language tag ("de", "de-CH", "pt-BR"): its own when we have it,
    else English."""
    base = str(tag or "").strip().lower().replace("_", "-").split("-", 1)[0]
    return base if base in LANGUAGES else DEFAULT


def offered(tag) -> bool:
    """Whether a language tag is one we speak (Home Assistant in Italian isn't, yet)."""
    return str(tag or "").strip().lower().replace("_", "-").split("-", 1)[0] in LANGUAGES


@contextmanager
def speaking(language, country=""):
    """Say everything inside in `language` (a tag; resolved), with dates as `country` writes them."""
    token = _speaking.set((resolve(language), str(country or "").upper()))
    try:
        yield
    finally:
        _speaking.reset(token)


def for_device(own, home) -> str:
    """The language a device speaks: its own choice (Settings › Device "Language"), else Home
    Assistant's, else English."""
    own = str(own or "").strip().lower()
    return own if own in LANGUAGES else resolve(home)


def choices() -> list[list[str]]:
    """The languages a device can speak, each named in itself, for the editor: [[code, name], ...]."""
    return [[code, NAMES[code]] for code in LANGUAGES]


def language() -> str:
    return _speaking.get()[0]


def country() -> str:
    return _speaking.get()[1]


# ---------------------------------------------------------------- plurals (CLDR's rules, for whole numbers)

def plural(n, lang: str | None = None) -> str:
    """The plural form a count takes: "one", "few" (Romanian: 2-19, and 0) or "other"."""
    lang = lang or language()
    try:
        n = abs(int(n))
    except (TypeError, ValueError):
        return "other"
    if lang == "fr":
        return "one" if n in (0, 1) else "other"
    if lang == "ro":
        if n == 1:
            return "one"
        return "few" if n == 0 or 1 <= n % 100 <= 19 else "other"
    return "one" if n == 1 else "other"


def has(key: str) -> bool:
    """Whether the table has a word (for a name that may be the add-on's own or a source's)."""
    return key in WORDS


def entry(key: str, lang: str | None = None):
    """The table's entry for a word in a language, or English's when that language has none."""
    row = WORDS[key]
    got = row.get(lang or language())
    return got if got not in (None, "") else row[DEFAULT]


def say(key: str, n=None, **params) -> str:
    """A word or phrase in the current language. `n` picks its plural form and fills {n};
    the rest fill their {placeholders}."""
    lang = language()
    got = entry(key, lang)
    if isinstance(got, dict):
        got = got.get(plural(n, lang)) or got.get("other") or next(iter(got.values()))
    if n is not None:
        params["n"] = number(n) if isinstance(n, float) else n
    return got.format(**params) if params else got


def cap(text: str) -> str:
    """The first letter a capital, for a word standing alone as a label ("marți" -> "Marți")."""
    return text[:1].upper() + text[1:] if text else text


# ---------------------------------------------------------------- numbers

_DECIMAL = {"en": "."}
_GROUP = {"en": ",", "fr": " "}          # French groups with a narrow space


def number(value, decimals: int | None = None, group: bool = False) -> str:
    """A number as the language writes it: "2.5" or "2,5"; with `group`, "10,370" / "10.370" /
    "10 370" (Spanish groups only from 10 000)."""
    lang = language()
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    if decimals is None:
        text = (f"{v:,.0f}" if group else f"{v:.0f}") if v == int(v) else (f"{v:,}" if group else repr(v))
    else:
        text = f"{v:,.{decimals}f}" if group else f"{v:.{decimals}f}"
    if group and lang == "es" and abs(v) < 10000:
        text = text.replace(",", "")
    return text.translate({ord(","): "\x00", ord("."): _DECIMAL.get(lang, ",")}).replace(
        "\x00", _GROUP.get(lang, "."))


# ---------------------------------------------------------------- names in dates

def name(kind: str, i: int) -> str:
    """A month's or weekday's name: kind "month" / "mon" (1-12), "weekday" / "wd" / "wdn" (Monday 0),
    "am" / "pm" (i ignored)."""
    if kind in ("am", "pm"):
        return say(f"time.{kind}")
    return say(f"{kind}.{i}")


def date_pattern(kind: str) -> str:
    """A date's pattern in the language (strftime codes; clock.strftime fills the names):
    "date" (21 Oct), "day_date" (Tue, 21 Oct), "day_full" (Tuesday, 21 October), "weekday_date"
    (Tuesday 21 October), "weekday_date_year", "short_day_date" (Tue 21 Oct), "day_month"
    (21 October), "month_year" (October 2026). American English puts the month first."""
    row = WORDS[f"date.{kind}"]
    lang = language()
    if lang == "en" and country() == "US" and row.get("en_US"):
        return row["en_US"]
    return entry(f"date.{kind}", lang)


def page_words() -> dict:
    """The words presets write on a page, and Home Assistant's state words, in every language, for
    the editor: {key: {language: text}}. A preset writes them in the device's language when the
    page is made; from then on they're the person's own words."""
    return {k: {lang: entry(k, lang) for lang in LANGUAGES} for k in WORDS if k.startswith(("page.", "state."))}


def missing() -> dict[str, list[str]]:
    """Every word a language doesn't have yet: {language: [key, ...]} (said in English meanwhile)."""
    return {lang: sorted(k for k, row in WORDS.items() if row.get(lang) in (None, ""))
            for lang in LANGUAGES}
