#!/usr/bin/env python3
"""Render frames for the CrowPanel 5.79" e-paper panel.

The rotation is rebuilt from scratch on every run: a page appears only if it is
in the configured order AND currently has something to say. An empty Jellyfin
library drops the watch page out of the cycle rather than wasting a slot on it;
the dryer page exists only while the dryer is running.

Reads secrets.json for live Home Assistant data, and falls back to fixture.json
so it can be developed anywhere.

  ./render.py                      next page in the rotation -> frame.png
  ./render.py --page cat           force one page
  ./render.py --batt 86 --rssi -62 record panel telemetry with the render
  ./render.py --catalogue          every page and state, plus a contact sheet
"""
import argparse
import json
from datetime import datetime
from pathlib import Path

from PIL import Image

from . import pages
from . import sources
from . import theme as T


def save_atomic(img, path, fmt=None):
    """Write via a temp file and rename.

    The panel can fetch at any moment; an in-place save means it can read a
    half-written file. rename() is atomic on POSIX, so it only ever sees a
    complete frame.
    """
    tmp = path.with_suffix(path.suffix + ".tmp")
    # Pillow infers the format from the extension, and ".png.tmp" means
    # nothing to it -- so always say the format explicitly.
    img.save(tmp, fmt or path.suffix.lstrip(".").upper())
    tmp.replace(path)

HERE = Path(__file__).parent
STATE = HERE / "state.json"
DEFAULT_ROTATION = "solar,cat,watch,cat,temps"


def config():
    try:
        return json.loads((HERE / "secrets.json").read_text())
    except Exception:
        return {}


def load_state():
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {}


def save_state(st):
    STATE.write_text(json.dumps(st, indent=2))


def eligible(data, rotation):
    out = []
    for name in rotation:
        if name in pages.ALWAYS:
            out.append(name)
        elif name == "watch" and data.watch:
            out.append(name)
        elif name == "dryer" and data.dryer_remaining():
            out.append(name)
    return out or ["solar"]


def ctx(name, idx, total, data, clock=None):
    return {
        "clock": clock or datetime.now().strftime("%H:%M"),
        "label": f"{name.replace('_', ' ')} · {idx + 1}/{total}",
        "battery_pct": data.panel.get("battery_pct", 0),
    }


def render(name, data, c, item=None):
    if name == "watch":
        return pages.watch(data, c, item)
    if name == "dryer":
        return pages.dryer(data, c)
    return pages.ALWAYS[name](data, c)


def contact_sheet(frames, gap=14, bg=150):
    sheet = Image.new("L", (T.W + gap * 2, gap + (T.H + gap) * len(frames)), bg)
    for i, f in enumerate(frames):
        sheet.paste(f.convert("L"), (gap, gap + i * (T.H + gap)))
    return sheet


