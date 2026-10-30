"""Every service outside the add-on, in one list: what it is, where it's reached, what uses it.

The one registry the editor's status card, Settings › Services, health (which service an address
belongs to, so its problem sensor is the right one) and the fetchers (where to ask) all read. A
service is named once here; its name is also its problem sensor's (binary_sensor.epaper_problem_<id>),
so a name never changes.

Two groups:
  "outside"  on the internet (ESPN, the racing calendars, Flightradar24, OpenSky, Iconify). Each has
             one or more addresses, and each address a `probe`: the add-on's own reader run on a test
             answer. Try again runs it at the address in use; Settings › Services can point an
             address at a mirror in the same form, which the probe checks before it's used
             (`set_address`), and Use the original address is the way back.
  "home"     Home Assistant itself (the Energy dashboard, its notifications, its icons): no address
             to change, and Try again asks Home Assistant again.
Your data sources are listed after them (their addresses are edited in Settings › Data sources).

Nothing here fetches on its own: a probe runs only when a person asks (Try again, Check and use).
"""
from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable
from urllib.parse import urlsplit

import config
import health

HEADERS = {"User-Agent": "Crowpanel-Epaper (HomeAssistant Addon)"}
PROBE_LIMIT = 4 * 1024 * 1024          # a test answer bigger than this isn't what any service sends


class Refused(Exception):
    """A probe's answer, in plain words, when an address isn't the service it should be."""


@dataclass(frozen=True)
class Address:
    key: str                                    # "main", or the part's own ("api")
    label: str                                  # what's there, in Settings
    original: str                               # the service's own address: the prefix paths are joined to
    probe: Callable[[Any, str], Awaitable[str]] | None = None   # (session, base) -> what it found, or Refused


@dataclass(frozen=True)
class Service:
    id: str                                     # its problem sensor's slug: feeds.clean_slug(name)
    name: str
    group: str                                  # "outside" or "home"
    gives: str                                  # what it gives, in Settings
    addresses: tuple = ()                       # Address, for an outside service
    uses: Callable[[dict], bool] | None = None  # whether an element of a page reads it
    retry: Callable[[Any], Awaitable[str]] | None = None    # Try again for one with no address
    forget: Callable[[], None] | None = None    # after Try again worked: drop what holds back the next fetch


# ---------------------------------------------------------------- probes: the add-on's own readers, on a test answer

def _http_words(code: int) -> str:
    if code in (401, 403):
        return f"It refused the add-on (error {code})."
    if code in (404, 410):
        return f"It doesn't have what the add-on asks for there (error {code})."
    if code == 429:
        return "It asked the add-on to slow down (error 429). The add-on tries again later on its own."
    if code >= 500:
        return f"It's having trouble on its side (error {code})."
    return f"It answered with error {code}."


def plain(text: str | None) -> str:
    """An error, as a person reads it: what happened, never a Python class name."""
    if not text:
        return ""
    m = re.search(r"\bHTTP (\d{3})\b", text)
    if m:
        return _http_words(int(m.group(1)))
    low = text.lower()
    if "timeout" in low or "timed out" in low:
        return "It didn't answer in time."
    if any(k in low for k in ("dns", "name or service", "nodename", "getaddrinfo", "name resolution")):
        return "Home Assistant couldn't find it on the internet. Check that Home Assistant is online."
    if "certificate" in low or re.search(r"\bssl(error|\b(?!:default))", low):
        return "Its secure connection couldn't be checked."
    if any(k in low for k in ("cannot connect", "connection refused", "connectorerror", "disconnected",
                              "connection reset", "network is unreachable")):
        return "Home Assistant couldn't connect to it. Check that Home Assistant is online."
    if any(k in low for k in ("jsondecode", "contenttype", "unicodedecode", "not in the form")):
        return "It answered, but not in the form the add-on reads."
    if re.match(r"^[A-Z]\w*(Error|Exception)\b", text):
        return "Something went wrong asking it."
    said = text.strip().rstrip(".")
    return said[:1].upper() + said[1:] + "."


