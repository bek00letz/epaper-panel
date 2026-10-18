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
- Evaluates `alert` and `when` page conditions (`show_if`), per-element `show_if` visibility, and `quiet_hours` schedule/presence state, then builds the in-memory PNG buffers:
  - `frames.png` — every active rotation slice stacked vertically (`792 × 272·N`). The panel holds it in PSRAM and blits a 272 px slice, so paging with the hardware buttons or an IKEA BILRESA scroll remote needs no network round trip. When an `alert` (interrupt) page triggers, `frames.png` shrinks to a 1-page strip containing only that alert for `hold_minutes` and calls `esphome.<device>_show_page`, decoding in ~1 s and preventing the panel's timer from rotating away during the hold window.
  - `frame.png` (and `/frame.png?page=N`) — single-page PNG slice for the current slot or any specific slice index `N`, driving dashboard previews and single-page wake flows.

### Self-Describing Strip Metadata & In-Flight Download Guard

Two subtle hardware/firmware race conditions originally caused intermittent black screens or remote navigation glitches:
1. **Torn In-Flight Downloads:** ESPHome's `online_image` clears/reallocates its target PSRAM buffer as soon as an HTTP download starts (`GET /frames.png`), taking ~5–6 s to decode a multi-page strip. If the 10-second rotation interval or a remote action fired mid-download, the display lambda blitted an uninitialized/zeroed PSRAM buffer (`COLOR_ON` with `invert_colors: true` = solid black screen).
2. **Asynchronous Sensor Desync:** `sensor.epaper_categories` (`ha_cat_offsets`, `ha_cat_sizes`, `ha_cat_pill_widths`) arrived over the ESPHome native API out of lockstep with the HTTP strip download, so a remote `page_step` could compute a slice offset beyond the strip height (`y_offset >= strip.height`).

To eliminate both races atomically and keep manual scrolling and locks responsive:
- **Self-Describing Metadata Rows (`meta_y`):** `server.py` encodes a binary header starting at row `meta_y = dh * total_slices` (`x = 0 ..`, 1 bit per pixel, MSB first, black = 1, wrapping row-major across rows if needed):
  - `Byte 0`: `0xA5` magic marker (`10100101`)
  - `Byte 1`: `0x02` format version (version 2)
  - `Byte 2`: `cat_count` (`N`, up to 30)
  - `Bytes 3 .. 3 + 3·N - 1`: `(offset, size, pill_width)` tuple for each category (v1 backward-compatible prefix)
  - `Byte 3 + 3·N`: `0xA5` when **Night / Quiet Hours** (`quiet_hours_active`) is active, or `0x00` when inactive
  - `Bytes 3 + 3·N + 1 .. + 2`: `rotate_seconds` (`(rot_sec >> 8) & 0xFF`, `rot_sec & 0xFF`) so local PSRAM rotation interval syncs without reflashing
  - `Bytes 3 + 3·N + 3 .. + 4`: 16-bit content hash (`etag_b0`, `etag_b1`) so `HTTP 304 Not Modified` responses skip redundant physical e-paper refreshes
  - `Byte 3 + 3·N + 5`: `flags` (bit 0: `FLAG_INTERRUPT` indicating an emergency Home Assistant alert owns the screen)
  - `Bytes 3 + 3·N + 6 .. + 7`: `page_count` (`P`, 16-bit big-endian)
  - `N × 4 Bytes`: 32-bit Blake2s stable identities for each category (`cat_ids`)
  - `P × 4 Bytes`: 32-bit Blake2s stable identities for each slice (`sub_ids`, derived from ESPN event IDs, flight callsigns, Jellyfin items, or layout keys)
  - Final Byte: CRC-8 checksum (polynomial `0x07`, init `0x00`) covering all preceding bytes
- **Identity-Based Locking & Navigation Resolution:** Firmware tracks `pinned_cat_id`, `pinned_sub_id`, `cur_cat_id`, and `cur_sub_id` rather than numeric indices (`cat_idx`, `sub_idx`). When background downloads arrive (`on_download_finished`), even if new categories are inserted or removed, the panel searches `sub_ids` for the locked slice or `cat_ids` for the locked category, remapping `page`, `cat_idx`, and `sub_idx` losslessly. Sub-item rotation memory (`cat_sub_pos`) is remapped across category identity vectors so category insertions never scramble per-category cyclic rotation. If a locked event finishes and departs the rotation, the lock releases cleanly with diagnostic logging.
- **Atomic Parse, `downloading_frames` Guard & 15s Manual Scroll Debounce (`user_cool_sec`):** `esphome/crowpanel-epaper.yaml` sets `id(downloading_frames) = true` before `component.update: frames` and clears it inside `on_download_finished`. Any manual button or remote action resets `user_cool_sec = 0`. Incoming background `refresh_now` actions route through `request_refetch`, which defers downloads (`pending_refetch = true`) whenever `user_cool_sec < 15` and executes them 15 seconds after manual scrolling stops.
- **Self-Contained Widget Active Windows & On-Demand `sensor.epaper_*` Publishing:**
  - Composite widgets (`sports_match`, `sports_racing`, `flight_tracker`) store their active-window parameters (`pre_buffer_hours`, `post_buffer_hours`, `window_mode`, `team`, `auto_window`) directly on the element in `layouts.json`.
  - During `eligible_pages()`, `_evaluate_widget_gate()` evaluates `compute_sports_active_window()`, `compute_racing_active_window()`, or `fetch_overhead_flights()` directly in Python so `tier: "when"` pages work immediately without requiring users to create or configure Home Assistant helper sensors.
  - `publish_computed()` only polls and publishes `sensor.epaper_*` entities (`sensor.epaper_sports_<league>`, `sensor.epaper_racing_<series>`, `sensor.epaper_flights_overhead`, `sensor.epaper_closest_aircraft`, `sensor.epaper_quiet_hours`, `sensor.epaper_panel_last_render`) for widgets actually present in `layouts.json`, and registers them via MQTT Auto-Discovery with a `unique_id` and `E-Paper Studio` device block when an MQTT broker is available.

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
in the bottom footer bar alongside the active category/sub-item pills.

**Rotation order as a single string.** `solar,cat,watch,cat,temps,dryer` —
repeating a name weights it, removing it disables it. Editable directly in the
editor's top bar with no ambiguity between "enabled" and "in the list".

**Structured bindings over raw Jinja.** Rather than requiring users to write
complex Jinja expressions (`{{ ((as_timestamp(...) - as_timestamp(now())) / 86400) | round(0, 'ceil') | int }}`),
elements declare structured intent (`show: days_until`, `date_formatted`, `attribute`,
`last_changed`). `binding.py` compiles and sanitizes the Jinja expression, while
`prefix` and `suffix` are applied in Python so numeric formatting and fallbacks
remain predictable and resilient.


