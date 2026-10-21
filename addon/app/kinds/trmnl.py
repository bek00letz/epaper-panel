"""TRMNL: a battery screen that deep-sleeps, wakes on a timer or its button, and fetches one picture.

It speaks TRMNL's "bring your own server" protocol, as its open-source
firmware sends it (usetrmnl/firmware: src/api-client, src/bl.cpp,
src/display_session.cpp, lib/trmnl/src/parse_response_api_*.cpp):

  GET  /api/setup    ID (its MAC address), FW-Version, Model. A JSON body with
                     "status": 200 pairs it (api_key, friendly_id, image_url);
                     "status": 404 says it isn't known, and it shows "message".
  GET  /api/display  ID, Access-Token (its key), Refresh-Rate, Battery-Voltage,
                     RSSI, Width, Height, Model, FW-Version, Update-Source
                     ("timer", "button", ...), Image-Cached. The answer says
                     which picture (image_url, filename) and how long to sleep
                     (refresh_rate). "status" 0 is the only one we send: 202
                     makes it poll every 5 s, 500 wipes its Wi-Fi.
  POST /api/log      its log lines, kept briefly for the editor.
  GET  image_url     the picture: a 1-bit PNG at the size it reports. It sends
                     ID and Access-Token here too, because the address starts
                     with the server address it was given.

What it shows and how long it sleeps is the shared mode for screens that
sleep (paging.py): every picture it can fetch is drawn ahead in the render
cycle, and a wake only picks one (a timer wake moves through the rotation, a
button wake goes to the next page). This file is only the protocol. It can't
be woken early: alerts show at its next wake. Pairing happens only inside the
10-minute window "Add new device" opens in the editor.

Off unless the add-on option `trmnl` turns it on (config.TRMNL).
"""
from __future__ import annotations

import asyncio
import re
import secrets
import time
import urllib.parse
from collections import OrderedDict, deque
from datetime import datetime

from aiohttp import web

import config
import devices
import frames
import health
import paging
import panel_setup
import reach
import runtime
from entities import publish_entity
from kinds import WRONG_KEYS, Kind, device_for, of as kind_of, register, shown
from render import sleep, theme as T

PAIR_SECONDS = 600                      # how long "Add new device" listens for a new TRMNL
KEEP_IMAGES = 4                         # pictures kept for the device to fetch after /api/display
KEEP_LOGS = 20

MAC_RE = re.compile(r"^[0-9A-F]{2}(:[0-9A-F]{2}){5}$")
HOST_RE = re.compile(r"^[A-Za-z0-9.\-]+(:[0-9]{1,5})?$|^\[[0-9A-Fa-f:.]+\](:[0-9]{1,5})?$")
FRIENDLY_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

# What the TRMNL shows on its own screen (its font is plain ASCII).
NOT_PAIRING = "Not paired yet. In Home Assistant, open e-Paper and add this TRMNL as a device."
PAIRED_MESSAGE = "Paired with e-Paper. Your pages come next."


