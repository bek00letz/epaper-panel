# Changelog

## 0.8.27
- **Self-Contained Active Window Controls for Sports, Racing & Flight Cards (Zero Manual HA Sensor Wiring):**
  - Previously, making `sports_match` only appear on matchdays required manually creating/wiring a `show_if` check against `sensor.sports_premier_league`, which broke when switching leagues (e.g. to Champions League or NBA) and didn't exist at all for `sports_racing` (Formula 1, Formula E, NASCAR, IndyCar).
  - **`sports_match` (All 9 Leagues + Optional Team Filter):** Added an **Only show page during active matchday window** toggle, `show before (hrs)`, and `show after (hrs)` directly in the Studio element inspector. Switching leagues (`Premier League`, `UEFA Champions League`, `La Liga`, `Bundesliga`, `Serie A`, `NBA`, `NFL`, `MLB`, `NHL`) or specifying a `team` filter automatically updates the active window and syncs the page condition — no manual Home Assistant sensor creation or editing required.
  - **`sports_racing` (Formula 1, Formula E, NASCAR & IndyCar):** Added `compute_racing_active_window()` in `server.py` and full inspector controls (**Only show page during active race window**, **Window Mode**: `Around Each Session (FP / Quali / Race)` vs `Entire Race Weekend (FP1 → Checkered Flag)`, `show before (hrs)`, and `show after (hrs)`). Evaluates both the `sportstimes` session schedule (`fp1`, `fp2`, `fp3`, `qualifying`, `sprint`, `gp`/`race`) and live ESPN telemetry.
  - **`flight_tracker`:** Added **Only show page when aircraft overhead (> 0)** toggle directly in the widget inspector.
  - **Direct Python Evaluation in `eligible_pages()`:** Pages with `tier: "when"` containing `sports_match`, `sports_racing`, or `flight_tracker` now evaluate their widget's live active window directly in Python (`_evaluate_widget_gate()`), so active windows work out-of-the-box even before Home Assistant polls any external sensor.
- **Unified `sensor.epaper_*` Namespace, On-Demand Publishing (No Bloat) & MQTT `unique_id` Support:**
  - All add-on-generated sensors now use the `sensor.epaper_*` prefix (`sensor.epaper_sports_<league>`, `sensor.epaper_racing_<series>`, `sensor.epaper_flights_overhead`, `sensor.epaper_closest_aircraft`, `sensor.epaper_quiet_hours`, `sensor.epaper_panel_last_render`, plus user data sources `sensor.epaper_<slug>`) with `attribution: "E-Paper Studio"`.
  - **On-Demand Only (Zero Entity Bloat):** `publish_computed()` scans `layouts.json` and only polls/publishes sports, racing, or flight sensors for leagues, series, or radars actually present on your pages.
  - **Automatic Legacy Sensor Migration:** Existing layouts, `show_if` rules, and exploded widgets referencing legacy names (`sensor.sports_*`, `sensor.f1_status`, `sensor.formula_e_status`, `sensor.overhead_aircraft_count`, `sensor.closest_aircraft`) are automatically migrated to `sensor.epaper_*` in `sanitize_layouts()`.
  - **MQTT Auto-Discovery `unique_id` & Device Grouping:** All active `sensor.epaper_*` sensors are registered via MQTT Auto-Discovery (`publish_mqtt_discovery`) with a deterministic `unique_id` and grouped under the **E-Paper Studio** device in Home Assistant when an MQTT broker is present.
  - **`✦ E-Paper` Filter Chip & `E-PAPER` Badge in Studio Entity Picker:** Added a dedicated **`✦ E-Paper`** filter pill and **`E-PAPER`** badge in the right-rail Entities Explorer so app-native sensors are immediately recognizable.

## 0.8.26
- **Manual Scroll Protection & 15-Second Background Fetch Debounce (`user_cool_sec` & `request_refetch`):**
  - Eliminated device freezes when scrolling manually through pages while a 1-minute background update fires.
  - Every physical button press (`key_next`, `key_prev`, `key_ok`, `key_top`, `key_bottom`) and remote action (`page_step`, `mode_toggle`, `lock_toggle`, `category_step`, `sub_step`, `show_page`, `show_category`) now starts a **15-second interaction cooldown (`user_cool_sec`)**.
  - Incoming `refresh_now` pushes from Home Assistant and internal refresh timers now route through `request_refetch`, which checks `user_cool_sec < 15`. If the user is actively scrolling, the network download is **paused/deferred (`pending_refetch = true`)** and automatically executed 15 seconds after manual scrolling stops.
  - Reduced `online_image` `buffer_size` from `32768` to `4096` (and `http_request` `buffer_size_rx` to `4096`) so multi-page PNG decoding yields to the ESPHome main loop between 4 KB chunks rather than blocking in a single 14-second `loop()` call.
- **Decoupled Fast Local PSRAM Page Rotation (`rotate_sec`) vs Background Network Fetch (`panel_refresh_interval`):**
  - Previously, every rotation step on the ESP32 triggered `script.execute: refetch` (making an HTTP request on every page turn) and ignored the Studio UI's `rotate_seconds` (`#rotinterval`) setting.
  - The self-describing metadata row in `frames.png` now encodes `rotate_seconds` (2 bytes MSB/LSB) alongside a 16-bit content hash (`etag_b0`, `etag_b1`).
  - The ESP32 now runs a 5-second interval loop that rotates pages **locally in PSRAM** every `rotate_sec` (`30s` default, ~480 ms blit, zero network activity) while `fetch_idle_sec` independently triggers background data fetches every `panel_refresh_interval` minutes.
