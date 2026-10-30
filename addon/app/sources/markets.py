"""What you hold, on any market: stocks, indices and currencies (Yahoo Finance), coins (CoinGecko).

A holding is a symbol on any exchange as Yahoo Finance writes it (TLV.RO is Banca Transilvania in
Bucharest, SAP.DE is SAP in Frankfurt, 7203.T is Toyota in Tokyo, ^GDAXI is the DAX, EURRON=X is a
euro in lei), or a coin by its CoinGecko id (bitcoin) priced in a currency of yours. Each shows in
its own currency, with the price, the day's change and the past week as a line.

Asking carefully, since both services are free and owe us nothing:
  * one request for every symbol a page shows (Yahoo's spark, 20 at a time), one for every coin
    (CoinGecko's markets, for the week's line) and one for all their prices in every currency asked;
  * every five minutes at most, and not at all while every exchange a page shows is closed and its
    closing price is already in (it's asked again when the first one opens);
  * what a symbol is (its name, currency, exchange and hours) once a day;
  * after a failure, longer and longer waits (pacing.py), Retry-After honoured; the last prices
    stay on the page with their age (render/markets.py), never an endless retry;
  * a symbol no page shows any more is no longer asked for: live_data forgets what nobody reads.

Sources chosen (30 Oct 2026): Stooq's quotes went away and its history now needs a browser, so
stocks come from Yahoo Finance's chart endpoints, which need no key and cover every exchange Yahoo
lists (Bucharest included). They're unofficial: Yahoo publishes no terms or limits for them and
may change them. CoinGecko's public API needs no key either; its free use asks for credit
("Data from CoinGecko", drawn on the page). Both are in services.py, so a mirror can stand in.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from zoneinfo import ZoneInfo

import pacing
import runtime
import services

YAHOO, COINGECKO = "yahoo_finance", "coingecko"
EVERY = 300                         # prices: at most every five minutes
ABOUT_EVERY = 86400                 # what a symbol is: once a day
MOST = 8                            # holdings on one page
BATCH = 20                          # symbols in one request
PACE_YAHOO = pacing.Pace("Yahoo Finance", first=EVERY, most=3 * 3600)
PACE_GECKO = pacing.Pace("CoinGecko", first=EVERY, most=3 * 3600)

_SYMBOL = re.compile(r"^[A-Z0-9^][A-Z0-9.\-=^&]{0,23}$")
_COIN = re.compile(r"^[a-z0-9][a-z0-9\-]{0,63}$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")


@dataclass(frozen=True)
class Holding:
    kind: str                       # "quote" (Yahoo) or "coin" (CoinGecko)
    symbol: str                     # TLV.RO, or a coin's id: bitcoin
    currency: str = ""              # a coin's: what it's priced in ("" is Home Assistant's)
    label: str = ""                 # your own name for it


def clean_symbol(raw) -> str:
    s = str(raw or "").strip().upper().replace(" ", "")
    return s if _SYMBOL.match(s) else ""


def clean_coin(raw) -> str:
    s = str(raw or "").strip().lower()
    return s if _COIN.match(s) else ""


def clean_currency(raw) -> str:
    s = str(raw or "").strip().upper()
    return s if _CURRENCY.match(s) else ""


def holdings_of(el: dict) -> list[Holding]:
    """The holdings an element shows, cleaned, in its order, at most MOST, each once."""
    out, seen = [], set()
    for h in (el.get("holdings") or []) if isinstance(el, dict) else []:
        if not isinstance(h, dict):
            continue
        if h.get("coin"):
            got = Holding("coin", clean_coin(h.get("coin")), clean_currency(h.get("currency")), str(h.get("label") or "").strip()[:40])
        else:
            got = Holding("quote", clean_symbol(h.get("symbol")), "", str(h.get("label") or "").strip()[:40])
        key = (got.kind, got.symbol, got.currency)
        if got.symbol and key not in seen:
            seen.add(key)
            out.append(got)
    return out[:MOST]


# ---------------------------------------------------------------- reading Yahoo's answers

def _num(v) -> float | None:
    if isinstance(v, bool) or v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f and abs(f) != float("inf") else None


def read_spark(body) -> dict:
    """Yahoo's spark answer -> {symbol: {price, previous, change, change_pct, trend, traded_at}}.
    A symbol Yahoo doesn't know is left out. Raises ValueError for an answer of another form."""
    if not isinstance(body, dict):
        raise ValueError("not a set of symbols")
    out = {}
    for sym, v in body.items():
        if not isinstance(v, dict) or not isinstance(v.get("close"), list):
            continue
        closes = [c for c in (_num(x) for x in v["close"]) if c is not None]
        stamps = [t for t in v.get("timestamp") or [] if isinstance(t, (int, float))]
        price = _num(v.get("fulldayPrice")) if _num(v.get("fulldayPrice")) is not None else (closes[-1] if closes else None)
        if price is None:
            continue
        prev = _num(v.get("previousClose"))
        change = _num(v.get("fulldayChange"))
        pct = _num(v.get("fulldayChangePercent"))
        if change is None and prev:
            change = price - prev
        if pct is None and prev:
            pct = (price - prev) / prev * 100
        out[str(sym).upper()] = {"price": price, "previous": prev, "change": change, "change_pct": pct,
                                 "trend": closes[-60:], "traded_at": max(stamps) if stamps else None}
    return out


