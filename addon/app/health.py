"""Whether each outside service is answering, and errors described safely.

Every service the add-on reaches (ESPN, Flightradar24, your data sources,
Home Assistant's weather and calendars) reports here when it answers and when
it fails. The editor shows it in /api/status, and Home Assistant gets one
problem sensor per service (entities.publish_health), so a service that stops
answering is never silent.

`describe()` is the only way an exception should reach a log line or an API
response: aiohttp's errors carry the request headers (the add-on's Home
Assistant token, Jellyfin's key) in their repr.
"""
from __future__ import annotations

import re
import time

# A service has a problem once it has failed continuously for this long, so a
# single blip doesn't flip a sensor in Home Assistant.
GRACE = 300.0
# A service nobody has used for this long is forgotten (its widget or source
# was removed), and so is its problem sensor.
FORGET_AFTER = 86400.0

_services: dict[str, dict] = {}
clock = time.time

_SECRETS = (
    (re.compile(r"(?i)(bearer\s+)[^\s'\",)]+"), r"\1•••"),
    (re.compile(r"(?i)((?:authorization|x-emby-token|x-api-key|api[_-]?key|token|password)['\"]?\s*[:=]\s*['\"]?)[^\s'\",)&]+"), r"\1•••"),
    (re.compile(r"\?[^\s'\")]*"), "?…"),                  # query strings can carry keys
)


def describe(exc: BaseException) -> str:
    """A short, safe description of an error: what failed and where, never headers or keys."""
    status = getattr(exc, "status", None)
    info = getattr(exc, "request_info", None)
    if info is not None:                                # aiohttp ClientResponseError and friends
        url = getattr(info, "real_url", None) or getattr(info, "url", None)
        where = f"{url.host}{url.path}" if url is not None and getattr(url, "host", None) else ""
        msg = getattr(exc, "message", "") or ""
        text = f"HTTP {status}{' ' + str(msg) if msg else ''}{' from ' + where if where else ''}"
    else:
        detail = str(exc)
        text = f"{type(exc).__name__}: {detail}" if detail else type(exc).__name__
    for pattern, repl in _SECRETS:
        text = pattern.sub(repl, text)
    return text[:200]


def _entry(name: str, kind: str) -> dict:
    e = _services.get(name)
    if e is None:
        e = _services[name] = {"name": name, "kind": kind, "ok_at": None, "failing_since": None,
                               "error": None, "used_at": clock()}
    e["kind"] = kind
    e["used_at"] = clock()
    return e


def ok(name: str, kind: str = "service") -> None:
    e = _entry(name, kind)
    if e["failing_since"] is not None:
        print(f"{name}: answering again", flush=True)
    e.update(ok_at=clock(), failing_since=None, error=None)


def fail(name: str, exc: BaseException | str, kind: str = "service") -> str:
    """Record a failure; logs it once per distinct error. Returns the safe description."""
    e = _entry(name, kind)
    text = exc if isinstance(exc, str) else describe(exc)
    if e["error"] != text:
        print(f"{name}: {text}", flush=True)
    e["error"] = text
    if e["failing_since"] is None:
        e["failing_since"] = clock()
    return text


def problem(e: dict) -> bool:
    return e["failing_since"] is not None and clock() - e["failing_since"] >= GRACE


def status() -> list[dict]:
    """Every service in use, for the editor: name, kind, last success, the problem if any."""
    now = clock()
    for name in [n for n, e in _services.items() if now - e["used_at"] > FORGET_AFTER]:
        del _services[name]
    return [{**e, "problem": problem(e)} for e in sorted(_services.values(), key=lambda e: e["name"])]


# The outside services the add-on uses, by address: a host, or a host and the start of a path
# where one host serves several (GitHub's raw files are both the racing calendars and Iconify).
# Every request through the shared session reports here (trace_config), so a new fetcher is
# covered without any code of its own. Addresses not listed (your data sources, Home Assistant
# itself) are tracked elsewhere or not at all.
SERVICES = {
    "site.api.espn.com": "ESPN",
    "data-cloud.flightradar24.com": "Flightradar24",
    "opensky-network.org": "OpenSky",
    "raw.githubusercontent.com/sportstimes/": "Racing calendar",
    "raw.githubusercontent.com/iconify/": "Iconify",
    "api.iconify.design": "Iconify",
    "formulaecal.com": "Formula E calendar",
    "www.fiaformulae.com": "Formula E",
}


def service_for(url) -> str | None:
    """The service an address belongs to (SERVICES: the longest match), or None."""
    if hasattr(url, "host"):
        host, path = url.host or "", url.path or "/"
    else:
        from urllib.parse import urlsplit
        parts = urlsplit(str(url))
        host, path = parts.hostname or "", parts.path or "/"
    best = None
    for key, name in SERVICES.items():
        h, slash, prefix = key.partition("/")
        if h == host and (not slash or path.startswith("/" + prefix)) and (best is None or len(key) > len(best[0])):
            best = (key, name)
    return best[1] if best else None


# Passed as a request's trace_request_ctx: "not found" here is a normal answer.
MISSING_OK = object()


def trace_config():
    """aiohttp tracing that records every request to a known service."""
    import aiohttp

    async def on_end(session, ctx, params):
        name = service_for(params.url)
        if name is None:
            return
        # A request may say a 404 is an answer, not a failure: something looked up that may
        # not exist yet (next year's racing calendar), passed as trace_request_ctx=MISSING_OK.
        missing_ok = getattr(ctx, "trace_request_ctx", None) is MISSING_OK and params.response.status == 404
        if params.response.status < 400 or missing_ok:
            ok(name)
        else:
            fail(name, f"HTTP {params.response.status} from {params.url.host}")

    async def on_exception(session, ctx, params):
        name = service_for(params.url)
        if name is not None:
            fail(name, params.exception)

    tc = aiohttp.TraceConfig()
    tc.on_request_end.append(on_end)
    tc.on_request_exception.append(on_exception)
    return tc


def reset() -> None:
    _services.clear()