class Trmnl(Kind):
    id = "trmnl"
    name = "TRMNL"
    picks_page = "addon"
    owns_interval = "addon"
    setup_flow = "pair"
    stays_on = False                    # it always sleeps between updates

    def enabled(self) -> bool:
        return config.TRMNL

    def displays(self) -> list[str]:
        own = [k for k, d in T.DISPLAYS.items() if d.get("kind") == self.id]
        reported = sorted({T.get_display(d.get("display"))["id"] for d in devices.all_devices()
                           if d.get("kind") == self.id})
        return own + [k for k in reported if k not in own and T.get_display(k).get("kind") == self.id]

    def routes(self) -> list:
        return [
            web.get("/api/setup", api_setup),
            web.get("/api/display", api_display),
            web.post("/api/log", api_log),
            web.get("/api/image/{name}", api_image),
        ]

    def editor_routes(self) -> list:
        return [
            web.get("/api/devices/{id}/pair", editor_pair_get),
            web.post("/api/devices/{id}/pair", editor_pair_open),
        ]

    def describe(self, dev: dict) -> dict:
        st = devices.state(dev["id"])
        setup = dev.get("setup") or {}
        return {
            "paired": bool(setup.get("mac")),
            "friendly_id": setup.get("friendly_id") or "",
            "awake_s": paging.awake_average(dev),
            "pairing_left": pairing_left(dev["id"]),
            "paired_at": st.get("paired_at"),
            "last_seen": st.get("last_seen"),
            "battery": st.get("battery"),
            "battery_v": st.get("battery_v"),
            "rssi": st.get("rssi"),
            "model": st.get("model") or "",
            "firmware": st.get("firmware") or "",
            "log": [e["message"] for e in list(_rt(dev).get("logs") or [])[-3:]],
        }

    def entities(self, dev: dict) -> set[str]:
        return {"sensor.epaper_battery", "sensor.epaper_battery_voltage", "sensor.epaper_wifi_signal",
                "sensor.epaper_last_seen"}

    async def render(self, session, dev, spec, st, quiet_active, quiet_reason) -> runtime.Frames:
        """Every picture it can fetch at its next wakes, drawn ahead (paging.draw_ahead)."""
        rt = _rt(dev)
        await paging.draw_ahead(dev, spec, st, quiet_active, quiet_reason, ART)
        f = runtime.Frames()
        f.names = list(st.live)
        f.cat_names = list(st.live)
        f.cat_count = len(st.live)
        f.rotate_seconds = paging.update_seconds(dev) * paging.rotate_updates(dev)
        # What the device was last sent: the editor's "what it shows".
        last = rt.get("last_png") or b""
        f.strip = f.single = last
        f.strip_etag = f.single_etag = frames._etag(last) if last else ""
        return f


def _rt(dev: dict) -> dict:
    return runtime.device(dev["id"]).kind


def _orientation(spec: dict) -> int:
    try:
        orient = int(spec.get("orientation") or 0)
    except (TypeError, ValueError):
        orient = 0
    return orient if orient in (0, 90, 180, 270) else 0


class _Art(paging.Art):
    """A TRMNL's pictures: 1-bit PNGs at its size, turned for its mounting."""

    async def page(self, dev, spec, st, plans, pos, item, clock) -> bytes:
        orient, display = _orientation(spec), T.get_display(spec.get("display"))["id"]
        plan = plans[pos]
        count = max(1, plan["want"])
        fg = T.footer_plan(clock=clock, pages=[(p["name"], max(1, p["want"])) for p in plans],
                           orientation=orient, display=display)
        imgs = await frames.draw_category(plan, count, pos, footer=fg, page_def=spec["pages"][plan["name"]],
                                          orient=orient, display=display, only=min(item, count - 1),
                                          today=await frames.date_for_time(kind_of(dev).sleeps(dev)))
        return frames._png(imgs[0])

    async def sleep(self, dev, spec, text) -> bytes:
        orient, display = _orientation(spec), T.get_display(spec.get("display"))["id"]
        img = await asyncio.to_thread(sleep.render_sleep_page, text, orient, display)
        return frames._png(T.orient_for_panel(T.to_1bit(img), orient, display=display))

    async def empty(self, dev, spec, clock) -> bytes:
        orient, display = _orientation(spec), T.get_display(spec.get("display"))["id"]
        img = await asyncio.to_thread(frames.empty_page, orient, display, clock)
        return frames._png(T.orient_for_panel(T.to_1bit(img), orient, display=display))


ART = _Art()


# ---------------------------------------------------------------- pairing

# One window at a time: {"device": id, "until": monotonic seconds}. Gone on a restart.
_PAIRING: dict = {}


def open_pairing(device_id: str, clock=time.monotonic) -> int:
    _PAIRING.update(device=str(device_id), until=clock() + PAIR_SECONDS)
    return PAIR_SECONDS


def pairing_left(device_id: str, clock=time.monotonic) -> int:
    if _PAIRING.get("device") != str(device_id):
        return 0
    return max(0, int(_PAIRING["until"] - clock()))


def _waiting_device() -> dict | None:
    dev_id = _PAIRING.get("device")
    if not dev_id or pairing_left(dev_id) <= 0:
        return None
    try:
        dev = devices.get(dev_id)
    except KeyError:
        return None
    return dev if dev.get("kind") == Trmnl.id and shown(dev) else None