async def _get(session, url: str, *, as_text: bool = False, polite: bool = False):
    """A test answer from an address: its JSON (or text), or Refused saying why not. `polite`: the
    add-on names itself with where to reach who runs it, as Wikimedia asks."""
    import aiohttp
    import pacing
    try:
        async with session.get(url, headers={"User-Agent": pacing.user_agent()} if polite else HEADERS, allow_redirects=False,
                               timeout=aiohttp.ClientTimeout(total=20, sock_connect=10),
                               trace_request_ctx=health.Ask(judged=True)) as r:
            if r.status != 200:
                raise Refused(_http_words(r.status))
            raw = await pacing.read_all(r.content, PROBE_LIMIT)     # to its end, not what has arrived so far
    except Refused:
        raise
    except Exception as exc:                    # noqa: BLE001 -- anything on the way is a reason, said plainly
        raise Refused(plain(health.describe(exc))) from None
    if raw is None:
        raise Refused("It answered with far more than the service it stands for sends.")
    text = raw.decode("utf-8", "replace")
    if as_text:
        return text
    try:
        return json.loads(text)
    except ValueError:
        raise Refused("It answered, but not with data the add-on can read (it isn't JSON).") from None


def _many(n: int, one: str, more: str | None = None) -> str:
    return f"{n} {one if n == 1 else (more or one + 's')}"


def _year() -> int:
    return datetime.now(timezone.utc).year


def _races(read, body, what: str) -> list:
    try:
        races = read(body)
    except (ValueError, TypeError, AttributeError, KeyError):
        races = []
    if not races:
        raise Refused(f"It answered, but not with {what} the add-on can read.")
    return races


async def _probe_espn(session, base: str) -> str:
    from sources import sports
    data = await _get(session, f"{base}/soccer/eng.1/scoreboard")
    if not isinstance(data, dict) or not isinstance(data.get("events"), list) or not isinstance(data.get("leagues"), list):
        raise Refused("It answered, but not with a scoreboard the add-on can read.")
    try:
        for ev in data["events"][:3]:
            sports._parse_espn_event(ev, "", None, "soccer/eng.1")
    except (ValueError, TypeError, AttributeError, KeyError, IndexError):
        raise Refused("It answered, but its games aren't in the form the add-on reads.") from None
    return f"Premier League's scoreboard, {_many(len(data['events']), 'game')}"


async def _probe_sessions(session, base: str, path: str, series: str) -> str:
    from sources import racing
    year = _year()
    races = _races(racing._read_sessions, await _get(session, base + path.format(year=year)), "a race calendar")
    return f"{series}'s {year} calendar, {_many(len(races), 'race')}"


async def _probe_racing_calendar(session, base: str) -> str:
    return await _probe_sessions(session, base, "/f1/{year}.json", "Formula 1")


async def _probe_formulaecal(session, base: str) -> str:
    return await _probe_sessions(session, base, "/{year}", "Formula E")


async def _probe_formula_e(session, base: str) -> str:
    from sources import racing
    races = _races(racing._read_events, await _get(session, base, as_text=True), "a race calendar")
    return f"Formula E's calendar, {_many(len(races), 'race')}"


# A box of open sea at 0°, 0°: a flight feed answers it with no planes and no one's home in it.
_SEA = (1.0, -1.0)


async def _probe_flightradar24(session, base: str) -> str:
    hi, lo = _SEA
    data = await _get(session, f"{base}?bounds={hi},{lo},{lo},{hi}&faa=1&air=1&gnd=0")
    if not isinstance(data, dict) or not ({"full_count", "version"} & set(data)):
        raise Refused("It answered, but not with a flight feed the add-on can read.")
    planes = sum(1 for v in data.values() if isinstance(v, list))
    return f"A flight feed, {_many(planes, 'plane')} in the test area"


