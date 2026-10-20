# Several screens, any kind: the design

Agreed 2026-10-20, before any code. **All three steps are built** (0.11.0,
and TRMNL on main after it); what follows is the plan as agreed, with notes
on what changed while building. This is the plan the work is built from;
[ARCHITECTURE.md](../ARCHITECTURE.md) describes what exists, and changes to it
as each step lands. Rule #1 in [AGENTS.md](../AGENTS.md) applies throughout:
this is a framework for every device of every supported kind, not support for
the two on our desk.

## What changes, in one paragraph

Today the add-on drives one screen: one `layouts.json`, one size, one
rotation, one panel link. After this, it drives **devices**: any number,
of any supported kind and size. Each one shows a **design**, which it either
owns or shares with other devices. A TRMNL is one kind of device, added as a
module on top. A screen can be taken away from home and still show your data.

## The three ideas

**Device.** A screen you own. It has a name, a kind, a size and orientation,
its own settings, its own quiet hours, its own key, and (for kinds that
need it) its own place in the rotation and last battery and Wi-Fi readings.

**Design.** What a screen shows: pages and rotation, in today's
`layouts.json` format. A design is drawn for a size.

**Arrangement.** Where each element sits on one size of a design. A
design has one arrangement per size it's shown at. Content (what an element
shows, its binding, its condition) belongs to the design. Its box belongs to
the arrangement.

Pages are placed in exact pixels, and screens differ in shape (the 5.79" is
about 2.9 : 1 and read from 3 m; a TRMNL is 5 : 3 and read from a desk). So
"the same design at another size" can never be a plain scale. A new size
starts from an automatic fit and is yours to adjust.

## Adding a device

Like setting up a phone. All three ship together:

| Choice | What happens |
|---|---|
| **Set up as new** | The device gets its own new design (starter pages for its kind and size) |
| **Copy from another device** | A one-time copy of that device's design, fitted to the new size, then independent ("restore from a backup") |
| **Show the same pages as another device** | Linked: the design is shared, so edits land on every device that shows it. A different size gets its own arrangement ("iCloud sync") |

On a linked design, an element added at one size appears on the other sizes
in an automatic position, marked "not arranged yet" in the editor until
someone places it.

**Quiet hours are per device.** Several screens usually means several uses
(a bedroom, a hallway, a desk at work). A new device is offered the quiet hours
of the device it was copied or linked from, or of the first device, as a
starting point.

## Device kinds

A kind is a small module with one interface. The core knows nothing about
any particular kind:

- **Sizes**: the display profiles it supports (`theme.DISPLAYS`), or the size
  the device reports.
- **Routes**: what it adds to the device port.
- **Output**: what a fetch gets. A CrowPanel gets the EPF frame file (the strip,
  with its overlays drawn on the device); a TRMNL gets one 1-bit PNG.
- **Who picks the page**: the device (CrowPanel) or the add-on (TRMNL).
- **Who owns the wake interval**: the device (CrowPanel) or the add-on (TRMNL).
- **Whether it can be woken early**: through Home Assistant (CrowPanel at home)
  or not at all (TRMNL; CrowPanel away from home).

`crowpanel` is today's code moved behind this interface, unchanged in
behaviour. `trmnl` is the new module, and an add-on option turns it on. With
it off, its routes don't exist and the editor shows nothing of it.

### CrowPanel (unchanged)

- The panel owns which page is shown and its refresh interval, settable on the
  panel and in the editor as today.
- A second CrowPanel is set up through Panel setup like the first. Its YAML
  carries its own key in the download address. `panel_setup.py` fills that
  in; nothing under `components/` changes for this.
- `panel_link` maps each CrowPanel device to its own ESPHome node, by the node
  chosen in its setup. It never guesses.

### TRMNL

From TRMNL's open-source firmware (`usetrmnl/firmware`, commit `383d6ff`,
19 Oct 2026). The tests pin these against requests built from that source.

