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

Lives in your Home Assistant sidebar, behind your existing login. Designed to be accessible to anyone—from an enthusiast building custom rotation loops to someone setting up a quick screen to track when their next pension or bin collection arrives.

- **✨ One-Click Ready-Made Presets:** Click **Add Preset** to choose from battle-tested screen templates (`Next Pension / Event Countdown`, `Room Climate & Comfort`, `Solar Power & Battery`, `Pet & Door Presence`, `Bin Day Collection`, `Giant Sofa Clock`). Each preset pre-configures icons, sofa-legible font scales, and entity bindings in one click.
- **🎨 Lovelace Dark & Light Theme:** Beautiful interface styled to match Home Assistant with an instant dark/light mode toggle, Inter typography, and an authentic CrowPanel hardware frame preview with Fit vs 100% zoom controls.
- **🏷️ Intelligent Entity Browser:** Filter entities with fast category chips (`📅 Dates & Calendars`, `🌡️ Sensors`, `⚡ Binary`, `❄️ Climate`, `🔒 Security`, `👤 People`). Add entities via drag-and-drop or with the one-click **➕ Add** button on each card.
- **🛋️ 3-Metre Sofa Legibility Verdict:** Per-element real-time feedback (**"Renders at 106 px = 18 mm — effortless from 3 m sofa"**) guarantees your facts stay readable from across the room.
- **Plain-English Bindings & Countdowns:** An element says what it wants—an entity's state, an attribute, when it last changed, a date countdown (`days_until`), or formatted dates (`date_formatted`)—without writing Jinja templates. A visual "say it differently" table turns raw values like `on` or `Outdoor Cat` into `outside` without code. Raw Jinja templates remain available for advanced power users.

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

Whether you mount the panel normally, **upside-down (`180°`)** to route the
USB-C cable cleanly, or **vertically in portrait (`90°` / `270°`)**, the editor
header and **Panel setup** wizard let you pick your mounting orientation:
- The canvas switches between **792×272** (landscape) and **272×792** (portrait)
  with a one-click **Reflow** helper to restack existing elements.
- The server pre-rotates each page into the physical `792×272` framebuffer
  before serving `/frames.png`, so changing orientation in the editor works
  immediately on **Save / Push to panel** without reflashing ESPHome.
- When generating new ESPHome firmware for `180°` or `270°` mounts, the wizard
  also swaps the `Next` and `Prev` button pins (`GPIO 4` and `GPIO 6`) so the
  physical rocker matches how the board is mounted.

## Install

1. **Settings → Add-ons → Add-on Store → ⋮ → Repositories**, add
   `https://github.com/bek00letz/epaper-panel`
2. Install **E-paper panel** and start it.
3. Open **E-paper** in the sidebar and click **Panel setup** to generate a
   ready-to-flash ESPHome YAML (with your Home Assistant address, Wi-Fi, and
   auto-generated API encryption key & OTA password pre-filled) to paste into
   your ESPHome Dashboard.

With no data sources set up the add-on simply renders the entities you already
have. Optional add-on settings let you customize `esphome_device` (also synced
automatically by the **Panel setup** wizard) and `frame_token` (optional token
authentication on port `8099`, automatically appended to the wizard's generated
frame URLs).

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
