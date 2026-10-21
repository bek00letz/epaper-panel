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
   │   GET /frames.epf  ◄───────┼───────┤   frames per device (ETag / 304)          │
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
| `devices.py` | The screens the add-on drives, the design each shows, the shared library; keys; the move in from one panel |
| `kinds/` | Kinds of device (`crowpanel.py`, `trmnl.py`): their sizes, device-port and editor routes, how they're woken, and what they fetch; which kinds are on; the one key check (`device_for`) and the wrong-key slowdown |
| `paging.py` | Screens that sleep between updates (a TRMNL; a CrowPanel updating every 2 minutes or more): pictures drawn ahead, the cursor, the sleep time, the awake time |
| `cadence.py` | When things happen on the clock: the render cycle just after each minute starts, and when each device asks (the always-on hint, a sleep's wake) |
| `timing.py` | Every screen's two timers, Update every and Rotate every: the choices, what a screen set before 0.13 means, and what the editor shows |
| `render/arrange.py` | One design on several sizes: element IDs, automatic placement, each size's arrangement |
| `reach.py` / `companion.py` / `companion/epaper_panel/` | Reaching home: how screens away from home get in, and the Home Assistant integration that passes them on |
| `frames.py` | Per design: which pages are live, their values, alerts. Per device: quiet hours, then its kind renders it |
| `entities.py` / `mqtt_bridge.py` | The add-on's own values, and mirroring them into Home Assistant |
| `sources/` | Outside data (flights, sports, racing, weather, calendars, to-do lists), always through `live_data.py` |
| `panel_link.py` / `panel_ops.py` | Finding a panel and asking it to refresh or step |
| `panel_setup.py` / `firmware_gen.py` / `firmware/panel.yaml` | Panel setup, and the one source of the firmware YAML |
| `web.py` | The device port (shared routes; each kind adds its own) and the Ingress-only editor API |
| `layouts_store.py`, `ha.py`, `hass.py`, `fixture.py` | Checking what the editor saves (stored through `devices`); Home Assistant calls; offline stand-in |
| `render/` | Drawing: layout, theme, footer geometry, sleep screen, the EPF encoder |

The add-on runs two HTTP listeners in one event loop:
- **Port `8080` (Ingress only):** the editor and its API. It refuses any client
  other than Home Assistant's Ingress proxy (`172.30.32.2`).
- **Port `8099` (the device port):** what each device fetches, found by its
  key (`kinds.device_for`): for a CrowPanel `/frames.epf` and `/frame.epf`, the
  PNG versions for older clients, and a minimal `/status`; for a TRMNL (when
  its option is on) `/api/setup`, `/api/display`, `/api/log` and its pictures. ETag /
  `304 Not Modified`. Every device has its own key. The first panel's is the
  install's frame token: the option, or one the add-on generates. Its frames
  start requiring it once the panel has first used it (`frame_token.py`), so
  moving a panel over never blanks it.

Just after each minute starts (`cadence.py`), and right away on a save or
push, `frames.refresh_frames()`:

- Runs the data sources and widgets and records their values (see
  [The add-on's own values](#the-add-ons-own-values)).
- Per design: evaluates `alert` and `when` conditions and per-element
  `show_if`, and resolves the live pages' values, once however many screens
  show it (`frames.DesignState`).
- Per device: evaluates its quiet hours, then its kind renders the pages at
  its size and mounting. For a CrowPanel that's one **frame file**
  (`render/epf.py`), fitted to what that panel holds. For a screen that
  sleeps, it's every picture it can fetch at its next wakes
  ([Screens that sleep](#screens-that-sleep)).

**The clock is lined up** (`cadence.py`). The cycle starts at hh:mm:00.5 by
the add-on's clock (a `refresh_seconds` under a minute adds renders within
it; longer, it renders on whole minutes, every so many from midnight in Home
Assistant's time zone). The first after a start runs at once. A render that
runs past the next one's start is followed by another at once, with a log
line: never a skipped minute. Every device asks a moment after the render has
usually finished (`fetch_second`: the slowest of the last few renders plus a
margin, at most 20 s into the minute): an always-on CrowPanel is told when on
every answer (`X-EPF-Next`), and a screen that sleeps has its sleep cut to wake
then. So a clock on a page is right within a few seconds; counted from when
each happened to start, it could be two minutes behind. The devices need no
clock of their own: every hint is "this long from now".

**A request never draws.** The cycle draws everything a device can fetch
before the next cycle; the device port's routes only hand over what's ready.
A device's radio is on while it waits for its answer, so drawing then costs
battery, and two places that draw would sooner or later draw differently.
The one exception: a device that asks before anything was drawn for the size
it has now (just after a start, or it just said it has a new size) is drawn
for there and then, and the log says so. `tests/test_draw_ahead.py` drives
every kind's device routes after a cycle and fails if anything draws; a new
kind or route has to be added there. Commands (`POST /api/action/refresh`)
aren't fetches: they ask for a cycle, which is where drawing happens.

## Devices, designs and kinds

The add-on drives **devices** (`devices.py`): screens of any supported kind
and size. Each shows a **design**, its pages and rotation, and several can
show the same one. The **library** (saved presets and places) is shared by
every design.

| Belongs to | What | Stored in |
|---|---|---|
| The device | kind, name, size (`display`), orientation, quiet hours, key, its two timers (`update_minutes`, `rotate_seconds`, `rotate_updates`), its kind's setup (a CrowPanel's ESPHome settings) | `devices.json` (0600) |
| The design | pages, rotation | `designs/<id>.json`; one never saved is the shipped starter pages |
| The library | saved presets and places | `library.json` |
| What a device reports | how much it holds; for a screen that sleeps, its cursor, when each page last changed, recent awake times, a stay-awake request | `state/<id>.json` |

- **One shape for the editor and the renderer.** A device's *view*
  (`devices.view`) is its design plus its own settings plus the library:
  exactly what `layouts.json` held. So the editor's pages, drafts
  (`drafts/<id>.json`) and version tags are per device, and saving a view
  puts each part back where it belongs. Editor requests name the device with
  `?device=`; without it they mean the first.
- **The move in.** The first start with devices turns `layouts.json`,
  `panel_setup.json`, `draft.json` and `panel_capacity` into device 1 and
  design 1, and leaves those files untouched, so the previous add-on version
  still finds them. Device 1 keeps everything the panel knew: its key is the
  install's frame token, its download address is the same, and its Home
  Assistant entities keep their names. Other devices' entities end in a
  suffix fixed when they're added (`_kitchen`), so a rename never renames them.
- **Kinds** (`kinds/`) say what a device of that kind supports: its display
  profiles (`theme.DISPLAYS[*].kind`), the routes it adds to the device port
  and to the editor's API, whether the add-on can wake it (`link`), who picks
  the page, whether it can stay connected (`stays_on`) and so whether this
  screen sleeps between updates (`sleeps`), how a new one is set up (`setup_flow`: install or
  pair), what the editor shows about it (`describe`), its own settings and the
  entities it publishes. The core names no kind. `crowpanel` is the panel
  described in the rest of this file; `trmnl` has [its own section](#trmnl).
- **Two timers per screen** (`timing.py`), the same for every kind and the
  one source of truth for when it fetches. **Update every**: 1 minute is
  always on (a CrowPanel stays connected, its buttons answer at once, alerts
  and Home Assistant reach it straight away); 2 minutes up to a day, it
  sleeps between updates, and longer is lower power. **Rotate every**: always
  on, seconds, and the panel turns its pages itself; asleep, a whole number of
  updates (each wake refreshes the page on screen, every Nth moves on), at
  least once a day. Each mode keeps its own, so switching back finds what you
  had. They're set in Settings › Device and apply at once, never sent with the
  pages; a new screen chooses between two cards, always on picked. A kind
  that can't stay connected (`stays_on` false: a TRMNL) has no always-on
  choice and starts at 5 minutes. Whether a screen sleeps is never assumed
  from its kind otherwise: a plugged-in panel may sleep, one on a battery may
  stay on.
- **What 0.12 kept means the same.** Before 0.13 a screen had a Low Power Mode
  switch (`low_power`), a wake interval (`wake_minutes`) and, for a CrowPanel,
  its own refresh interval in Panel setup (`refresh_interval`). A screen not
  set since means what they meant: Low Power Mode off is always on, on keeps
  its wake interval, and the rotation time it kept with its pages is its own.
  They're never written or removed, so going back to 0.12 finds them as they
  were.
- **A kind can be optional.** `Kind.enabled()` is its add-on option. While
  it's off its routes aren't added (`web.make_apps`), its devices aren't drawn,
  and the editor lists none of them or their sizes (`kinds.shown`,
  `kinds.shown_devices`). They stay in `devices.json` for when it's on again.
- **Per-device runtime** (`runtime.device(id)`): the current frames, what was
  left out to fit, and the panel link. Alerts and lingering widget pages are
  per design (`runtime.alert`, `runtime.linger`), so an alert seizes every
  screen that shows its design.
- **Adding a screen** (`devices.add`): new (the starter page,
  `starter_design.json`, arranged by hand for every shipped size), a copy of
  another screen's pages placed for the new size (`arrange.bake`), or the
  same design (linked). Removing one is remembered with its key, so Undo puts
  it back.

### One design, several sizes

A design is made on one canvas (`canvas`, like `792x272`, after turning for
mounting). Every element has an ID, unique in the design, which the editor
gives it. Any other canvas has an **arrangement**: per element ID, its box
and text size there (`arrange.ARRANGE_KEYS`). Content and order belong to
the design and are the same everywhere.

- An element with no arrangement for a canvas is placed automatically: the
  design's content area (above the footer band) scaled to fit and centred. The
  view marks it `_auto`; the editor outlines it in dashes, and the first move
  or resize gives that size its own place for it.
- Saving a view (`arrange.merge_pages`) puts boxes into the design on its own
  canvas, or into that canvas's arrangement elsewhere. A new element made on
  another size gets a place on the design's canvas too. A deleted element
  leaves every arrangement. Renaming a page keeps them: they're filed by ID.
- A model or mounting change in the editor asks `/api/arrange` for the pages
  placed on the new canvas, as one undoable change sent like any other.
- **Groups** (`type: group`, `members`, `style`, `pad`) are a style around
  several elements: outline, pill, or the area inverted. Their shape is worked
  out at draw time from the members that are showing (`layout.group_box`), so
  it follows them on every size. The editor keeps the group's own box in step
  for picking, and a group comes with its members when selected.

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
  `theme.footer_plan()`, the same plan the footer is drawn with. The
  firmware draws its highlight and padlocks through that transform and
  hard-codes no layout. This is what ended the 0.8.33–0.8.37 overlay
  back-and-forth: before, the footer's numbers lived in two places and
  disagreed in portrait.
- **The footer fits itself to the screen.** `footer_plan()` plans one footer
  per screen and strip of pages. When it doesn't fit, things give way in a
  fixed order (`theme.FOOTER_STEPS`): first the page name (shortened, then
  dropped), then pill padding, then the two padlocks share one spot, then
  the counts shorten ("2/5" to "2"), then the margins, then the pill text,
  and last the clock. The clock comes last because it's how you see the
  panel is still syncing. The band at the bottom keeps the same height on
  every screen. Pill outlines are drawn from the panel's own shape
  (`theme.in_pill`), so its highlight covers them exactly.
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
- **The panel holds 2 MB of pages** (two 2 MB buffers in PSRAM, or 1 MB on a
  board that can't spare it) and says so on every download (`?cap=`). The
  add-on fits the frame file to it (`frames.fit_counts`): every page keeps its
  first item, extra items are shared out in rotation order, and pages at the
  end are left out only if one each doesn't fit. Items within a page are in
  order of importance (your teams, live, upcoming, finished; the closest
  aircraft; the newest episode). What was left out is in
  `sensor.epaper_panel_pages` and `/api/status` (`fit`).
- **A failed download is owed** (`note_fetch`, `fetch_due`): retried after
  30 s, doubling to 10 min, even while resting, because only a download can
  tell a sleeping panel that quiet hours are over. A refresh asked for while a
  download runs follows it.
- **While someone is scrolling** (15 s after the last press), new frames
  wait, so the pages don't change under them.
- **One input path, two doors.** The buttons and the dial call
  `PanelController::dispatch(NavAction)`: a person is at the panel, so a press
  while asleep only wakes it, and rotation and ghost clearing hold off.
  Home Assistant actions call `remote(NavAction)`: the panel wakes *and* does
  what was asked, and nobody is counted as standing there.
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
- **Wi-Fi**: one network connects straight away (`fast_connect`); several
  are scanned for, so a panel that travels joins whichever it finds. Where it
  finds none, it opens its own Wi-Fi with ESPHome's captive portal (a setting
  per screen, on by default) and its screen says which to join. A network
  chosen there replaces every network in the YAML until the next install:
  ESPHome stores one, keyed to the build.
- **HTTPS** addresses are checked against ESP-IDF's certificate bundle
  (`esp_crt_bundle_attach`), like a browser would.
- **A way back**: `esphome/rollback/` holds the YAML of earlier firmware
  versions, each pinned to its tag.

## The add-on's own values

Values the add-on computes (feeds, sports, racing, flights, quiet hours, last
render) live in one record inside the add-on, `runtime.PUBLISHED`.

- **Pages read that record directly** (`binding.local_value`) for `state` and
  `attribute` bindings. They don't round-trip through Home Assistant, so they
  work without a broker and never race the publish. So do the simple
  form's conditions on them (`conditions.local`, `frames.resolve_conditions`):
  "New to watch is above 0" is answered from the record. Raw Jinja that names
  a `sensor.epaper_*` entity still goes through Home Assistant.
- **Home Assistant gets them over MQTT discovery only** (`mqtt_bridge.py`). The
  Supervisor hands over the broker login (`services: mqtt:want`). Each value
  is a sensor with a `unique_id` under an "E-Paper Studio" device, has
  availability through the add-on's last will, and is published only when it
  changes. A value is withdrawn only when nothing configured produces it any
  more and it hasn't been refreshed for an hour (never in the first hour after
  a start). A source that is *failing* still produces it (`PUBLISHER.keep`),
  so an outage never deletes an entity.
- **Every outside service reports its health** (`health.py`): the widgets'
  services by host through aiohttp tracing on the shared session, and each
  data source. Home Assistant gets one problem sensor per service
  (`binary_sensor.epaper_problem_<name>`, on after five minutes of failing),
  and `/api/status` lists them (`services`).
- 0.8.x also wrote every value straight into the state machine
  (`POST /api/states`), so each sensor existed twice and the MQTT copy became
  `_2`. That path is switched off (`PUBLISH_VIA_STATES_API`). A one-time step
  removes the directly written states and restores each entity's intended ID.
  It only touches IDs Home Assistant suffixed itself (`<id>_<n>`).

## Outside data

`live_data.py`. Flights, sports, racing, weather, calendars and to-do lists are fetched in
the background; a render only reads what's already there and never waits on
an outside service. The first read of something new returns at once, using the
caller's fallback, and schedules the fetch. When it lands, the render loop
wakes, so a new widget fills in within seconds. A failed fetch keeps the last
good value, unless it has a `stale_after` age (an aircraft list older than five
minutes is dropped). Your data sources (`feeds/`) go through the same store,
each on its own interval. The eight fetchers in `sources/` are decorated `@runtime.live(seconds)`;
their own caches still stop them hitting a service more often than it allows.
The editor's preview (and its aircraft list) wait for fresh data, because
there a person asked.

## Icons

Every icon is drawn from its outline (SVG path data), crisp at any size and
cut to 1 bit with the rest of the page (`render/vector.py`). What the panel
can draw is one list, by name (`render/icons.py`): `layout.can_draw_icon`,
the editor's picker (`GET /api/icons`, outlines in pages from
`POST /api/icons/outlines`, `app/glyphs.js`) and the states an icon offers
all read it, so nothing offers an icon that draws as nothing.

- **Material Design Icons ship with the add-on** (`icons/mdi.json.gz`, the
  version Home Assistant served when it was built), so a first start, a Home
  Assistant restart or Home Assistant being unreachable still draws them all.
- **Home Assistant's own set is copied whole when it differs**
  (`iconsets.copy_home_assistant`): its frontend serves Material Design Icons
  as plain files on the add-on's network (`/static/mdi/iconMetadata.json`
  names the version and its chunks). Checked at start and every five minutes,
  but only fetched when Home Assistant's version changed and its icon version
  isn't the shipped one; every chunk, every outline checked, or nothing.
  Kept in `/data/icons/` and used from the next start before anything draws.
- **Custom sets are copied whole when their files change**
  (`iconsets.copy_custom`), from the mapped configuration folder: Custom
  Icons' SVG folder (`local:`) and Iconify sets, the ones switched on in its
  settings (asked of Home Assistant: `custom_icons/activesets`; the last
  answer, else Custom Icons' own defaults, while it can't say); and script sets HACS installs (custom-brand-icons' `phu:` and
  those written like it). A custom SVG becomes outlines only: shapes,
  groups, transforms, fill and stroke; scripts, links, pictures and text are
  never kept, and nothing of the file is shown as it is.
- A render never waits on any of this: the copy runs in the background and
  swaps a whole set in when it's ready (`icons.install`).
- One icon can't cost more than about twice the largest real one
  (`vector.MAX_*`: characters, commands, shapes, the area they cover,
  points): beyond that it's refused when copied and draws as nothing, so a
  crafted file can't slow a render. A zip member is read no further than the
  size it states, which is checked first.
- Sizes are what the old icon font gave: an icon fills its box's width by its
  whole square, and its height by its ink (`layout._fit_outline`). The font
  (`fonts/mdi.ttf`) stays, switched off, as the way back
  (`icons.FROM_FONT`).

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
after 120 s with no input of any kind (a press, or Home Assistant waking it), and morning wakes it; a manual sleep lasts until
someone wakes it. A page or category lock wins over quiet hours, and an alert
wins over everything.

## Reaching the panel

`panel_link.py` is the only code that talks to a panel, through Home
Assistant. Each CrowPanel device has its own link. It never guesses names:

- **Actions**: an ESPHome node offering `refresh_now`, `page_step` and
  `show_page` is a panel. The device name from that panel's setup picks it.
  The only panel in Home Assistant is taken as ours only while the add-on
  drives a single CrowPanel.
- **Several panels' entities**: each panel's firmware names it after its
  screen (`friendly_name`), so Home Assistant's device has that name.
  Panel setup records it (`setup.installed_name`) when it writes the file,
  and the link takes the one device with that name, or reports.
- **Entities** (refresh interval, IP, Wi-Fi) are found by registry
  `unique_id`, which ESPHome builds from the firmware's entity names
  (`<MAC>/0/number/Refresh interval`). It survives any rename of the entity ID.
- **A refresh is delivered or kept pending.** Alerts, quiet hours starting or
  ending, and what a person does (Send, Push, the Refresh button, the action
  endpoint) call `request_refresh()`. `panel_link_loop` retries
  with a backoff (5 s, 15 s, 30 s, then every 60 s) until Home Assistant
  confirms it. This matters most when quiet hours end, because the panel
  doesn't fetch on its own until it's woken.
- **Update every is the one source of truth** for how often a panel
  fetches. Always on, the panel fetches on its own timer, its "Refresh
  interval" number in Home Assistant, aimed by each answer's `X-EPF-Next` at
  a moment after the add-on's next render (`cadence.py`; firmware without it
  keeps the plain interval); the add-on keeps that at Update every
  (`crowpanel.keep_its_timer`, checked every ten minutes in the background),
  because the panel keeps the number it had through an upgrade and even a
  reinstall. Sleeping, its own timer doesn't run and it can't be woken early,
  so `link` is None. Pages coming and going (a match starting, planes
  overhead) wait for it: a panel on a battery may fetch once an hour, and the
  add-on must not override that. Only the reasons above wake it early
  (`PROACTIVE_TIMED_PUSH` is off).
- **One render at a time.** `refresh_frames` holds a lock, so an older render
  can never finish last and put old pages back.
- **Live widget pages linger** (`render/linger.py`). Once a widget page has
  appeared, it stays 5 minutes after its condition last held, so a plane at
  the edge of the radius doesn't reshape the rotation every minute.

## Screens that sleep

`paging.py`. A TRMNL always, and a CrowPanel updating every 2 minutes or
more, sleep between updates and let the add-on pick the page. They share one mode; each kind keeps
only its protocol (how a wake asks, how the answer is said).

- **Drawn ahead** (`draw_ahead`, from the kind's `render`). Every item of
  every live page, the empty page and the sleep screen, each as the kind's
  picture (a TRMNL's PNG, a CrowPanel's one-page frame file), kept whole per
  screen until the next cycle replaces it. All of them rather than just the
  next one, so wakes close together (a press, then another) still find theirs.
- **"updated" is when the page last changed** (`steady`). A page is drawn
  again with the time it had; if it comes out the same, nothing changed and it
  keeps its bytes, so its name or ETag stays the same and the screen neither
  downloads nor flashes. Only on the day after does the day join the time.
- **A wake only picks** (`wake`). The cursor (in `state/<id>.json`): a
  timer wake shows the page it's on, drawn fresh, until that page has been
  shown at Rotate every's number of wakes (`shown`), then moves through every
  item of every live page (`step`); a person goes to the next page and the
  count starts again. Alerts show while they last; conditions and linger apply as
  everywhere.
- **The sleep time** (`sleep_seconds`): Update every (2 minutes to a day;
  `timing.py`), cut short to wake just after quiet hours start, and then
  to wake a moment after a minute's render (`cadence.align_sleep`: never
  later than asked). A TRMNL counts its `refresh_rate` from when it falls
  asleep, after drawing, so it lands a few seconds later still. During quiet hours: the sleep
  screen until they end, plus a minute. A press shows a page for two minutes.
  Presence has no end, so it checks again at its interval.
- **Quiet hours** come from the cycle, presence included. Their schedule is
  checked again against the clock at the wake (only arithmetic), so a wake
  just after they start or end never trusts a cycle from a minute before. A
  stale "quiet" would otherwise sleep until the same time tomorrow.
- **The awake time** (`awake_seconds`): how long the screen stays awake after
  this wake before it sleeps. None after a timer wake, a minute after a press,
  ten minutes when the editor asked it to stay awake for an update (counted
  from the wake that delivered the request). A TRMNL's protocol has no such
  field.
- **How long it was awake** (`note_awake`): each screen's last twelve awake
  times, as it reports them, and their average in the editor next to battery
  and Wi-Fi. A TRMNL sends `Wake-Time` (its previous wake, in ms,
  `sleep_session.cpp`); a CrowPanel will send `awake_ms`.

## TRMNL

`kinds/trmnl.py`, off unless the add-on option `trmnl` is on
(`config.TRMNL`). A TRMNL deep-sleeps, wakes on a timer or its button, asks
for one picture and sleeps again. It speaks TRMNL's "bring your own server"
protocol; everything here comes from its open-source firmware
(`usetrmnl/firmware`, commit `383d6ff`), and `tests/test_trmnl.py` builds its
requests and reads the answers the way that source does.

- **Pairing.** Adding a TRMNL in the editor makes the device (name, pages)
  and opens a ten-minute window for it (`POST /api/devices/{id}/pair`; one
  window at a time). In it, `GET /api/setup` from a MAC address no other
  TRMNL has is given a new key (`devices.rekey`) and a friendly ID. Outside
  it, the answer is HTTP 200 with `"status": 404` and a message: only then
  does the firmware show the message, and it sleeps five minutes before
  asking again. Refusals count as wrong keys. `image_url` is empty in the
  reply: a setup picture would replace the device's own logo, and its first
  page follows in the same wake.
- **Each wake** (`GET /api/display`) needs its key in `Access-Token` and
  its MAC in `ID`. Its battery, Wi-Fi, model and firmware go to
  `state/<id>.json` and to sensors. A reported `Width` × `Height` that isn't
  the device's size becomes its size (`theme.sized_display`: the TRMNL OG's
  own profile, or `trmnl_<w>x<h>` made from it), and it renders at the new
  size at once.
