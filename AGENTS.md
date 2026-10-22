# Notes for agents

Read [ARCHITECTURE.md](ARCHITECTURE.md) before changing how anything works.
This file is about not stepping on rakes.

## Working on this project

Many sessions work on this at once. One coordinator owns the project's state
and its releases; everyone else builds. These rules apply to every session,
including ones the coordinator didn't start. **Start by reading
[docs/STATUS.md](docs/STATUS.md)**: what's released, what's in flight, the
backlog and the decisions already made.

**Workers**
- Work on your own branch in your own git worktree, never in the shared
  folder (`~/Documents/HA/epaper`). Never switch the shared folder's branch:
  it stays on `main`.
- Note each change under **Unreleased** at the top of `addon/CHANGELOG.md`,
  in plain language.
- Never bump the version, tag or push. When done, report to the coordinator:
  your branch, what changed, what's tested, what isn't, and whether it touches
  the firmware (`components/` or `addon/app/firmware/`).

**The coordinator**
- Is the only one who merges into `main`, bumps the version in
  `addon/config.yaml`, turns "Unreleased" into the release's heading, tags
  `vX.Y.Z` and pushes. Only after the user says yes to that specific release.
- Updates `docs/STATUS.md` after every release and every finished piece of
  work.
- Has the "framework, not patch" review run when a good amount of work has
  piled up since the last one: several features or a large release, not every
  small fix. The review session ("framework-review", or a new one with the
  same brief) reads `git diff <last reviewed>..<release branch>`, changes
  nothing, and reports ranked findings; fixes go to workers. STATUS.md records
  where the last review ended.

**A release that touches the firmware** (`components/` or the firmware YAML)
is tagged and pushed before the user installs the panel's firmware: the panel
builds `components/epf` from the tag matching the add-on version.

**Release checklist**
1. The full test suite, once:
   `./.venv/bin/python -m unittest discover -s tests`
2. If the firmware changed, it compiles locally: a copy of the generated YAML
   with the `epf` source as `type: local`, then
   `.esphome-venv/bin/esphome compile <copy>`.
3. The reference YAML is regenerated:
   `python tests/test_firmware.py --write-reference`.
4. The CHANGELOG entry is in plain language and says whether the firmware
   changed.
5. `docs/STATUS.md` is updated.
6. Tag and push, then tell the user exactly what to do in Home Assistant:
   Rebuild the add-on; when the firmware changed, open the editor's
   Settings › Install or update and choose Send to ESPHome, then Install in
   the ESPHome add-on.

## Rule #1: this is a product, not a patch

**We are building a product other people install, not fixes that work "for
now".** The bulk of the bugs and vulnerabilities have been cleaned out, and the
code was refactored so it stays easy to work on. Keep it that way:

- **Fix the cause, not the symptom.** A change that only makes one scenario
  look right is not done. Say plainly when something is a mitigation.
- **Build frameworks, not one-offs.** Support for a device, a size or a data
  source must work for every device of that kind, every size and every user,
  not the one on our desk. No hard-coded models, sizes, addresses or names.
- **One source of truth.** No second path that does the same thing slightly
  differently.
- **Pin the behaviour with tests**, and keep what works disabled (not
  deleted) until its replacement has proven itself.

## Only ship it if Apple would ship it

**Everything we make together — apps, sites, scripts with UI, artifacts,
dashboards, even CLI output — has to look and feel like something Apple
shipped.**

