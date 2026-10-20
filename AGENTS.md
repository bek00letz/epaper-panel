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
   Settings › Install or update so it writes the new file, then Install in
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
| `<homeassistant>:8099` | The device port: what each device fetches, found by its key (`kinds.device_for`). For a CrowPanel: `/frames.epf`, `/frame.epf`, the PNG fallbacks, and a minimal `/status`. `POST /api/action/refresh|page` always need a key. The first panel's frames need it once that panel has used it (`frame_token.py`). Remappable in the add-on's network settings |
| `<homeassistant>:8099` for a TRMNL | Only while the add-on option `trmnl` is on: `GET /api/setup` (pairing, only in the editor's ten-minute window), `GET /api/display` (one wake), `POST /api/log`, `GET /api/image/<hash>`. All but setup need its key in `Access-Token` |
| ESPHome node (`crowpanel-epaper`) | Exposes `refresh_now`, `show_page`, `page_step`, and `hold_toggle` actions over the encrypted ESPHome native API |

The device port is built to be reachable from the internet (Settings ›
Reaching home): never add anything to it that answers without a device's key
through `kinds.device_for` (the one exception is a TRMNL's `/api/setup`, which
answers only inside the editor's pairing window), and never let it say more
than a frame does.

## Conventions

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
  Size, orientation, seconds per page and quiet hours are the device's; pages
  and rotation are the design's. Read and write them through `devices.view` /
  `save_view` (or `layouts_store`), never by file. A kind of device lives in
  `kinds/`; the core never names one. A kind can be optional (`Kind.enabled`):
  list devices for anything a person or a render sees through
  `kinds.shown_devices()`, so a kind that's off shows nowhere.
- **A size a screen reports is a profile too**: `theme.sized_display` gives
  the kind's own profile, or `<kind>_<w>x<h>` made from it, which
  `theme.get_display` understands anywhere. Don't add one to `DISPLAYS` at
  runtime.
- **The first device keeps its legacy names**: the install's frame token, its
  download address, its entity IDs, its name in Home Assistant ("E-paper
  panel"). Don't "tidy" them: that's what keeps an upgraded panel working
  without a reflash.
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
- **Strokes under ~4 px are invisible on this panel** (145 dpi, so 3 px is
  0.5 mm). Icons drawn in the lambda need chunky geometry.

## TRMNL gotchas

From its firmware (`usetrmnl/firmware`), which is the authority here, not
TRMNL's API docs. `tests/test_trmnl.py` pins each of these.

- **Only ever send `"status": 0` from `/api/display`.** 202 makes it poll
  every five seconds (battery gone in a day), and 500 makes it forget its key
  *and its Wi-Fi*. Even for an error, send 0 and keep what it shows.
- **Always send `refresh_rate`**, at least 60. A missing one is stored as 0.
- **A refusal from `/api/setup` is HTTP 200 with `"status": 404`.** With any
  other HTTP code the firmware drops the message and shows nothing useful.
- **`filename` is the picture's hash and at most 31 characters**, never
  `empty_state` or `screen_wiper.png` (both mean something to it). Anything
  that changes every wake (a clock) makes it download and flash every wake:
  that's why "updated" is when the page last changed (`trmnl.steady`).
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
The 0.9 editor stays at `?classic=1` (`web/classic.html`) until the new one has
proven itself; ask the user before removing it. `docs/editor-redesign/` holds
the inventory every change is checked against.

- **Five things, one place each.** The screen (its name is the toolbar's
  title and switches between screens; Settings for the rest), the panel's
  state (status at the head of the page strip), the rotation (the page strip, above the
  canvas by default so the window reads from general to specific (below or
  down the side is a setting), *is* the rotation: drag to reorder, a page can sit in it twice), a page (the
  inspector when nothing is selected), an element (canvas and inspector).
  Don't give any of them a second home.
- **The canvas is the task**, so the chrome is deliberately quiet and the panel
  sits in a dark frame that reads as the device. Do not add colour or weight
  that competes with it. The canvas shows only the add-on's own render
  (`/api/preview`); everything else on it is an outline.
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
- **No confirmation dialogs.** Deleting shows an undo toast instead. There is
  a 60-deep undo stack; use it rather than asking "are you sure?".
- **One floating system** (`app/ui.js`): popover, menu, sheet, toast. No
  `prompt()`, `alert()` or `confirm()`; names are edited in place.
- **Hit targets are 44 pt.** Controls are 32 px with a padded hit area under a
  mouse and 44 px on touch. Don't shrink them to fit more in.
- **The legibility note sits under the size field** it describes. It is the
  one opinionated thing in the editor and the reason the tool is specific to
  this panel rather than a generic canvas.
- **Text goes in as text.** Build nodes with `h()`; only the icon constants
  in `util.js` use `innerHTML`. The editor shares an origin with Home Assistant.
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
  a content or shape change: the panel's refresh interval is the user's. A
  TRMNL can't be woken at all; its wake interval is a setting of that screen,
  and the editor says alerts show at its next wake. A CrowPanel away from
  home can't be woken either (that goes through Home Assistant's ESPHome
  connection, which is home only).

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