- **Sequential Sub-Item Rotation Memory Across Category Passes (`cat_sub_pos`):**
  - Fixed multi-item categories (Watch/Media feeds, Airspace Radar flights, Sports matches) always resetting `sub_idx = 0` on every rotation pass or after a 1-minute data refresh.
  - Added per-category sub-item position memory (`std::vector<int> cat_sub_pos`) on the ESP32. Pass 1 through a multi-item category now displays sub-item `1/N`, Pass 2 displays `2/N`, Pass 3 displays `3/N`, and background 1-minute `frames.png` refreshes preserve both `cat_sub_pos` and the currently displayed `sub_idx` without resetting the rotation timer.
- **HTTP `304 Not Modified` & `Last-Modified` Cleanups:**
  - Added RFC 2822 `Last-Modified` header to `_frame_headers()` in `server.py`, eliminating `[W][http_request:032]: No header with name last-modified found` in ESPHome logs.
  - When `online_image` receives `HTTP 304 (Not Modified)` and the 16-bit strip hash (`last_strip_hash`) and page index are unchanged, `on_download_finished` now skips the redundant physical e-paper `redraw`.

## 0.8.25
- **Configurable Night / Quiet Hours (Zero-Ghosting Deep Idle):**
  - Added an optional, fully configurable **Night / Quiet Hours** schedule (`quiet_hours`) accessible via the top toolbar (`🌙 Quiet`) or **Settings → Night / Quiet Hours…** (`enabled: false` by default).
  - Supports a daily time window (`start` to `end` in `HH:MM`, including overnight windows like `23:30` to `07:00`) and/or an optional Home Assistant presence entity (`zone.home`, `person.*`, `group.*`, `input_boolean.*`) that activates Quiet Hours automatically when everyone is away (`0`, `not_home`, `away`, `off`).
  - **How it works:** While Quiet Hours are active, the server suppresses background `refresh_now` pushes to the panel and encodes a quiet-mode flag (`0xA5`) in the self-describing metadata row of `frames.png`. The ESP32 pauses its 10-second auto-rotation timer so the e-paper screen performs **zero physical flashes** overnight (eliminating e-ink wear and bedroom flashing while retaining the crisp image at zero power), yet **stays 100% awake on Wi-Fi** so physical buttons and IKEA BILRESA scroll remotes still page instantaneously.
  - Optional **Allow Interrupt Alerts (`allow_alerts`)** override lets high-priority `alert` tier pages wake and update the panel even during Quiet Hours.
  - Publishes `sensor.epaper_quiet_hours` (`active` / `inactive`) with schedule and reason attributes to Home Assistant.
- **New E-Ink Native Primitives & Visual Styling:**
  - **`box` (Card / Container / Pill / 50% Screen):** Structural rectangle/rounded card primitive supporting `outline`, `black` (solid fill), `white` (opaque mask), and `screen` (50% checkerboard grey pattern) with configurable corner `radius` and border `thickness`.
  - **Inverted & Pill Badges on `text`, `number`, and `icon`:** Any text, number, or icon element can now toggle `Invert (White on Black)` and/or `Pill / Badge Frame` with configurable corner `radius` for high-contrast headers, status tags, and callout badges.
  - **`bar` (Progress / Gauge Bar):** Horizontal (`solid` or `segmented` battery blocks) or `vertical` tank/column gauge bound to any numeric entity or template, with configurable `min_val`, `max_val`, `title`, `suffix`, and `show_label`.
  - **`bar_chart` (Multi-Bar History Column Chart):** Renders historical Home Assistant sensor data bucketed into `4`–`24` discrete vertical columns over `1`–`72` hours with min/max scale labels and current value readout.
  - **`qr` (Zero-Dependency 1-Bit QR Code Generator):** Pure-Python ISO/IEC 18004 QR code renderer (`addon/app/render/qr.py`) supporting URLs, static text, live Home Assistant entity states, or **Guest Wi-Fi credentials** (`WIFI:T:WPA;S:...;P:...;;`) with crisp module scaling and optional caption header.
- **Per-Element Conditional Visibility (`show_if`):**
  - Every individual element on a page now supports an optional `show_if` condition (structured entity state comparison or raw Jinja expression) in the inspector, allowing badges, warning icons, or secondary metrics to appear or hide dynamically on the same canvas without duplicating whole pages.
- **Studio Multi-Select (`Shift+Click`), Group Alignment & Custom Presets:**
  - **Multi-Select (`Shift+Click`):** Hold `Shift` and click elements on the canvas to select multiple elements at once. Dragging or pressing arrow keys moves the entire selection together.
  - **Multi-Element Alignment & Distribution Toolbar:** Selecting 2+ elements opens a dedicated alignment inspector (`Align Left`, `Center H`, `Align Right`, `Align Top`, `Middle V`, `Align Bottom`, `Distribute H`, `Distribute V`, `Duplicate Selected`, `Delete Selected`).
  - **Save Page as Custom Preset:** Save any designed page into your personal **Custom Presets** library (`💾 Save Page as Preset…`), stored in `layouts.json` (`custom_presets`) and accessible with one click in the **Page Presets** modal alongside two new built-in presets (`Energy & Battery Gauges` and `Guest Wi-Fi QR Card`).