- **Pairing.** The device's Wi-Fi setup page takes only a server address
  (changing it clears the device's key). The device then calls
  `GET {base}/api/setup` with `ID` (its MAC address), `FW-Version` and
  `Model`, and expects `api_key`, `friendly_id` and `image_url`. The
  add-on answers only inside the 10-minute window opened by **Add a TRMNL** in
  the editor. Outside it, unknown devices are refused.
- **Each wake.** `GET {base}/api/display` with `ID`, `Access-Token`,
  `Refresh-Rate`, `Battery-Voltage`, `RSSI`, `Width`, `Height`, `Model`,
  `FW-Version`, `Update-Source` (`timer` or `button`), `Image-Cached`, and
  optional extras (charging, `special_function`). The reply carries
  `image_url`, `filename`, `refresh_rate`, plus `update_firmware: false` and
  `reset_firmware: false`.
- **The image** is a 1-bit PNG at the reported `Width` × `Height` (the
  firmware also takes BMP). `image_url` must be a full address. The add-on
  builds it from the address the device itself called, so home, a tunnel and
  Home Assistant's address all work without configuration.
- **`filename` is the image's content hash.** The device skips the download
  when it already shows that file (`Image-Cached`), which saves battery when
  nothing changed.
- **The page each wake.** The add-on keeps a cursor per device. A timer wake
  advances it through the rotation (page conditions and linger apply as for the
  CrowPanel); a button wake goes to the next page.
- **`refresh_rate` is in every reply.** The firmware stores whatever it
  receives, and a missing value is stored as 0, so the add-on always sends one:
  the device's wake interval (an add-on setting per TRMNL). During quiet hours
  it's the sleep page and the time until they end.
- **Alerts** show at the next wake. A sleeping TRMNL can't be woken, and the
  editor says so on that device.
- **The footer is in the picture.** There are no on-device overlays, so the
  page counter and "updated 14:05" are drawn into the image. The timestamp
  matters more here, because a TRMNL screen can be up to one interval old.
- `/api/log` is accepted and kept briefly for the device's row in the editor.
- Battery and Wi-Fi go to the editor and, with a broker, to Home Assistant
  sensors through `mqtt_bridge` (never `POST /api/states`).

## Keys

- **Every device has its own key.** It identifies the device as well as
  allowing it in. Keys can be revoked one at a time in the editor.
- **Your existing panel keeps the install's frame token** as its key, and
  its exact download address. It becomes device 1 with no change on the panel.
- **The "works without the token until the panel first uses it" switch-over**
  exists only for installs whose panel predates tokens. Behind a tunnel or Home
  Assistant every request comes from an internal address, so "only on the home
  network" can't be told apart by address. Instead: the moment any way of
  reaching home from outside is turned on, keys are required for everything,
  with no switch-over. A panel that already uses its token (Settings shows
  frame protection "on") is unaffected either way.
- **Wrong keys slow down**, counted per device ID and per address seen, so
  keys can't be guessed. Nothing on the device port answers without a key:
  not `/status`, not the PNG versions.

## Reaching home from anywhere

The device port is built to be safe on the internet. How it's reached is the
user's choice, in Settings → **Reaching home**:

1. **Home network only** (default): the LAN address, as today.
2. **Through Home Assistant's address**: a companion integration serves the
   device endpoints under Home Assistant's own address
   (`https://<your-ha>/api/epaper/…`). It works wherever Home Assistant is
   already reachable: Nabu Casa, Cloudflare, DuckDNS, a reverse proxy.
3. **Your own address**: a tunnel or proxy (e.g. Cloudflare Tunnel) pointed
   at the add-on's device port, with that address entered once.

Options 2 and 3 both ship from the start.

**The companion integration** (`custom_components/epaper_panel/`, shipped
inside the add-on and versioned with it):

- The editor installs it into `/config/custom_components/` (the add-on already
  maps `/config` read-write) when the user picks option 2, then asks for one
  Home Assistant restart. Each add-on update refreshes it, and the editor shows
  when a restart is still needed for a newer copy.
- It registers one Home Assistant view under `/api/epaper/` that needs no Home
  Assistant login and forwards each request, headers included, to the add-on's
  device port on the internal network. **All key checks stay in the add-on**:
  one place, one set of tests.
- It does nothing else, so there's no second copy of any logic to drift.

**Away from home:**

- **TRMNL** works over HTTPS. Its firmware encrypts but doesn't check
  certificates, so its key is only as private as the network it's on; a key
  unlocks one screen's pictures and pairing again replaces it. Still to
  confirm on a real device.
- **CrowPanel** fetches over HTTPS since 0.11.0, checked against ESP-IDF's
  certificate bundle, and knows several Wi-Fi networks, plus its own hotspot
  for choosing one from a phone. A network chosen on the hotspot replaces
  the ones in its YAML until the next install.
- **A CrowPanel away from home can't be woken early.** Push and its remote
  buttons go through Home Assistant's ESPHome connection, which only reaches
  the home network. Away, it runs on its own refresh interval, like a TRMNL,
  and the editor says so on that device rather than showing an error.

## Rendering

- Values are fetched once per cycle and shared by every design.
- Each design is drawn once per size it's shown at, in its arrangement for
  that size. A CrowPanel's strip is packed per device, because overlays,
  orientation and capacity (`?cap=`) are per device. A TRMNL's PNG is drawn
  per wake from the current render.
- One render at a time, as today (`refresh_frames` holds the lock).

## Editor

- **A device switcher at the head of the page strip.** The canvas takes that
  device's size, and the legibility note uses its viewing distance.
- **Add a device** is a sheet: pick the kind, then New, Copy from… or Same
  pages as…. For a TRMNL it opens the pairing window and shows the address to
  enter on the device, for whichever way of reaching home is on.
- **Editing a linked design at another size** shows one quiet line under the
  canvas: "Arranging for TRMNL. Text and data are shared with Living room."
  Moving or resizing changes only this size; changing what an element shows
  changes it everywhere.
- **Each device's settings** (name, quiet hours, wake interval for kinds the
  add-on wakes, key, revoke) live in Settings under that device. "Four things,
  one place each" becomes five: the device joins the panel, rotation, page and
  element.