- **The page** is the shared mode's ([Screens that sleep](#screens-that-sleep)):
  drawn ahead in the cycle, picked at the wake. A timer wake moves through
  the rotation; a button wake, or any other wake reason, goes to the next page.
  `filename` is the picture's hash, so an unchanged page costs no download and
  no flash.
- **`refresh_rate` is always sent** (the firmware stores a missing one as 0):
  the shared mode's sleep time.
- **`Wake-Time`** (how long it was awake at its previous wake) is kept for the
  editor's average.
- **The picture** (`image_url`) is a 1-bit PNG, `Content-Type: image/png`
  exactly (what `bl.cpp` decodes as PNG). Its address is built from the one
  the device called (`base_address`: the forwarded host and the companion's
  prefix when it came through a proxy) because the firmware sends `ID` and
  `Access-Token` only to addresses that start with its server's.
- **Only `status` 0 is ever sent**: 202 makes it poll every five seconds,
  and 500 makes it forget its key and its Wi-Fi.
- `/api/log` is kept in memory (the last 20 lines) for the editor.

## Reaching home

`reach.py`. Screens away from the home network reach the add-on one of
three ways, chosen in Settings: at home only (the default), through Home
Assistant's address, or through the user's own address.

- **At home only**, requests that came through something on Home
  Assistant's internal network with proxy headers (a tunnel app, the
  companion) are refused, so a tunnel pointed at the add-on by mistake doesn't
  open it up.
