> Vibecoded! While I strive to keep things safe and limit vulnerabilities, you should be aware and use at your own risk.

# E-paper panel

A Home Assistant add-on that puts your home on an Elecrow CrowPanel e-paper
display: big, calm, readable from across the room. You design each page in a
visual editor in Home Assistant's sidebar, and the panel rotates through them,
showing a page only when it has something to say.

![Pages the add-on renders](docs/pages.png)

## Why it looks like this

The panel hangs about three metres from a sofa. At that distance a 25 px
letter is just about readable and 110 px is effortless, and the 5.79" panel is
only 272 px tall. So instead of a dense dashboard you walk up to, each page
shows one or two things in large type, and the panel takes turns. There's no
grey on a 1-bit screen, so size carries the hierarchy. The editor tells you,
for every piece of text, how tall it will be in millimetres and whether it
reads from where you sit.

## What you can do with it

- **Design pages in a visual editor** that shows exactly what the panel will
  show, rendered by the same engine.
- **Start from a preset** (room temperature, solar today, countdown, bin day,
  weather, month and agenda, clock, door or pet, battery and solar, guest
  Wi-Fi, plane overhead, Formula 1, match score, what's on) and pick your
  sensor, or start blank.
- **Show any Home Assistant entity**: its value, its unit, one of its
  details, when it last changed, days until a date, a calendar event's name.
  Say it in your own words ("on" becomes "Running") without templates.
- **Values that pick their own unit**: 950 W, then 1.23 kW. A label can
  follow along: "Watts used", then "kW used".
- **Pages that show only when it matters**: the dryer page while the dryer
  runs, the match page on match days, the planes page while one is overhead.
- **Alerts** that take over the panel at once ("arriving home", "water
  leak") and hand it back after a set time.
- **Live data with no accounts or keys**: weather with a forecast, planes
  overhead, Formula 1, Formula E, NASCAR, IndyCar, football, NBA, NFL, MLB,
  NHL.
- **Your own data sources**: what's new and unwatched in Jellyfin, any JSON
  address, a Home Assistant long-term statistic.
- **Quiet hours**: no flashing and no downloads overnight, with a sleep
  screen that says when it wakes.
- **Control it from Home Assistant**: go to a page, step through pages, lock
  a page, sleep, refresh, from automations, dashboards or a scroll remote.

## Getting started

### 1. Install the add-on

1. In Home Assistant, go to **Settings › Add-ons › Add-on store**, open the
   **⋮** menu, choose **Repositories** and add
   `https://github.com/bek00letz/epaper-panel`.
2. Install **E-paper panel** and start it.
3. Open **E-paper** in the sidebar.

Optional: install the **Mosquitto broker** add-on too. Then the add-on's own
values (data sources, quiet hours, live sports and flights) also appear as
Home Assistant entities you can use in automations. Everything else works
without it.

### 2. Set up the panel

1. In the editor, open **Settings** (the gear) › **Install or update**.
2. Check Home Assistant's address and your Wi-Fi details. The add-on makes an
   encryption key and a frame token for you.
3. **Copy** or **Download** the panel's file. If Home Assistant's ESPHome
   folder is there, the add-on has already written it in.
4. In the **ESPHome** add-on: **New device**, give it a name, pick
   **ESP32-S3**, then **Skip**. **Edit** the new device, replace everything
   with the file, and **Install**. Use USB-C the first time; after that it
   updates over Wi-Fi.
5. When Home Assistant finds the panel under **Settings › Devices &
   services**, choose **Configure** and paste the encryption key.

**Settings › Panel** then shows it as connected.

### 3. Make your first page

1. Choose **New page** at the front of the page strip.
2. Pick a preset, for example **Room temperature**.
3. Pick your sensor from the list. The preview shows it straight away.
4. Choose **Add page**, then **Send to panel**.

That's it. The page joins the rotation, and the panel shows it the next time
it checks for new pages (or right away, if it's reachable).

## Walkthroughs

### Add a sensor's value to a page

1. Choose **Insert** in the toolbar (or press ⌘I).
2. Type part of the sensor's name, like `battery`, and pick it. It lands in
   the middle of the page, formatted for its unit. You can also drag a sensor
   from the list to where you want it.
3. In the inspector, change what it shows, the text before and after, or the
   decimals.
4. Under **Text**, the note says how tall it will be and whether it reads
   from your distance. Leave **Size** empty and the text fills its box.

### Show a page only while something is true

1. Click the page in the page strip, then click an empty part of the canvas.
   The inspector shows the page.
2. Under **Shows**, choose **Only when**, pick the sensor, and pick or type
   the state, like `active` for a timer or `on` for a switch.
3. The inspector says whether it's true right now. **Now on the panel**, at
   the front of the strip, lists every page that's hidden and why.

For anything the simple form can't say, choose **Use a custom condition** and
write a Home Assistant template.

**As an alert** makes the page take over the panel the moment its condition
turns true, even during quiet hours if you allow it, and give it back after
the number of minutes you set.

### Arrange the rotation

The page strip is the rotation: the panel shows the pages in that order.

- **Drag** a page to move it, or focus it and use Alt with the arrow keys.
- **Show again** (in the inspector, or right-click a page) puts a page in
  twice so it comes round more often.
- **Take out** keeps the page but stops showing it. It waits under "Not in
  rotation".
- **Each page shows for** sets how long every page stays up.

The strip sits above the canvas. **Settings › Editor › Page strip** puts it
below, or down the side.

### Give two pages the same layout

1. On the page whose layout you like, select everything (⌘A) and copy (⌘C).
2. Open the other page.
3. **Paste** (⌘V) adds copies in the same place and size.
   **Paste and match** (⌥⇧⌘V) instead gives the elements already on this
   page the place, size and text style of what you copied, paired up by
   kind. Your sensors and words stay.

Copying works across pages, after a reload, and between two open editor
windows.

### Watts that become kilowatts

1. Select a value that shows a sensor with a unit, like power in W.
2. Under **Units**, choose **Step up**. It stays in W below 1,000 and shows
   1.23 kW above, with the decimals you choose for the stepped-up value.
   Wh, g, m, B, Hz, s and others step up the same way. **Convert** shows a
   value in another unit: m/s in km/h, °C in °F, km in miles.
3. For a label underneath, choose **Add a label that follows the unit**.
   Under **Say it differently**, turn `W` into `Watts used` and `kW` into
   `kW used`.

### Reach something under something else

A click picks the smallest thing under the pointer, so a card never blocks
what's inside it. Click again without moving to get the next one; the stack
is outlined and a label says "2 of 3". **Layers**, above the canvas, lists
everything on the page with the front at the top. Drag to change the order,
or use ⌘] and ⌘[. Right-click lists everything under the pointer.

### Text that's too long

Turn on **Wrap onto more lines**, or choose **Wrap it** on the note that says
the text is cut off. With **Size** empty, wrapped text fills its box.

### Quiet hours and sleep

**Settings › Quiet hours** sets a nightly window, and optionally "while
nobody's home" from a person, group or zone. While quiet hours last, the
panel doesn't flash or download. The sleep screen shows closed eyes and when
it will wake. The panel's buttons still work: a press shows your pages, and
after two minutes untouched it goes back to sleep.

**Sleep now** (in Now on the panel), holding the dial's centre for a second,
or the panel's **Sleep** switch in Home Assistant all put it to sleep until
someone wakes it.

### Data sources

**Settings › Data sources** fetches things Home Assistant can't answer
itself. Each source becomes `sensor.epaper_<name>`, which pages show like any
other sensor.

- **Jellyfin: new and unwatched.** Home Assistant's Jellyfin integration
  knows who's watching, not what's new in your library. This asks Jellyfin
  directly, groups a series into one entry, and leaves out anything older
  than the days you choose (30 by default).
- **Any JSON address**, with headers and the path to the value.
- **A long-term statistic**, like this month's solar, from Home Assistant's
  own records.

**Test** shows what a source would publish before you save it.

## The editor

- **Toolbar**: undo and redo, **Insert**, copy and paste for the selection,
  whether your changes are saved, Settings, and **Send to panel**.
- **Page strip**: your pages in rotation order. At its front: **Now on the
  panel** (is it up to date, what's rotating, what's hidden and why, quiet
  hours, Sleep now, Clear ghosting, See every page) and **New page**.
- **Canvas**: the page as the panel will draw it, in a frame that stands in
  for the device. **Guides** shows the footer and every element's box.
  **Fit** or **Actual size**.
- **Inspector**: whatever's selected, or the page when nothing is.
- **Settings**: the panel (model, mounting, how often it checks, ghost
  clearing, sleep), installing it, quiet hours, data sources, and the editor
  itself (appearance, legibility distance, where the page strip goes).

**Saving.** Your changes are saved as you go, but the panel only gets them
when you choose **Send to panel**. The dot on the button means something isn't
sent yet. **Now on the panel › Throw away unsent changes** goes back to what's
on the panel (and that's undoable too). If another window sent changes in the
meantime, the two merge; you're only asked when both changed the same page.

**Undo** goes back 60 steps. Nothing asks "are you sure?": deleting shows
**Undo** instead.

**The previous editor** is still there for now: add `?classic=1` to the
editor's address.

### Keyboard shortcuts

Press **?** in the editor for the full list.

| | |
|---|---|
| Undo, redo | ⌘Z, ⇧⌘Z |
| Copy, cut, paste | ⌘C, ⌘X, ⌘V |
| Paste and match | ⌥⇧⌘V |
| Duplicate, delete | ⌘D, ⌫ |
| Select everything on the page | ⌘A |
| Nudge 1 px, 10 px | arrows, ⇧ arrows |
| Bring forward, send backward | ⌘], ⌘[ |
| To the front, to the back | ⌥⌘], ⌥⌘[ |
| Next element on the canvas | Tab |
| Next or previous page | ⌘↓, ⌘↑ |
| Insert | ⌘I |
| Send to panel | ⌘S |
| Snapping off while dragging | hold ⌥ |

On Windows and Linux, use Ctrl for ⌘ and Alt for ⌥.

### Elements

| Element | What it's for |
|---|---|
| Text, Value | Words or a sensor. Three fonts, bold or regular, plain, inverted or outlined with rounded corners, wrapping |
| Icon | Any of the 7,000 Material Design icons |
| Card, Divider | Frames, solid blocks, half-tone areas, rules |
| Gauge | A bar for a battery, a tank or a load: solid, in segments, or upright |
| Sparkline, Bar chart | A sensor's history, up to a week |
| QR code | A link, a sensor's value, or your guest Wi-Fi |
| Weather | Now and the next 3 to 5 days, from your weather entity (with an Open-Meteo fallback for Home Assistant's own location) |
| Month, Agenda | A calendar for this month, and the next events |
| Devices | A set of devices, showing only the ones that are on right now |
| Flights | The nearest plane, or a radar of the planes around you, from Flightradar24 with OpenSky as a fallback. Home, an airport code, or saved places |
| Racing | Formula 1, Formula E, NASCAR, IndyCar: standings and countdowns, around each session or the whole weekend |
| Match | Live scores for the Premier League, Champions League, La Liga, Bundesliga, Serie A, NBA, NFL, MLB, NHL, optionally one team |

Widgets have a **Text size** slider. **Break apart** turns weather, flights,
agenda, racing and match widgets into plain text, values and icons you can
move one by one.

## On the panel

The panel shows **categories** (your pages, in rotation order) and, inside
some, **items** (several planes, several episodes, several games). The footer
shows the time, the category and item, and a padlock when something is
locked.

| Control | Press | Hold |
|---|---|---|
| Dial, turn | Next or previous category, or item | |
| Dial, centre | Switch between categories and the items inside one | 1 s: sleep, or wake |
| Top button | Lock the category | Lock this page |
| Bottom button | Back to the first page | Fetch new pages now and clear ghosting, in one flash |

While you're scrolling, new pages wait until 15 s after your last press, so
nothing changes under your finger. If you mount the panel upside down or in
portrait, the buttons follow.

**Ghost clearing.** E-paper keeps faint traces of what it showed before. A
full refresh cleans them but flashes once, so the panel does one only when
nobody's looking: after a set number of quiet refreshes, on an automatic
change, never when you press a button. Choose the number in **Settings ›
Panel**, or **Clear ghosting** whenever you like.

## Home Assistant

### Actions

The panel offers these actions (as `esphome.<device>_<action>`), for
automations, dashboard buttons and remotes like the IKEA BILRESA scroll wheel.

| Action | Takes | Does |
|---|---|---|
| `refresh_now` | | Fetch new pages now (or once scrolling stops) |
| `show_page` | `index` | Go to a page, counting from 0 in rotation order |
| `show_category` | `category`, `sub` | Go to a category and an item in it |
| `page_step` | `delta` | Step forward or back: categories or items, whichever is active |
| `category_step`, `sub_step` | `delta` | Step categories, or items, specifically |
| `mode_toggle` | | Switch between categories and items |
| `lock_toggle` | | Lock or unlock, whichever is active |
| `category_pin_toggle`, `hold_toggle` | | Lock the category, or this page |

### Entities

From the panel (ESPHome): **Sleep** (switch), **Refresh interval**,
**Ghost clear after**, **Ghost clearing**, **Clear ghosting** (button),
**Panel IP** and **Panel Wi-Fi**.

From the add-on, with an MQTT broker, under an **E-Paper Studio** device:
`sensor.epaper_quiet_hours`, `sensor.epaper_panel_last_render`, one sensor per
data source, and the live widgets' own (`sensor.epaper_flights_overhead`,
`sensor.epaper_closest_aircraft`, `sensor.epaper_racing_<series>`,
`sensor.epaper_sports_<league>`), plus a **Refresh panel** button. They show
as unavailable while the add-on is stopped, and one that no page has used for
an hour is withdrawn.

## Supported panels

All are Elecrow CrowPanel e-paper boards with an ESP32-S3.

| Model | SKU | Pixels | Status |
|---|---|---|---|
| CrowPanel 5.79" | DIS08792E | 792 × 272 | Tested on the device |
| CrowPanel 4.2" | DIS08042E | 400 × 300 | Supported, not tested on a device |
| CrowPanel 2.9" | DIS08029E | 296 × 128 | Supported, not tested on a device |
| CrowPanel 7.5" | DIS08075E | 800 × 480 | Supported, not tested on a device |
| CrowPanel 10.2" | DIS08102E | 960 × 640 | Supported, not tested on a device |

Choose your model and how it's mounted (landscape, upside down, portrait, or
portrait flipped) in **Settings › Panel**. When you switch between landscape
and portrait, the editor offers to rearrange the current page.

## Privacy and security

- **The editor is behind your Home Assistant login.** It answers only Home
  Assistant's own Ingress proxy, not anything else on your network.
- **The panel's port (8099) serves pictures of pages, nothing else.** No
  layouts, entity names or locations. Frames are protected by a token the
  add-on makes for you; actions on that port always need it. Don't expose
  it to the internet.
- **No accounts, no analytics.** The add-on contacts outside services only
  for the widgets you put on a page (weather fallback, flights, sports and
  racing) and the data sources you set up. Airport codes are looked up from a
  copy bundled with the add-on.
- **The panel talks to Home Assistant encrypted**, with its own key, which
  also protects its updates over Wi-Fi.

## How it works

Home Assistant does the work; the panel only draws. The add-on renders every
page with real fonts, turns it into black and white pixels, and packs all the
pages into one checked file. The panel downloads that in the background,
checks it, and copies one page at a time into the display, so pressing a
button redraws in under a second with no network round trip.
[ARCHITECTURE.md](ARCHITECTURE.md) has the measurements behind each decision.

## Honest limitations

- **You choose the entities.** Presets and search help, but the add-on
  doesn't guess what belongs on your wall.
- **Only the 5.79" is tested on a device.** The others work in the renderer
  and the firmware generator.
- **No battery reading.** The board's battery pin isn't documented.
- **It expects mains power.** Deep sleep would cost instant updates, remote
  control and alerts; quiet hours give you the dark, still nights without
  that.

## Development

```bash
# run it on your computer, with stand-in data when there's no Home Assistant
DATA_DIR=/tmp/epaper-data ./.venv/bin/python addon/app/server.py

# the tests, including the panel's firmware core compiled on this machine
./.venv/bin/python -m unittest discover -s tests
```

The editor is at `http://127.0.0.1:8080/`, and what the panel would fetch at
`http://127.0.0.1:8099/frames.png`. Read [AGENTS.md](AGENTS.md) before
changing anything: it lists the rakes, and the editor's design decisions.
[CHANGELOG](addon/CHANGELOG.md) says what changed in each release.

## Credits

[ESPBoards](https://github.com/ESPBoards/esphome-lvgl-crowpanel-epaper-5.79-4.2)
for the 5.79" and 4.2" display component; Elecrow for publishing their demo
source, the reference for the pins;
[Lato](https://www.latofonts.com/) (SIL OFL),
[DejaVu](https://dejavu-fonts.github.io/) (free licence),
[Roboto Mono](https://fonts.google.com/specimen/Roboto+Mono) (Apache 2.0);
[Material Design Icons](https://pictogrammers.com/library/mdi/) (Apache 2.0);
[OurAirports](https://ourairports.com/) (public domain) for airport codes.
