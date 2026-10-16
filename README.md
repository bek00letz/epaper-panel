> Vibecoded with Opus 5.

# E-paper panel

A Home Assistant add-on that renders your entities onto an Elecrow CrowPanel
e-paper display, with a drag-and-drop editor for designing the pages.

![The pages it renders](docs/pages.png)

Designed around one constraint: the panel hangs about three metres from a
sofa. At that distance a 25 px character is at the threshold of legibility and
110 px is effortless — on a 272 px-tall panel that means **one fact per screen,
set large**, rotating, rather than a dense dashboard you have to walk up to.

## The editor

![The editor](docs/editor.jpg)

Lives in your Home Assistant sidebar, behind your existing login. Drag an
entity from the list onto the canvas, drag it where you want it, and the
preview you see is a live render from the real engine — not an approximation.

It also tells you, per element, what the panel will actually produce:
**"Renders at 106 px = 13 mm — comfortable"**, measured against the viewing
distance the whole project is built around.

Most pages need no templating. An element says what it wants — an entity's
state, an attribute, when it last changed — and a "say it differently" table
turns `Outdoor Cat` into `outside` without a line of Jinja. Raw templates are
still there when you need them.

## Pages appear when they matter

Each page has a tier:

| Tier | Behaviour |
|---|---|
| **In rotation** | takes its turn |
| **Only when true** | joins the rotation only while a condition holds |
| **Interrupt** | never rotates; seizes the screen when something happens, holds, then hands it back |

So a dryer page exists only while the dryer is running, and an "arriving
home" page can take over the panel for fifteen minutes and then vanish.

## Hardware

Built and tested on the **CrowPanel 5.79"** (`DIS08792E`) — ESP32-S3, 792×272,
1-bit, about 139 × 48 mm. The firmware is ESPHome and lives in
[`esphome/`](esphome/).

It needs the external component
[`ESPBoards/esphome-lvgl-crowpanel-epaper-5.79-4.2`](https://github.com/ESPBoards/esphome-lvgl-crowpanel-epaper-5.79-4.2);
stock `waveshare_epaper` has no model for this panel. The other CrowPanel
e-paper sizes should be a matter of resolution and model string, but are
untested.

The five buttons are **discrete push-buttons**, not a rotary encoder, whatever
Elecrow's wiki calls them. Paging is instant because the panel holds every page
in PSRAM and blits a slice.

## Install

1. **Settings → Add-ons → Add-on Store → ⋮ → Repositories**, add
   `https://github.com/bek00letz/epaper-panel`
2. Install **E-paper panel** and start it.
3. Open **E-paper** in the sidebar.
4. Copy [`esphome/secrets.example.yaml`](esphome/secrets.example.yaml) to
   `esphome/secrets.yaml`, fill in your Wi-Fi, API encryption key, and OTA
   password, and flash [`esphome/crowpanel-epaper.yaml`](esphome/crowpanel-epaper.yaml)
   (pointing at `http://<home-assistant>:8099/frames.png`).

With no data sources set up the add-on simply renders the entities you already
have. Optional add-on settings let you customize `esphome_device` (default
`crowpanel_epaper`, used when pushing page changes or alerts) and `frame_token`
(optional token authentication on port `8099`).

## Data sources (optional)

Some things Home Assistant cannot answer. Sources fetch them and publish them
back as `sensor.epaper_<name>` entities, which pages then bind to like anything
else:

- **Jellyfin** — what is new *and* unwatched. HA's own Jellyfin integration
  reports who is watching; it knows nothing about your library.
- **Any JSON API** — a URL, headers, and a path into the response.
- **A long-term statistic** — e.g. this month's solar. Statistics are
  websocket-only in HA, so templates cannot reach them.

## How it works

Home Assistant renders; the panel draws. The panel fetches a tall PNG of every
page, holds it in PSRAM, and pages locally — so a button press redraws in about
800 ms with no network round trip.

[ARCHITECTURE.md](ARCHITECTURE.md) has the measurements behind the design
decisions, including why the fetch cost turned out to be per-pixel rather than
per-byte, and what that means for battery.

## Honest limitations

- **It assumes you know your entities.** The picker shows friendly names and
  live values, but nothing suggests what is worth putting on a wall.
- **`show_if` conditions are still raw Jinja.** The value fields are not; this
  is the next thing to fix.
- **Only the 5.79" is tested.**
- **No battery readout.** The voltage divider's GPIO is undocumented on this
  board.
- **Mains power is assumed.** Deep sleep would cost instant updates, remote
  control and alerts that arrive when they happen — a bad trade for a panel
  near a socket.

## Credits

[ESPBoards](https://github.com/ESPBoards/esphome-lvgl-crowpanel-epaper-5.79-4.2)
for the display component, Elecrow for publishing their demo source (the
authoritative pin reference), [Lato](https://www.latofonts.com/) (SIL OFL) and
[Material Design Icons](https://pictogrammers.com/library/mdi/) (Apache 2.0).