def build_data(cfg, st, args):
    panel = {"battery_pct": args.batt if args.batt is not None
             else st.get("battery_pct", 0),
             "rssi": args.rssi if args.rssi is not None else st.get("rssi", 0)}

    if cfg.get("ha_token") and cfg.get("ha_base"):
        data = sources.from_ha(cfg["ha_base"], cfg["ha_token"],
                               db_path=cfg.get("db_path",
                                               "/config/home-assistant_v2.db"),
                               panel=panel)
        src = "home assistant"
    else:
        data = sources.from_fixture(HERE / "fixture.json")
        data.panel = panel
        src = "fixture"

    key = cfg.get("jellyfin_key")
    days = args.watch_days or cfg.get("watch_days") or sources.WATCH_WINDOW_DAYS
    data.watch = sources.jellyfin_new(key, days=days) if key else []
    return data, src


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--page", help="force a single page")
    ap.add_argument("--catalogue", action="store_true")
    ap.add_argument("--rotation", default=DEFAULT_ROTATION)
    ap.add_argument("--batt", type=int, help="panel battery %% reported by the device")
    ap.add_argument("--rssi", type=int, help="panel wifi rssi reported by the device")
    ap.add_argument("--step", type=int, default=1,
                    help="slots to move: 1 = next (the timed rotation), -1 = back (dial)")
    ap.add_argument("--pin-toggle", action="store_true",
                    help="pin the current page, or unpin if already pinned")
    ap.add_argument("--watch-days", type=int, default=None,
                    help="how recent an unwatched item must be to count as new")
    ap.add_argument("--out")
    args = ap.parse_args()

    cfg = config()
    st = load_state()
    out = Path(args.out or cfg.get("out_dir") or (HERE / "out"))
    out.mkdir(parents=True, exist_ok=True)

    data, src = build_data(cfg, st, args)
    print(f"source: {src} | jellyfin: {len(data.watch)} new | battery: "
          f"{data.panel['battery_pct']}%")

    if args.catalogue:
        long_title = {"title": "Minions & Monsters", "detail": "film · 30 aug"}
        cases = [("solar", None), ("solar_month", None), ("cat", None)]
        cases += [(f"watch{i}", it) for i, it in enumerate(data.watch)]
        cases += [("watch_long", long_title), ("watch_empty", None),
                  ("temps", None), ("dryer", None)]
        data._s[sources.ENT["dryer"]] = {"state": "active", "remaining": "1:12:30"}

        frames = []
        for n, (tag, item) in enumerate(cases):
            name = "watch" if tag.startswith("watch") else tag
            img = T.to_1bit(render(name, data, ctx(name, n, len(cases), data, "18:04"), item))
            img.save(out / f"{n+1:02d}_{tag}.png")
            frames.append(img)
        contact_sheet(frames).save(out / "catalogue.png")
        print(f"catalogue -> {out}")
        return

    rotation = [p.strip() for p in args.rotation.split(",") if p.strip()]
    live = eligible(data, rotation)

    # Render every page in the rotation once. They go out as one tall strip the
    # panel keeps in PSRAM -- that is what lets the dial page with no network --
    # and the slice for the current slot is reused as frame.png for previews.
    frames, seen_watch = [], 0
    for i, nm in enumerate(live):
        item = None
        if nm == "watch" and data.watch:
            item = data.watch[seen_watch % len(data.watch)]
            seen_watch += 1
        frames.append(T.to_1bit(render(nm, data, ctx(nm, i, len(live), data), item)))

    tall = Image.new("1", (T.W, T.H * len(frames)), 1)
    for i, f in enumerate(frames):
        tall.paste(f, (0, i * T.H))
    # PNG, not BMP. BMP skips zlib and is ~13% faster in wall-clock, but it is
    # 13x the bytes, and holding the radio up costs more per second than the
    # CPU does: ~466 vs ~391 mA-s for the strip. See ARCHITECTURE.md.
    save_atomic(tall, out / "frames.png")

    # Which page is "current" still matters for the preview and for anything
    # driving the panel by request rather than by dial.
    pinned = st.get("pinned")
    if args.pin_toggle:
        current = live[st.get("slot", 1) - 1] if live else None
        pinned = None if pinned else current
        st["pinned"] = pinned

    if args.page and args.page in live:
        idx = live.index(args.page)
    elif pinned and pinned in live:
        idx = live.index(pinned)
    else:
        idx = (st.get("slot", 0) + args.step - 1) % len(live)
        st["slot"] = idx + 1

    save_atomic(frames[idx], out / "frame.png")

    st["pages"] = live
    st["battery_pct"] = data.panel["battery_pct"]
    st["rssi"] = data.panel["rssi"]
    st["rendered_at"] = datetime.now().isoformat(timespec="seconds")
    save_state(st)

    tall_bytes = (out / "frames.png").stat().st_size
    print(f"rotation {live} -> {live[idx]}"
          f"{' [pinned]' if st.get('pinned') else ''} | "
          f"strip {len(frames)}p {T.W}x{T.H * len(frames)} {tall_bytes}B")


if __name__ == "__main__":
    main()