async def _probe_opensky(session, base: str) -> str:
    hi, lo = _SEA
    data = await _get(session, f"{base}?lamin={lo}&lamax={hi}&lomin={lo}&lomax={hi}")
    if not isinstance(data, dict) or "time" not in data or not isinstance(data.get("states"), (list, type(None))):
        raise Refused("It answered, but not with a flight feed the add-on can read.")
    return f"A flight feed, {_many(len(data.get('states') or []), 'plane')} in the test area"


async def _probe_iconify_sets(session, base: str) -> str:
    import iconsets
    data = await _get(session, f"{base}/collections.json")
    try:
        found = iconsets._available_from(json.dumps(data))
    except (ValueError, TypeError, AttributeError, KeyError):
        found = []
    if not found:
        raise Refused("It answered, but not with Iconify's list of sets.")
    return f"Iconify's list, {_many(len(found), 'set')} e-paper can draw"


async def _probe_iconify_api(session, base: str) -> str:
    data = await _get(session, f"{base}/mdi.json?icons=home")
    if not isinstance(data, dict) or not isinstance((data.get("icons") or {}).get("home"), dict):
        raise Refused("It answered, but not with Iconify's icons.")
    return "Icon previews"


async def _probe_yahoo(session, base: str) -> str:
    from sources import markets
    data = await _get(session, f"{base}/v8/finance/spark?symbols=%5EGSPC,EURUSD%3DX&range=5d&interval=60m", polite=True)
    try:
        got = markets.read_spark(data)
    except ValueError:
        got = {}
    if not got:
        raise Refused("It answered, but not with prices the add-on can read.")
    return f"Prices, {_many(len(got), 'symbol')} in the test"


async def _probe_coingecko(session, base: str) -> str:
    from sources import markets
    data = await _get(session, f"{base}/simple/price?ids=bitcoin&vs_currencies=usd&include_24hr_change=true", polite=True)
    try:
        got = markets.read_coin_prices(data)
    except ValueError:
        got = {}
    if not (got.get("bitcoin") or {}).get("prices"):
        raise Refused("It answered, but not with coin prices the add-on can read.")
    return "Coin prices"


# A page every Wikipedia has, by its title in each: what Try again reads.
_EARTH = {"en": "Earth", "ro": "Pământ", "es": "Tierra", "de": "Erde", "fr": "Terre"}


def _probe_wikipedia(lang: str):
    async def probe(session, base: str) -> str:
        from urllib.parse import quote
        from sources import place
        got = place.read_summary(await _get(session, f"{base}/{quote(_EARTH[lang])}", polite=True))
        if not got:
            raise Refused("It answered, but not with a summary the add-on can read.")
        return f"Summaries in {_LANGUAGE_NAMES[lang]}"
    return probe


async def _probe_wikidata(session, base: str) -> str:
    from sources import place
    try:
        got = place.read_labels(await _get(session, f"{base}?action=wbgetentities&ids=Q2&props=labels&languages=en&format=json",
                                           polite=True), "Q2")
    except ValueError:
        got = {}
    if not got:
        raise Refused("It answered, but not with facts the add-on can read.")
    return "Facts about places"


_LANGUAGE_NAMES = {"en": "English", "ro": "Romanian", "es": "Spanish", "de": "German", "fr": "French"}


# ---------------------------------------------------------------- Try again for Home Assistant's own

async def _retry_icons(session) -> str:
    import iconsets
    import runtime
    iconsets._ha_failed.clear()                 # asked by a person: not held back by the last failure
    said = await iconsets.copy_home_assistant(session, runtime.HASS)
    return "Up to date" if said == "unchanged" else said[:1].upper() + said[1:]


def _direct(module: str, name: str, words: Callable[[Any], str]):
    async def run(session):
        import importlib
        fn = getattr(importlib.import_module(module), name)
        return words(await (getattr(fn, "direct", fn))(session))
    return run


