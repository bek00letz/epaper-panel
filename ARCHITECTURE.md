# Architecture

## The constraint everything follows from

The panel is 139 × 48 mm and sits about 3 m from the sofa. At that distance
20/20 vision resolves a capital letter at roughly 4.4 mm — eye-chart threshold.
Comfortable glancing needs about 3× that.

| Text height | On panel | At 3 m |
|---|---|---|
| 11 px | 1.9 mm | invisible |
| 25 px | 4.4 mm | threshold, squinting |
| 75 px | 13 mm | comfortable |
| 110 px | 19 mm | effortless |

The panel is 272 px tall, so **one effortless line costs 40% of the screen**.
That kills the dense-dashboard idea: there is room for exactly one fact per
screen, which is why the panel rotates instead of tiling.

A second consequence: hierarchy is carried by *size*, not tone — there is no
grey on a 1-bit panel. The only exception is text above ~90 px, where a 50%
checkerboard screen reads as deliberate grey (used for the "nothing new"
empty state).

The footer is deliberately ~20 px, illegible from the sofa. It is the
walk-past layer: a timestamp so you can tell a live panel from a frozen one.

## Data flow

```
   ┌── panel (ESPHome) ────┐        ┌── E-paper Add-on (server.py) ──────────┐
   │ timer / button / push │        │ :8098 Ingress UI & API                 │
   │                       │        │ :8099 LAN Frame Server                 │
   │   GET /frames.png ◄───┼────────┤   in-memory FRAMES (ETag / 304)        │
   │   blit slice          │        │     ▲                                  │
   │                       │        │     │ frame_loop (60s) / save / push   │
   │   POST show_page  ◄───┼────────┤     ├ feeds/ (Jellyfin, REST, WS stats)│
   └───────────────────────┘        │     ├ HA REST /api/template            │
                                    │     └ HA REST /api/history/period      │
                                    └────────────────────────────────────────┘
```

The add-on runs two HTTP listeners inside the same event loop:
- **Port `8098` (Ingress-only):** serves the drag-and-drop layout editor and REST API (`X-Ingress-Path` aware), protected by Home Assistant's authentication.
- **Port `8099` (LAN frame server):** exposes `/frames.png`, `/frame.png`, and `/status` to the ESP32 panel on the local network (with `ETag` / `304 Not Modified` support and optional `frame_token` authentication).

Every 60 seconds (and immediately on layout save or panel push), `server.py` runs `refresh_frames()`:

- Polls configured `feeds/` (`jellyfin`, `rest`, `statistics`) and publishes their results back to Home Assistant as `sensor.epaper_<name>` entities.
- Evaluates `alert` and `when` page conditions (`show_if`) and builds two in-memory PNG buffers:
  - `frames.png` — every active rotation page stacked vertically (`792 × 272·N`). The panel holds it in PSRAM and blits a 272 px slice, so paging with the hardware buttons needs no network round trip. When an `alert` (interrupt) page triggers, `frames.png` shrinks to a 1-page strip containing only that alert for `hold_minutes` and calls `esphome.<device>_show_page`, decoding in ~1 s and preventing the panel's 5-minute timer from rotating away during the hold window.
  - `frame.png` — the single-page slice for the current slot, driving dashboard previews and single-page wake flows.

## Measured numbers

All from the device, not estimates:

| | |
|---|---|
| Partial refresh | **480 ms** |
| Full server-side render | **~250 ms** (including the Jellyfin call) |
| Decode, 1 page (2.8 KB) | **~1.0 s** |
| Decode, 6 pages (12.3 KB) | **~6.0 s** |
| Slice copy, direct (215 K px) | **328 ms** |
| Slice via `it.image()` at a negative offset | ~1,980 ms |
| Page change, button to pixels | **~810 ms** |

### Where fetch time actually goes

Three configurations, measured on the device:

| Configuration | Time |
|---|---|
| PNG strip, 12.3 KB, 512 B rx buffer | 5,960 ms |
| BMP strip, 163 KB, 512 B rx buffer | 5,184 ms |
| BMP strip, 163 KB, 8 KB rx buffer | 4,892 ms |

Dropping PNG saved 13%; a 16x larger receive buffer saved another 6%. So
**neither the codec nor the network dominates** — 1.29 M pixels in ~4.9 s is
~3.8 us each, which is `runtime_image`'s per-pixel write path. It calls through
per pixel regardless of source format, so switching to a raw bit-packed buffer
would not avoid it; only a custom component that `memcpy`s rows would, and that
is a rewrite rather than a setting.

The lever that works inside ESPHome is **fetching fewer pixels**: a single page
is 215 K pixels, roughly 0.8 s. That is the case for making a timer wake fetch
one page and only a button wake fetch the strip.

**PNG is kept despite being slower**, because wall-clock is not the cost that
matters on battery. ESPHome's ESP32 default is `power_save_mode: light`, so the
modem idles down between DTIM beacons during pure-CPU work. Rough energy:

| | Radio | CPU | Total |
|---|---|---|---|
| BMP 163 KB | 4.9 s @ ~95 mA | concurrent | ~466 mA·s |
| PNG 12.3 KB | 0.15 s @ ~95 mA | 5.8 s @ ~65 mA | ~391 mA·s |

Holding the receiver up costs more per second than running the decoder. These
are modelled, not metered — worth confirming with a meter, but the direction is
not close enough to be in doubt.

