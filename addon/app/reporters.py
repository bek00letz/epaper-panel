"""Reporters: the computers that send AI usage to the add-on (usage.py, docs/ai-usage.md).

A reporter isn't a screen: it shows nothing and fetches nothing, so it isn't a device. It has a
name, a key and the platform it said it was, kept in `reporters.json` (0600). Its key only sends
usage: devices.authenticate never sees it, so it can't fetch a frame or wake anything.

Pairing is the TRMNL's, with a code instead of a MAC address. The editor opens a ten-minute
window (one at a time) and shows a six-letter code; the reporter sends it once to
`POST /api/usage/pair` and is given its key, which it keeps in the computer's own key store (the macOS Keychain, the Secret Service on Linux, a
file Windows encrypts for that account). A
wrong code counts as a wrong key (kinds.WRONG_KEYS), so guessing slows down to nothing.

On the device port:
  POST /api/usage/pair   {"code", "platform"} -> {"key", "id", "name"}, only inside the window
  POST /api/usage        a report, its key in X-EPF-Key (the companion passes it on; it drops
                         Authorization, so a reporter away from home uses this header)
In the editor's API (behind Ingress):
  GET    /api/reporters                 who reports, when each was last heard, and what they found
  POST   /api/reporters/pair            open the window: {"code", "left", "command", "addresses"}
  GET    /api/reporters/pair            the window's state, and whether a reporter joined in it
  PUT    /api/reporters/{id}            rename
  DELETE /api/reporters/{id}            remove; its key stops at once (POST .../restore puts it back)
"""
from __future__ import annotations

import hmac
import json
import os
import re
import secrets
import time
from datetime import datetime, timezone

from aiohttp import web

import config
import reach
import usage
from firmware_gen import REPO, component_ref

STORE = "reporters.json"
PAIR_SECONDS = 600
CODE_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"       # no 0/O or 1/I to misread
CODE_LEN = 6
KEY_HEADER = "X-EPF-Key"
REMEMBER_REMOVED = 10
PLATFORMS = ("macos", "linux", "windows")


# ---------------------------------------------------------------- the store

def _path():
    return config.DATA_DIR / STORE


def _load() -> dict:
    try:
        got = json.loads(_path().read_text())
    except (OSError, ValueError):
        got = {}
    if not isinstance(got, dict):
        got = {}
    got.setdefault("reporters", [])
    got.setdefault("removed", [])
    got.setdefault("next", 1)
    return got


def _save(store: dict) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(store, indent=2))
    os.chmod(tmp, 0o600)
    tmp.replace(path)


def all_reporters() -> list[dict]:
    return list(_load()["reporters"])


def get(reporter_id) -> dict:
    found = next((r for r in all_reporters() if r["id"] == str(reporter_id)), None)
    if found is None:
        raise KeyError(f"no reporter {str(reporter_id)[:12]!r}")
    return found


def clean_name(raw) -> str:
    name = re.sub(r"[\x00-\x1f\x7f]", "", str(raw or "")).strip()
    if len(name) > 32:
        raise ValueError("Keep the name to 32 characters.")
    return name