- **Through Home Assistant's address**, the companion integration
  (`companion/epaper_panel/`) registers one view, `/api/epaper/…`, with no
  Home Assistant login, and passes requests to the device port on the internal
  network. It drops Home Assistant's own `Authorization` and cookies and adds
  `X-Forwarded-*`. All key checks stay in the add-on. The add-on installs it
  into `/config/custom_components`, keeps it at its own version on every
  start, asks for one restart, then creates its config entry (the flow asks
  nothing). The address screens use is Home Assistant's external URL, or Home
  Assistant Cloud's.
- **Away from home, every request needs a key** (no switch-over), and a
  sender with 10 wrong keys in 10 minutes is refused for 10 minutes
  (`kinds.WrongKeys`). The sender is the proxy's word for it (`CF-Connecting-IP`,
  `X-Forwarded-For`) only when the request came from the internal network.
- **CrowPanels** fetch over HTTPS from the address in their YAML, checked
  against ESP-IDF's certificate bundle (`epf_client.h`). Away from home they
  can't be woken early: that goes through Home Assistant's ESPHome connection.
- **TRMNLs** are given the address when they pair: the editor shows the home
  one and, with Reaching home on, the away one (`reach.public_base`). The
  companion passes `Access-Token` on like any other header. Their firmware
  encrypts but doesn't check certificates, so a server impersonating ours on
  a hostile network could read a TRMNL's key; the key only fetches that
  screen's pictures, and pairing again replaces it.

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

