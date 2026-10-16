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

The add-on repository is https://github.com/bek00letz/epaper-panel, added in
HA as a custom add-on repository. `repository.yaml` at the root makes it one;
the add-on itself lives in `addon/`.

## Endpoints & Ports

| Endpoint | Purpose |
|---|---|
| HA Sidebar (`:8080` via Ingress) | Drag-and-drop visual editor and JSON API, behind Home Assistant authentication |
| `<homeassistant>:8099` | Frame server (`/frames.png`, `/frame.png`, `/status`) for the ESP32 panel on the LAN (can be remapped in HA Add-on network settings if port `8099` is already in use on the host, or protected via `frame_token`) |
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
```

Then open `http://127.0.0.1:8080/` for the editor and
`http://127.0.0.1:8099/frames.png` for what the panel would fetch, and
*look at it*. Several layout bugs here — a detached cat
tail, a stray dash on the dryer icon, a missing ear — were invisible in code and
obvious in the image. Render it and open it.

For firmware, copy `esphome/secrets.example.yaml` to `esphome/secrets.yaml` and
run `esphome config esphome/crowpanel-epaper.yaml` to validate the schema.

## Firmware gotchas

- The panel needs the external component; stock `waveshare_epaper` has no model
  for it. `invert_colors: true` is required.
- **`GPIO7` is the display's power rail.** Nothing renders until it is high.
- `online_image` actions are `component.update: <id>`, not `online_image.update`.
- This is an **esp-idf** build: no Arduino APIs. Use the `wifi_info` text sensor
  for the IP, not `WiFi.localIP()`.
- `psram: mode: octal` assumes an N8R8 board. Unconfirmed; if it will not boot,
  comment it out and read the boot log.
- **Trust Elecrow's demo source over their wiki** for pin numbers.
- **`on_boot` fires before wifi is associated.** A fetch there races the
  network and loses, and with `have_frames` reset by the reboot the panel then
  shows the diagnostic screen until the next interval. `refetch` waits on
  `wifi.connected` first; keep it that way.
- **Changing a global that the display lambda reads does nothing on its own.**
  Follow it with `script.execute: redraw`, or the change only appears at the
  next unrelated refresh. This is what made the hold indicator look stuck.
- **Image fetch cost is per-pixel, not per-byte or per-codec.** Changing format
  or buffer sizes moves it ~10%. Reducing pixel count is the only big lever
  without writing a custom component. Measurements in ARCHITECTURE.md.
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

## Security & data hygiene

- The add-on gets a supervisor token automatically (`homeassistant_api: true`).
  All entity IDs and source slugs interpolated into Home Assistant API paths
  must be validated (`valid_entity_id` / `feeds.clean_slug`).
- Data source secrets (`key`, `headers` in `/data/sources.json`) are stored with
  `0600` permissions and masked (`••••••••`) when served via `GET /api/sources`.
- Never interpolate unescaped user or entity strings into `innerHTML` in
  `web/index.html` — the editor runs inside Home Assistant Ingress on the same
  origin as Home Assistant.
- Never commit real IP addresses, domain names, API keys, or personal names.