def add(platform: str = "", name: str = "") -> dict:
    store = _load()
    rid = str(store["next"])
    store["next"] += 1
    rep = {"id": rid, "name": clean_name(name), "platform": platform if platform in PLATFORMS else "",
           "key": secrets.token_urlsafe(24), "added_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    store["reporters"].append(rep)
    _save(store)
    return rep


def rename(reporter_id, name) -> dict:
    store = _load()
    for r in store["reporters"]:
        if r["id"] == str(reporter_id):
            r["name"] = clean_name(name)
            _save(store)
            return r
    raise KeyError(f"no reporter {str(reporter_id)[:12]!r}")


def remove(reporter_id) -> dict:
    """Its key stops working at once. Remembered (key and all) so Undo can put it back."""
    store = _load()
    found = next((r for r in store["reporters"] if r["id"] == str(reporter_id)), None)
    if found is None:
        raise KeyError(f"no reporter {str(reporter_id)[:12]!r}")
    store["reporters"] = [r for r in store["reporters"] if r is not found]
    store["removed"] = (store["removed"] + [found])[-REMEMBER_REMOVED:]
    _save(store)
    return found


def restore(reporter_id) -> dict:
    store = _load()
    found = next((r for r in store["removed"] if r["id"] == str(reporter_id)), None)
    if found is None:
        raise KeyError(f"no removed reporter {str(reporter_id)[:12]!r}")
    store["removed"] = [r for r in store["removed"] if r is not found]
    store["reporters"].append(found)
    _save(store)
    return found


def authenticate(provided: str) -> dict | None:
    if not provided:
        return None
    given = provided.encode("utf-8", "replace")
    found = None
    for r in all_reporters():
        if hmac.compare_digest(given, str(r.get("key") or "").encode()):
            found = found or r
    return found


# ---------------------------------------------------------------- pairing

# One window at a time: {"code", "until" (monotonic), "joined": reporter id}. Gone on a restart.
_PAIRING: dict = {}


def _code() -> str:
    return "".join(secrets.choice(CODE_CHARS) for _ in range(CODE_LEN))


def open_pairing(clock=time.monotonic) -> dict:
    _PAIRING.clear()
    _PAIRING.update(code=_code(), until=clock() + PAIR_SECONDS, joined="")
    return pairing(clock)


def pairing(clock=time.monotonic) -> dict:
    left = max(0, int(_PAIRING.get("until", 0) - clock())) if _PAIRING.get("code") else 0
    return {"code": _PAIRING.get("code", "") if left else "", "left": left, "joined": _PAIRING.get("joined", "")}


def clean_code(raw) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(raw or "").upper())[:CODE_LEN * 2]


def join(code: str, platform: str = "", clock=time.monotonic) -> dict | None:
    """The reporter a right code inside the window makes, or None. A code works once."""
    want = _PAIRING.get("code", "")
    if not want or pairing(clock)["left"] <= 0:
        return None
    if not hmac.compare_digest(clean_code(code).encode(), want.encode()):
        return None
    rep = add(platform)
    _PAIRING.update(code="", until=0, joined=rep["id"])
    return rep


# ---------------------------------------------------------------- the device port

def _sender_checks(request) -> str:
    from kinds import WRONG_KEYS                   # kinds imports the kinds, which import a lot
    why = reach.refusal(request)
    if why:
        raise web.HTTPForbidden(text=why)
    who = reach.sender(request)
    wait = WRONG_KEYS.blocked_for(who)
    if wait:
        raise web.HTTPTooManyRequests(text="Too many wrong keys. Try again later.",
                                      headers={"Retry-After": str(int(wait) + 1)})
    return who


async def _body(request) -> object:
    if request.content_length is not None and request.content_length > usage.MAX_BYTES:
        raise web.HTTPRequestEntityTooLarge(max_size=usage.MAX_BYTES, actual_size=request.content_length)
    raw = await request.content.read(usage.MAX_BYTES + 1)
    if len(raw) > usage.MAX_BYTES:
        raise web.HTTPRequestEntityTooLarge(max_size=usage.MAX_BYTES, actual_size=len(raw))
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise web.HTTPBadRequest(text="A report is JSON.")


async def device_pair(request):
    from kinds import WRONG_KEYS
    who = _sender_checks(request)
    body = await _body(request)
    body = body if isinstance(body, dict) else {}
    platform = usage.slug(body.get("platform"))
    rep = join(body.get("code"), platform)
    if rep is None:
        WRONG_KEYS.wrong(who)
        raise web.HTTPUnauthorized(text="That code isn't right, or its ten minutes are up. Open Settings › AI usage "
                                        "in the editor for a new one.")
    print(f"AI usage: a reporter paired ({platform or 'platform not said'})", flush=True)
    return web.json_response({"key": rep["key"], "id": rep["id"], "name": rep["name"]})


async def device_report(request):
    from kinds import WRONG_KEYS
    who = _sender_checks(request)
    rep = authenticate(request.headers.get(KEY_HEADER) or "")
    if rep is None:
        WRONG_KEYS.wrong(who)
        raise web.HTTPUnauthorized(text="invalid or missing key")
    body = await _body(request)
    try:
        report, dropped = usage.clean(body)
    except ValueError as exc:
        raise web.HTTPBadRequest(text=str(exc))
    usage.save(rep["id"], report)
    if report.get("platform") and report["platform"] in PLATFORMS and rep.get("platform") != report["platform"]:
        store = _load()
        for r in store["reporters"]:
            if r["id"] == rep["id"]:
                r["platform"] = report["platform"]
        _save(store)
    return web.json_response({"ok": True, "windows": sum(len(p["windows"]) for p in report["providers"]),
                              "dropped": dropped[:20]})


