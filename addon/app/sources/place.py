"""Place of the day: a city or a wonder, the same for everyone on a given day.

The places are the add-on's own list (reference/places.json), spread across the world, so the
page works with nothing fetched: its name, region, country and local time are always there. Once a
day, for that day's place only, the add-on asks:

  * Wikipedia (its summary endpoint) for a short description, in each language a screen speaks;
  * Wikidata for its facts: population, elevation, its region in each language, where it is;
  * OpenStreetMap (the Overpass API) for the streets and water around it, drawn as lines
    (render/place.py), never as map pictures: OpenStreetMap's tile servers don't allow fetching
    tiles nobody is looking at, and e-paper wants hard edges, not dithered pictures.

All of it is kept on disk for the day, so a restart asks nothing again, and each part is asked
only until it's in (a part that fails is asked again within the hour, with longer waits after
each failure: pacing.py). One place a day is about ten requests in all, far inside every one of
these services' fair use. Their credits are drawn on the page: Wikipedia, © OpenStreetMap
contributors (its licence asks for it).

Every device with the page shows the same place on the same day: the day is Home Assistant's.
"""
from __future__ import annotations

import hashlib
import json
import math
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
WIKIPEDIA, WIKIDATA, OSM = "wikipedia", "wikidata", "openstreetmap"
RETRY = 1800                       # a part that didn't come in is asked again within half an hour (paced)
PACE_WIKI = pacing.Pace("Wikipedia", first=RETRY, most=6 * 3600)
PACE_DATA = pacing.Pace("Wikidata", first=RETRY, most=6 * 3600)
PACE_OSM = pacing.Pace("OpenStreetMap", first=RETRY, most=6 * 3600)
EXTRACT_MOST = 600                 # characters of description kept: more than any screen shows

ROADS = {"motorway": "major", "trunk": "major", "primary": "major", "secondary": "major",
         "tertiary": "minor", "unclassified": "minor", "residential": "minor", "living_street": "minor",
         "pedestrian": "minor", "footway": "path", "path": "path", "track": "path", "steps": "path"}


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
            "lat": place["lat"], "lon": place["lon"], "tz": place["tz"], "kind": place["kind"], "km": place["km"],
            "names": {}, "regions": {}, "summary": {}, "population": None, "elevation": None, "map": None}


# ---------------------------------------------------------------- reading the answers

def read_summary(body) -> dict | None:
    """Wikipedia's page summary -> {title, text, qid, lat, lon}; None for a page that isn't one
    (a disambiguation page, a missing one)."""
    if not isinstance(body, dict) or body.get("type") not in ("standard", None) or not body.get("extract"):
        return None
    text = " ".join(str(body.get("extract") or "").split())
    if len(text) > EXTRACT_MOST:
        text = text[:EXTRACT_MOST].rsplit(" ", 1)[0] + "…"
    coords = body.get("coordinates") or {}
    return {"title": str(body.get("title") or ""), "text": text, "qid": str(body.get("wikibase_item") or ""),
            "lat": coords.get("lat"), "lon": coords.get("lon")}


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
    lat, lon, region: its region's id}. Raises ValueError for an answer of another form."""
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
    at = next(iter(_best(_claims(e, "P625"))), None)
    lat = lon = None
    if at and isinstance(_value(at), dict):
        lat, lon = _value(at).get("latitude"), _value(at).get("longitude")
    # Its region now: preferred, else one that hasn't ended (P582), as Wikidata lists them.
    regions = [c for c in _best(_claims(e, "P131")) if not (c.get("qualifiers") or {}).get("P582")]
    region = (_value(regions[0]) or {}).get("id", "") if regions else ""
    return {"titles": titles, "names": names, "population": round(population) if population else None,
            "elevation": round(elevation) if elevation is not None else None, "lat": lat, "lon": lon, "region": region}


def read_labels(body, qid: str) -> dict:
    try:
        labels = body["entities"][qid].get("labels") or {}
    except (KeyError, TypeError):
        raise ValueError("no entity") from None
    return {k: v.get("value") for k, v in labels.items() if k in LANGUAGES and isinstance(v, dict) and v.get("value")}


def _metres(lat0: float, lon0: float):
    k = math.cos(math.radians(lat0))
    return lambda lat, lon: (round((lon - lon0) * 111320.0 * k), round((lat - lat0) * 110540.0))


def read_map(body, lat: float, lon: float) -> dict:
    """OpenStreetMap's ways (Overpass, out geom) -> {"lines": [[kind, [[x, y], ...]]], "areas": [...]},
    in metres east and north of the place, a point dropped when it's within 2 m of the last."""
    if not isinstance(body, dict) or not isinstance(body.get("elements"), list):
        raise ValueError("no elements")
    to = _metres(lat, lon)
    lines, areas = [], []
    for el in body["elements"]:
        if not isinstance(el, dict) or not isinstance(el.get("geometry"), list):
            continue
        tags = el.get("tags") or {}
        pts = []
        for g in el["geometry"]:
            try:
                p = to(float(g["lat"]), float(g["lon"]))
            except (KeyError, TypeError, ValueError):
                continue
            if not pts or abs(p[0] - pts[-1][0]) + abs(p[1] - pts[-1][1]) > 2:
                pts.append(list(p))
        if len(pts) < 2:
            continue
        closed = pts[0] == pts[-1] or (el["geometry"][0] == el["geometry"][-1])
        if tags.get("natural") == "water" or tags.get("waterway") == "riverbank" or (tags.get("water") and closed):
            if len(pts) >= 3:
                areas.append(["water", pts])
        elif tags.get("waterway") in ("river", "canal"):
            lines.append(["river", pts])
        elif tags.get("waterway") == "stream":
            lines.append(["stream", pts])
        elif tags.get("highway") in ROADS:
            lines.append([ROADS[tags["highway"]], pts])
    order = {"stream": 0, "river": 1, "path": 2, "minor": 3, "major": 4}
    lines.sort(key=lambda ln: order.get(ln[0], 0))
    return {"lines": lines, "areas": areas}


def overpass_query(lat: float, lon: float, km: float, paths: bool) -> str:
    """The streets and water within a square `km` across, centred on the place."""
    dy = km / 2 / 110.54
    dx = km / 2 / (111.32 * max(0.05, math.cos(math.radians(lat))))
    box = f"{lat - dy:.5f},{lon - dx:.5f},{lat + dy:.5f},{lon + dx:.5f}"
    kinds = "|".join(k for k, v in ROADS.items() if paths or v != "path")
    return (f'[out:json][timeout:25][bbox:{box}];(way["highway"~"^({kinds})$"];way["natural"="water"];'
            f'way["waterway"~"^(river|canal|stream|riverbank)$"];);out geom qt;')


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
    for pace in (PACE_WIKI, PACE_DATA, PACE_OSM):
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
            if facts["lat"] is not None and facts["lon"] is not None:
                entry["lat"], entry["lon"] = facts["lat"], facts["lon"]
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
        if "map" not in done:
            q = overpass_query(entry["lat"], entry["lon"], float(entry["km"]), paths=entry.get("kind") == "wonder")
            body = await pacing.get(session, services.url(OSM), PACE_OSM, method="POST", data={"data": q}, timeout=40)
            try:
                entry["map"] = read_map(body, entry["lat"], entry["lon"])
            except ValueError:
                pacing.unreadable(PACE_OSM, "map data")
                raise LookupError("map") from None
            pacing.answered(PACE_OSM)
            done.add("map")
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
    return bool(entry) and {"qid", "facts", "map"} <= set(entry.get("done") or [])