# ---------------------------------------------------------------- which elements read which service

def _theirs(el) -> bool:
    """An element reads the add-on's services, not one of your data sources in their place (shapes.py)."""
    import shapes
    return not shapes.own_source(el)


def _type(*types):
    return lambda el: el.get("type") in types


def _outside(*types):
    return lambda el: el.get("type") in types and _theirs(el)


def _racing(test: Callable[[Any], bool]):
    def uses(el):
        if el.get("type") != "sports_racing" or not _theirs(el):
            return False
        from sources import racing
        return test(racing.series_of(el.get("entity") or el.get("series") or "f1"))      # as widgets._racing asks
    return uses


def _on_calendar(service_id: str):
    return _racing(lambda ser: any(cal.service == service_id for cal in ser.calendars))


def _scores(el) -> bool:
    return el.get("type") == "sports_match" and not str(el.get("entity") or "").strip() and _theirs(el)


def _counts(*which):
    def uses(el):
        if el.get("type") == "badge":
            return str(el.get("counts") or "updates") in (*which, "all")
        return False
    return uses


def _forget_calendars():
    from sources import racing
    racing.forget_failed()


def _either(*tests):
    return lambda el: any(t(el) for t in tests)


def _holds(kind: str):
    """A Stocks and coins element that holds one of this kind ("quote", "coin")."""
    def uses(el):
        if el.get("type") != "markets":
            return False
        from sources import markets
        return any(h.kind == kind for h in markets.holdings_of(el))
    return uses


def _forget(module: str, name: str):
    def run():
        import importlib
        getattr(importlib.import_module(module), name)()
    return run


def _all(*runs):
    def run():
        for r in runs:
            r()
    return run


# ---------------------------------------------------------------- the list