- **Single-Page Slice Endpoint (`/frame.png?page=N`):**
  - `/frame.png` now accepts an optional `?page=N` query parameter to serve any individual rendered slice PNG directly by index.

## 0.8.24
- **Editable & Customizable Composite Widgets (`font_scale`, Layout Density & Break Apart):**
  - **Typography Scale (`font_scale` 0.70×–1.60×) & Density Controls:** All composite widgets (`weather_forecast`, `calendar_month`, `calendar_agenda`, `flight_tracker`, `sports_racing`, `sports_match`, `dynamic_grid`) now expose a **Font Scale (`70%`–`160%`)** slider, **Show Outer Border** toggle, and layout-specific density controls (`Forecast Days` 3–5, `Split Hero + Forecast` vs `Full-Width Forecast Only`, `Max Events` 2–6, `Max Matches` 2–4, `Radar Split` vs `Telemetry Only`).
  - **✂️ Break Apart into Editable Elements:** New one-click inspector action (`POST /api/widget/explode`) that decomposes any composite widget (`weather_forecast`, `flight_tracker`, `sports_racing`, `sports_match`, `calendar_agenda`, `dynamic_grid`) into standard, individually draggable `text`, `number`, `icon`, and `line` elements on the canvas for unlimited pixel-level customization.
- **Weather Forecast Multi-Tier Fallback Engine:**
  - Fixed `weather_forecast` cards getting stuck on `"Forecast loading..."` on modern Home Assistant (`2024.3+`, where `state_attr('weather.x', 'forecast')` was removed).
  - `fetch_weather_forecast()` in `server.py` now tries 4 tiers automatically: (1) HA REST `POST /api/services/weather/get_forecasts?return_response` (`hourly` + `daily`), (2) HA WebSocket `weather/get_forecasts` fallback, (3) legacy `attributes.forecast`, and (4) **automatic Open-Meteo API fallback** using your `zone.home` coordinates and WMO weather codes if the HA weather integration fails or is unavailable.
- **Eliminated Black "Sleep-Like" Screen & Remote Desync Bugs:**
  - **Root Cause 1 (Torn In-Flight Downloads):** ESPHome's `online_image` clears/reallocates its target PSRAM buffer as soon as an HTTP download starts (`GET /frames.png`), taking ~5–6 seconds to decode. Previously, if the 10s timer ticked or a remote action fired mid-download, the display lambda blitted an uninitialized/zeroed PSRAM buffer (`COLOR_ON` with `invert_colors: true` = solid black screen) until the user rotated the dial.
  - **Root Cause 2 (Stale `cat_offsets` / `cat_sizes`):** `ha_cat_offsets` and `ha_cat_sizes` arrived asynchronously over the ESPHome native API out of lockstep with `frames.png`, causing `page_step` from an IKEA BILRESA scroll remote to compute out-of-range slice indices (`y_offset >= strip.height`).
  - **Fix — Self-Describing Strip Metadata & Download Guard:** `server.py` now embeds a self-describing binary header (`0xA5` magic, `cat_count`, `(offset, size, pill_width)` per category, and `quiet_hours_active`) in the bottom-right pixels of `frames.png`. The firmware reads this header atomically inside `on_download_finished` and guards `redraw`, `page_step`, `mode_toggle`, `lock_toggle`, and `show_page` with `downloading_frames` so mid-download triggers defer cleanly until decoding finishes.
- **Studio Canvas Smart Alignment Guides:**
  - Dragging an element on the canvas now snaps to and renders live magenta alignment guides for canvas centerlines (`X = W/2`, `Y = H/2`) and other elements' edges and centers (`±5 px` threshold; hold `Alt` to bypass snapping).

## 0.8.23
- **Custom Flight Tracker Coordinates & Airport Presets:**
  - Added support for custom latitude and longitude on flight tracker cards (allowing traffic monitoring above specific airports such as TSR, LHR, JFK, FRA, or any custom coordinate) with graceful fallback to Home Assistant's `zone.home` coordinates.
  - Multi-location cache: flight tracker cache is now keyed per location and radius, allowing multiple cards or airports without cache collisions.
  - Added Airport Presets (Home, TSR Timisoara, LHR Heathrow, JFK New York, FRA Frankfurt) and custom location label input in the Visual Editor inspector.
  - Added location tags to on-screen distance badges (`1.5 KM E · LHR`) and radar headers.
- **Formula E Motorsport Pit-Wall Tracker:**
  - Added native Formula E support (`series: "fe"`) to `sports_racing`.
  - Integrates with authoritative Formula E season calendar feeds (`sportstimes/f1` and `formulaecal.com`), automatically resolving current/upcoming ePrix rounds, practice sessions, qualifying, and race sessions.
  - Publishes `sensor.formula_e_status` to Home Assistant with state (`PRE`, `IN`, `POST`), event name, circuit, and localized session schedule.
  - Features dedicated electric motorsport iconography (`mdi:car-electric`).