def routes() -> list:
    return [web.post("/api/usage/pair", device_pair), web.post("/api/usage", device_report)]


# ---------------------------------------------------------------- the editor

def describe(rep: dict, heard: dict | None) -> dict:
    """What the editor shows about a reporter. Never its key."""
    heard = heard or {}
    return {"id": rep["id"], "name": rep.get("name") or "", "platform": rep.get("platform") or heard.get("platform") or "",
            "added_at": rep.get("added_at") or "", "heard_at": heard.get("heard_at") or "",
            "quiet": bool(heard.get("quiet")), "skipped": heard.get("skipped") or []}


def view() -> dict:
    reps = all_reporters()
    now = usage.current(reps)
    heard = {h["id"]: h for h in now["reporters"]}
    return {"reporters": [describe(r, heard.get(r["id"])) for r in reps],
            "providers": [{"provider": p["provider"], "name": p["name"], "account": p["account"],
                           "windows": len(p["windows"]), "reporters": p["reporters"]} for p in now["providers"]]}


def install_command(code: str, address: str, platform: str = "macos", version: str | None = None) -> str:
    """What the person runs on their computer: the reporter at this add-on's own release (as the panel's
    firmware is), set up with this window's code and the address it reports to. One line for Terminal
    on a Mac or Linux, one for PowerShell on Windows."""
    ref = component_ref(config.ADDON_VERSION if version is None else version)
    raw = f"https://raw.githubusercontent.com/{REPO}/{ref}/reporter"
    if platform == "windows":
        return (f"& ([scriptblock]::Create((irm {raw}/install.ps1))) "
                f"-Ref {ref} -Address {address} -Code {code}")
    return f"curl -fsSL {raw}/install.sh | bash -s -- --ref {ref} --address {address} --code {code}"


def commands(code: str, addresses: list[dict]) -> dict:
    """{"home": {platform: command}, "away": {...}}: every way in, for every computer the reporter runs on."""
    return {a["where"]: {pf: install_command(code, a["url"], pf) for pf in PLATFORMS} for a in addresses}


async def _addresses(request) -> list[dict]:
    from kinds import device_port_addresses
    return await device_port_addresses()


async def editor_list(request):
    return web.json_response(view())


async def editor_pair_open(request):
    got = open_pairing()
    addrs = await _addresses(request)
    return web.json_response({**got, "addresses": addrs, "commands": commands(got["code"], addrs)})


async def editor_pair_get(request):
    got = pairing()
    joined = got.get("joined")
    rep = None
    if joined:
        try:
            rep = describe(get(joined), next((h for h in usage.current([get(joined)])["reporters"]), None))
        except KeyError:
            rep = None
    return web.json_response({**got, "reporter": rep})


async def editor_rename(request):
    try:
        body = await request.json()
        rep = rename(request.match_info["id"], (body or {}).get("name"))
    except KeyError:
        raise web.HTTPNotFound(text="That computer isn't connected any more.")
    except ValueError as exc:
        raise web.HTTPBadRequest(text=str(exc))
    return web.json_response(describe(rep, None))


async def editor_remove(request):
    try:
        rep = remove(request.match_info["id"])
    except KeyError:
        raise web.HTTPNotFound(text="That computer isn't connected any more.")
    return web.json_response({"ok": True, "id": rep["id"]})


async def editor_restore(request):
    try:
        rep = restore(request.match_info["id"])
    except KeyError:
        raise web.HTTPNotFound(text="That computer can't be put back any more.")
    return web.json_response(describe(rep, None))


def editor_routes() -> list:
    return [web.get("/api/reporters", editor_list),
            web.post("/api/reporters/pair", editor_pair_open),
            web.get("/api/reporters/pair", editor_pair_get),
            web.put("/api/reporters/{id}", editor_rename),
            web.delete("/api/reporters/{id}", editor_remove),
            web.post("/api/reporters/{id}/restore", editor_restore)]