How a screen is powered is its owner's business, so it's a setting of each
screen (Update every), never a property of a kind. Three setups make sense:

| Setup | Update every | What you get |
|---|---|---|
| Plugged in | 1 minute (always on) | Instant updates, alerts at once, remote control. The default. |
| On a battery, always connected | 1 minute (always on) | The same, for as long as the battery lasts. The 5.79" idles below about 0.25 W (brief 0.5 W redraws), so a 20,000 mAh power bank (about 74 Wh) lasts roughly ten days, a bigger one weeks. A long test on a power bank is under way. |
| Sleeping between updates | 2 minutes to a day | Months on a battery, longer the longer it sleeps. Pages and alerts arrive at its next update; a button press updates it right away. A plugged-in panel can sleep too. |

### Sleeping between updates

Update every 2 minutes or more (Settings › Device, or the second card when
adding a screen; always on is the default) makes a CrowPanel a
[screen that sleeps](#screens-that-sleep).

**One firmware for both modes; the add-on decides on every download.**

- The panel says why it's awake when it fetches `/frames.epf`:
  `wake=timer|button|boot`, and `awake_ms=` (how long it was awake last
  time). Only firmware that can sleep sends `wake`, and the editor says when a
  sleeping panel hasn't yet (`firmware_sleeps`).
- While it sleeps between updates, every answer (200, 304 and 503 alike)
  carries `X-EPF-Sleep: <seconds>; awake=<seconds>`: how long until it checks
  again, counted from this answer, and how long to stay awake before
  sleeping. Always on, there's no such header, and the panel stays connected
  as it always has; instead every answer (200, 304 and 503) carries
  `X-EPF-Next: <milliseconds>`, when its own timer should fetch next, counted
  from when the answer's headers arrived. Older firmware ignores headers it
  doesn't know.
- Why a header and not a field in the frame file: a frame file is drawn once
  per cycle and served to every download, while the sleep time is worked out
  per download (the clock, quiet hours, a stay-awake request), and a 304 has
  no body at all. The frame file stays a picture of the pages.
- **A timer wake** gets one page, picked by the shared mode, as a frame file
  of its own (with the identity that page has among all of them, so a press
  afterwards keeps its place). It shows it and sleeps (`awake=0`). An
  unchanged page has the same ETag, so it's a 304: no download, and no
  redraw if the display kept its picture.
- **A button wake** (or a boot) gets every page, as always, and
  `awake=60`: it stays awake a minute after the last press, then sleeps.
- **Stay awake** (the editor, for an update over Wi-Fi) is the same field:
  at its next check the answer says `awake=600`, and any download in those ten
  minutes gets what's left. A press on the panel makes that check happen now.
- **Switching** takes effect at its next download. To sleep, the add-on asks
  a connected panel to fetch at once (a person did something); to stay on,
  the panel is asleep and finds out at its next update or press. The editor
  says which.
- Sleeping, the panel can't be woken early, so its kind gives no
  link: alerts show at its next check and its Refresh button leaves Home
  Assistant. Its ghosting and sleep settings live on the panel: change them
  while it's asked to stay awake.

### The firmware

The same firmware for both modes (`PowerPolicy` in `epf_core.h`, tested on
the host; the glue in `epf_client.h`; `go_to_sleep` in `firmware/panel.yaml`).

- ESPHome `deep_sleep` is always compiled in, with no `run_duration`: it
  never sleeps unless an answer says so, and `deep_sleep.enter` takes the
  duration then. Wake sources: the timer, and the five buttons (`EXIT 1`,
  `HOME 2`, `NEXT 4`, `OK 5`, `PRV 6`, all RTC-capable on the ESP32-S3) as
  `ext1` `ANY_LOW`, set just before it sleeps.
- `esp_sleep_get_wakeup_cause()` says timer, button or a fresh start; the
  first download says which (`wake=`), with how long the last wake was awake
  (`awake_ms=`, kept in RTC memory, `epf_power.cpp`).
- **When it sleeps:** once the answer's awake time has passed (and a minute
  after the last press), the download is done, and the display has finished
  its refresh. Deep sleep cuts the display's power, so a refresh still
  running would be cut short. The CrowPanel driver refreshes in the
  background and says when it's done (`is_idle()`); the Waveshare driver used
  for the other sizes can't, so the panel waits 6 s after its last redraw
  (`firmware_gen.display_settled`). Never during an update over Wi-Fi.