SERVICES: tuple[Service, ...] = (
    Service("espn", "ESPN", "outside", "Scores, and live race results and standings",
            (Address("main", "Scoreboards", "https://site.api.espn.com/apis/site/v2/sports", _probe_espn),),
            uses=_either(_scores, _racing(lambda ser: bool(ser.espn)))),
    Service("racing_calendar", "Racing calendar", "outside", "Race weekends and session times (Formula 1, Formula E, IndyCar)",
            (Address("main", "Calendars", "https://raw.githubusercontent.com/sportstimes/f1/main/_db", _probe_racing_calendar),),
            uses=_on_calendar("racing_calendar"), forget=_forget_calendars),
    Service("formula_e", "Formula E", "outside", "Formula E's own season calendar",
            (Address("main", "Calendar page", "https://www.fiaformulae.com/en/calendar", _probe_formula_e),),
            uses=_on_calendar("formula_e"), forget=_forget_calendars),
    Service("formula_e_calendar", "Formula E calendar", "outside", "Formula E session times",
            (Address("main", "Calendars", "https://formulaecal.com/api/year", _probe_formulaecal),),
            uses=_on_calendar("formula_e_calendar"), forget=_forget_calendars),
    Service("flightradar24", "Flightradar24", "outside", "Planes overhead, and a flight you follow",
            (Address("main", "Flight feed", "https://data-cloud.flightradar24.com/zones/fcgi/feed.js", _probe_flightradar24),),
            uses=_either(_outside("flight_tracker"), _type("flight_follow")), forget=_forget("sources.flights", "forget_follow")),
    Service("opensky", "OpenSky", "outside", "Planes overhead, when Flightradar24 doesn't answer",
            (Address("main", "Flight feed", "https://opensky-network.org/api/states/all", _probe_opensky),),
            uses=_outside("flight_tracker")),
    Service("yahoo_finance", "Yahoo Finance", "outside", "Stock, index and currency prices",
            (Address("main", "Prices", "https://query1.finance.yahoo.com", _probe_yahoo),),
            uses=_holds("quote"), forget=_forget("sources.markets", "forget")),
    Service("coingecko", "CoinGecko", "outside", "Coin prices",
            (Address("main", "Prices", "https://api.coingecko.com/api/v3", _probe_coingecko),),
            uses=_holds("coin"), forget=_forget("sources.markets", "forget_coins")),
    Service("wikipedia", "Wikipedia", "outside", "Place of the day's description",
            tuple(Address(lang, f"Summaries in {name}", f"https://{lang}.wikipedia.org/api/rest_v1/page/summary", _probe_wikipedia(lang))
                  for lang, name in _LANGUAGE_NAMES.items()),
            uses=_type("place_of_day"), forget=_forget("sources.place", "forget")),
    Service("wikidata", "Wikidata", "outside", "Place of the day's facts",
            (Address("main", "Facts", "https://www.wikidata.org/w/api.php", _probe_wikidata),),
            uses=_type("place_of_day"), forget=_forget("sources.place", "forget")),
    Service("iconify", "Iconify", "outside", "Icon sets you add in Settings › Icons",
            (Address("main", "Icon sets", "https://raw.githubusercontent.com/iconify/icon-sets/master", _probe_iconify_sets),
             Address("api", "Previews", "https://api.iconify.design", _probe_iconify_api))),
    Service("icons_from_home_assistant", "Icons from Home Assistant", "home", "Home Assistant's own icons, kept in step with it",
            retry=_retry_icons),
    Service("energy_dashboard", "Energy dashboard", "home", "Energy totals, the grid now and energy cost",
            uses=_type("energy_total", "grid_now", "energy_cost"),
            retry=_direct("sources.energy", "fetch_dashboard", lambda got: "Read the Energy dashboard")),
    Service("home_assistant_notifications", "Home Assistant notifications", "home", "Its notifications",
            uses=_either(_type("notifications"), _counts("notifications")),
            retry=_direct("sources.needs_you", "fetch_notifications", lambda got: _many(len(got or []), "notification"))),
    Service("home_assistant_updates", "Home Assistant updates", "home", "Updates waiting to be installed",
            uses=_either(_type("updates"), _counts("updates")),
            retry=_direct("sources.needs_you", "fetch_updates", lambda got: _many(len(got or []), "update"))),
    Service("home_assistant_repairs", "Home Assistant repairs", "home", "Repairs it suggests",
            uses=_counts("repairs"),
            retry=_direct("sources.needs_you", "fetch_repairs", lambda got: _many(int(got or 0), "repair"))),
)
BY_ID = {s.id: s for s in SERVICES}
BY_NAME = {s.name: s for s in SERVICES}


def get(service_id: str) -> Service | None:
    return BY_ID.get(service_id)


def name(service_id: str) -> str:
    """A service's name, as health records it (and its problem sensor is called)."""
    return BY_ID[service_id].name


# ---------------------------------------------------------------- addresses: the original, or the person's own

def _path() -> Path:
    return config.DATA_DIR / "services.json"


_overrides: tuple[Path, dict] | None = None     # (the file it was read from, what it says)


def overrides() -> dict:
    """{service id: {address key: url}}: only what the person changed; nothing here means the originals."""
    global _overrides
    p = _path()
    if _overrides is None or _overrides[0] != p:
        try:
            got = json.loads(p.read_text())
        except (OSError, ValueError):
            got = {}
        _overrides = (p, {sid: {k: v for k, v in keys.items() if isinstance(v, str) and _address(sid, k)}
                          for sid, keys in (got if isinstance(got, dict) else {}).items()
                          if sid in BY_ID and isinstance(keys, dict)})
    return _overrides[1]


def _save(found: dict) -> None:
    global _overrides
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({k: v for k, v in found.items() if v}, indent=2))
    tmp.replace(p)
    _overrides = None


def _address(service_id: str, key: str = "main") -> Address | None:
    s = BY_ID.get(service_id)
    return next((a for a in s.addresses if a.key == key), None) if s else None


