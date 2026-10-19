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
   ┌── panel (ESPHome) ─────────┐       ┌── add-on (addon/app) ─────────────────────┐
   │ dial / buttons / HA action │       │ :8080 editor + API, Ingress only          │
   │                            │       │ :8099 frames for the LAN                  │
   │ download task:             │       │                                           │
   │   GET /frames.epf  ◄───────┼───────┤   in-memory FRAMES (ETag / 304)           │
   │   check, then swap         │       │     ▲ render loop (60 s) / save / push    │
   │ main loop:                 │       │     ├ feeds/, widgets (sports, flights…)  │
   │   copy page + overlays     │       │     ├ HA /api/template, history, ws       │
   │                            │       │     └ mqtt_bridge → HA entities           │
   │   refresh_now  ◄───────────┼───────┤   panel_link → esphome.<node>_refresh_now │
   └────────────────────────────┘       └───────────────────────────────────────────┘
```

Where things live in `addon/app/`:

| Module | What it does |
|---|---|
| `server.py` | Entry point: starts the web apps and the background loops |
| `config.py` / `runtime.py` | Settings from the environment; what the running add-on holds. Always read as `config.X` / `runtime.X`, so changes are seen everywhere |
| `frames.py` | Which pages are live, their values, alerts, quiet hours, rendering, packing the frame file |
| `entities.py` / `mqtt_bridge.py` | The add-on's own values, and mirroring them into Home Assistant |
| `sources/` | Outside data (flights, sports, racing, weather, calendars), always through `live_data.py` |
| `panel_link.py` / `panel_ops.py` | Finding the panel and asking it to refresh or step |
| `panel_setup.py` / `firmware_gen.py` / `firmware/panel.yaml` | Panel setup, and the one source of the firmware YAML |
| `web.py` | The LAN frame server and the Ingress-only editor API |
| `layouts_store.py`, `ha.py`, `hass.py`, `fixture.py` | Pages on disk; Home Assistant calls; offline stand-in |
| `render/` | Drawing: layout, theme, footer geometry, sleep screen, the EPF encoder |

The add-on runs two HTTP listeners in one event loop:
- **Port `8080` (Ingress only):** the editor and its API. It refuses any client
  other than Home Assistant's Ingress proxy (`172.30.32.2`).
- **Port `8099` (LAN):** `/frames.epf` and `/frame.epf` for the panel, the PNG
  versions for the editor and older clients, and a minimal `/status`. ETag /
  `304 Not Modified`, optional `frame_token`.

Every 60 seconds, and right away on a save or push, `frames.refresh_frames()`:

- Runs the data sources and widgets and records their values (see
  [The add-on's own values](#the-add-ons-own-values)).
- Evaluates `alert` and `when` conditions, per-element `show_if` and quiet hours.
- Renders every live page, rotates it for the mounting orientation, and packs
  the lot into one **frame file** (`render/epf.py`).

### The frame file (EPF v3)

A 64-byte header, a category directory, a page directory, the pages as raw
1-bit rows exactly as the panel's buffer stores them, and a CRC-32. The panel
copies a page straight into its display buffer: no decoding.

- **Identity, not position.** Every category and page has a stable 32-bit ID
  (ESPN event, flight callsign, Jellyfin item, page name). The panel keeps
  its place and its locks by ID when pages come and go, and an alert never
  moves a lock.
- **The server owns the geometry.** The header's reserved bytes carry the
  footer pill positions in logical pixels, plus the rotate-and-mirror
  transform to the physical buffer (`FLAG_GEOMETRY`). They come from
  `theme.footer_geometry()`, the same function the footer is drawn with. The
  firmware draws its highlight and padlocks through that transform and
  hard-codes no layout. This is what ended the 0.8.33–0.8.37 overlay
  back-and-forth: before, the footer's numbers lived in two places and
  disagreed in portrait.
- **Mirroring.** The 5.79" and 4.2" (SSD1683) drivers store each row
  right-to-left, so pages are flipped before packing (`epf.MIRRORED_MODELS`),
  and the header says so.

### The firmware

`components/epf/` is an ESPHome external component. `epf_core.h` holds all
the logic (parsing, the pixel mapping, overlays and the navigation state
machine) with no ESP-IDF in it, and is compiled and tested on the host by
`tests/test_firmware.py` against frame files from the server's own encoder.
`epf_client.h` adds the network and the display.

- **Downloads never block.** A FreeRTOS task downloads into a back buffer
  and checks everything: CRC, that the file is for this panel's size, and
  that every offset and count stays inside the file. The main loop swaps it
  in. The dial, the buttons and the Home Assistant connection never wait on
  the network.
- **While someone is scrolling** (15 s after the last press), new frames
  wait, so the pages don't change under them.
- **One input path.** Every button, the dial, remotes and Home Assistant
  actions call `PanelController::dispatch(NavAction)`. That's also how the
  panel knows whether a person caused a redraw.
- **Ghost clearing** (`WaveformPolicy`). A person never causes a full
  refresh. Once N partials have built up (default 10, the "Ghost clear after"
  setting), the next automatic change is full. There's a fallback after 60 s
  still with 3×N built up, and a full refresh for alerts and when quiet hours
  start. "Every Nth refresh" restores the old fixed count. The driver's own
  `full_update_every` is set out of reach so only the policy decides.
- **The YAML has one source**: `addon/app/firmware/panel.yaml`, filled in by
  `firmware_gen.py`. Panel setup writes it into Home Assistant's ESPHome
  folder (keeping the previous file as `.previous`).
  `esphome/crowpanel-epaper.yaml` is the same output for a reference setup,
  and a test keeps them identical. The component is pinned to the add-on's
  release tag, so panel and add-on always agree on the format.
- **A way back**: `esphome/rollback/` holds the YAML of the previous
  firmware, pinned to its tag.

## The add-on's own values

Values the add-on computes (feeds, sports, racing, flights, quiet hours, last
render) live in one record inside the add-on, `runtime.PUBLISHED`.

- **Pages read that record directly** (`binding.local_value`) for `state` and
  `attribute` bindings. They don't round-trip through Home Assistant, so they
  work without a broker and never race the publish. Raw Jinja that names a
  `sensor.epaper_*` entity still goes through Home Assistant.
- **Home Assistant gets them over MQTT discovery only** (`mqtt_bridge.py`). The
  Supervisor hands over the broker login (`services: mqtt:want`). Each value
  is a sensor with a `unique_id` under an "E-Paper Studio" device, has
  availability through the add-on's last will, and is published only when it
  changes. Values unused for an hour are withdrawn, never in the first hour
  after a start.
- 0.8.x also wrote every value straight into the state machine
  (`POST /api/states`), so each sensor existed twice and the MQTT copy became
  `_2`. That path is switched off (`PUBLISH_VIA_STATES_API`). A one-time step
  removes the directly written states and restores each entity's intended ID.
  It only touches IDs Home Assistant suffixed itself (`<id>_<n>`).

## Outside data

`live_data.py`. Flights, sports, racing, weather and calendars are fetched in
the background; a render only reads what's already there and never waits on
an outside service. The first read of something new returns at once, using the
caller's fallback, and schedules the fetch. When it lands, the render loop
wakes, so a new widget fills in within seconds. A failed fetch keeps the last
good value. The seven fetchers in `sources/` are decorated `@runtime.live(seconds)`;
their own caches still stop them hitting a service more often than it allows.
The editor's preview (and its aircraft list) wait for fresh data, because
there a person asked.

## Sleeping

The frame file always starts with a sleep page (`render/sleep.py`, flagged
`CAT_FLAG_SLEEP`, no pill), so the panel can fall asleep instantly and offline.
The dial never pages onto it, and Home Assistant's `show_page`/`show_category`
numbers count only your pages.

Asleep is one state in `PanelController`: the sleep page is shown, with no
rotation, no timed downloads and no redraw unless the sleep page itself
changes. It's entered by holding the dial centre, the panel's **Sleep**
switch, or quiet hours (`CAT_FLAG_SLEEP_AUTO`, sent while they last if
"Sleep screen" is on). Any input first only wakes the panel, back to the page
it was on, and fetches fresh frames. During quiet hours it goes back to sleep
after 120 s untouched, and morning wakes it; a manual sleep lasts until
someone wakes it. A page or category lock wins over quiet hours, and an alert
wins over everything.

## Reaching the panel

`panel_link.py` is the only code that talks to the panel, through Home
Assistant. It never guesses names:

- **Actions**: an ESPHome node offering `refresh_now`, `page_step` and
  `show_page` is a panel. The device name from Panel setup picks one if there
  are several; with exactly one, it is used.
- **Entities** (refresh interval, IP, Wi-Fi) are found by registry
  `unique_id`, which ESPHome builds from the firmware's entity names
  (`<MAC>/0/number/Refresh interval`). It survives any rename of the entity ID.
- **A refresh is delivered or kept pending.** New content, alerts and the
  quiet-hours wake-up call `request_refresh()`. `panel_link_loop` retries
  with a backoff (5 s, 15 s, 30 s, then every 60 s) until Home Assistant
  confirms it. This matters most when quiet hours end, because the panel
  doesn't fetch on its own until it's woken.
- **The panel's own refresh interval is the one source of truth** for how
  often it fetches. The add-on only pushes when there is something new
  (`PROACTIVE_TIMED_PUSH` is off).
- **Live widget pages linger** (`render/linger.py`). Once a widget page has
  appeared, it stays 5 minutes after its condition last held, so a plane at
  the edge of the radius doesn't reshape the rotation every minute.

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