- **Local & Preferred Timezone Conversion for Sports & Motorsport:**
  - Automatically queries Home Assistant's configured timezone (`/api/config` -> `time_zone`, e.g. `Europe/Bucharest`) or accepts card-level custom timezone overrides.
  - All sports kickoff times (Premier League, NBA, NFL, Champions League, etc.) and racing session times (F1, Formula E) are automatically converted from UTC to the user's local timezone (e.g. converting 13:00 UTC to `16:00 EEST` / `15:00 EET`).
  - Added localized time attributes (`first_kickoff_local`, `last_kickoff_local`, `window_start_local`, `window_end_local`) to `sensor.sports_{league_slug}` for easy Jinja automation templates.

## 0.8.22
- **Real-Time ADS-B Flight Tracking:**
  - Replaced deprecated/rate-limited OpenSky Network feed with ultra-fast, rate-limit-free Flightradar24 live feed with OpenSky fallback.
  - Automatically fetches live aircraft within range of Home Assistant home coordinates (`zone.home`), delivering flight routes (`BEY → DUS`), aircraft models (`A320`, `B77W`), speed, altitude, and heading.
  - Dynamically synchronizes `sensor.overhead_aircraft_count` and `sensor.closest_aircraft` to the card's configured radius (clamped to realistic ADS-B line-of-sight: max 250 km).
- **Dynamic Sports Matchday Active Window:**
  - Added smart matchday active window computation engine for all leagues (Premier League, UEFA Champions League, La Liga, Bundesliga, Serie A, NBA, NFL, MLB, NHL).
  - Automatically prioritizes today's games (`?dates=YYYYMMDD`) over previous round results, dynamically showing the card from configurable pre-match buffer (default: 2 hrs before kickoff) until post-match buffer (default: 2 hrs after final whistle).
  - Automatically keeps card active if any game is live / in progress.
  - Publishes `sensor.sports_{league_slug}` (e.g. `sensor.sports_premier_league`, `sensor.sports_nba`) with state `active`/`idle` and rich matchday metadata for 1-click Page Tier conditional display (`show_if: "{{ is_state('sensor.sports_premier_league', 'active') }}"`).
  - Added configurable pre-kickoff and post-whistle buffer controls to the Visual Editor inspector.

## 0.8.20
- **Feed / Watch Sub-Item Cycling:**
  - Resolved issue where secondary episode detail elements in the watch/feed card remained frozen on the first item's episode title.
  - Added multi-tier resolution in `server.py` sub-item slicing to seamlessly cycle both titles and episode details whether configured via structured entity attributes, custom Jinja templates (`{{ state_attr(...) }}`), or template values matching the feed's initial detail.
  - Exposed `/api/layouts` on the panel LAN port for diagnostic inspection.

## 0.8.19
- **Remote & Hierarchical Navigation Actions:**
  - Added native `action: mode_toggle` to switch between Category mode and Sub-category navigation, supporting remote automations (IKEA Bilresa, Matter/Zigbee remotes) with on-screen active pill inversion sync.
  - Upgraded `action: page_step` to be context-aware (steps sub-items when in sub-mode; steps categories when in category mode), eliminating 1D/2D state desync and black overhang boxes.
  - Added `action: lock_toggle` for unified contextual single-click locking (Category lock in category mode, Panel lock in sub-mode).
  - Ensured `show_page` recalculates `cat_idx` and `sub_idx` from category offsets so absolute page jumps never desynchronize.

## 0.8.18
- **Render Loop Fix:**
  - Resolved `TypeError: string indices must be integers, not 'str'` in `build_frames` by using display dictionary `disp["margin"]` instead of string identifier `display["margin"]`.
  - Restored continuous background rendering and real-time category sensor updates (`sensor.epaper_category_pill_widths`).

## 0.8.17
- **Security & Authentication Hardening:**
  - Enforced `_check_frame_auth` token validation across physical refresh and page stepping action endpoints (`/api/action/refresh`, `/api/action/page`), preventing unauthenticated physical e-paper refresh denial-of-service on LAN port 8099.
  - Added full support for `Authorization: Bearer <token>` in addition to `X-Frame-Token` and query parameter tokens.
  - Hardened `/api/panel/setup` GET & POST handlers to mask Wi-Fi credentials in generated YAML and secrets text, preventing plaintext password leaks over the web interface.
  - Removed risky positional index fallback in `feeds.unmask_secrets()`, ensuring secrets are matched strictly by feed slug to prevent credential cross-contamination when feeds are reordered or added.
- **ESP32-S3 Firmware Memory Safety & Live Sync:**
  - Added screen coordinate bounds checking (`rx < dw && ry < dh`) in both Category and Sub-item active pill inversion loops, eliminating out-of-bounds PSRAM writes and ESP32-S3 `LoadProhibited`/`StoreProhibited` panics.
  - Replaced `.empty()` sensor checks with dynamic vector assignment in `ha_cat_offsets` and `ha_cat_sizes`, allowing Home Assistant category and layout changes to sync live without requiring a physical panel power-cycle.
  - Added `ha_cat_pill_widths` text sensor for real-time pill width synchronization from Home Assistant.
  - Added `!std::isnan(x)` check on `ha_cat_count` to prevent undefined behavior during initial sensor discovery.
  - Tuned rotary dial center button (`key_ok`, GPIO 5) to toggle navigation mode on a long hold (1000ms–5000ms), eliminating accidental mode switches caused by rotary dial scroll tilt wobble.