def url(service_id: str, key: str = "main") -> str:
    """Where to ask a service: the person's own address for it, or its original."""
    a = _address(service_id, key)
    if a is None:
        raise KeyError(f"{service_id}/{key}")
    return overrides().get(service_id, {}).get(key) or a.original


def _split(address: str) -> tuple[str, str]:
    parts = urlsplit(address)
    return (parts.hostname or "").lower(), parts.path.rstrip("/")


def addresses() -> list[tuple[str, str, str]]:
    """(host, path prefix, service name) for every address in use or original: health's map
    (health.service_for), so a mirror reports as its service and the original still does too."""
    out = []
    for s in SERVICES:
        for a in s.addresses:
            for where in {a.original, url(s.id, a.key)}:
                host, path = _split(where)
                out.append((host, path, s.name))
    return out


def clean_address(raw: str) -> str:
    """An address as stored: https or http, a host, no query or fragment, no trailing slash."""
    text = str(raw or "").strip()
    parts = urlsplit(text)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise Refused("That isn't a web address. It starts with https://, like https://mirror.example.com/calendars.")
    if parts.query or parts.fragment or "{" in text or "}" in text:
        raise Refused("Leave out anything after ? or # and any { }: the add-on adds what it asks for itself.")
    if parts.username or parts.password:
        raise Refused("Leave out a name and password: the add-on can't send them safely in an address.")
    return text.rstrip("/")


async def set_address(session, service_id: str, key: str, raw: str | None) -> dict:
    """Use another address for a service, once its probe reads a test answer from it; None or ""
    (or the original itself) goes back to the original. Returns {said} or raises Refused/KeyError."""
    a = _address(service_id, key)
    if a is None or a.probe is None:
        raise KeyError(f"{service_id}/{key}")
    found = {sid: dict(keys) for sid, keys in overrides().items()}
    if not raw or clean_address(raw) == a.original.rstrip("/"):
        found.get(service_id, {}).pop(key, None)
        _save(found)
        return {"said": "Back to the original address."}
    address = clean_address(raw)
    said = await a.probe(session, address)
    found.setdefault(service_id, {})[key] = address
    _save(found)
    return {"said": said}


# ---------------------------------------------------------------- Try again

async def try_again(session, service_id: str) -> dict:
    """Ask a service now, the way the add-on does, and say what came back. Asked by a person."""
    import runtime
    s = BY_ID.get(service_id)
    if s is not None:
        try:
            if s.addresses:
                said = [await a.probe(session, url(s.id, a.key)) for a in s.addresses if a.probe]
                text = "; ".join(said)
            else:
                text = await s.retry(session)
        except Refused as exc:
            health.fail(s.name, str(exc))
            return {"ok": False, "error": str(exc)}
        except Exception as exc:                # noqa: BLE001 -- said plainly, and recorded as health would
            text = health.fail(s.name, exc)
            return {"ok": False, "error": plain(text)}
        health.ok(s.name)
        if s.forget:
            s.forget()
    else:
        src = _source(service_id)
        if src is None:
            raise KeyError(service_id)
        import feeds
        import shapes
        label = source_name(src)
        try:
            if feeds.fills(src):                # one that fills a page: read in the add-on's form for it
                kind = feeds.fills(src)
                items = shapes.read(kind, await feeds.fetch_json(src, session))
                text = f"{shapes.get(kind).name} pages' data, {shapes.get(kind).summary(items)}"
            else:
                rows = await feeds.run_one(src, {"ha_base": config.HA_BASE, "ha_token": config.HA_TOKEN, "session": session})
                text = _many(len(rows), "value")
        except ValueError as exc:
            return {"ok": False, "error": plain(health.fail(label, str(exc), kind="source"))}
        except Exception as exc:                # noqa: BLE001
            return {"ok": False, "error": plain(health.fail(label, exc, kind="source"))}
        health.ok(label, kind="source")
    runtime.LIVE.retry_failed()                 # what failed before is asked again at once
    return {"ok": True, "said": text}


