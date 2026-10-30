"""Place of the day: a city or a wonder, the same for everyone on a given day.

The places are the add-on's own list (reference/places.json), spread across the world, so the
page works with nothing fetched: its name, region, country and local time are always there. Once a
day, for that day's place only, the add-on asks:

  * Wikipedia (its summary endpoint) for a short description, in each language a screen speaks;
  * Wikidata for its facts: population, elevation, its region in each language.

All of it is kept on disk for the day, so a restart asks nothing again, and each part is asked
only until it's in (a part that fails is asked again within the hour, with longer waits after
each failure: pacing.py). One place a day is about eight requests in all, far inside both
services' fair use. Wikipedia is credited on the page, as its licence asks.

There's no map: the user's call (30 Oct), small screens don't show one well.

Every device with the page shows the same place on the same day: the day is Home Assistant's.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote

import config
import pacing
import runtime
import services
from render.words import LANGUAGES

LIST = Path(__file__).resolve().parent.parent / "reference" / "places.json"
WIKIPEDIA, WIKIDATA = "wikipedia", "wikidata"
RETRY = 1800                       # a part that didn't come in is asked again within half an hour (paced)
PACE_WIKI = pacing.Pace("Wikipedia", first=RETRY, most=6 * 3600)
PACE_DATA = pacing.Pace("Wikidata", first=RETRY, most=6 * 3600)
EXTRACT_MOST = 600                 # characters of description kept: more than any screen shows



@lru_cache(maxsize=1)
def places() -> tuple:
    return tuple(json.loads(LIST.read_text(encoding="utf-8"))["places"])


def continent(p: dict) -> str:
    """Where in the world a place is, as its time zone says ("Europe", "America", "Asia"...)."""
    return str(p["tz"]).split("/", 1)[0].replace("Australia", "Pacific")


@lru_cache(maxsize=1)
def _order() -> tuple:
    """The list in a fixed order that hops around the world: each continent's places are spread
    evenly through the cycle (in an order of their own, by a hash of each id), so a week visits
    several continents. A place added to the list moves which day has which."""
    groups: dict[str, list] = {}
    for p in sorted(places(), key=lambda p: hashlib.sha256(p["id"].encode()).hexdigest()):
        groups.setdefault(continent(p), []).append(p)
    spread = [((k + 0.5) / len(g), name, p) for name, g in sorted(groups.items()) for k, p in enumerate(g)]
    return tuple(p for _, _, p in sorted(spread, key=lambda t: (t[0], t[1])))


def of_day(day: date) -> dict:
    """The place a day shows: the same for every device and every add-on on that day."""
    order = _order()
    return order[day.toordinal() % len(order)]


def offline(place: dict) -> dict:
    """What the page knows with nothing fetched: the list's own facts."""
    return {"id": place["id"], "name": place["name"], "region": place["region"], "country": place["country"],
            "tz": place["tz"], "names": {}, "regions": {}, "summary": {}, "population": None, "elevation": None}


# ---------------------------------------------------------------- reading the answers

def read_summary(body) -> dict | None:
    """Wikipedia's page summary -> {title, text, qid}; None for a page that isn't one
    (a disambiguation page, a missing one)."""
    if not isinstance(body, dict) or body.get("type") not in ("standard", None) or not body.get("extract"):
        return None
    text = " ".join(str(body.get("extract") or "").split())
    if len(text) > EXTRACT_MOST:
        text = text[:EXTRACT_MOST].rsplit(" ", 1)[0] + "…"
    return {"title": str(body.get("title") or ""), "text": text, "qid": str(body.get("wikibase_item") or "")}


def _claims(entity: dict, prop: str) -> list:
    return [c for c in (entity.get("claims") or {}).get(prop) or [] if c.get("rank") != "deprecated"
            and (c.get("mainsnak") or {}).get("snaktype") == "value"]


def _value(c):
    return ((c.get("mainsnak") or {}).get("datavalue") or {}).get("value")


def _when(c) -> str:
    q = (c.get("qualifiers") or {}).get("P585") or []
    try:
        return str(q[0]["datavalue"]["value"]["time"])
    except (KeyError, IndexError, TypeError):
        return ""


def _best(cs: list) -> list:
    """Wikidata's own pick: its preferred statements, else every normal one."""
    preferred = [c for c in cs if c.get("rank") == "preferred"]
    return preferred or cs


def _amount(v) -> float | None:
    try:
        return float(str(v["amount"]).lstrip("+"))
    except (KeyError, TypeError, ValueError):
        return None


FOOT = "http://www.wikidata.org/entity/Q3710"


