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

Lives in your Home Assistant sidebar, behind your existing login. Designed to be accessible to anyone—from an enthusiast building custom rotation loops to someone setting up a quick screen to track upcoming events, bin collection, or solar generation.

- **One-Click Screen Presets:** Click **Add Preset** to choose from battle-tested screen templates (`Event & Schedule Countdown`, `Room Climate & Comfort`, `Solar Power & Generation`, `Door & Pet Presence`, `Bin Day Collection`, `Digital Clock & Date`). Presets pre-configure iconography, font scales, and layout geometries without overriding your own entities.
- **Typography & Font Picker:** Select between **Lato** (clean modern sans-serif), **DejaVu Sans** (classic high-legibility sans-serif), and **Roboto Mono** (monospace, ideal for clocks and tabular numbers) with Bold and Regular weight controls.
- **Persistent Advanced Coordinates:** Advanced pixel coordinate controls (X, Y, W, H) remain expanded across element selections for power-user precision.
- **Duplicate & Rename Pages:** Clone any page in one click to iterate without breaking existing designs, and rename pages with automatic rotation list updates and Undo support.
- **Flexible Viewing Distance Legibility:** Real-time font size and millimetre calculation with customizable viewing distances: **Desk (0.8 m)**, **Bedside (1.5 m)**, **Sofa (3.0 m)**, **Wall (5.0 m)**, or **Disabled**.
- **Lovelace Dark & Light Theme:** Styled to match Home Assistant with an instant dark/light mode toggle, Inter typography, and CrowPanel hardware bezel frame simulation with Fit vs 100% zoom controls.
- **Intelligent Entity Browser:** Filter entities with fast category chips (`Dates & Calendars`, `Sensors`, `Binary`, `Climate`, `Security`, `People`). Add entities via drag-and-drop or with the one-click **＋ Add** button on each card.
- **Zero-Reflash Hardware Refresh Rate Slider:** Adjust how frequently the hardware panel fetches and redraws directly from the editor toolbar or Home Assistant (1–60 minutes). Changing the slider dynamically updates the panel's internal timer live without requiring firmware reflashes.
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

## Hardware & Supported Models

The add-on is designed for the **Elecrow CrowPanel E-Paper** family (ESP32-S3).

### Compatibility Matrix

| Model | SKU | Resolution | Active Area | Aspect Ratio | Driver Component | Status |
|---|---|---|---|---|---|---|
| **CrowPanel 5.79"** | `DIS08792E` | 792 × 272 px | 139.1 × 47.7 mm | ~2.9:1 (panoramic) | `crowpanel_epaper` (`5.79in`) | **Primary / Fully Tested** |
| **CrowPanel 4.2"** | `DIS08042E` | 400 × 300 px | 84.8 × 63.6 mm | 4:3 | `crowpanel_epaper` (`4.2in`) | Supported |
| **CrowPanel 2.9"** | `DIS08029E` | 296 × 128 px | 66.9 × 29.1 mm | ~2.3:1 (compact) | `waveshare_epaper` (`2.90inv2`) | Supported |
| **CrowPanel 7.5"** | `DIS08075E` | 800 × 480 px | 163.2 × 97.9 mm | 5:3 | `waveshare_epaper` (`7.50inv2`) | Supported |
| **CrowPanel 10.2"** | `DIS08102E` | 960 × 640 px | 215.0 × 143.4 mm | 3:2 (large) | `waveshare_epaper` (`10.2in`) | Supported |

> [!NOTE]
> The **CrowPanel 5.79"** is the primary reference board on which the rendering pipeline and firmware were originally developed. You can switch models at any time using the **Model** selector in the editor toolbar or inside the **Panel setup** wizard; the editor and firmware generator will automatically adjust dimensions, aspect ratios, component platforms, and DPI legibility metrics.

### Firmware & ESPHome Integration

The firmware is ESPHome and sample configurations live in [`esphome/`](esphome/). The built-in **Panel setup** wizard generates ready-to-paste YAML for your selected model:
- Models **5.79"** and **4.2"** use the [`ESPBoards/esphome-lvgl-crowpanel-epaper-5.79-4.2`](https://github.com/ESPBoards/esphome-lvgl-crowpanel-epaper-5.79-4.2) external component.
- Models **2.9"**, **7.5"**, and **10.2"** use ESPHome's standard `waveshare_epaper` platform.

The physical buttons on the device are **discrete push-buttons**, not a rotary encoder. Paging is instantaneous because the panel holds every page in ESP32 PSRAM and blits a slice.

### Mounting Orientations (`0°`, `90°`, `180°`, `270°`)

Whether you mount the panel normally, **upside-down (`180°`)** to route the USB-C cable cleanly, or **vertically in portrait (`90°` / `270°`)**, the editor toolbar and **Panel setup** wizard let you configure mounting orientation:
- The canvas adapts to your model's logical aspect ratio (e.g. **792×272** landscape or **272×792** portrait on the 5.79") with a one-click **Reflow** helper to restack existing elements.
- The server pre-rotates each page into the panel's native framebuffer before serving `/frames.png`, so changing orientation in the editor works immediately on **Save / Push to panel** without reflashing ESPHome.
- When generating new ESPHome firmware for `180°` or `270°` mounts, the wizard also swaps the `Next` and `Prev` button pins (`GPIO 4` and `GPIO 6`) so the physical buttons match the board's orientation.

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
