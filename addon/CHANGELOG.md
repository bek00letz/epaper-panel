# Changelog

## 0.8.6
- **Proactive Server-Side Push for Hardware Refresh Slider:** The editor toolbar's **Panel Refresh** slider (1–60 min) now actively drives physical panel refreshes directly over Home Assistant's native ESPHome API.
  - **Works Immediately Without Reflashing Firmware:** Previously, changing the slider only updated an internal JSON field and attempted to set a Home Assistant number entity that didn't exist on hardware running initial firmware (which had a fixed 5-minute loop hardcoded). The add-on now actively commands the panel (`esphome.<device>_page_step` and `esphome.<device>_refresh_now`) according to your selected interval.
  - **Instant Visual Feedback:** Moving the slider triggers an immediate pre-render and refresh push to the physical panel on the spot, resetting the ticker loop to the new cadence.
  - **Multi-Slug Entity Syncing:** Attempts live updates across both `crowpanel_epaper` and `e_paper_panel` number entity namespaces for seamless compatibility with reflashed nodes.

## 0.8.5
- **Live Reactive "Show Only When Active" Condition Syncing:** The page condition (`show_if`) is now seamlessly and automatically populated with the exact entities configured across your dynamic grid spots.
  - **Zero Manual Jinja Editing:** As you type, paste, or select entities from Home Assistant autocomplete into any spot (Spot 1, Spot 2, Spot 3, Spot 4), the page's condition bar (`{{ is_state('entity_1','on') or is_state('entity_2','on') ... }}`) updates reactively in real time.
  - **Dynamic Entities Preset Tier: "when":** The "Dynamic Entities" preset now defaults to `tier: "when"` ("Show only when active") as intended, but with clean entity bindings rather than broken dummy zones.
  - **Automatic Legacy Dummy Entity Cleanup:** Simply opening or selecting any page containing a dynamic grid instantly updates its `show_if` to match the real configured spots, purging any leftover dummy `switch.zone_X` placeholders.
  - **Safe Spot State Handling:** When spots are initially blank or during page configuration, the page remains visible until monitored entities are configured and evaluated, preventing newly added pages from disappearing before you finish setting them up.

## 0.8.4
- **Visual Icon Picker for All Spots & Elements:** Selecting icons no longer requires memorizing or manually typing `mdi:...` names.
  - Every icon field across the editor—including standard **Icon** elements, **Dynamic Grid Header Icon**, and **Dynamic Grid Spots**—now features an interactive visual preview button rendering the actual glyph, alongside a convenient `Browse…` button.
  - Clicking any icon button opens an Apple-grade visual icon picker dialog.
- **Instant Search Across 7,000+ Material Design Icons:** Added an optimized client-side search engine backed by the full MDI codepoint registry, providing zero-latency 60fps search results with live glyph previews.
- **Quick-Category Chips:** Added curated category chips to the icon picker modal for one-click access: `Popular`, `🐱 Cat & Pets`, `🐾 Paw`, `♨️ Heating`, `🛏️ Bed & Furniture`, `⚡ Power`, `💡 Lights`, `🏠 Home`, `☀️ Weather`, and `🌡️ Climate`.
- **Intelligent Entity-to-Icon Auto-Suggestion:** Binding an entity to a spot in the Dynamic Grid inspector automatically suggests relevant icons based on the entity domain and name (e.g., cat/paw blankets automatically assign `mdi:paw` or `mdi:radiator`; lights assign `mdi:lightbulb`; switches assign sockets/power), while preserving manual overrides.