- **Rendering Engine & Backend Stability:**
  - Resolved fatal `UnboundLocalError / NameError: cat_pill_widths` in `server.py` that caused immediate render loop crashes.
  - Corrected runaway render loop timing (`await asyncio.sleep(REFRESH)`), restoring user-configured refresh intervals (e.g. 5m / 10m).
  - Implemented `step_panel_page` to properly forward relative page steps to ESPHome via Home Assistant services.
  - Hardened Jinja template generation for `last_changed` and `last_updated` against missing entities, and validated `replace` configuration types to prevent unhandled `AttributeError`.
  - Added boundary clamping for calendar month/year rendering and dynamic grid calculations to prevent `IndexError` and division-by-zero crashes.
  - Bounded footer category pill width against sub-item pill positions to prevent visual overlapping on narrow displays.

## 0.8.16
- **Self-Describing Image Header & Permanent Anti-Desync Architecture:**
  - `frames.png` now encodes the authoritative category count, slice offsets, and sub-page sizes directly into a dedicated invisible header scanline appended to the image strip.
  - ESPHome parses this metadata directly out of the downloaded image buffer in PSRAM on `on_download_finished`.
  - Solves the asynchronous metadata race condition where Home Assistant entity updates desynced from the image currently held in panel PSRAM, permanently preventing missing categories (such as sports match / scores) or wrong slice navigation when conditional pages dynamically join or leave the rotation.
  - Immediate proactive push (`refresh_now`) is triggered whenever structural category changes are detected by the server.
- **Apple Craftsmanship & Polish Standard Lock Badges:**
  - Redesigned the padlock from a 10×13px dot into a prominent, high-contrast 28×24px rounded status badge (`[ 🔒 ]`) featuring concentric 4px corners, a 3px thick shackle, a bold body, and a clean keyhole cutout.
  - **Category Lock Badge:** Renders immediately following the category pill (`[ 1/9 WATCH ] [ 🔒 ]`).
  - **Panel Lock Badge:** Renders beside the sub-item pill (`[ 🔒 ] [ 1/2 ]`) or in the right status corner.
- **Rocker Switch Hardware Hardening & Anti-Chatter:**
  - Added software crosstalk suppression (`last_ok_press_ms` filter) to ignore mechanical contact bleed when pressing the dial in (preventing inadvertent rotate-left or rotate-right triggers).
  - Center dial push (`key_ok`) now triggers instantly `on_press` with a robust 30ms symmetric debounce filter, eliminating dropped clicks or timeouts from firm presses.
  - Symmetrical 750ms threshold across `key_top` and `key_bottom` eliminated button click "dead zones."
  - When in sub-item mode, categories with a single page automatically fall back to category navigation instead of stalling.
- **Periodic Scheduled Refetching:**
  - Ensured that sensor data refetches on the scheduled interval (`panel_refresh_interval`) whether the panel is actively auto-rotating or pinned on a specific card.

## 0.8.15
- **Structured Footer Navigation & Dynamic Focus Inversion:**
  - Shifted category title and counter closer to the system clock on the left (e.g. `14:40  [ 1/5 LIVING ROOM ]`).
  - Added sub-item counter towards the right of the screen (e.g. `[ 1/4 ]`) for categories with multiple items.
  - Active selection is indicated by Apple-grade solid inversion (solid black pill with crisp white text):
    - **Category Mode (default):** Category pill is inverted, signaling that turning the rotary dial steps through categories.
    - **Sub-Item Mode (when dial is clicked):** Category pill reverts to outline, and Sub-item pill becomes inverted, signaling that turning the dial steps strictly through sub-items inside that category.
    - Clicking the dial again toggles focus back to Category mode.
- **Orientation-Aware Hardware Button Actions:**
  - Dynamic pin mapping based on orientation:
    - **Physical Top Button (GPIO 1 on 180° mounts / GPIO 2 on 0° mounts):** Short click (<600ms) toggles **Category Lock**; Long hold (>1000ms) toggles **Panel Lock**.
    - **Physical Bottom Button (GPIO 2 on 180° mounts / GPIO 1 on 0° mounts):** Short click (<600ms) instantly resets back to **Page 1 (Category 1)**; Long hold (>1000ms) forces an immediate network refetch from Home Assistant.
- **Relocated Status Badges from Canvas to Footer Chrome:**
  - Moved the exact slide lock padlock (`pinned`) and category lock badge (`cat_pinned`) into the uneditable 32px footer bar, liberating the top-right canvas area so cards and headers never get occluded.
  - Category lock renders right beside the category pill; Panel lock renders beside the sub-item pill (or right margin).
- **Activity Watchdog & Anti-Freezing:**
  - Any button press or dial turn resets the panel activity watchdog (`idle_sec = 0`), guaranteeing the user their full refresh interval of uninterrupted viewing without the screen suddenly rotating away.
  - Background network image fetches and display updates are suppressed while the user is actively interacting (`idle_sec <= 30`), completely eliminating dial input lag and screen freezes.
  - Debounced screen redraw to 80ms restart, giving buttery-smooth dial responsiveness without e-paper thrashing.

