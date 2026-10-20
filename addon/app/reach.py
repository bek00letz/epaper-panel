"""Reaching home: how screens away from the home network reach the add-on.

Three ways, chosen in the editor (Settings, Reaching home):

  home   the home network only (the default). Requests that came through a
         proxy on Home Assistant's internal network are refused, so a tunnel
         pointed at the add-on by mistake doesn't open it to the internet.
  ha     through Home Assistant's own address: the companion integration
         (companion.py) passes /api/epaper/... to the device port.
  own    the user's own address: a tunnel or proxy pointed at the device port.

Away from home every request needs a key, with no switch-over (frame_token),
and wrong keys slow down per sender (kinds.WrongKeys).
"""
from __future__ import annotations

import ipaddress
import json
import re
import urllib.parse

import aiohttp

import config
import health

MODES = ("home", "ha", "own")
FILE = "reach.json"
COMPANION_PREFIX = "/api/epaper"

# Home Assistant's internal network: Home Assistant itself, the Supervisor and other apps.
INTERNAL = ipaddress.ip_network("172.30.32.0/23")
PROXY_HEADERS = ("X-Forwarded-For", "CF-Connecting-IP", "X-Real-IP", "X-Forwarded-Prefix", "Forwarded")


def settings() -> dict:
    try:
        found = json.loads((config.DATA_DIR / FILE).read_text())
    except (OSError, ValueError):
        found = {}
    mode = found.get("mode") if found.get("mode") in MODES else "home"
    return {"mode": mode, "address": str(found.get("address") or "")}


def clean_address(raw: str) -> str:
    """A public https address for "own", without a trailing slash. Raises ValueError with what to fix."""
    raw = str(raw or "").strip().rstrip("/")
    if not raw:
        raise ValueError("Enter the address your tunnel gives you, like https://panel.example.com.")
    parts = urllib.parse.urlsplit(raw if "://" in raw else "https://" + raw)
    if parts.scheme != "https":
        raise ValueError("Use an https address: screens send their key with every request.")
    if not parts.hostname or parts.query or parts.fragment:
        raise ValueError("That doesn't look like an address. It should be like https://panel.example.com.")
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", ""))


def save(mode: str, address: str = "") -> dict:
    if mode not in MODES:
        raise ValueError("Pick one of the three ways.")
    current = settings()
    out = {"mode": mode, "address": clean_address(address) if mode == "own" else current["address"]}
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = config.DATA_DIR / (FILE + ".tmp")
    tmp.write_text(json.dumps(out))
    tmp.replace(config.DATA_DIR / FILE)
    print(f"reach: screens reach the add-on {describe(out['mode'])}", flush=True)
    return out


def describe(mode: str) -> str:
    return {"home": "on the home network only", "ha": "through Home Assistant's address",
            "own": "through your own address"}[mode]


def remote_on() -> bool:
    return settings()["mode"] != "home"


# ---------------------------------------------------------------- where a request came from

def _peer(request) -> ipaddress._BaseAddress | None:
    try:
        return ipaddress.ip_address((request.remote or "").removeprefix("::ffff:"))
    except ValueError:
        return None


def through_proxy(request) -> bool:
    """Whether the request came through something on Home Assistant's internal network
    (the companion integration, a tunnel app) rather than straight from a screen."""
    peer = _peer(request)
    return bool(peer and peer in INTERNAL and any(h in request.headers for h in PROXY_HEADERS))


def through_companion(request) -> bool:
    return through_proxy(request) and request.headers.get("X-Forwarded-Prefix") == COMPANION_PREFIX


def sender(request) -> str:
    """Who sent a request, for slowing down wrong keys: the proxy's word for it when it came
    through one on the internal network, otherwise the address it came from."""
    if through_proxy(request):
        # The companion overwrites X-Forwarded-For and passes every other header on as the
        # screen sent it, so through it a CF-Connecting-IP is whatever the sender claims.
        names = ("X-Forwarded-For",) if through_companion(request) else ("CF-Connecting-IP", "X-Real-IP", "X-Forwarded-For")
        for name in names:
            value = (request.headers.get(name) or "").split(",")[0].strip()
            if value:
                return value[:64]
    return (request.remote or "")[:64]


def refusal(request) -> str | None:
    """Why this request may not come in this way, or None."""
    mode = settings()["mode"]
    if through_companion(request):
        return None if mode == "ha" else "Reaching home through Home Assistant is off in the add-on's settings."
    if through_proxy(request) and mode == "home":
        return "This add-on only answers screens at home. Turn on Reaching home in its settings."
    return None


# ---------------------------------------------------------------- addresses

async def ha_address(hass) -> str:
    """Home Assistant's address outside the home: its external URL, or Home Assistant Cloud's. "" if it has none."""
    try:
        cfg = await hass.rest("GET", "/config")
        url = str((cfg or {}).get("external_url") or "").rstrip("/")
        if url.startswith("https://"):
            return url
    except Exception as exc:
        print(f"reach: couldn't read Home Assistant's address: {health.describe(exc)}", flush=True)
    try:
        cloud = await hass.ws({"type": "cloud/status"})
        domain = (cloud or {}).get("remote_domain")
        if (cloud or {}).get("remote_enabled") and domain and re.fullmatch(r"[a-z0-9.-]+", domain):
            return f"https://{domain}"
    except Exception:
        pass                                   # no Home Assistant Cloud: nothing to say
    return ""


async def public_base(hass) -> str | None:
    """The base address screens use away from home, or None on the home network only."""
    s = settings()
    if s["mode"] == "own":
        return s["address"]
    if s["mode"] == "ha":
        addr = await ha_address(hass)
        return addr + COMPANION_PREFIX if addr else None
    return None


async def addon_hostname(session: aiohttp.ClientSession | None) -> str:
    """This add-on's name on Home Assistant's internal network (what a tunnel app points at)."""
    if not config.HA_TOKEN or session is None:
        return ""
    try:
        async with session.get("http://supervisor/addons/self/info",
                               headers={"Authorization": f"Bearer {config.HA_TOKEN}"},
                               timeout=aiohttp.ClientTimeout(total=3)) as r:
            if r.status == 200:
                return str(((await r.json()).get("data") or {}).get("hostname") or "")
    except Exception as exc:
        print(f"reach: couldn't ask the Supervisor for this add-on's name: {health.describe(exc)}", flush=True)
    return ""


def service_address(hostname: str) -> str:
    """Where a tunnel app on Home Assistant points to reach the device port."""
    return f"http://{hostname}:{config.FRAME_PORT}" if hostname else ""