- **How long:** what the answer said, less the time it has been awake since.
- **What's on screen survives the sleep.** The frames don't (they're in
  PSRAM), but the picture does, and so does its ETag (RTC memory). A timer
  wake sends it, so an unchanged page (the sleep screen through a long
  absence, a one-page rotation) is a 304: no download, no redraw, no flash.
  Anything more after that downloads the frames again.
- **No answer at all** on a timer wake (no Wi-Fi, the add-on down): it was
  told to sleep before, so it's on a battery; it sleeps and tries again after
  60 s, doubling to 10 min, never longer than its interval. A press that
  can't reach the add-on stays awake a minute first. A fresh start that can't
  reach it stays connected, so its own Wi-Fi setup can open.
- **Floating buttons.** If the button pins float in deep sleep, `ANY_LOW`
  wakes the panel the moment it sleeps. Three button wakes in a row within
  2 s of falling asleep turn the buttons off as a wake source until the next
  timer wake, so a fault costs a few wakes per interval, not the battery.
- **The Home Assistant connection stays, and a wake never waits for it.** It
  connects if the panel is awake long enough (after a press, while asked to
  stay awake). `api: reboot_timeout` is `0s`: by default ESPHome restarts a
  panel that no client has connected to for 15 minutes, which helps nothing
  here and would cut a stay-awake short.

