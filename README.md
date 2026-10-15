# Living-room e-paper panel

An Elecrow CrowPanel 5.79" e-paper display showing household status from Home
Assistant and Jellyfin, intended to sit in a living room and be read from about
three metres away.

Home Assistant renders the screens as 1-bit PNGs; the panel fetches and draws
them. Almost no logic lives on the device.

## Hardware

| | |
|---|---|
| Board | Elecrow CrowPanel 5.79" e-paper, SKU `DIS08792E` |
| MCU | ESP32-S3 (assumed N8R8 — 8 MB octal PSRAM; unconfirmed) |
| Panel | 792 × 272, 1-bit, dual SSD1683 cascade |
| Physical size | ~139 × 48 mm, ~145 dpi |
| Power | USB-C today. JST connector + onboard charging for a 1S LiPo later |

Pins (from the [Elecrow wiki](https://www.elecrow.com/wiki/CrowPanel_ESP32_E-paper_5.79-inch_HMI_Display.html)):
display `clk 12 / mosi 11 / cs 45 / dc 46 / reset 47 / busy 48`, display power
rail `GPIO7` (nothing renders until it is high), Exit `IO1`, Menu `IO2`,
dial `IO4 / IO6` with press on `IO5`.

ESPHome has no built-in driver for this panel. It needs the external component
[`ESPBoards/esphome-lvgl-crowpanel-epaper-5.79-4.2`](https://github.com/ESPBoards/esphome-lvgl-crowpanel-epaper-5.79-4.2)
with `model: "5.79in"` and `invert_colors: true`.

## Layout

```
┌──────────────────────────────────────────────────────────┐
│  ☀  10.6            ╭─╮                                  │  one fact,
│     kWh today    ╭──╯ ╰──╮                               │  set large
│ ──────────────────────────────────────────────────────── │
│  18:04              solar · 1/5                     86 % │  diagnostics
└──────────────────────────────────────────────────────────┘
```

Pages: `solar`, `solar_month`, `cat`, `watch`, `temps`, `dryer`.

## Running it

Development, on any machine with the repo:

```bash
./.venv/bin/python render.py --catalogue --out out   # every page + contact sheet
./.venv/bin/python render.py --out out               # one frame, as deployed
```

With no `secrets.json` it falls back to `fixture.json`, a snapshot of live
Home Assistant state, so the renderer runs anywhere.

Deployed, on the Home Assistant box, driven by `shell_command.epaper_render`.
See [ha/SETUP.md](ha/SETUP.md).

## Current state

Working: display, wifi, OTA, live HA data, Jellyfin "new and unwatched",
server-side rendering, the control dashboard, local page switching from the
buttons, and page selection pushed from Home Assistant
(`esphome.crowpanel_epaper_show_page`).

Buttons work. The five controls are **discrete push-buttons, not a rotary
encoder** — see [ARCHITECTURE.md](ARCHITECTURE.md#the-dial-is-not-a-dial). A
page change takes about 810 ms end to end.

| Button | Pin | Does |
|---|---|---|
| Next | `IO4` | forward one page |
| Prev | `IO6` | back one page |
| OK (dial press) | `IO5` | hold this page, stopping the rotation; again to release |
| Home | `IO2` | re-render from Home Assistant and refetch |
| Exit | `IO1` | release the hold, back to page one |

The panel also exposes actions to Home Assistant, so remotes, dashboard
buttons and automations can drive it:

| Action | Does |
|---|---|
| `esphome.crowpanel_epaper_page_step` (`delta`) | move relative — what a remote needs |
| `esphome.crowpanel_epaper_show_page` (`index`) | jump to a page |
| `esphome.crowpanel_epaper_hold_toggle` | hold / release |
| `esphome.crowpanel_epaper_refresh_now` | re-render and refetch |

These only work while the panel is **awake**. Its own buttons work under deep
sleep because pressing one wakes it; nothing external can. Remote control and
deep sleep are therefore close to mutually exclusive — see
[ARCHITECTURE.md](ARCHITECTURE.md#battery-and-deep-sleep).

A held page shows a padlock in the top-right corner — without it a stopped
rotation just looks like a fault. Data still refreshes while held; only the
page stops moving.

**Not done: deep sleep.** The panel is mains-powered. See
[ARCHITECTURE.md](ARCHITECTURE.md#battery-and-deep-sleep) for the measurements
that decide how it should be built.

## Known issues

- **Battery percentage is a placeholder.** The voltage divider's GPIO is not
  documented for this board and has not been found. The footer shows whatever
  the panel reports, currently nothing.
- **`shell_command` injection.** `epaper_render` interpolates
  `input_text.e_paper_rotation` into a shell command. Anyone who can edit that
  helper can run commands as Home Assistant. Low risk on a private LAN, real
  nonetheless. Fix: have the renderer read the helper over the API itself.
- **`sensor.indoor_temperature`** (the indoor temp,
  still named "Currently Bedroom") is unavailable, so `temps` shows `--`.
- **Cat "since" time is unreliable.** `sensor.cat_location.last_changed`
  resets on every Home Assistant restart, so it often reports a restart rather
  than the cat actually going out.