def _mac(raw) -> str | None:
    mac = str(raw or "").strip().upper().replace("-", ":")
    return mac if MAC_RE.match(mac) else None


def _friendly_id() -> str:
    taken = {(d.get("setup") or {}).get("friendly_id") for d in devices.all_devices()}
    while True:
        fid = "".join(secrets.choice(FRIENDLY_CHARS) for _ in range(6))
        if fid not in taken:
            return fid


def _ascii(text: str) -> str:
    return re.sub(r"[^\x20-\x7e]", "", str(text))[:120]


def _refused(message: str) -> web.Response:
    # An HTTP 200 carrying "status": 404, because only then does the firmware show `message`
    # (parse_response_api_setup.cpp reads the body's status; device_setup.cpp shows it on 404).
    return web.json_response({"status": 404, "api_key": "", "friendly_id": "", "image_url": "",
                              "message": _ascii(message)})


async def api_setup(request):
    """A TRMNL asking to be let in. Only inside the pairing window; never for a key it already has."""
    why = reach.refusal(request)
    if why:
        raise web.HTTPForbidden(text=why)
    who = reach.sender(request)
    wait = WRONG_KEYS.blocked_for(who)
    if wait:
        raise web.HTTPTooManyRequests(text="Too many wrong keys. Try again later.",
                                      headers={"Retry-After": str(int(wait) + 1)})
    mac = _mac(request.headers.get("ID"))
    dev = _waiting_device()
    if mac is None or dev is None:
        WRONG_KEYS.wrong(who)                          # someone knocking: slows down a scan
        return _refused(NOT_PAIRING)
    owner = next((d for d in devices.all_devices()
                  if d.get("kind") == Trmnl.id and (d.get("setup") or {}).get("mac") == mac), None)
    if owner is not None and owner["id"] != dev["id"]:
        return _refused(f"This TRMNL is already the device {owner.get('name')}. Pair it again from there.")
    key = devices.rekey(dev["id"])                      # a key it had before stops working
    setup = dev.get("setup") or {}
    fid = setup.get("friendly_id") or _friendly_id()
    devices.update(dev["id"], setup={**setup, "mac": mac, "friendly_id": fid})
    devices.set_state(dev["id"], model=_clip(request.headers.get("Model")),
                      firmware=_clip(request.headers.get("FW-Version")),
                      paired_at=datetime.now().astimezone().isoformat(timespec="seconds"))
    _PAIRING.clear()
    print(f"{dev['name']}: paired a TRMNL ({_clip(request.headers.get('Model')) or 'model not said'})", flush=True)
    return web.json_response({"status": 200, "api_key": key, "friendly_id": fid,
                              # Empty: no setup picture. One would replace the device's own logo,
                              # and the first page follows in the same wake (bl.cpp).
                              "image_url": "", "message": PAIRED_MESSAGE})


# ---------------------------------------------------------------- a wake

def _clip(value, n=32) -> str:
    return re.sub(r"[^\x20-\x7e]", "", str(value or ""))[:n]


def _number(value, cast=float):
    try:
        out = cast(str(value).strip())
    except (TypeError, ValueError):
        return None
    return out if out == out and abs(out) < 1e6 else None      # not NaN, not absurd


# A lithium cell's resting voltage against its charge, the usual curve. An
# estimate: load, temperature and age all move it.
BATTERY_CURVE = ((4.20, 100), (4.10, 90), (4.00, 80), (3.92, 70), (3.85, 60), (3.80, 50),
                 (3.75, 40), (3.70, 30), (3.65, 20), (3.55, 10), (3.40, 5), (3.20, 0))


def battery_percent(volts: float | None) -> int | None:
    if volts is None or volts < 2.5 or volts > 5.0:
        return None                                    # no reading (or USB power without a cell)
    if volts >= BATTERY_CURVE[0][0]:
        return 100
    for (v_hi, p_hi), (v_lo, p_lo) in zip(BATTERY_CURVE, BATTERY_CURVE[1:]):
        if volts >= v_lo:
            return round(p_lo + (p_hi - p_lo) * (volts - v_lo) / (v_hi - v_lo))
    return 0


