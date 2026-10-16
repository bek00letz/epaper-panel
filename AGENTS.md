# Notes for agents

Read [ARCHITECTURE.md](ARCHITECTURE.md) before changing how anything works.
This file is about not stepping on rakes.

## Deploying

**The project is a Home Assistant add-on, installed from git.** No files get
copied by hand any more.

```bash
git push                      # from here
```

Then in Home Assistant: **Settings → Add-ons → E-paper panel → Rebuild**
(or Reload the repository first if `config.yaml` changed).

The add-on repository is https://github.com/bek00letz/epaper-panel, added in
HA as a custom add-on repository. `repository.yaml` at the root makes it one;
the add-on itself lives in `addon/`.

> Earlier versions ran `render.py` from `/config/epaper/` and were deployed by
> curling files from a laptop. That caused two outages that both looked like
> hardware faults and were stale code. If you find references to
> `shell_command.epaper_update` or `/config/www/epaper/`, they are obsolete.

## Addresses

| | |
|---|---|
| Home Assistant | `homeassistant.local:8123` (Proxmox VM on a Dell OptiPlex 7070 Ultra, SSD — not resource-constrained) |
| Panel | `crowpanel-epaper.local`, hostname `crowpanel-epaper` |
| Jellyfin | `jellyfin.local:8096` |
| Add-on frame port | `<ha>:7410` — the panel fetches here, no auth, LAN only |
| **Port 8099 is taken** | the Homegar adaptation. Leave it alone; that is why the panel is on 7410 |
| Editor | HA sidebar → E-paper (ingress, behind your HA login) |

Never route the panel through the Cloudflare tunnel (`homeassistant.example.com`). It would
make a living-room display depend on the internet and expose the webhook
publicly.

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
  builds the template. A literal `value` still wins, as the escape hatch for
  things the model cannot express. Shipped pages should demonstrate the easy
  path, not the ninja path.
- **A page that cannot render must not take the panel down.** `sources` returns
  `None` rather than raising, and pages draw `--`.
- **Fonts ship with the project** (`fonts/Lato-*.ttf`, SIL OFL). Do not depend
  on system fonts — the HA container has a different set from a Mac.

## Verifying a change

```bash
# run the service locally; it falls back to the fixture with no HA token
DATA_DIR=/tmp/epaper-data ./.venv/bin/python addon/app/server.py
```

Then open `http://127.0.0.1:8080/` for the editor and
`http://127.0.0.1:8099/frames.png` for what the panel would fetch, and
*look at it*. Several layout bugs here — a detached cat
tail, a stray dash on the dryer icon, a missing ear — were invisible in code and
obvious in the image. Render it and open it.

For firmware, `esphome config` catches schema errors but not behaviour. A full
`esphome run` compiles and OTAs in about 20 s once the toolchain is cached.

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

## Things deliberately not done

- **`utility_meter` for monthly solar.** The recorder already has it.
- **Per-page enable toggles.** The rotation string is the single source of
  truth; two controls would create an "enabled but not listed" ambiguity.
- **Posters on the watch page.** At 24 × 37 mm they carry nothing at 3 m. The
  title set large does the work.
- **Deep sleep**, so far — it costs instant OTA, which everything has leaned on.

## Hazards

- The add-on gets a supervisor token automatically (`homeassistant_api: true`),
  so there is no long-lived token to store. The Jellyfin key is add-on config,
  not a file in the repo.
- The recorder DB is opened **read-only** (`mode=ro`). Keep it that way.