# ---------------------------------------------------------------- your data sources

def source_name(src: dict) -> str:
    import feeds
    return f"Source “{feeds.clean_slug(src.get('name'))}”"


def _sources() -> list[dict]:
    from layouts_store import load_sources
    import feeds
    return [s for s in load_sources() if isinstance(s, dict) and s.get("type") in feeds.REGISTRY and feeds.clean_slug(s.get("name"))]


def _source(service_id: str) -> dict | None:
    import feeds
    return next((s for s in _sources() if feeds.clean_slug(source_name(s)) == service_id), None)


def _source_uses(src: dict) -> Callable[[dict], bool]:
    """A page's element uses a source: it shows one of its sensors, or reads it in place of the
    add-on's services (shapes.py)."""
    import feeds
    import shapes
    ids = set(feeds.source_entities(src))
    return lambda el: (bool(src.get("id")) and shapes.own_source(el) == src.get("id")) or any(i in json.dumps(el) for i in ids)


# ---------------------------------------------------------------- what Settings and the status card read

def _pages_using(uses, pages_of) -> list[str]:
    if uses is None:
        return []
    out = []
    for page_name, page in pages_of:
        if any(isinstance(el, dict) and uses(el) for el in (page.get("elements") or [])) and page_name not in out:
            out.append(page_name)
    return out


def _all_pages() -> list[tuple[str, dict]]:
    """Every page of every design a device shows: what the add-on fetches for."""
    import devices
    out = []
    for design_id in sorted(devices.designs_in_use()):
        for page_name, page in (devices.design(design_id).get("pages") or {}).items():
            if isinstance(page, dict):
                out.append((page_name, page))
    return out


def _state(name: str, known: dict) -> dict:
    e = known.get(name)
    if e is None:
        return {"asked": False, "ok_at": None, "failing_since": None, "problem": False, "error": None, "plain": ""}
    return {"asked": True, "ok_at": e["ok_at"], "failing_since": e["failing_since"], "problem": e["problem"],
            "error": e["error"], "plain": plain(e["error"])}


def listing(pages=None) -> list[dict]:
    """Every service, for Settings › Services: outside ones, Home Assistant's, then your data sources;
    what uses it, its state (health), and its addresses."""
    import feeds
    pages = _all_pages() if pages is None else pages
    known = {e["name"]: e for e in health.status()}
    out = []
    for s in SERVICES:
        out.append({"id": s.id, "name": s.name, "group": s.group, "gives": s.gives, "by_pages": s.uses is not None,
                    "used_by": _pages_using(s.uses, pages), "can_try": bool(s.addresses or s.retry),
                    "addresses": [{"key": a.key, "label": a.label, "original": a.original, "current": url(s.id, a.key),
                                   "changeable": a.probe is not None} for a in s.addresses],
                    **_state(s.name, known)})
    for src in _sources():
        label = source_name(src)
        out.append({"id": feeds.clean_slug(label), "name": label, "group": "source", "gives": "", "source_id": src.get("id"), "by_pages": True,
                    "used_by": _pages_using(_source_uses(src), pages), "can_try": True, "addresses": [],
                    **_state(label, known)})
    listed = {s["name"] for s in out}
    for e in health.status():                   # anything else that reports (a source since removed, say)
        if e["name"] not in listed:
            out.append({"id": feeds.clean_slug(e["name"]), "name": e["name"], "group": "source" if e["kind"] == "source" else "outside",
                        "gives": "", "used_by": [], "can_try": False, "addresses": [], **_state(e["name"], known)})
    return out


def problems() -> list[dict]:
    """The services whose problem sensor is on, for the status card: id, name, since when, why."""
    out = []
    for e in health.status():
        if e["problem"]:
            import feeds
            out.append({"id": feeds.clean_slug(e["name"]), "name": e["name"], "since": e["failing_since"],
                        "error": e["error"], "plain": plain(e["error"])})
    return out