### Battery reading (designed, not built yet)

Elecrow's staff say the stock 5.79" can't read its battery
(forum.elecrow.com, discussion 1063); the board charges a LiPo through an
LTC4054 and nothing connects the cell to an ADC pin. The option, per screen
in Install or update, off by default: **Battery reading on GPIO n**, saying
plainly "Needs a resistor divider from the battery to that pin, soldered on;
the board has none." On, the generated YAML adds an `adc` sensor on that pin
(with the divider's ratio), and the voltage goes to the add-on with each
download, to the editor and to the same battery sensors a TRMNL has. Not
built yet: it needs a board with the divider to check against, and until
it's built the editor doesn't offer it, since it would do nothing.

### What it costs

At a 15-minute interval: 96 wakes a day. A timer wake fetches one page
(about 0.8 s of decode instead of about 6 s for the strip, see
[Measured numbers](#measured-numbers)) and is awake about 3 s, roughly
10 mAh a day of wakes. Between wakes, the board's sleep current decides:
anywhere from 0.24 mAh a day (10 µA) to 120 mAh a day (5 mA, a USB-serial
chip or regulator that never sleeps). On 5,000 mAh that's somewhere between
over a year and about five weeks: the sleep current is the number to
measure.

### To measure on a real board

- **Sleep current**, with the USB cable out. The CH340 USB-serial chip and
  the regulator's quiescent current are the usual reasons boards like this
  disappoint.
- **Whether the buttons' pull-ups work in deep sleep.** The demo reads them as
  plain inputs, so the board has pull-ups of its own; if they hang off a rail
  that's cut in sleep, the pins float and `ANY_LOW` wakes the panel in a
  loop. The RTC's own pull-ups are the fallback.
- **Whether the display needs a full, flashing refresh after every wake.**
  As built, it does: the CrowPanel driver makes its first refresh after any
  start a full one, and the display's power rail (`GPIO7`) is cut in deep
  sleep, so the controller loses its picture memory anyway. An unchanged page
  is a 304 and isn't redrawn at all. Holding the rail (`gpio_hold_en` on
  GPIO7) and putting the controller into its memory-keeping sleep might allow
  partial refreshes after a wake, at the controller's sleep current and a
  change to the driver: worth trying once the sleep current is known.
- **How long the first press takes**, from a deep-sleeping panel to the page
  on screen: boot, Wi-Fi, the strip's download and decode.
- A USB power bank may switch off when the panel sleeps, seeing "nothing
  plugged in". Use a LiPo on the JST, or a bank with an always-on mode.

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

The sensor's `detail` ("2 new episodes · yesterday") is kept as it always
was, and each part of it is also an attribute of its own (`jellyfin.PARTS`).
Every item in `items` carries the same parts, so a page that steps through
the items shows each one's own value (`subitems.item_value`).
A page that binds only details about the whole list (`subitems.WHOLE_FEED`,
such as `up_next`) stays one screen. The editor's three Jellyfin presets
(`legacy.js`) find the source's sensor through `feed` in `/api/entities`.

**A 30-day recency window.** Without it the rotation cycles a backlog forever
(58 unwatched Heroes episodes, 32 of The Voice). Settable in the data source
configuration.

**Conditional and interrupt pages.** The rotation is rebuilt every run from
pages that currently have something to say. `watch` drops out when nothing is
new rather than showing "nothing new" on the wall; `dryer` exists only while the
timer runs. When an `alert` page fires, the server replaces the strip with a
single-page alert frame for `hold_minutes` and pushes a refresh to the panel.
An alert that ends "when something happens" (`ends: until`, `until_if`) is
the same alert with the condition "it started and its Until hasn't happened
yet", and `hold_minutes` as its limit (`frames.check_alerts`,
`conditions.py`): it lets go when either changes or at the limit, and comes
back when the Until is undone while the start still holds. A held alert is
in memory only: a restart forgets it, and a start that's still true fires
again.

**To-do lists through Home Assistant's `todo.get_items`**, not each
service's own API, so every kind of list works (Shopping list, Local To-do,
Google Tasks, Todoist, CalDAV) with no keys. Home Assistant hands the items
over in the list's stored order, not by due date, so `render/todo.py`
orders them (due first, then the list's order) and gives the due labels,
for the page and for the add-on's count of what's due today or overdue
(`sensor.epaper_todo_<list>_due`, `entities.publish_todo_due`, one per list
on a page) alike. A list that doesn't fit
ends with "and 4 more" instead of paging: one calm screen.

**The panel owns which page is shown; the server owns what the pages are.**
(For an always-on CrowPanel. A TRMNL can't page on its own, and a sleeping
CrowPanel shows one page per timer wake, so for those the add-on picks:
see [Screens that sleep](#screens-that-sleep).)
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