## 0.8.14
- **Orientation-Aware Pin Badges & Rocker Button Inversion (180° / 270° Mounts):**
  - Padlock indicator (`pinned`) and Category Pin badge (`cat_pinned`) are now dynamically mapped to physical screen coordinates and drawn right-side up in the viewer's visual top-right corner, eliminating inverted or clipped badges on 180° mounts.
  - Rocker dial GPIOs (`4` and `6`) are automatically swapped in the ESPHome configuration for 180° mounts so rotating clockwise/right advances forward regardless of board inversion.
- **Dynamic Jinja Decimal Precision for Number Elements:**
  - `_fmt_number()` now respects custom Jinja template decimal formatting when templates dynamically switch between whole integers and floating point units (e.g. Watts to Kilowatts).

## 0.8.13
- **Universal Clipboard Fix (HTTP, HTTPS, & Ingress iFrames):**
  - Resolved clipboard copying failures where `navigator.clipboard` was undefined in non-secure HTTP contexts (`http://homeassistant.local:8123` or IP access) or blocked by Ingress iframe security policies.
  - Added synchronous `document.execCommand('copy')` fallback with direct DOM element selection and off-screen textarea buffers, guaranteeing that user gesture tokens are never discarded across asynchronous network boundaries.
  - Added tactile feedback to all copy buttons (`Copy key`, `Copy OTA password`, `Copy YAML`, `Copy secrets.yaml`), flashing `✓ Copied!` with subtle emerald highlight and displaying toast confirmations.
  - Added dedicated `Copy` button for the OTA password field.
  - Added automatic change detection across all panel setup inputs (`cfg_dev`, `cfg_host`, `cfg_port`, `cfg_ssid`, `cfg_pw`, `cfg_otapw`) so generated YAML stays perpetually up-to-date.