def read_report(headers) -> dict:
    """What a wake says about the device, from its headers (request_headers.cpp)."""
    volts = _number(headers.get("Battery-Voltage"))
    return {
        "source": _clip(headers.get("Update-Source"), 16).lower(),
        "battery_v": round(volts, 2) if volts is not None else None,
        "battery": battery_percent(volts),
        "rssi": _number(headers.get("RSSI"), int),
        "width": _number(headers.get("Width"), int),
        "height": _number(headers.get("Height"), int),
        "model": _clip(headers.get("Model")),
        "firmware": _clip(headers.get("FW-Version")),
        "image_cached": str(headers.get("Image-Cached") or "").lower() == "true",
        # How long it was awake at its previous wake, in ms (sleep_session.cpp).
        "wake_ms": headers.get("Wake-Time"),
    }


def base_address(request) -> str:
    """The address the device called, without /api/...: where its picture is, so the
    firmware sends its key there too (it does for addresses that start with its server's)."""
    if reach.through_proxy(request):
        proto = (request.headers.get("X-Forwarded-Proto") or "https").split(",")[0].strip().lower()
        host = (request.headers.get("X-Forwarded-Host") or request.host or "").split(",")[0].strip()
        prefix = reach.COMPANION_PREFIX if reach.through_companion(request) else ""
    else:
        proto, host, prefix = request.scheme, request.host or "", ""
    if proto not in ("http", "https") or not HOST_RE.match(host):
        raise web.HTTPBadRequest(text="That address can't be used for a picture.")
    return f"{proto}://{host}{prefix}"


def _keep_image(dev: dict, png: bytes) -> str:
    """Keep a picture for the device to fetch; its name is its content hash, so an
    unchanged picture has the same name and the device skips the download."""
    rt = _rt(dev)
    name = "ep-" + paging.digest(png)                         # 19 characters: the firmware keeps 31
    images = rt.setdefault("images", OrderedDict())
    images[name] = png
    images.move_to_end(name)
    while len(images) > KEEP_IMAGES:
        images.popitem(last=False)
    rt["last_png"] = png
    # What the editor shows as "what it shows", straight away rather than at the next render.
    f = runtime.device(dev["id"]).frames
    f.strip = f.single = png
    f.strip_etag = f.single_etag = frames._etag(png)
    return name


async def _publish(dev: dict, rep: dict, seen: str) -> None:
    session = runtime.SESSION
    name = dev.get("name") or "TRMNL"
    if rep["battery"] is not None:
        await publish_entity(session, devices.entity_id("sensor.epaper_battery", dev), rep["battery"], {
            "friendly_name": f"{name} · Battery", "unit_of_measurement": "%", "device_class": "battery",
            "estimated_from_voltage": True})
        await publish_entity(session, devices.entity_id("sensor.epaper_battery_voltage", dev), rep["battery_v"], {
            "friendly_name": f"{name} · Battery voltage", "unit_of_measurement": "V", "device_class": "voltage"})
    if rep["rssi"] is not None:
        await publish_entity(session, devices.entity_id("sensor.epaper_wifi_signal", dev), rep["rssi"], {
            "friendly_name": f"{name} · Wi-Fi signal", "unit_of_measurement": "dBm",
            "device_class": "signal_strength"})
    await publish_entity(session, devices.entity_id("sensor.epaper_last_seen", dev), seen, {
        "friendly_name": f"{name} · Last seen", "device_class": "timestamp", "icon": "mdi:clock-check-outline"})