def read_entity(body, qid: str) -> dict:
    """Wikidata's entity -> {titles: {lang: title}, names: {lang: label}, population, elevation (m),
    region: its region's id}. Raises ValueError for an answer of another form."""
    try:
        e = body["entities"][qid]
    except (KeyError, TypeError):
        raise ValueError("no entity") from None
    titles = {k[:-4]: v.get("title") for k, v in (e.get("sitelinks") or {}).items()
              if k.endswith("wiki") and k[:-4] in LANGUAGES and isinstance(v, dict)}
    names = {k: v.get("value") for k, v in (e.get("labels") or {}).items() if k in LANGUAGES and isinstance(v, dict)}
    pops = _best(_claims(e, "P1082"))
    pop = max(pops, key=_when, default=None)            # the latest count Wikidata stands by
    population = _amount(_value(pop)) if pop else None
    ele = next(iter(_best(_claims(e, "P2044"))), None)
    elevation = None
    if ele:
        v = _value(ele)
        elevation = _amount(v)
        if elevation is not None and isinstance(v, dict) and v.get("unit") == FOOT:
            elevation *= 0.3048
    # Its region now: preferred, else one that hasn't ended (P582), as Wikidata lists them.
    regions = [c for c in _best(_claims(e, "P131")) if not (c.get("qualifiers") or {}).get("P582")]
    region = (_value(regions[0]) or {}).get("id", "") if regions else ""
    return {"titles": titles, "names": names, "population": round(population) if population else None,
            "elevation": round(elevation) if elevation is not None else None, "region": region}


def read_labels(body, qid: str) -> dict:
    try:
        labels = body["entities"][qid].get("labels") or {}
    except (KeyError, TypeError):
        raise ValueError("no entity") from None
    return {k: v.get("value") for k, v in labels.items() if k in LANGUAGES and isinstance(v, dict) and v.get("value")}


# ---------------------------------------------------------------- the day's place, asked part by part

def _path() -> Path:
    return config.DATA_DIR / "place_of_the_day.json"


def _load(day: str, place: dict) -> dict:
    try:
        got = json.loads(_path().read_text(encoding="utf-8"))
        if got.get("day") == day and got.get("id") == place["id"]:
            return got
    except (OSError, ValueError, AttributeError):
        pass
    return {"day": day, **offline(place), "done": []}


def _save(entry: dict) -> None:
    p = _path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(entry, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        tmp.replace(p)
    except OSError as exc:
        print(f"place of the day: couldn't keep today's place ({exc})", flush=True)


def forget() -> None:
    """Try again: every part not in yet is asked at once."""
    for pace in (PACE_WIKI, PACE_DATA):
        pace.forget()


async def _summary(session, lang: str, title: str) -> dict | None:
    url = f"{services.url(WIKIPEDIA, lang)}/{quote(title.replace(' ', '_'), safe='')}"
    try:
        body = await pacing.get(session, url, PACE_WIKI, missing_ok=True)
    except pacing.Missing:
        return None
    pacing.answered(PACE_WIKI)
    return read_summary(body)


async def fill(session, entry: dict, place: dict) -> bool:
    """Ask for each part of the day's place not in yet. Returns whether anything came in. A part
    that fails is left for the next time (live_data, at most every RETRY, paced)."""
    done, changed = set(entry.get("done") or []), False
    try:
        if "qid" not in done:
            got = await _summary(session, "en", place["wiki"])
            if got:
                entry["summary"]["en"] = got["text"]
                entry["qid"] = got["qid"]
            done.add("qid")
            changed = True
        qid = entry.get("qid") or ""
        if qid and "facts" not in done:
            body = await pacing.get(session, f"{services.url(WIKIDATA)}?action=wbgetentities&ids={qid}&props=claims|labels|sitelinks"
                                             f"&languages={'|'.join(LANGUAGES)}&sitefilter={'|'.join(l + 'wiki' for l in LANGUAGES)}&format=json",
                                    PACE_DATA)
            try:
                facts = read_entity(body, qid)
            except ValueError:
                pacing.unreadable(PACE_DATA, "facts")
                raise LookupError("facts") from None
            pacing.answered(PACE_DATA)
            entry.update(titles=facts["titles"], names=facts["names"], population=facts["population"],
                         elevation=facts["elevation"], region_id=facts["region"])
            done.add("facts")
            changed = True
        rid = entry.get("region_id") or ""
        if rid and "region" not in done:
            body = await pacing.get(session, f"{services.url(WIKIDATA)}?action=wbgetentities&ids={rid}&props=labels"
                                             f"&languages={'|'.join(LANGUAGES)}&format=json", PACE_DATA)
            try:
                entry["regions"] = read_labels(body, rid)
            except ValueError:
                pacing.unreadable(PACE_DATA, "facts")
                raise LookupError("region") from None
            pacing.answered(PACE_DATA)
            done.add("region")
            changed = True
        for lang in LANGUAGES:
            if lang == "en" or f"summary:{lang}" in done or "facts" not in done:
                continue
            title = (entry.get("titles") or {}).get(lang)
            got = await _summary(session, lang, title) if title else None
            if got:
                entry["summary"][lang] = got["text"]
            done.add(f"summary:{lang}")
            changed = True
    except LookupError:
        pass                                    # said by health; the rest waits for the next time
    finally:
        entry["done"] = sorted(done)
        if changed:
            _save(entry)
    return changed


@runtime.live(RETRY)
async def fetch_place(session, day: str):
    """The day's place (a day in Home Assistant's time zone, "2026-10-30"), with what has come in."""
    try:
        d = date.fromisoformat(day)
    except ValueError:
        return None
    place = of_day(d)
    entry = _load(day, place)
    await fill(session, entry, place)
    return entry


def complete(entry: dict | None) -> bool:
    return bool(entry) and {"qid", "facts"} <= set(entry.get("done") or [])
