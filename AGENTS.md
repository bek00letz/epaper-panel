# Notes for agents

Read [ARCHITECTURE.md](ARCHITECTURE.md) before changing how anything works.
This file is about not stepping on rakes.

## The single most important thing: there is no automatic deploy

Editing a `.py` file here changes **nothing** on the Home Assistant box. The
renderer runs from `/config/epaper/` on HA, which is a separate copy.

This has caused two outages already, both of which looked like hardware faults
and were actually stale code.

To deploy, serve this directory over HTTP and call the update action:

```bash
# on this machine
python -m http.server 8099 --bind 0.0.0.0   # from the project root
```

```python
# then, over the HA API
ha_call_service(domain="shell_command", service="epaper_update", return_response=True)
```

`shell_command.epaper_update` curls `render.py`, `pages.py`, `sources.py` and
`theme.py` from `http://dev-host.local:8099/`, writing to `.new` and moving on
success, then re-renders. **Always check its `stdout`** — it is the only
confirmation the deploy landed.

If you change the host serving the files, update the `epaper_update` entry in
HA's `configuration.yaml`.

## Addresses

| | |
|---|---|
| Home Assistant | `homeassistant.local:8123` (Proxmox VM on a Dell OptiPlex 7070 Ultra, SSD — not resource-constrained) |
| Panel | `crowpanel-epaper.local`, hostname `crowpanel-epaper` |
| Jellyfin | `jellyfin.local:8096` |
| Dev machine serving files | `dev-host.local:8099` |

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
- **Pages take `(data, ctx)` and return a canvas.** Register them in
  `pages.ALWAYS` or `pages.CONDITIONAL`.
- **A page that cannot render must not take the panel down.** `sources` returns
  `None` rather than raising, and pages draw `--`.
- **Fonts ship with the project** (`fonts/Lato-*.ttf`, SIL OFL). Do not depend
  on system fonts — the HA container has a different set from a Mac.

## Verifying a change

```bash
./.venv/bin/python render.py --catalogue --out out   # all pages and states
```

Then *look at* `out/catalogue.png`. Several layout bugs here — a detached cat
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
- **Writes to `/config/www/epaper/` must be atomic.** The panel can fetch at any
  moment; `render.save_atomic()` writes to `.tmp` and renames.
- **Strokes under ~4 px are invisible on this panel** (145 dpi, so 3 px is
  0.5 mm). Icons drawn in the lambda need chunky geometry.

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

- `shell_command.epaper_render` interpolates `input_text.e_paper_rotation` into
  a shell command. That is a command-injection path for any HA user. Fix by
  having the renderer read the helper over the API.
- `secrets.json` holds a long-lived HA token and the Jellyfin API key. It is not
  in version control and must not be pasted into logs or chat.
- The recorder DB is opened **read-only** (`mode=ro`). Keep it that way.