async def api_display(request):
    """One wake: what it reports, which picture, and how long to sleep."""
    dev = device_for(request, Trmnl.id, always=True)
    known = (dev.get("setup") or {}).get("mac")
    if known and _mac(request.headers.get("ID")) != known:
        WRONG_KEYS.wrong(reach.sender(request))        # its key, from another device
        raise web.HTTPUnauthorized(text="invalid or missing token")
    rep = read_report(request.headers)
    now = datetime.now().astimezone()

    if rep["width"] and rep["height"]:
        size = T.sized_display(Trmnl.id, rep["width"], rep["height"])
        if size and size != T.get_display(dev.get("display"))["id"]:
            dev = devices.update(dev["id"], display=size)
            print(f"{dev['name']}: says it is {rep['width']} × {rep['height']}; drawing for that", flush=True)
            runtime.LIVE._event().set()               # render at the new size now
    seen = now.isoformat(timespec="seconds")
    devices.set_state(dev["id"], last_seen=seen, wake_source=rep["source"],
                      **{k: rep[k] for k in ("battery", "battery_v", "rssi", "model", "firmware") if rep[k] not in (None, "")})
    paging.note_awake(dev, rep["wake_ms"])
    await _publish(dev, rep, seen)

    try:
        got = await paging.wake(dev, person=rep["source"] not in ("timer", ""), art=ART, now=now)
        png, sleep_for = got.picture, got.sleep
    except Exception as exc:
        # Nothing new to show: it keeps its picture and asks again at its next wake.
        print(f"{dev['name']}: couldn't pick its picture: {health.describe(exc)}", flush=True)
        png, sleep_for = None, paging.update_seconds(dev)
    body = {"status": 0, "image_url": "", "filename": "", "refresh_rate": int(sleep_for),
            "update_firmware": False, "firmware_url": "", "reset_firmware": False}
    if png:
        name = _keep_image(dev, png)
        body.update(image_url=f"{base_address(request)}/api/image/{name}", filename=name)
    return web.json_response(body)


async def api_image(request):
    dev = device_for(request, Trmnl.id, always=True)
    png = (_rt(dev).get("images") or {}).get(request.match_info["name"])
    if png is None:
        raise web.HTTPNotFound(text="That picture is gone. A new one is drawn at the next wake.")
    return web.Response(body=png, content_type="image/png", headers={"Cache-Control": "no-cache"})


async def api_log(request):
    """The device's log lines ({"logs": [...]}, serialize_request_api_log.cpp), kept briefly."""
    dev = device_for(request, Trmnl.id, always=True)
    try:
        body = await request.json()
    except Exception:
        body = {}
    entries = body.get("logs") if isinstance(body, dict) else None
    logs = _rt(dev).setdefault("logs", deque(maxlen=KEEP_LOGS))
    for entry in entries if isinstance(entries, list) else []:
        msg = entry.get("message") if isinstance(entry, dict) else entry
        if msg:
            logs.append({"at": time.time(), "message": _clip(msg, 200)})
    return web.Response(status=204)


# ---------------------------------------------------------------- the editor

def _trmnl_by_path(request) -> dict:
    try:
        dev = devices.get(request.match_info["id"])
    except KeyError:
        raise web.HTTPNotFound(text="There's no such device.")
    if dev.get("kind") != Trmnl.id or not shown(dev):
        raise web.HTTPNotFound(text="That device isn't a TRMNL.")
    return dev


async def _home_host() -> str:
    """Home Assistant's name on the home network: what a panel's setup was given, or its own home
    address. Never the browser's, which may be a tunnel's (reach.home_address)."""
    for dev in devices.all_devices():
        raw = str((dev.get("setup") or {}).get("ha_host") or "").strip()
        host = urllib.parse.urlsplit(raw if "://" in raw else f"//{raw}").hostname or ""
        if reach.HOST_RE.fullmatch(host):
            return host                                # what a panel's setup was given
    return await reach.home_address(runtime.HASS, runtime.SESSION)


async def _pairing(request, dev: dict) -> dict:
    port = await panel_setup._detect_external_port(runtime.SESSION)
    addresses = [{"where": "home", "url": f"http://{await _home_host()}:{port}"}]
    away = await reach.public_base(runtime.HASS)
    if away:
        addresses.append({"where": "away", "url": away})
    dev = devices.get(dev["id"])
    return {"device": dev["id"], **KIND.describe(dev), "update_minutes": KIND.update_minutes(dev), "addresses": addresses,
            "reach": reach.settings()["mode"]}


async def editor_pair_get(request):
    return web.json_response(await _pairing(request, _trmnl_by_path(request)))


async def editor_pair_open(request):
    """Listen for this TRMNL for ten minutes (a new one, or pairing an old one again)."""
    dev = _trmnl_by_path(request)
    open_pairing(dev["id"])
    print(f"{dev['name']}: listening for a TRMNL for {PAIR_SECONDS // 60} minutes", flush=True)
    return web.json_response(await _pairing(request, dev))


KIND = register(Trmnl())