**Decode scales with pixels, not bytes.** The 6-page strip is only 4× the bytes
of one page but 6× the decode time. This was measured after assuming the
opposite; the assumption was wrong and would have produced a bad design.

**Do not use `it.image()` at a negative offset to pick a slice.** It works, but
walks all 1.29 M pixels of the strip to discard five sixths of them — about
2 s, which made paging *slower* than the network round trip it replaced.
`Image::get_pixel()` is public, so the display lambda copies only the 272 rows
it needs: 328 ms. This is why holding the strip is worth anything at all.

## The dial is not a dial

The five controls are **discrete push-buttons**, from Elecrow's own `5.79_key`
demo:

```c
#define HOME_KEY 2   #define EXIT_KEY 1
#define PRV_KEY  6   #define NEXT_KEY 4   #define OK_KEY 5
```

All active-low; the demo uses plain `INPUT`, so the board has its own pull-ups.
The Elecrow wiki calls IO4/IO6 a "rotary switch", which led to an ESPHome
`rotary_encoder` on those pins — it waits for quadrature transitions that two
independent buttons never produce, so no event ever fired. Treat the wiki's pin
table as unverified; the demo source is authoritative.

## Battery and deep sleep

Not yet implemented. The measurements above decide how it should be:

| Approach | Awake per wake | Per day | 5000 mAh lasts |
|---|---|---|---|
| Fetch the strip every wake | ~8.5 s | ~61 mAh | ~2.5 months |
| Single page on timer, strip only on a dial wake | ~3 s | ~22 mAh | ~7.5 months |

The second is barely more code: `esp_sleep_get_wakeup_cause()` distinguishes a
timer wake from an `ext1` (button) wake. A timer wake fetches `frame.png` and
sleeps in ~3 s; a dial wake pays the 6 s for the strip once, then every further
click is instant. You only pay for paging when you actually page. The renderer
already writes both files, so no server changes are needed.

**Deep sleep and remote control are close to mutually exclusive.** The panel
is unreachable ~290 s in every 300, so a Matter remote or dashboard button
would land maybe 3% of the time. Its own buttons are fine — they wake it. If
the panel ends up near a socket, staying mains-powered with a 60 s refresh and
working remote control is arguably the better product than deep sleep.

Caveats before enabling it:
- Deep sleep makes OTA nearly impossible — awake ~30 s in every 300. Keep the
  panel mains-powered while iterating.
- `ext1` with `ANY_LOW` treats a floating pin as a press and will wake the panel
  in a loop. Pull-ups are mandatory.
- Measure the board's real sleep current before mounting it somewhere awkward.
  The CH340 USB-serial chip is the usual reason these boards disappoint.
- A USB powerbank will not work: it sees a deep-sleeping ESP32 as "nothing
  plugged in" and cuts output after 10–30 s. Use a 1S LiPo on the JST.

## Decisions

**Thin client, not on-device rendering.** Drawing this in ESPHome display
lambdas means C++ inside YAML, manual glyph sets, hand-computed text widths and
a reflash per tweak. Pillow gives real fonts and a seconds-long iteration loop,
and keeps the data logic where it is debuggable.

**Not a screenshotted Lovelace dashboard.** Anti-aliased grey dithers badly at
1-bit, it needs headless Chromium on the HA box, and it breaks on frontend
updates.

**Long-term statistics over WebSocket, not a `utility_meter`.** The recorder's
long-term statistics already hold monthly/yearly totals with history, so a
helper would have started from zero and added nothing. `feeds/statistics.py`
queries `recorder/statistics_during_period` over the Home Assistant WebSocket
API and publishes the aggregated value as a `sensor.epaper_<name>` entity, so
pages can bind to it without direct SQLite file access.

**Jellyfin over its own API, not the HA integration.** The integration reports
who is watching; it knows nothing about the library. "New and unwatched" is
`/Items/Latest?IsPlayed=false&GroupItems=true`, which also groups a series into
one entry with a count. Sonarr/Radarr cannot answer it — they know what was
downloaded, not what was watched.

**A 30-day recency window.** Without it the rotation cycles a backlog forever
(58 unwatched Heroes episodes, 32 of The Voice). Settable in the data source
configuration.

**Conditional and interrupt pages.** The rotation is rebuilt every run from
pages that currently have something to say. `watch` drops out when nothing is
new rather than showing "nothing new" on the wall; `dryer` exists only while the
timer runs. When an `alert` page fires, the server replaces the strip with a
single-page alert frame for `hold_minutes` and pushes a refresh to the panel.

**The panel owns which page is shown; the server owns what the pages are.**
Paging had to move onto the device to be quick, which means display state
(current page, held or not) lives on the panel and is lost on reboot. The
server still decides the rotation's contents and order. The cost is that the
dashboard can no longer step the panel's page directly — it pushes through
`esphome.<device>_show_page` instead.

**Held state is drawn on the device, not baked into the image.** The pages are
pre-rendered server-side and the panel does not know which it will show when
one is rendered, so the padlock is drawn by the display lambda over the slice,
in the top-right margin that every page leaves free.

**Rotation order as a single string.** `solar,cat,watch,cat,temps,dryer` —
repeating a name weights it, removing it disables it. Editable directly in the
editor's top bar with no ambiguity between "enabled" and "in the list".