## Storage and the way back

- `/data/devices.json`: the devices, with keys stored `0600`.
- `/data/designs/<id>.json`: each design, today's format plus arrangements
  per size.
- **Migration**: on first start, `layouts.json` becomes design 1, and today's
  panel becomes device 1 with the existing token and address. `layouts.json` is
  left in place, untouched, so the previous add-on version still finds the
  pages as they were. It's removed only after the new store has proven itself,
  and only with the user's OK.

## Order of work

1. **Devices in the core.** *Done 2026-10-20: `devices.py`, `kinds/`, renders
   split per design and per device, per-device keys. Old and new code produce
   byte-identical frame files for the same pages (checked at four sizes,
   every rotation, with quiet hours on).* The device and design store, the migration, the
   kind interface with `crowpanel` behind it, and per-device keys. Nothing
   visible changes and the existing tests still pass.
2. **Adding devices.** New, Copy and Linked, arrangements per size, the device
   switcher, per-device quiet hours, and Reaching home with both ways (the
   companion integration included). A second CrowPanel works at this point.
   *Built 2026-10-20.* Decided along the way, with the user:
   - The switcher is the toolbar's title. "Set up as new" starts with one
     starter page that needs nothing a Home Assistant might lack (the date,
     `sun.sun`, an icon, a QR code to the guide).
   - A model or mounting change starts the pages from an automatic fit for the
     new size; switching back restores the old layout (each size keeps its own).
   - Firmware: HTTPS with the certificate bundle, several Wi-Fi networks, and
     each panel named after its screen in Home Assistant, which is also how two
     panels' entities are told apart (by device name, recorded when the file is
     written). Needs a release tag to reach panels.
   - Also built: group styles across selected elements (a real group, shaped
     by its members on every size), snapping for several elements at once, a
     Refresh button per screen.
3. **The TRMNL kind**, as the module. *Built 2026-10-20 (`kinds/trmnl.py`,
   `tests/test_trmnl.py`), re-checked against the firmware's current source,
   still commit `383d6ff`.* Decided along the way, with the user:
   - A device that reports a size other than 800 × 480 gets a profile of its
     own (`trmnl_<w>x<h>`), its physical size estimated from the TRMNL OG's
     pixel density.
   - A button press during quiet hours shows the next page, and two minutes
     later it's back to the sleep screen.
   - Battery as an estimated percentage (a standard lithium curve) plus the
     voltage as its own sensor.
   - "updated HH:MM" is when that page last changed, not the wake: otherwise
     every picture differs, and the TRMNL downloads and flashes on every wake.
     Whether it checks in is "Last seen", in the editor and Home Assistant.
   Found in the firmware and not in the plan above: both replies carry a
   `status` (setup: 200 pairs, 404 shows our message, but only in an HTTP 200;
   display: only 0 is safe, 202 polls every 5 s and 500 wipes its Wi-Fi); the
   picture needs `Content-Type: image/png` exactly; the setup reply's
   `image_url` is left empty, because a setup picture would replace the
   device's own logo.

## Rules this changes

Updated in AGENTS.md and ARCHITECTURE.md (the first in step 2, the others in
step 1):

- "Never expose port 8099 to the internet" becomes "the device port is safe
  on the internet: per-device keys, nothing without a key, wrong keys slow
  down".
- "The panel owns which page is shown" becomes per kind.
- "One display per install" goes away.

## Not verified until real hardware

- TRMNL: pairing end to end, which PNG variants its decoder takes in practice,
  HTTPS through Cloudflare and Nabu Casa, real sleep timing and battery life.
- CrowPanel: a second panel side by side; HTTPS once the firmware change is
  agreed; behaviour on another Wi-Fi network.
