#!/usr/bin/env python3
"""E-paper panel service.

Renders the rotation on a timer and serves it two ways:

  * port 8099  - frames for the panel. No auth: the panel has no credentials
                 and cannot use ingress. LAN only.
  * ingress    - the editor and its API, behind Home Assistant's own login.

Frames are held in memory and swapped by reference, so a fetch can never see
a half-written file and there is nothing to clean up on disk.
"""
import asyncio
import io
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import aiohttp
from aiohttp import web
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
from render import pages, sources, theme as T  # noqa: E402

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
WEB_DIR = Path(__file__).parent / "web"
HA_BASE = os.environ.get("HA_BASE", "http://supervisor/core")
HA_TOKEN = os.environ.get("HA_TOKEN", "")
REFRESH = int(os.environ.get("REFRESH_SECONDS", "60") or 60)

FRAME_PORT = 8099
INGRESS_PORT = 8080

DEFAULT_ROTATION = "solar,solar_month,cat,watch,cat,temps"


class Frames:
    """The current render. Readers take a reference; the writer replaces it."""

    def __init__(self):
        self.strip = b""
        self.single = b""
        self.names: list[str] = []
        self.rendered_at = None
        self.error = None


FRAMES = Frames()


def _png(img) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def render_all(data, rotation):
    """Render every eligible page; return (strip_png, first_png, names)."""
    live, seen_watch, imgs = [], 0, []
    for name in rotation:
        if name in pages.ALWAYS:
            live.append(name)
        elif name == "watch" and data.watch:
            live.append(name)
        elif name == "dryer" and data.dryer_remaining():
            live.append(name)
    live = live or ["solar"]

    for i, name in enumerate(live):
        item = None
        if name == "watch" and data.watch:
            item = data.watch[seen_watch % len(data.watch)]
            seen_watch += 1
        ctx = {
            "clock": datetime.now().strftime("%H:%M"),
            "label": f"{name.replace('_', ' ')} · {i + 1}/{len(live)}",
            "battery_pct": 0,
        }
        if name == "watch":
            img = pages.watch(data, ctx, item)
        elif name == "dryer":
            img = pages.dryer(data, ctx)
        else:
            img = pages.ALWAYS[name](data, ctx)
        imgs.append(T.to_1bit(img))

    strip = Image.new("1", (T.W, T.H * len(imgs)), 1)
    for i, im in enumerate(imgs):
        strip.paste(im, (0, i * T.H))
    return _png(strip), _png(imgs[0]), live


def build_frames():
    """Blocking: fetch state and draw. Runs in a thread.

    Without a token (i.e. running outside the add-on) it falls back to the
    captured fixture, so the service can be developed and smoke-tested
    anywhere.
    """
    if HA_TOKEN:
        data = sources.from_ha(HA_BASE, HA_TOKEN)
    else:
        data = sources.from_fixture(Path(__file__).parent / "render" / "fixture.json")
    key = os.environ.get("JELLYFIN_KEY") or ""
    if key:
        data.watch = sources.jellyfin_new(
            key,
            base=os.environ.get("JELLYFIN_BASE") or sources.JELLYFIN_BASE,
            user=os.environ.get("JELLYFIN_USER") or sources.JELLYFIN_USER,
        )
    return render_all(data, [p.strip() for p in DEFAULT_ROTATION.split(",") if p.strip()])


async def render_loop(app):
    while True:
        try:
            strip, single, names = await asyncio.to_thread(build_frames)
            nxt = Frames()
            nxt.strip, nxt.single, nxt.names = strip, single, names
            nxt.rendered_at = datetime.now().isoformat(timespec="seconds")
            globals()["FRAMES"] = nxt          # swap by reference
            print(f"rendered {names} ({len(strip)}B strip)", flush=True)
        except Exception as exc:                # a bad render must not stop the loop
            print(f"render failed: {exc!r}", flush=True)
            FRAMES.error = repr(exc)
        await asyncio.sleep(REFRESH)


async def frame_png(request):
    f = FRAMES
    if not f.single:
        raise web.HTTPServiceUnavailable(text="no frame rendered yet")
    return web.Response(body=f.single, content_type="image/png")


async def frames_png(request):
    f = FRAMES
    if not f.strip:
        raise web.HTTPServiceUnavailable(text="no frame rendered yet")
    return web.Response(body=f.strip, content_type="image/png")


async def status(request):
    f = FRAMES
    return web.json_response({
        "pages": f.names,
        "rendered_at": f.rendered_at,
        "strip_bytes": len(f.strip),
        "error": f.error,
        "refresh_seconds": REFRESH,
    })


async def editor_index(request):
    index = WEB_DIR / "index.html"
    if not index.exists():
        return web.Response(text="Editor not built yet.", content_type="text/plain")
    return web.FileResponse(index)


async def start(app_runners):
    panel = web.Application()
    panel.add_routes([
        web.get("/frame.png", frame_png),
        web.get("/frames.png", frames_png),
        web.get("/status", status),
    ])

    editor = web.Application()
    editor.add_routes([
        web.get("/", editor_index),
        web.get("/api/status", status),
    ])
    if WEB_DIR.exists():
        editor.router.add_static("/static/", WEB_DIR)

    for app, port in ((panel, FRAME_PORT), (editor, INGRESS_PORT)):
        runner = web.AppRunner(app)
        await runner.setup()
        await web.TCPSite(runner, "0.0.0.0", port).start()
        app_runners.append(runner)
        print(f"listening on :{port}", flush=True)


async def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    runners = []
    await start(runners)
    await render_loop(None)


if __name__ == "__main__":
    asyncio.run(main())