This is not about a visual style (not "make it white", not "add Liquid
Glass"). It's about the small details people never notice consciously but
always feel. Before calling anything done, check it against this list:

### Feel
- Motion uses springs, not linear or default ease curves. Short (≈0.2–0.4s),
  interruptible, and it respects Reduce Motion.
- Every interaction answers back right away: press states, hover states,
  focus rings, haptics where the platform has them.
- Nothing jumps. Layout shifts, content popping in, and spinners that flash
  for 50ms are bugs. Use skeletons or fade-ins, and hold back loading
  indicators until a delay has passed.
- Sensible defaults so the first run already feels right. Fewer settings, not
  more.

### Look
- Typography does the hierarchy: the system font stack (SF Pro /
  -apple-system), tight tracking on large titles, a real type scale, tabular
  numbers where digits line up.
- Spacing sits on a consistent grid (4/8pt). Optical alignment wins over
  mathematical alignment when they disagree.
- Concentric corner radii (inner radius = outer radius − padding),
  continuous/squircle corners where possible.
- Restrained color: one accent, semantic colors, real dark mode (not
  inverted), hairline separators instead of heavy borders.
- Icons are SF Symbols, or match their weight and optical size.

### Care
- Empty states, error states, and edge cases get designed too, not left as
  defaults. Error messages are human, specific, and say what to do next.
- Copy is short and plain, in sentence case. No jargon, no exclamation marks.
- Accessibility is built in: Dynamic Type / scalable text, contrast,
  VoiceOver labels, keyboard navigation, hit targets of 44pt or more.
- Works at every size: phone width, narrow windows, huge screens. No
  horizontal scroll, no clipped text.
- Small touches nobody asked for: a correct app/tab icon, a sensible window
  title, remembered state, natural keyboard shortcuts, smart truncation.

When a tradeoff comes up between shipping fast and getting these details
right, flag it instead of quietly dropping the detail.

## Deploying

**The project is a Home Assistant add-on, installed from git.** No files get
copied by hand.

```bash
git push                      # from here
```

Then in Home Assistant: **Settings → Add-ons → e-Paper Panel → Rebuild**
(or Reload the repository first if `config.yaml` changed).

**Every release that ships is tagged `v<version>` and the tag pushed.** The
panel's firmware builds `components/epf` from the tag matching the add-on
version (`firmware_gen.component_ref`). Without the tag, the panel can't be
built. Treat any change under `components/` as a firmware change.

The add-on repository is https://github.com/bek00letz/epaper-panel, added in
HA as a custom add-on repository. `repository.yaml` at the root makes it one;
the add-on itself lives in `addon/`.

## Endpoints & Ports

| Endpoint | Purpose |
|---|---|
| HA Sidebar (`:8080` via Ingress) | Drag-and-drop visual editor and JSON API. Answers only Home Assistant's Ingress proxy (`172.30.32.2`); any other app on the internal network gets 403 |
| `<homeassistant>:8099` | The device port: what each device fetches, found by its key (`kinds.device_for`). For a CrowPanel: `/frames.epf` (`?cap=`, and from firmware that can sleep `wake=` and `awake_ms=`; while it sleeps between updates every answer has `X-EPF-Sleep`; always on, `X-EPF-Next`), `/frame.epf`, the PNG fallbacks, and a minimal `/status`. `POST /api/action/refresh|page` always need a key. The first panel's frames need it once that panel has used it (`frame_token.py`). Remappable in the add-on's network settings |
| `<homeassistant>:8099` for a TRMNL | Only while the add-on option `trmnl` is on: `GET /api/setup` (pairing, only in the editor's ten-minute window), `GET /api/display` (one wake), `POST /api/log`, `GET /api/image/<hash>`. All but setup need its key in `Access-Token` |
| ESPHome node (`crowpanel-epaper`) | Exposes `refresh_now`, `show_page`, `page_step`, and `hold_toggle` actions over the encrypted ESPHome native API |

The device port is built to be reachable from the internet (Settings ›
Reaching home): never add anything to it that answers without a device's key
through `kinds.device_for` (the one exception is a TRMNL's `/api/setup`, which
answers only inside the editor's pairing window), and never let it say more
than a frame does.

## Conventions

- **A request never draws.** The render cycle (`frames.refresh_frames` →
  `kinds.<kind>.render`) draws everything a device can fetch; device-port
  routes only hand over what's ready. The one exception is a device that asks
  before anything was drawn for the size it has now, and it's logged.
  `tests/test_draw_ahead.py` drives every kind's routes: add a new kind or
  route there. A screen that sleeps (a TRMNL; a CrowPanel updating every 2
  minutes or more) uses `paging.py` for what to show and how long to sleep;
  its kind keeps only its protocol.
- **The clock is lined up** (`cadence.py`, the user's call, 21 Oct: always,
  no setting). The render cycle runs just after each minute starts, and every
  device asks a moment after it: an always-on CrowPanel by each answer's
  `X-EPF-Next`, a screen that sleeps by its sleep being cut to wake then.
  Don't add a timer that counts from when something started; a new kind
  asks `cadence` when to come back.
- **Two timers per screen are the one source of truth** for when it fetches
  and whether it sleeps (`timing.py`): **Update every** (`update_minutes`;
  1 minute is always on, 2 or more sleeps between updates) and **Rotate
  every** (always on: `rotate_seconds`; asleep: `rotate_updates`, a whole
  number of updates). Set in the editor's Settings › Device (and the cards
  when adding a screen), applied at once, never sent with the pages. Read
  them through the kind (`Kind.update_minutes`, `Kind.sleeps`) or `timing`,
  never from a device's fields or a panel's own setup. A CrowPanel's own
  "Refresh interval" in Home Assistant is kept at Update every by the add-on
  (`crowpanel.keep_its_timer`). Whether a screen sleeps is never assumed from
  its kind, except that a kind that can't stay connected (`Kind.stays_on`
  false: a TRMNL) has no always-on choice. Before 0.13, `low_power`,
  `wake_minutes` and Panel setup's `refresh_interval` did this; they're read
  only as what an unset screen means and never written, so 0.12 still finds
  them.
- **Everything in `theme.py` is in panel pixels** (792 × 272), so the numbers
  match the design directly. Do not introduce a scaling factor.
- **Draw on an 8-bit canvas, threshold at the end** (`theme.to_1bit`). No
  dithering: hard edges are what e-ink wants.
- **No grey.** Size carries hierarchy. `theme.screen()` exists for large text
  only; at small sizes a checkerboard just looks broken.
- **Pages are data, not code** — `default_layouts.json`, or the user's own in
  `/data/designs/<id>.json`. An element carries its own box; there is no layout
  algorithm, because the editor produces absolute positions.
- **Never assume one screen.** Every render, push, link, entity, setup and key
  belongs to a device (`devices.py`), and a design can be shown by several.
  Size, orientation, quiet hours and its two timers are the device's; pages
  and rotation are the design's. Read and write them through `devices.view` /
  `save_view` (or `layouts_store`), never by file. A kind of device lives in
  `kinds/`; the core never names one. A kind can be optional (`Kind.enabled`):
  list devices for anything a person or a render sees through
  `kinds.shown_devices()`, so a kind that's off shows nowhere.
- **Everything about a size is in its profile** (`theme.DISPLAYS`), the
  firmware's facts too: `frame_model` (its id in a frame file), `mirrored`,
  `full_refresh` and `keep_picture` (the C++ for its driver). `epf.py` and
  `firmware_gen.py` read them; never add a table keyed by a size elsewhere.
- **A size a screen reports is a profile too**: `theme.sized_display` gives
  the kind's own profile, or `<kind>_<w>x<h>` made from it, which
  `theme.get_display` understands anywhere. Don't add one to `DISPLAYS` at
  runtime.
- **The first device keeps its legacy names**: the install's frame token, its
  download address, its ESPHome node name, its entity IDs. Don't "tidy" them:
  that's what keeps an upgraded panel working without a reflash. Its name is
  different: the add-on never changes it on its own, but a name the person
  gives it in the editor reaches Home Assistant at its next install, as for
  any screen (the user's call, 21 Oct). Home Assistant keeps the entity IDs.
- **A preset sets up what it needs, in place** (the user's call, 21 Oct:
  framework, not patch). A preset that needs a data source, or anything
  else before it can show something (Guest Wi-Fi's network), asks for it in
  its own next step in New page (`app/setup.js`, `SETUPS`), never by sending
  the person to Settings first. What it sets up is saved where Settings
  shows it (a data source through `PUT /api/sources`, the one store), so a
  second page reuses it and there is no second path.
- **Elements have IDs, unique in the design, and the editor gives them**
  (`doc.ensureIds`). Arrangements for other sizes are filed by them. Never
  make an element's identity depend on its position or its page.
- **Geometry is per size, content is shared.** `arrange.ARRANGE_KEYS` (box,
  text size) may differ between screen sizes; everything else an element has
  is the same on every screen showing the design. Don't add a per-size field
  anywhere else.
- **Prefer a structured binding over raw Jinja** (`render/binding.py`). An
  element says `{entity, show, format, prefix, suffix, replace}` and the engine
  builds the template. Supports `show: state`, `attribute`, `last_changed`, `last_updated`,
  `days_until` (days until date/calendar event), `date_formatted`, and `calendar_title`.
  `prefix` and `suffix` are applied in Python after Jinja evaluation and number formatting
  so they never break `float()` or inject template syntax. A literal `value` still wins
  as the escape hatch.
- **A page or element that cannot render must not take the panel down.**
  `resolve_templates` batches templates in one request for speed, but falls
  back to per-template evaluation if any expression in the batch has a syntax
  error.
- **Fonts ship with the project** (`fonts/Lato-*.ttf`, SIL OFL) and are cached
  in memory (`@lru_cache`). Do not depend on system fonts — the HA container
  has a different set from macOS.
- **Icons are outlines, and one list says what can be drawn**
  (`render/icons.py`, ARCHITECTURE.md › Icons). Material Design Icons ship
  with the add-on; Home Assistant's set and custom sets are copied whole into
  `/data/icons` when they change (`iconsets.py`), never per icon, never on
  demand, never during a render. Ask `layout.can_draw_icon` before offering
  an icon; never draw from `fonts/mdi.ttf` (the way back, `icons.FROM_FONT`).
  A custom SVG is read for its shapes only: never show one as it is.

## Verifying a change

```bash
# run the service locally; it falls back to render/fixture.json with no HA token
DATA_DIR=/tmp/epaper-data ./.venv/bin/python addon/app/server.py

# the tests (Python, plus the firmware core compiled on this machine)
./.venv/bin/python -m unittest discover -s tests
```

Then open `http://127.0.0.1:8080/` for the editor and
`http://127.0.0.1:8099/frames.png` for what the panel would fetch, and
*look at it*. Several layout bugs here — a detached cat
tail, a stray dash on the dryer icon, a missing ear — were invisible in code and
obvious in the image. Render it and open it.

For firmware: `tests/test_firmware.py` compiles `components/epf/epf_core.h`
on the host and checks it against the server's real frame files. The ESPHome
YAML comes only from `addon/app/firmware/panel.yaml`. After changing it, run
`python tests/test_firmware.py --write-reference` to refresh
`esphome/crowpanel-epaper.yaml`. To check it builds, compile a copy with the
`epf` source switched to `type: local` (`.esphome-venv/bin/esphome compile`).

## Firmware gotchas

- The panel needs the external component; stock `waveshare_epaper` has no model
  for it. `invert_colors: true` is required.
- **`GPIO7` is the display's power rail.** Nothing renders until it is high.
- The panel draws overlays from the geometry in the frame file. **Never
  hard-code footer positions in firmware**; change `theme.footer_plan()`.
- ESPHome leaves ESP-IDF's HTTP client out unless a component asks for it;
  `components/epf/__init__.py` does (`include_builtin_idf_component`).
- This is an **esp-idf** build: no Arduino APIs. Use the `wifi_info` text sensor
  for the IP, not `WiFi.localIP()`.
- `psram: mode: octal` assumes an N8R8 board. Unconfirmed; if it will not boot,
  comment it out and read the boot log.
- **Trust Elecrow's demo source over their wiki** for pin numbers.
- **A network chosen on the panel's own Wi-Fi (captive portal) replaces every
  network in its YAML** until the next install (ESPHome stores one, keyed to
  the build). Say so wherever the hotspot is offered; don't promise both.
- **One Wi-Fi network uses `fast_connect`; several are scanned for.** A fast
  connect only ever tries the first network (`firmware_gen.wifi_block`).
- **HTTPS is checked against ESP-IDF's certificate bundle**
  (`esp_crt_bundle_attach`, enabled in `components/epf/__init__.py`). Don't
  turn checking off to make a tunnel work; fix the tunnel's certificate.
- **`on_boot` fires before wifi is associated.** A fetch there races the
  network and loses. `refetch` waits on `wifi.connected` first; keep it that way.
- **Changing navigation state does nothing on screen on its own.** Follow it
  with `script.execute: redraw`, or the change only appears at the next
  unrelated refresh. This is what made the hold indicator look stuck.
- **Every input goes through `PanelController::dispatch()` (a person) or
  `remote()` (Home Assistant, automations).** Don't call navigation methods
  directly (they're private): the waveform policy and sleep rely on knowing
  whether a person is at the panel.
- **Full refreshes are the policy's decision** (`begin_redraw()` in the redraw
  script). Don't call `force_full_update()` anywhere else.
- **Only the main loop touches the front buffer and the display.** The
  download task writes the back buffer; `EpfClient::poll()` swaps them on the
  main loop. Keep it that way, or a page can be drawn mid-swap.
- **The own timer fetches when the answer said** (`X-EPF-Next`,
  `PanelController::aim_fetch`), checked in the 200 ms loop. A download
  starting uses the hint up (`reset_fetch_idle`), so a fetch out of turn is
  realigned by its own answer. Without a hint, the interval decides.
- **Only an answer from the add-on puts the panel to sleep** (`X-EPF-Sleep`,
  `PowerPolicy` in `epf_core.h`, script `go_to_sleep`). `deep_sleep` has no
  `run_duration` and must never get one: the same firmware stays connected
  when it's always on.
- **Never sleep while the display is refreshing.** Deep sleep cuts its power
  rail. The CrowPanel driver refreshes in the background, so the panel waits
  for `id(epd).is_idle()` (`firmware_gen.display_settled`).
- **Every button's `on_press` calls `PowerPolicy::note_press`**, or a press
  doesn't keep the panel awake. A new button needs it too.
- **Strokes under ~4 px are invisible on this panel** (145 dpi, so 3 px is
  0.5 mm). Icons drawn in the lambda need chunky geometry.

## TRMNL gotchas

From its firmware (`usetrmnl/firmware`), which is the authority here, not
TRMNL's API docs. `tests/test_trmnl.py` pins each of these.

- **`refresh_rate` is whole seconds, counted from when it falls asleep**
  (after drawing, `goToSleep` in `sleep_session.cpp`), not from the answer.
- **Only ever send `"status": 0` from `/api/display`.** 202 makes it poll
  every five seconds (battery gone in a day), and 500 makes it forget its key
  *and its Wi-Fi*. Even for an error, send 0 and keep what it shows.
- **Always send `refresh_rate`**, at least 60. A missing one is stored as 0.
- **A refusal from `/api/setup` is HTTP 200 with `"status": 404`.** With any
  other HTTP code the firmware drops the message and shows nothing useful.
- **`filename` is the picture's hash and at most 31 characters**, never
  `empty_state` or `screen_wiper.png` (both mean something to it). Anything
  that changes every wake (a clock) makes it download and flash every wake:
  that's why "updated" is when the page last changed (`paging.steady`).
- **The picture's address must start with the address the device was given**,
  or it doesn't send its key (`isSameOrigin` is a prefix check). Build it from
  the request (`trmnl.base_address`), never from a setting.
- **`Content-Type: image/png` exactly**: anything else is read as a BMP.
- **Its messages are ASCII.** Its font has nothing else.
- **It doesn't check HTTPS certificates.** Treat its key as readable by
  whoever can intercept its connection: a key must never unlock more than
  that one screen's pictures, and pairing again must replace it.
- **Nothing on the device port answers a TRMNL without its key**, except
  `/api/setup` in the window, and that gives a key only to a MAC address no
  other TRMNL has.

## Editor design decisions

The editor is `addon/app/web/`: `index.html`, `editor.css` and plain ES
modules in `app/` (no build step, nothing from the internet, the system font).
It's the only editor: the 0.9 one was removed in 0.13 (the way back is any tag
up to v0.12.0). `app/legacy.js` keeps the pieces of it this one still uses.
`docs/editor-redesign/` holds the inventory every change is checked against.

- **Five things, one place each.** The screen (its name is the toolbar's
  title and switches between screens; Settings for the rest), the panel's
  state (status at the head of the page strip), the rotation (the page strip, above the
  canvas by default so the window reads from general to specific (below or
  down the side is a setting), *is* the rotation: drag to reorder, a page can sit in it twice), a page (the
  inspector when nothing is selected), an element (canvas and inspector).
  Don't give any of them a second home. The one exception, on purpose (the
  user's call, 21 Oct): the screen bar under the canvas (`app/screenbar.js`)
  keeps four everyday screen settings in sight and in reach — power and
  Update every, Rotate every, quiet hours on or off, Mounted — like Control
  Center next to Settings. Settings › Device keeps them too and has the
  rest; both change them through the same functions. Nothing else goes in it.
- **Say "device", not "screen"** (the user's call, 21 Oct): in everything a
  person reads (the editor, its messages, the README, the add-on's options),
  the things you add and manage are devices: Add new device, Settings ›
  Device, "There's already a device called Kitchen." Next to "New page",
  "screen" read like another page. Code, API paths (`/api/devices`), stored
  keys and Home Assistant entity names keep their words; changing those
  would break upgrades. "Screen" stays where it means the display itself:
  the sleep screen, what's on screen.
- **The canvas is the task**, so the chrome is deliberately quiet and the panel
  sits in a dark frame that reads as the device. Do not add colour or weight
  that competes with it. The canvas shows only the add-on's own render
  (`/api/preview`); everything else on it is an outline.
- **New page is shelves of presets, one per thing a page shows**
  (`app/newpage.js`; the presets are data in `app/presets.js`). One shelf
  per group, your own first; a preset's looks, leagues or series are picked
  in its next step, never separate cards. Presets are drawn on the 5.79"
  and placed on other devices the way `arrange.auto_box` places a design
  (`fitToCanvas`, pinned against it). Thumbnails there use the add-on's
  example values (`/api/preview` with `example`), never the person's own
  data, and never "--". What a preset shows is listed sensible first
  (`rankSensors`: the Energy dashboard's sensor picked and said so, then
  the right device class and unit). `tests/test_presets.py` draws every
  look at every offered size and fails on words wider than their box.
  A preset never writes a unit or a time format (framework review, 21 Oct):
  a value takes its sensor's own unit (`unit: "entity"`, `withUnits`), and
  a clock is the add-on's own (`show: "now"`), 12- or 24-hour as Settings ›
  Time and language says. Clock is offered on every device; one that sleeps
  draws the date in its place (`render/clocktime.py`), never the editor.
- **The editor keeps no copies of the add-on's tables** (framework review,
  21 Oct): leagues, series, sport words, state words and every widget's
  descriptor (name, icon, box, fields, `changes_every`) come from
  `GET /api/catalog` at start (`app/catalog.js`). A condition's value
  chips are the catalog's words for its kind, then what
  `/api/entity_states` says it has (`conditions.valueChoices`). Basic elements (text,
  value, icon, card, divider, gauge, charts, QR) stay the editor's; a new
  widget is a descriptor in `widgets.py`, nothing in the editor.
- **An icon follows a sensor in its own Icon section** (the user's design,
  21 Oct; `app/follows.js`): the switch "Changes with a sensor" comes
  first, so it never moves under the pointer; off, the plain icon is under
  it; on, the sensor, a row per state and the same icon as "Anything else",
  one control and never two. States are offered, not filled in: chips you
  tap, each with an icon already chosen, from `GET /api/entity_states`
  (`render/states.offered`: the kind's words, `options`, the recorder's
  last 10 days with the icon each state had), only icons the panel can draw
  (`layout.can_draw_icon`). A state matches whatever its case
  (`layout.icon_for_state`, the one lookup for icons and status spots).
  Each state has its own look, Plain, Inverted or Outlined (the user's
  call, 21 Oct), chosen at the top of the icon picker; the icon's own
  Style is "Anything else"'s, so the Style row hides while it follows.
  A row is `{icon, look}`, or just an icon (the first shape, which keeps
  the icon's Style): `layout.icon_in_state` reads both.
- **The inspector is ordered by how often things are touched**: what it shows,
  how it looks, arrange, then "More". Rare settings go under More, not away.
- **Picking: smallest thing under the pointer first.** Clicking again without
  moving goes to the next one, with the stack outlined and an "n of m" label.
  The layer list (front at the top) and the right-click "Under the pointer"
  list reach everything else.
- **A drag starts after 4 px (8 on touch).** A click never moves anything and
  never records an undo step.
- **Edits save as you go, to the draft (`/api/draft`), never to the panel.**
  Only Send to panel writes `/api/layouts` (with `If-Match`) and pushes. A
  409 merges by page; only a page changed in both places asks the user.
- **What isn't sent is shown, never guessed at** (the user's call, 21 Oct).
  One comparison of the draft with what the panel has, `doc.changes`: by
  page and by element ID, each page's place in the rotation, and the
  settings sent with the pages. The 409 merge, the page strip and the status
  card all read it; don't compare a second way. In the strip, an orange ring
  and a dot by the name mean "not sent yet" and nothing else (a passed
  countdown is greyed, not ringed); a removed page stays at the end, greyed,
  until it's sent or put back. The status card lists what's waiting by
  page; a line opens its page with its changed elements outlined until the
  first click or edit, and Undo puts that one page or setting back to what
  the panel has (`doc.revertPage`, `revertSetting`), with an Undo toast.
  Equal means equal as data (`same`): the order keys were written in is
  never a change.
- **No confirmation dialogs.** Deleting shows an undo toast instead. There is
  a 60-deep undo stack; use it rather than asking "are you sure?". A choice
  is not a confirmation: a tile's Delete opens a small menu, Take out of
  rotation or Delete page (the user's design, 21 Oct), because they are
  different actions and picking one is what guards against a slip. Both
  have an Undo.
- **A page's tile has two buttons on its picture**, Duplicate and Delete
  (`strip.js`), over its last third, Duplicate above Delete, or across the
  bottom half if Settings › Editor says so, kept for each strip size. The
  strip's sizes are made for them: the last third of the widest picture
  (the 5.79", 2.9 : 1) at Small holds two buttons of at least 32 px, and
  each tap area reaches 44 pt, out past the picture where it must
  (Duplicate's upwards, Delete's downwards). Don't shrink a size below
  that. The right-click menu keeps the fuller list.
- **One floating system** (`app/ui.js`): popover, menu, sheet, toast. No
  `prompt()`, `alert()` or `confirm()`; names are edited in place.
- **A row never squeezes its label or its control** (the user's calls,
  21 Oct): a label wraps to two lines at most and a control gets the width
  it needs, or it goes under its label, full width, its note staying under
  the label. One CSS rule for every row, `.field` and `.gr` (editor.css,
  "Rows"): a wrapping flex row where each control asks for its width
  (`--need`; a segmented control's from `ui.segNeed`, a long label marked
  by `ui.field`). A new kind of row uses these classes, never its own
  layout. Don't shorten the words or shrink the text to make one fit.
- **Hit targets are 44 pt.** Controls are 32 px with a padded hit area under a
  mouse and 44 px on touch. Don't shrink them to fit more in.
- **The legibility note sits under the size field** it describes. It is the
  one opinionated thing in the editor and the reason the tool is specific to
  this panel rather than a generic canvas.
- **Text goes in as text.** Build nodes with `h()`; only the icon constants
  in `util.js` use `innerHTML`. The editor shares an origin with Home Assistant.
- **One descriptor per widget** (`widgets.py`): its name, icon, default
  box, settings and inspector fields, how its value is fetched and how often
  it changes, its example and whether it makes items of its page. The render
  cycle, examples, sub-items and the editor (through the catalog) read it. A
  new widget is a descriptor plus its drawing, nowhere else.
- **The editor keeps no copies of the server's tables.** Leagues, racing
  series, each sport's words, state words, widget descriptors and the time
  format come from `GET /api/catalog`, built from the tables themselves
  (`sources/sports.LEAGUES`, `sources/racing.SERIES`, `render/sport.py`,
  `render/states.py`, `widgets.py`, `timeformat.py`).
  Icons too: the picker lists `GET /api/icons` and draws each from its
  outline (`app/glyphs.js`), never from a font or a list of its own.
- **Times of day go through `render/clock.py`**: one 12/24-hour setting
  (`timeformat.py`, Home Assistant's country by default) for every device.
- **Dynamic units live in the renderer** (`render/units.py`), so the canvas and
  the panel agree. The editor's copy of the tables only draws the example.

## Inputs

Five discrete push-buttons, **not** a rotary encoder, despite what the Elecrow
wiki calls them: `NEXT 4`, `PRV 6`, `OK 5`, `HOME 2`, `EXIT 1`, all active-low.
Confirmed from Elecrow's `5.79_key` demo source, which is authoritative — the
wiki's pin table is unverified and its page is headed "5.19-inch".

When touching display code, `it.image()` at a negative offset is a trap: see
[ARCHITECTURE.md](ARCHITECTURE.md#measured-numbers).

## Talking to Home Assistant and the panel

- **A render never waits on an outside service.** Anything that calls ESPN,
  Flightradar24, OpenSky, a racing calendar, a data source, or a slow Home
  Assistant service goes through `live_data` (`@runtime.live(seconds)`, see
  `sources/`; `entities.publish_sources` for `feeds/`), and callers must cope
  with "no value yet".
- **A failing service must be visible.** A new service's host goes in
  `health.SERVICES`; anything else reports with `health.ok()` /
  `health.fail()`. That's what the problem sensors in Home Assistant show.
- **Only alerts, quiet hours and people wake the panel early.** Never push on
  a content or shape change: the screen's Update every is the user's. A
  screen that sleeps between updates (a TRMNL; a CrowPanel updating every 2
  minutes or more) can't be woken at all, and the editor says alerts show at
  its next update. A CrowPanel away from home can't be woken either (that goes
  through Home Assistant's ESPHome connection, which is home only).

- **Never guess an entity ID or an action name** from a device name. Find the
  panel through `panel_link.PanelLink` (service list, registry unique_ids).
- **Never write entities with `POST /api/states`.** The add-on's values go
  through `mqtt_bridge` (or stay internal without a broker). Writing both is
  what made every sensor exist twice in 0.8.x.
- **A call that can fail must say so.** Return whether Home Assistant accepted
  it, and show the truth in the editor. Don't report success you didn't get.

## Security & data hygiene

- **Errors reach logs and responses only through `health.describe(exc)`.**
  Never `repr(exc)` or `{exc!r}`: aiohttp's errors carry the request headers,
  which is how the add-on's Home Assistant token and Jellyfin's key ended up in
  the log before 0.10.1.

- **The LAN port serves frames and nothing else that matters.** No layouts,
  no page names, no quiet-hours reason (it can reveal whether anyone is home).
  Every device has its own key; the key is also how a request says which
  device it is. The first panel's key is the install's frame token
  (`frame_token.py`, the option or a generated one). Its frames switch to
  requiring it the first time the panel uses it, so a reinstall never leaves
  the panel blank. Actions always need a key.
- **Never read Home Assistant's own storage folder** (`.storage` in its
  configuration): it holds every integration's credentials. Ask Home
  Assistant through its API instead (as the way back,
  `iconsets.collections_on`, asks Custom Icons which collections are on);
  `tests/test_icon_sets.py` fails if any code names it.
- **Icons never depend on another integration.** Your own SVGs and Iconify
  sets are the add-on's own (`iconsets.py`, Settings › Icons). Don't send
  users to Custom Icons (thomasloven/hass-custom_icons): its "Download
  Iconify icons" replaces `aiohttp.ClientSession` for the whole Home
  Assistant process, which broke other integrations (Eufy cameras) until a
  restart (issue #37, our fix PR #38, unmerged). Its folder and zip are only
  read, so existing setups keep working.
- **An Iconify download happens only when the user asks**, never in the
  background loop, and only from `iconsets.ICONIFY` / `ICONIFY_API`.
- **No built-in location or timezone.** Home Assistant's settings are the
  source; a default would be someone's real home.

- The add-on gets a supervisor token automatically (`homeassistant_api: true`).
  All entity IDs and source slugs interpolated into Home Assistant API paths
  must be validated (`valid_entity_id` / `feeds.clean_slug`).
- Data source secrets (`key`, `headers` in `/data/sources.json`) are stored with
  `0600` permissions and masked (`••••••••`) when served via `GET /api/sources`.
- Never interpolate unescaped user or entity strings into `innerHTML` in
  `web/index.html` — the editor runs inside Home Assistant Ingress on the same
  origin as Home Assistant.
- Never commit real IP addresses, domain names, API keys, or personal names.