def _hm(ts, tz: ZoneInfo) -> str:
    """An exchange's opening or closing, as data ("10:00", always 24-hour): never shown."""
    t = datetime.fromtimestamp(ts, tz)
    return f"{t.hour:02d}:{t.minute:02d}"


def read_chart(body) -> dict:
    """Yahoo's chart answer -> what a symbol is: {name, currency, exchange, tz, kind, opens, closes,
    decimals}. Raises ValueError for an answer of another form."""
    try:
        meta = body["chart"]["result"][0]["meta"]
    except (KeyError, IndexError, TypeError):
        raise ValueError("no symbol in it") from None
    tz_name = str(meta.get("exchangeTimezoneName") or "UTC")
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz, tz_name = ZoneInfo("UTC"), "UTC"
    reg = ((meta.get("currentTradingPeriod") or {}).get("regular") or {})
    opens = _hm(reg["start"], tz) if isinstance(reg.get("start"), (int, float)) else ""
    closes = _hm(reg["end"], tz) if isinstance(reg.get("end"), (int, float)) else ""
    name = " ".join(str(meta.get("longName") or meta.get("shortName") or meta.get("symbol") or "").split())
    try:
        decimals = max(0, min(6, int(meta.get("priceHint"))))
    except (TypeError, ValueError):
        decimals = 2
    currency = str(meta.get("currency") or "")
    pair = re.match(r"^[A-Z]{3}([A-Z]{3})=X$", str(meta.get("symbol") or ""))
    if not currency and pair:                       # a currency pair is priced in its second currency
        currency = pair.group(1)
    return {"name": name, "currency": currency, "tz": tz_name,
            "exchange": str(meta.get("fullExchangeName") or meta.get("exchangeName") or ""),
            "kind": str(meta.get("instrumentType") or "").upper(), "opens": opens, "closes": closes,
            "decimals": decimals}


# ---------------------------------------------------------------- open or closed

def _local_minutes(hm: str) -> int | None:
    try:
        h, m = hm.split(":")
        return int(h) * 60 + int(m)
    except (ValueError, AttributeError):
        return None


def state(about: dict | None, traded_at, now: datetime) -> dict:
    """Whether a symbol's market is trading now, and what its change is: {"open": bool, "since":
    the day its last trade was, in its exchange's time zone, ISO}. Open means traded today, within
    its hours, on a weekday; a holiday or a stock not yet traded today counts as closed, so the
    change shown is said to be the last session's, never shown as live."""
    about = about or {}
    try:
        tz = ZoneInfo(about.get("tz") or "UTC")
    except Exception:
        tz = ZoneInfo("UTC")
    local = now.astimezone(tz)
    if about.get("kind") == "CRYPTOCURRENCY":
        return {"open": True, "since": local.date().isoformat()}
    if not isinstance(traded_at, (int, float)):
        return {"open": False, "since": ""}
    last = datetime.fromtimestamp(traded_at, tz)
    lo, hi = _local_minutes(about.get("opens", "")), _local_minutes(about.get("closes", ""))
    mins = local.hour * 60 + local.minute
    within = lo is not None and hi is not None and (lo <= mins < hi if lo < hi else (mins >= lo or mins < hi))
    is_open = local.weekday() < 5 and last.date() == local.date() and within
    return {"open": is_open, "since": last.date().isoformat()}