## 0.8.12
- **2D Hierarchical Navigation (Categories $\times$ Sub-Items):**
  - Expanded multi-item cards (`flight_tracker` with multiple aircraft overhead, `sports_match` with multiple scoreboard games, and `watch` with multiple queued episodes like *Scrubs* and *Brothers*) into consecutive sub-slices in the local PSRAM strip.
  - Implemented intuitive 2D category and sub-item mapping:
    - **Rotary Dial (Rotate Left / Right, GPIO 6 / 4):** Switches **only between Categories** (e.g. Solar $\leftrightarrow$ Weather $\leftrightarrow$ Watch $\leftrightarrow$ Scores $\leftrightarrow$ Flights $\leftrightarrow$ Cat). Users never have to scroll through 20 NBA games or 5 flights just to see the weather or cat!
    - **Dial Center Push (GPIO 5):** Short click (<500ms) steps through **sub-options within that category** (e.g. Knicks v Raptors $\rightarrow$ Bulls v Bucks; or Flight 1 $\rightarrow$ Flight 2 $\rightarrow$ Flight 3; or Scrubs $\rightarrow$ Brothers) with instantaneous partial refreshes (~300ms) directly from local PSRAM.
    - **Dial Long Push (>1000ms):** Toggles **Category Pin** (`cat_pinned`). The panel displays an Apple-polish category badge and locks the automatic interval timer to rotate *only* through sub-items inside that category (e.g. auto-cycling tonight's NBA games).
    - **Menu Button (GPIO 2):** Short click (<500ms) toggles **Item Pin** (`pinned`, lock icon appears, freezing on that exact item). Long hold (>1000ms) forces an immediate network refetch from Home Assistant.
    - **Exit Button (GPIO 1):** Unpins all and resets to Home (Category 0, Page 0).
- **Home Assistant Real-Time Category Sensors & API Actions:**
  - Automatically publishes `sensor.epaper_category_count`, `sensor.epaper_category_offsets`, `sensor.epaper_category_sizes`, and `sensor.epaper_category_names` to Home Assistant.
  - Added ESPHome actions `show_category`, `category_step`, `sub_step`, and `category_pin_toggle`.
  - Added `GET /api/manifest` and `GET /manifest.json` endpoints serving complete 2D category geometry.
- **Dynamic Radar & Scoreboard Pagination:**
  - Radar scope targeting reticle `[ ✈ ]` dynamically tracks the selected aircraft across sub-items.
  - Added concentric pagination pills `[ 1/3 ]`, `[ 2/3 ]` to flight telemetry and sports scoreboards, plus clear footer labels (`WATCH · 1/2`, `SCORES · 2/5`).

## 0.8.11
- **Circular PPI Radar Scope & Multi-Style Flight Tracker:**
  - Added tactical circular Plan Position Indicator (PPI) radar scope with outer boundary ring, intermediate range ring, cardinal tick marks (N, E, S, W), range scale badge, home reticle, and directional aircraft blips with callsign tags and target lock brackets (`[ ✈ ]`).
  - Added `radar style` selector to the Flight Tracker inspector:
    - `card` (default): The full-width 4-column telemetry card (preserved 100%).
    - `split`: Tactical circular PPI radar scope on the left + compact 3-column flight telemetry cards on the right.
    - `radar`: Dedicated circular PPI radar scope.
  - Added `flight_radar` preset ("Overhead PPI Radar & Telemetry") with automatic dynamic activation (`tier: "when"`).
- **Formula 1 & Motorsports Live Pit-Wall Tracker (`sports_racing`):**
  - Live pit-wall leaderboard rendering Top 10 driver positions, driver acronyms (`VER`, `NOR`, `HAM`), constructor names, live gaps (`LEADER`, `+2.1s`), tyre compound badges (`[S]`, `[M]`, `[H]`), and session lap counts (`LAP 42/53`).
  - Integrated off-week & pre-race schedule card featuring racing helmet glyph, circuit full name, city, and session start countdown.
  - Published `sensor.f1_status` (`PRE`, `IN`, `POST`) to Home Assistant with event name, circuit, and detail attributes for 1-click dynamic page tier gating (`tier: "when"`).
- **Live Sports Match Scoreboard (`sports_match`):**
  - Head-to-head live scoreboards for Soccer (Premier League, UEFA Champions League, La Liga, Serie A, Bundesliga), Basketball (NBA), NFL, MLB, and NHL.
  - Prominent typography for team names, huge centered score numbers (`2 — 1`), match clock / period badge (`74' · 2ND HALF`, `FINAL`, `Q3 8:12`), team records, and bottom scorers/events ticker.
- **Dual Engine Architecture (Approach A & Approach B Hybrid):**
  - **Approach A (Home Assistant `ha-teamtracker`):** If an entity is specified (e.g. `sensor.arsenal`, `sensor.boston_celtics`, `sensor.f1`), state, clock, scores, venue, down & distance, and last play are extracted directly from Home Assistant.
  - **Approach B (Public Scoreboard Feeds):** Zero-config fallback to public ESPN and OpenF1 APIs when no Home Assistant entity is configured. Allows users to simply choose a league and optional team name (e.g. `Premier League` + `Arsenal`) to start tracking live scores instantly.

## 0.8.10
- **Weather Forecast API Unwrapping & Precipitation Chance:**
  - Resolved Home Assistant REST API envelope quirk (`{"response": {eid: ...}}`) so `weather.get_forecasts` daily forecast items and High/Low ranges populate instantly.
  - Added precipitation probability (`% rain`) and precipitation volume (`mm`) indicators to both the current conditions chips and multi-day forecast strip.
  - Dynamically scaled chip font hierarchy to preserve breathing room from dividers.
- **Multi-Calendar Family Scheduling & Badges:**
  - `fetch_calendar_events` now supports comma-separated entity IDs (e.g. `calendar.personal, calendar.work, calendar.family`).
  - Fetches from all specified calendars concurrently, tags events with calendar source badges (e.g. `WORK`, `PERS`), deduplicates, and sorts chronologically.
  - Renders subtle outlined calendar origin badges on each agenda item.
- **Multilingual Font Fallback Chains:**
  - Installed Alpine Unicode font packages (`font-noto`, `font-noto-cjk`, `font-noto-arabic`, `font-noto-hebrew`, `font-dejavu`).
  - Added intelligent script detection in `theme.py` that transparently routes Cyrillic, Greek, Hebrew, Arabic, and CJK (Chinese, Japanese, Korean) characters through appropriate native glyph sets without rendering missing glyph tofu boxes (`□`).
- **MQTT Auto-Discovery & REST Control Actions:**
  - Publishes Home Assistant MQTT Auto-Discovery entities: `button.epaper_panel_refresh` (instant refresh and panel push) and `sensor.epaper_panel_last_render` (live render timestamp).
  - Added REST action endpoints `POST /api/action/refresh` and `POST /api/action/page` for easy integration with standard Home Assistant automations and webhooks.
- **Linux & Battery E-Ink Client Daemon:**
  - Added `client/linux/epaper-daemon.sh` with strict conditional `If-None-Match` ETag caching.
  - Automatically aborts screen refresh and redraw on `HTTP 304 Not Modified`, allowing battery e-readers (Kindle, Kobo, Android Termux, Raspberry Pi Zero) to go back to sleep in <100ms.

## 0.8.9
- **Monthly Wall-Calendar View (`calendar_month`):**
  - **Full Month Matrix:** A classic paper wall-calendar view showing days of the month aligned under days of the week, allowing you to easily look up what date falls on a Friday two weeks from now or what day the 26th is.
  - **High-Contrast Today Inversion:** Today's date leaps out instantly with a solid black circle/squircle and bold white text.
  - **Scheduled Event Indicators:** Link any Home Assistant `calendar.*` entity to automatically render neat event indicator dots under dates with scheduled events.
  - **Configurable Preferences:** Toggle headers, weekday names (`MON TUE...` vs `M T...`), first day of the week (Monday or Sunday), and optional card border.
- **Calendar & Upcoming Agenda (`calendar_agenda` & Combo Preset):**
  - **Upcoming Events List:** Displays upcoming events with inverted date pills (`TODAY 19:30`, `TOMORROW`, `TUE 20 OCT`), bold event summaries, and location or time subtitles.
  - **Calendar & Agenda Combo Preset:** A ready-made 1-click preset that places the month grid on the left and the upcoming agenda on the right for a complete command center.
- **Weather Conditions & 4-Day Forecast (`weather_forecast`):**
  - **Hero Current Conditions:** Renders large MDI weather condition icons (`mdi:weather-rainy`, `mdi:weather-sunny`, `mdi:weather-partly-cloudy`, etc.), prominent temperature readout, condition description, and compact pill badges for humidity, wind speed, and today's high/low.
  - **Multi-Day Forecast Strip:** Shows day names, crisp weather glyphs, high/low temperatures, and precipitation amount.
  - **Adaptive Geometry:** Automatically renders in split columns in landscape ($w \ge 480\text{px}$) and seamlessly transitions into stacked rows in portrait orientation ($416\times 792$) or compact widgets.
- **Live Overhead Aircraft Tracker (`flight_tracker`):**
  - **Live Airspace ADS-B Radar:** Tracks commercial and private aircraft flying overhead within a configurable radius (e.g. 35 km) around your home using OpenSky Network data.
  - **Flight Information:** Displays large callsign (e.g. `BAW71LK`, `THY41Y`), airline/country of origin, distance and compass direction (`8.4 KM SW`), altitude (in feet and meters with climb/descent arrows `↑`/`↓`/`→`), ground speed (kts and km/h), heading, and ADS-B ICAO transponder code.
  - **Automatic Airspace Sensors for Home Assistant:** Automatically publishes `sensor.overhead_aircraft_count` and `sensor.closest_aircraft` to Home Assistant.
  - **Automatic Dynamic Screen Surfacing:** Pair with page tier **Show only when active** (`show_if: "{{ states('sensor.overhead_aircraft_count') | int(0) > 0 }}"`) so the flight radar page automatically joins rotation only when an aircraft enters your local airspace, and recedes when the sky is clear.
- **Quick-Add Palette & Preset Library:**
  - Added dedicated one-click buttons for Month View, Agenda, Weather, and Flights in the editor's Add Element palette.
  - Added 4 ready-to-use page presets with custom vector icons in the Presets library.

## 0.8.8
- **Apple-Grade Header & Toolbar Redesign:** Restored a clean, spacious, and uncluttered layout to the top navigation bar.
  - **Grouped Toolbars:** Grouped 17 sprawling individual controls into 4 logical zones: *Brand*, *Page Navigation*, *Canvas Tools*, and *Status & Output Actions*.
  - **Page Actions Menu (`•••`):** Replaced repetitive page buttons with a compact popover menu containing *Duplicate Page*, *Rename Page*, and *Delete Page*.
  - **Settings Menu (`⚙️`):** Secondary administrative options (*Panel Setup & Firmware*, *Data Sources*, and *Dark/Light Theme*) now tuck neatly into an unobtrusive settings popover.
  - **Clear Primary Call to Action:** Replaced ambiguous double-save buttons with a single high-contrast **Push to Panel** action that automatically saves and renders in one click.
- **Hardware Page Rotation Timing (`X-Rotate-Seconds`):**
  - **Cycle Interval Selector:** Added an explicit **`Cycle interval`** dropdown (`15s`, `30s`, `45s`, `1 min`, `2 min`, `5 min`, or `Manual`) right inside the **Active Rotation** strip.
  - **Dynamic HTTP Timing Headers:** The server now emits `X-Next-Refresh-Seconds`, `X-Rotate-Seconds`, and `X-Page-Count` response headers on every `/frames.png` and `/frame.png` fetch, allowing hardware to dynamically adjust its cycle cadence and deep-sleep timers without requiring firmware reflashes.

## 0.8.7
- **Dynamic Multi-Row Grid Scaling (2×2, 2×3, 2×4…):** Dynamic Grid is no longer restricted to 4 spots or squished into a single crowded row when monitoring 5+ devices.
  - **Balanced 2D Matrices:** When monitoring 5 or 6 items, the display automatically arranges into an elegant 2×3 grid in landscape (or 3×2 in portrait). When monitoring 7 or 8 items, it flows into a balanced 2×4 grid.
  - **Dynamic Last-Row Balancing:** When odd numbers of items are active (e.g. 5 active zones), the trailing row automatically stretches and balances its cards evenly across the screen width rather than leaving awkward empty holes.
  - **Single Row/Stack Option:** Users can switch between `Balanced Grid` and `Single Row / Stack` via the new `layout` selector in the inspector.
- **Large Icons & "Icons Only" Mode:**
  - **Clean "Icons Only" View:** Added a `show` mode selector (`Icon + Name + Secondary Tag`, `Icon + Name Only`, or `Icons Only`). In `Icons Only` mode, cards suppress all text and display huge, crisp glyphs centered inside Apple squircle cards with high-contrast active state badges.
  - **Manual Icon Sizing:** Added an `icon size` selector (`Auto`, `Medium (48px)`, `Large (64px)`, `Huge (80px)`) giving users direct control over glyph presence across their layout.
  - **Per-Spot Text Suppression:** Individual spots can now have their text hidden independently via a `Hide text` checkbox, enabling hybrid screens where primary spots have names while secondary spots show minimalist icons.
- **Dynamic State-Based & Off Icons:**
  - **Visual Off / Inactive Icon Picker:** Every spot now provides a dedicated `off icon` field and visual picker alongside the active icon.
  - **Smart Automatic State Fallbacks:** When entities transition to off or idle states, common icons automatically transform (e.g., `mdi:lightbulb` $\to$ `mdi:lightbulb-off`, `mdi:radiator` $\to$ `mdi:radiator-disabled`, `mdi:lock` $\to$ `mdi:lock-open`, `mdi:power` $\to$ `mdi:power-off`).
  - **Multi-State Support:** Supports custom state mappings (e.g., heating, cooling, idle, off) displaying corresponding state badges (`HEAT`, `IDLE`, `OFF`) and matching icons.

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
