# Notes for agents

Read [ARCHITECTURE.md](ARCHITECTURE.md) before changing how anything works.
This file is about not stepping on rakes.

## Deploying

**The project is a Home Assistant add-on, installed from git.** No files get
copied by hand.

```bash
git push                      # from here
```

Then in Home Assistant: **Settings → Add-ons → E-paper panel → Rebuild**
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
| `<homeassistant>:8099` | Frame server for the panel on the LAN: `/frames.epf`, `/frame.epf`, the PNG fallbacks, and a minimal `/status`. `POST /api/action/refresh|page` always need the token. Frames need it once the panel has used it (`frame_token.py`). Remappable in the add-on's network settings |
| ESPHome node (`crowpanel-epaper`) | Exposes `refresh_now`, `show_page`, `page_step`, and `hold_toggle` actions over the encrypted ESPHome native API |

Never expose port `8099` or the panel's endpoints to the public internet.

## Conventions

- **Everything in `theme.py` is in panel pixels** (792 × 272), so the numbers
  match the design directly. Do not introduce a scaling factor.
- **Draw on an 8-bit canvas, threshold at the end** (`theme.to_1bit`). No
  dithering: hard edges are what e-ink wants.
- **No grey.** Size carries hierarchy. `theme.screen()` exists for large text
  only; at small sizes a checkerboard just looks broken.
- **Pages are data, not code** — `default_layouts.json`, or the user's own in
  `/data/layouts.json`. An element carries its own box; there is no layout
  algorithm, because the editor produces absolute positions.
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
  hard-code footer positions in firmware**; change `theme.footer_geometry()`.
- ESPHome leaves ESP-IDF's HTTP client out unless a component asks for it;
  `components/epf/__init__.py` does (`include_builtin_idf_component`).
- This is an **esp-idf** build: no Arduino APIs. Use the `wifi_info` text sensor
  for the IP, not `WiFi.localIP()`.
- `psram: mode: octal` assumes an N8R8 board. Unconfirmed; if it will not boot,
  comment it out and read the boot log.
- **Trust Elecrow's demo source over their wiki** for pin numbers.
- **`on_boot` fires before wifi is associated.** A fetch there races the
  network and loses. `refetch` waits on `wifi.connected` first; keep it that way.
- **Changing navigation state does nothing on screen on its own.** Follow it
  with `script.execute: redraw`, or the change only appears at the next
  unrelated refresh. This is what made the hold indicator look stuck.
- **Every input goes through `PanelController::dispatch()`.** Don't call
  navigation methods directly (they're private): the waveform policy relies
  on dispatch to know a person is at the panel.
- **Full refreshes are the policy's decision** (`begin_redraw()` in the redraw
  script). Don't call `force_full_update()` anywhere else.
- **Only the main loop touches the front buffer and the display.** The
  download task writes the back buffer; `EpfClient::poll()` swaps them on the
  main loop. Keep it that way, or a page can be drawn mid-swap.
- **Strokes under ~4 px are invisible on this panel** (145 dpi, so 3 px is
  0.5 mm). Icons drawn in the lambda need chunky geometry.

## Editor design decisions

- **The canvas is the task**, so the chrome is deliberately quiet and the panel
  sits in a dark frame that reads as the device. Do not add colour or weight
  that competes with it.
- **The right rail is ordered by how often each panel is touched**: properties
  constantly, palette per element, entities only while hunting one. Do not
  reorder it alphabetically or by "importance".
- **No confirmation dialogs.** Deleting a page shows an undo toast instead.
  There is a 60-deep undo stack; use it rather than asking "are you sure?".
- **Controls are >=36px tall** (Fitts). Do not shrink them to fit more in.
- **The legibility chip lives in the Appearance group**, next to the size field
  it describes. It is the one opinionated thing in the editor and the reason
  the tool is specific to this panel rather than a generic canvas.

## Inputs

Five discrete push-buttons, **not** a rotary encoder, despite what the Elecrow
wiki calls them: `NEXT 4`, `PRV 6`, `OK 5`, `HOME 2`, `EXIT 1`, all active-low.
Confirmed from Elecrow's `5.79_key` demo source, which is authoritative — the
wiki's pin table is unverified and its page is headed "5.19-inch".

When touching display code, `it.image()` at a negative offset is a trap: see
[ARCHITECTURE.md](ARCHITECTURE.md#measured-numbers).

## Talking to Home Assistant and the panel

- **A render never waits on an outside service.** Anything that calls ESPN,
  Flightradar24, OpenSky, a racing calendar, or a slow Home Assistant
  service goes through `live_data` (`@runtime.live(seconds)`, see `sources/`), and
  callers must cope with "no value yet".

- **Never guess an entity ID or an action name** from a device name. Find the
  panel through `panel_link.PanelLink` (service list, registry unique_ids).
- **Never write entities with `POST /api/states`.** The add-on's values go
  through `mqtt_bridge` (or stay internal without a broker). Writing both is
  what made every sensor exist twice in 0.8.x.
- **A call that can fail must say so.** Return whether Home Assistant accepted
  it, and show the truth in the editor. Don't report success you didn't get.

## Security & data hygiene

- **The LAN port serves frames and nothing else that matters.** No layouts,
  no page names, no quiet-hours reason (it can reveal whether anyone is home).
  Every install has a frame token (`frame_token.py`, the option or a generated
  one). Frames switch to requiring it the first time the panel uses it, so a
  reinstall never leaves the panel blank. Actions always need it.
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