def next_open(about: dict | None, now: datetime) -> datetime | None:
    """When a symbol's exchange next opens (its hours, on the next weekday), or None if unknown."""
    about = about or {}
    lo = _local_minutes(about.get("opens", ""))
    if lo is None:
        return None
    try:
        tz = ZoneInfo(about.get("tz") or "UTC")
    except Exception:
        return None
    local = now.astimezone(tz)
    day = local.replace(hour=lo // 60, minute=lo % 60, second=0, microsecond=0)
    while day <= local or day.weekday() >= 5:
        day += timedelta(days=1)
    return day


# ---------------------------------------------------------------- fetching

_about: dict[str, dict] = {}                  # symbol -> {"at", "about"} (or "missing")
_last_quotes: dict[tuple, dict] = {}          # symbols -> {"at", "quotes"}: what the closed-market rest keeps


def forget() -> None:
    """Try again: ask at once, closed or not."""
    PACE_YAHOO.forget()
    _last_quotes.clear()


def forget_coins() -> None:
    PACE_GECKO.forget()


def about_known(symbol: str) -> dict | None:
    got = _about.get(symbol)
    return got.get("about") if got else None


@runtime.live(3600)
async def fetch_about(session, symbol: str):
    """What a symbol is, read once a day (asked again within the hour after a failure):
    read_chart's fields, or {"missing": True} when Yahoo doesn't know it."""
    t = time.time()
    got = _about.get(symbol)
    if got and t - got["at"] < ABOUT_EVERY:
        return got["about"]
    url = f"{services.url(YAHOO)}/v8/finance/chart/{quote(symbol, safe='')}?range=1d&interval=1d"
    try:
        body = await pacing.get(session, url, PACE_YAHOO, missing_ok=True)
    except pacing.Missing:
        about = {"missing": True}
    else:
        try:
            about = read_chart(body)
        except ValueError:
            pacing.unreadable(PACE_YAHOO, "symbol")
            raise
        pacing.answered(PACE_YAHOO)
    _about[symbol] = {"at": t, "about": about}
    runtime.prune(_about, 2 * ABOUT_EVERY)
    return about


def _resting(symbols: tuple, now: datetime) -> bool:
    """Whether every symbol's market is closed and its closing price is already in: then nothing
    changes until the first one opens, and nobody is asked."""
    last = _last_quotes.get(symbols)
    if not last:
        return False
    fetched = datetime.fromtimestamp(last["at"], timezone.utc)
    for s in symbols:
        about = about_known(s)
        if not about or about.get("missing") or about.get("kind") in ("CRYPTOCURRENCY",):
            return False
        q = last["quotes"].get(s)
        if q is None or state(about, q.get("traded_at"), now)["open"]:
            return False
        opens = next_open(about, fetched)
        if opens is None or opens <= now:          # it has opened since that answer
            return False
    return True


@runtime.live(EVERY)
async def fetch_quotes(session, symbols: tuple):
    """{symbol: read_spark's fields} for every symbol, in as few requests as Yahoo allows, with
    "at": when they were read. Nothing is asked while every market is closed and its close is in."""
    if not symbols:
        return {"at": time.time(), "quotes": {}}
    now = datetime.now(timezone.utc)
    if _resting(symbols, now):
        return _last_quotes[symbols]
    quotes = {}
    for k in range(0, len(symbols), BATCH):
        part = symbols[k:k + BATCH]
        url = f"{services.url(YAHOO)}/v8/finance/spark?symbols={quote(','.join(part), safe=',')}&range=5d&interval=60m"
        body = await pacing.get(session, url, PACE_YAHOO)
        try:
            quotes.update(read_spark(body))
        except ValueError:
            pacing.unreadable(PACE_YAHOO, "prices")
            raise
    pacing.answered(PACE_YAHOO)
    got = {"at": time.time(), "quotes": quotes}
    _last_quotes[symbols] = got
    if len(_last_quotes) > 64:
        _last_quotes.pop(next(iter(_last_quotes)))
    return got


def read_coin_markets(body) -> dict:
    """CoinGecko's markets (in US dollars) -> {id: {name, symbol, trend}}: each coin's week as a line."""
    if not isinstance(body, list):
        raise ValueError("not a list of coins")
    out = {}
    for c in body:
        if not isinstance(c, dict) or not c.get("id"):
            continue
        spark = ((c.get("sparkline_in_7d") or {}).get("price")) or []
        out[str(c["id"])] = {"name": str(c.get("name") or c["id"]), "symbol": str(c.get("symbol") or "").upper(),
                             "trend": [p for p in (_num(x) for x in spark) if p is not None][-84:]}
    return out


def read_coin_prices(body) -> dict:
    """CoinGecko's simple prices -> {id: {currency: {price, change_pct}}, "traded_at"}."""
    if not isinstance(body, dict):
        raise ValueError("not a set of coins")
    out = {}
    for cid, v in body.items():
        if not isinstance(v, dict):
            continue
        cur = {}
        for k, val in v.items():
            if k.endswith("_24h_change") or k == "last_updated_at":
                continue
            p = _num(val)
            if p is not None:
                cur[k.upper()] = {"price": p, "change_pct": _num(v.get(f"{k}_24h_change"))}
        out[str(cid)] = {"prices": cur, "traded_at": v.get("last_updated_at")}
    return out


@runtime.live(EVERY)
async def fetch_coins(session, ids: tuple, currencies: tuple):
    """{id: {name, symbol, trend, prices: {currency: {price, change_pct}}}} and "at". Two requests
    for every coin and currency: the week's line (in US dollars; its shape, which is what a line
    shows), and the prices in every currency asked (CoinGecko prices some, lei among them, only there)."""
    if not ids:
        return {"at": time.time(), "coins": {}}
    base = services.url(COINGECKO)
    joined = quote(",".join(ids), safe=",")
    markets = await pacing.get(session, f"{base}/coins/markets?vs_currency=usd&ids={joined}&sparkline=true", PACE_GECKO)
    prices = await pacing.get(session, f"{base}/simple/price?ids={joined}&vs_currencies={quote(','.join(c.lower() for c in currencies), safe=',')}"
                                        "&include_24hr_change=true&include_last_updated_at=true", PACE_GECKO)
    try:
        about, priced = read_coin_markets(markets), read_coin_prices(prices)
    except ValueError:
        pacing.unreadable(PACE_GECKO, "prices")
        raise
    pacing.answered(PACE_GECKO)
    coins = {cid: {**about.get(cid, {"name": cid, "symbol": "", "trend": []}), **priced.get(cid, {"prices": {}})}
             for cid in ids if cid in about or cid in priced}
    return {"at": time.time(), "coins": coins}


# ---------------------------------------------------------------- what a page shows

def rows(holdings: list[Holding], quotes: dict | None, abouts: dict, coins: dict | None, home_currency: str,
         now: datetime) -> list[dict]:
    """One row per holding, in the add-on's own fields (shapes "markets"): label, symbol, price,
    currency, change_pct, decimals, trend, open, since, at (when its price was read), missing
    (the service doesn't know it) or waiting (no price yet)."""
    out = []
    qs = (quotes or {}).get("quotes") or {}
    cs = (coins or {}).get("coins") or {}
    for h in holdings:
        row = {"kind": h.kind, "symbol": h.symbol, "label": h.label, "price": None, "currency": "", "change_pct": None,
               "decimals": 2, "trend": [], "open": True, "since": "", "at": None, "missing": False}
        if h.kind == "coin":
            cur = h.currency or home_currency or "USD"
            c = cs.get(h.symbol)
            row.update(currency=cur, at=(coins or {}).get("at"))
            if coins is not None and c is None:
                row["missing"] = True
            elif c:
                p = (c.get("prices") or {}).get(cur) or {}
                row.update(label=h.label or c.get("name") or h.symbol, price=p.get("price"), change_pct=p.get("change_pct"),
                           trend=c.get("trend") or [], decimals=coin_decimals(p.get("price")), since="24h")
                if p.get("price") is None:
                    row["missing"] = True
        else:
            about = abouts.get(h.symbol) or {}
            q = qs.get(h.symbol)
            if about.get("missing") or (quotes is not None and q is None and about):
                row["missing"] = True
            row.update(label=h.label or about.get("name") or h.symbol, currency=about.get("currency", ""),
                       decimals=about.get("decimals", 2), at=(quotes or {}).get("at"))
            if q:
                st = state(about, q.get("traded_at"), now)
                row.update(price=q["price"], change_pct=q.get("change_pct"), trend=q.get("trend") or [], **st)
        out.append(row)
    return out


def coin_decimals(price) -> int:
    p = abs(_num(price) or 0)
    return 0 if p >= 1000 else 2 if p >= 1 else 4 if p >= 0.01 else 6


async def fetch_rows(session, el: dict, home_tz: str | None) -> dict | None:
    """Everything a markets element draws: {"rows": [...], "at", "tz"}. None until something's in."""
    from sources.geo import get_home_currency
    holdings = holdings_of(el)
    if not holdings:
        return {"rows": [], "at": None, "tz": home_tz}
    symbols = tuple(h.symbol for h in holdings if h.kind == "quote")
    home_currency = await get_home_currency(session) if any(h.kind == "coin" and not h.currency for h in holdings) else ""
    coin_ids = tuple(dict.fromkeys(h.symbol for h in holdings if h.kind == "coin"))
    currencies = tuple(sorted({h.currency or home_currency or "USD" for h in holdings if h.kind == "coin"}))
    abouts = {s: await fetch_about(session, s) for s in symbols}
    abouts = {s: a for s, a in abouts.items() if a}
    quotes = await fetch_quotes(session, symbols) if symbols else {"at": None, "quotes": {}}
    coins = await fetch_coins(session, coin_ids, currencies) if coin_ids else {"at": None, "coins": {}}
    got = rows(holdings, quotes, abouts, coins, home_currency, datetime.now(timezone.utc))
    # A service that keeps failing says so, rather than leaving the page blank; one that hasn't
    # been asked yet stays blank for the seconds its first answer takes.
    failing = bool(symbols and PACE_YAHOO.failures) or bool(coin_ids and PACE_GECKO.failures)
    if not failing and all(r["price"] is None and not r["missing"] for r in got):
        return None
    ats = [r["at"] for r in got if r.get("at")]
    return {"rows": got, "at": min(ats) if ats else None, "tz": home_tz, "coins": bool(coin_ids), "failing": failing}


# ---------------------------------------------------------------- finding a symbol (the editor, when a person types)

def read_search(yahoo, gecko) -> list[dict]:
    """Yahoo's and CoinGecko's search answers -> [{kind, symbol, name, where}]: what can be shown."""
    out = []
    for q in (yahoo or {}).get("quotes") or []:
        sym = clean_symbol(q.get("symbol")) if isinstance(q, dict) else ""
        if not sym or q.get("quoteType") in ("OPTION", "FUTURE"):
            continue
        out.append({"kind": "quote", "symbol": sym, "name": " ".join(str(q.get("longname") or q.get("shortname") or sym).split()),
                    "where": " · ".join(x for x in (str(q.get("exchDisp") or ""), str(q.get("typeDisp") or "")) if x)})
    for c in ((gecko or {}).get("coins") or [])[:5]:
        cid = clean_coin(c.get("id")) if isinstance(c, dict) else ""
        if cid:
            out.append({"kind": "coin", "symbol": cid, "name": str(c.get("name") or cid),
                        "where": f"{str(c.get('symbol') or '').upper()} · Coin".lstrip(" ·")})
    return out


async def find(session, text: str) -> list[dict]:
    """Symbols and coins matching what a person typed, from both services (asked only then)."""
    q = " ".join(str(text or "").split())[:60]
    if len(q) < 2:
        return []
    yahoo = gecko = None
    try:
        yahoo = await pacing.get(session, f"{services.url(YAHOO)}/v1/finance/search?q={quote(q)}&quotesCount=8&newsCount=0", PACE_YAHOO)
        pacing.answered(PACE_YAHOO)
    except LookupError:
        pass
    try:
        gecko = await pacing.get(session, f"{services.url(COINGECKO)}/search?query={quote(q)}", PACE_GECKO)
        pacing.answered(PACE_GECKO)
    except LookupError:
        pass
    if yahoo is None and gecko is None:
        raise LookupError("neither service answered")
    return read_search(yahoo, gecko)