## 0.8.3
- **Auto-Save on Push & Full Strip Preview:** Clicking **Push to panel** or opening the **Full strip** modal now automatically commits and renders your latest canvas layout changes first, ensuring new pages, element modifications, and spot bindings are immediately included in the generated `/frames.png` strip and pushed to the physical display without having to remember to click "Save Changes" beforehand.
- **Dynamic Entities Preset Rotation Default:** The "Dynamic Entities" preset now defaults to `rotate` tier ("Always in rotation"), preventing newly created pages from being inadvertently hidden from rotation and the strip when monitored entities are initially off.
- **Dynamic Grid Auto-Hide & Real-Time Sync:** Added a dedicated **"Hide page when all spots off"** toggle to the Dynamic Grid inspector. Toggling it automatically manages the page's conditional `show_if` expression in real time, keeping the entity list synchronized whenever spots are added, edited, or removed.
- **Rotation Bar Visual Transparency:** Enhanced rotation pill badges to clearly indicate whether a conditional page is currently `live` (condition active, present in strip) or `idle (skipped)` (condition false, temporarily omitted from the rotation strip until an entity turns on).

## 0.8.2
- **"Dynamic Entities" Adaptive Multi-Spot Grid Element:** Added an intelligent `dynamic_grid` element designed for monitoring multiple related devices or zones (e.g. 1 to 4 heating blankets, radiators, climate zones, or lights) where only entities currently `on` (or matching a chosen state) are displayed:
  - **Dynamic Canvas Scaling (1 to 4 spots):** Automatically redistributes available screen area based on the number of active entities:
    - **1 Active:** Full-width hero card featuring a large icon, bold title, and prominent `ACTIVE` status badge.
    - **2 Active:** Balanced dual-card split (side-by-side columns in landscape, stacked cards in portrait).
    - **3 Active:** Trio card layout with clean icon anchors, bold spot labels, and runtime subtitles.
    - **4 Active:** Toggleable between a **2×2 Quadrant Grid** (balanced, high-legibility cards) and **4 Columns / Stack**.
  - **Customizable Spot Details:** Each monitored spot supports an entity ID, custom display name override (falling back to Home Assistant's friendly name), custom Material Design or custom icon, and a customizable secondary tag (`runtime` for "on for Xm", raw `state`, or `none`).
  - **Optional Header & Live Active Badge:** Optional header title (e.g. "Active Blanket Zones") and icon (e.g. `mdi:cat` or `mdi:lightning-bolt`), featuring a live active badge pill (`[ 2 / 4 ON ]`).
  - **Automatic Rotation Skip (`tier: "when"`):** When configured with `show_if`, the entire page is automatically bypassed during panel rotation when 0 entities are active, popping into view only when at least one entity turns on. If rotated while idle, it displays a calm, centered standby card.
- **"Dynamic Entities" Preset:** Added a ready-to-use "Dynamic Entities" screen template to the preset library (`Add Preset`) with preconfigured 4-zone monitoring and conditional rotation skip.
- **Orientation Reflow & Editor Inspector Integration:** Full support in the visual editor for adding dynamic grids, configuring spots, dragging/resizing, and automatic layout reflow between Landscape and Portrait orientations.

## 0.8.1
- **Apple-Grade Adaptive Layout Reflow:** Completely redesigned the Portrait ↔ Landscape reflow engine. Rather than naively squishing elements into a left-aligned vertical stack at `x = 20`, the new semantic engine detects element roles (Hero Stat, Visual Anchor / Icon, Subtitle, Trend Curve, Dividers) and creates a balanced, publication-grade layout:
  - **Portrait (272×792):** Horizontally centers hero icons (`90×90 px`), centers and sizes primary numbers and status readouts with units, pairs subtitles beneath stats, expands 24h trend curves across the full card width (`w: 240, h: 140-150 px`), converts side-by-side comparisons (e.g. Indoor vs. Outdoor temperature) into vertically stacked cards with horizontal dividers, and vertically balances the layout within the safe area.
  - **Landscape (792×272):** Restores the clean panoramic three-column hierarchy with left-column icons, center-left hero readouts and subtitles, and right-column trend curves and secondary statistics.
- **Zero-Reflash Live Hardware Refresh Slider:** Added an interactive refresh interval slider (1–60 min) directly into the editor stage toolbar and synchronized with Home Assistant's `number.<device>_refresh_interval` template entity. Adjusting the slider updates the physical panel's ticker loop on the fly without reflashing firmware.
- **LAN Host Port Auto-Detection & Custom Port Support:** Added automatic detection of external host-mapped ports via the Supervisor API (resolving LAN port 8099 conflicts with other add-ons such as Diivoo2MQTT) and added a dedicated **Port** field to the `Panel setup` wizard.

## 0.8.0
- **Multi-Model CrowPanel E-Paper Family Support:** Added built-in display profiles for the entire Elecrow CrowPanel E-Paper lineup:
  - `CrowPanel 5.79"` (`DIS08792E`, 792×272 px, 139.1×47.7 mm) — Primary & tested hardware default
  - `CrowPanel 4.2"` (`DIS08042E`, 400×300 px, 84.8×63.6 mm)
  - `CrowPanel 2.9"` (`DIS08029E`, 296×128 px, 66.9×29.1 mm)
  - `CrowPanel 7.5"` (`DIS08075E`, 800×480 px, 163.2×97.9 mm)
  - `CrowPanel 10.2"` (`DIS08102E`, 960×640 px, 215.0×143.4 mm)
- **Dynamic Hardware Model Selector:** Choose your display model in the editor toolbar or inside the `Panel setup` wizard. The editor updates the canvas aspect ratio, hardware bezel branding, safe-zone footer height, and pinned padlock boundaries in real time.
- **Model-Specific ESPHome Firmware Generation:** The `Panel setup` firmware wizard automatically configures drivers, loop dimensions, and component platforms (`crowpanel_epaper` for 5.79" & 4.2"; `waveshare_epaper` for 2.9", 7.5", & 10.2") tailored to the chosen model.
- **Physical DPI-Calibrated Legibility Checking:** Text physical millimeter sizes and viewing distance verdicts (`Desk 0.8m`, `Bedside 1.5m`, `Sofa 3.0m`, `Wall 5.0m`) scale accurately to the active model's millimeter width and pixel density.
- **Adaptive Footer & Orientation Reflow:** Built-in footer rule lines, clock/battery placement, and orientation reflow logic dynamically adapt to each screen model's native resolution and margins.

## 0.7.1
- **Typography & Font Picker:** Added font family selector (`Lato`, `DejaVu Sans`, and `Roboto Mono`) and weight control (`Bold` / `Regular`) for text and numeric elements, rendered via bundled TrueType fonts in PIL and previewed via web `@font-face`.
- **Persistent Advanced Pixel Coordinates:** The `Advanced Pixel Coordinates` inspector panel now remembers its expanded/collapsed state in `localStorage` across element selections and drag operations.
- **Page Duplication & Renaming:** Added `Duplicate` and `Rename` buttons to the page controls bar, allowing instant page cloning and in-place renaming with full rotation sequence updates and Undo/Redo history.
- **Customizable Viewing Distance & Legibility Check:** Replaced static 3m check with a configurable viewing distance selector (`Desk 0.8m`, `Bedside 1.5m`, `Sofa 3.0m`, `Wall 5.0m`, or `Disabled`), dynamically scaling font size thresholds and suppressing noise when disabled.
- **Refined Aesthetics & Emoji Restraint:** Removed decorative emojis from headers, select options, badges, and modals while keeping functional iconography strictly in domain filter chips and the element palette; replaced preset modal icons with crisp SVG vectors.
- **Generic Screen Presets & Entity Safety:** Replaced specific pension presets and arbitrary calendar entity auto-binding with a clean, generalized `Event & Schedule Countdown` preset with safe placeholder entity slots.

## 0.7.0
- **✨ One-Click Ready-Made Page Presets:** New preset library modal (`Add Preset`) featuring one-click screen templates designed for 3-metre sofa viewing: `Next Pension / Event Countdown`, `Room Climate & Comfort`, `Solar Power & Generation`, `Pet & Door Presence`, `Bin Day Waste Reminder`, and `Giant Sofa Clock & Date`. Each preset automatically configures iconography, element sizes, and entity bindings.
- **🎨 Modern Home Assistant Lovelace Dark & Light Theme:** Complete visual redesign with Inter typography, rich dark surfaces, high-contrast borders, tactile button micro-animations, an instant one-click `🌙 / ☀️` theme toggle, and an authentic CrowPanel hardware frame preview with Fit vs 100% zoom controls.
- **🏷️ Intelligent Entity Browser & Filter Chips:** Browse entities by domain category chips (`📅 Dates`, `🌡️ Sensors`, `⚡ Binary`, `❄️ Climate`, `🔒 Security`, `👤 People`), with friendly name prominence, live state pills, and instant one-click `➕ Add to Page` buttons alongside drag-and-drop.
- **Plain-English Countdown & Calendar Bindings:** Added native support for `show: "days_until"` (calculating days remaining until a future date or calendar event start), `show: "date_formatted"`, and `show: "calendar_title"`.
- **Modern Web Accessibility & Interaction Polish:** Applied `overscroll-behavior: contain` to prevent background scroll chaining during modal dialog interactions, added `Escape` key dialog dismissal, and enhanced canvas dragging with primary-button validation and pointer capture safety.

## 0.6.0
- **Mounting Orientation & Rotation (`0°`, `90°`, `180°`, `270°`):** Switch between `Landscape (0°)`, `Upside-down (180°)`, `Portrait CW (90°)`, and `Portrait CCW (270°)` directly from the editor header or `Panel setup` wizard. Pages are rendered in their logical aspect ratio (`792×272` or `272×792`) in the editor and automatically rotated into the panel's physical `792×272` framebuffer on the server, so orientation changes take effect on `Save` / `Push to panel` without reflashing ESPHome.
- **One-Click Page Reflow:** Switching between Landscape (`792×272`) and Portrait (`272×792`) adapts the canvas aspect ratio and safe-area guides (`y >= 752` in portrait) and offers a `Reflow` button (with Undo) to restack elements cleanly for the new orientation.
- **Automatic Rocker Button Swap (`180°` / `270°`):** Generating ESPHome YAML in the `Panel setup` wizard for `180°` or `270°` mounts automatically swaps `key_next` and `key_prev` GPIO pins (`4` and `6`) so the physical rocker buttons match the inverted/rotated mount.

## 0.5.0
- **Panel Setup & ESPHome Firmware Wizard:** Configure your Home Assistant host/IP, device name, Wi-Fi, and auto-generated API encryption key & OTA password directly in the editor UI (`Panel setup`), with one-click YAML copy/download and live Home Assistant panel connection status.
- **Visual `Show if` Condition Builder:** Configure `only when true` and `interrupt only` page conditions without writing raw Jinja (with a `Custom Jinja` mode still available for complex expressions).
- **Interactive Rotation Bar & Full Strip Preview:** Reorder, add/weight, or remove rotation pages via interactive pills, and preview the full rendered `/frames.png` strip directly from the header status pill or `Full strip` button.
- **Canvas Safe-Area Guides & Quick Alignment:** Toggle footer (`y >= 232`) and held-page padlock (`x >= 752`) margin guides on the canvas, and use quick-align (`Center X`, `Center Y`, `Full W`) and layer order (`↑` / `↓`) buttons in the inspector.

## 0.4.0
- Hardened security across the editor UI, Jinja bindings, Home Assistant API paths, and data source credentials.
- Fixed numeric elements with suffixes (`°`, `%`) rendering `--`, negative sparkline curves, and 1-page alert strip holds.
- Added font caching, shared HTTP sessions, `ETag` / `304 Not Modified` frame responses, and immediate re-render on save/push.
