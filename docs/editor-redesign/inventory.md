# Editor inventory (v0.9.7)

Everything the editor (`addon/app/web/index.html`) can do today. This is the
regression checklist for the redesign: every line must stay reachable.

How often: **C** constant (every session), **O** occasional (some sessions),
**R** rare (setup, once a month or less).

## Top bar

| | What | How often |
|---|---|---|
| 1 | Pick the page being edited (select, tags `[when]` / `[alert]`) | C |
| 2 | New page from a preset (opens Presets) | O |
| 3 | New blank page (browser prompt for a name) | O |
| 4 | Page menu: duplicate (prompt), rename (prompt), save as preset (2 prompts), delete (undo toast) | O / R |
| 5 | Undo, redo (60 deep) | C |
| 6 | Mounting orientation 0 / 180 / 90 / 270; switching landscape ↔ portrait offers "Reflow elements" | R |
| 7 | Guides: footer zone and padlock corner overlay | O |
| 8 | Quiet hours pill: off / window / active, opens Quiet hours | glance O, click R |
| 9 | Status pill: pages live, orientation, size, "panel update waiting" with the error; opens Full strip | glance C, click O |
| 10 | Settings menu: Panel setup, Quiet hours, Data sources, light / dark | R |
| 11 | Push to panel: save everything, then ask the panel to fetch now | C |

## Above the canvas

| | What | How often |
|---|---|---|
| 12 | Panel model (5 CrowPanel sizes); changes canvas size | R (also in Panel setup) |
| 13 | Resolution and "1-bit" badges | info only |
| 14 | Legibility distance: desk, bedside, sofa, wall, off (remembered) | R |
| 15 | Panel refresh interval slider, 1–60 min, sets the panel's own number entity live | R (also in Panel setup) |
| 16 | Fit / 100% zoom | O |

## Canvas

| | What | How often |
|---|---|---|
| 17 | Honest preview: every change re-renders through `POST /api/preview` (200 ms debounce) | C |
| 18 | Click to select; shift-click to add or remove; click empty space to deselect | C |
| 19 | Drag to move (one or many), snapping to margins, centre, footer line and other elements; Alt skips snapping | C |
| 20 | Resize from the bottom-right handle, with snapping | C |
| 21 | Drop an entity from the list to create a value or text at that point | O |
| 22 | Footer zone and padlock corner overlays (with item 7) | O |
| 23 | Device frame around the canvas (portrait narrows it) | — |

## Keyboard

| | What | How often |
|---|---|---|
| 24 | Cmd/Ctrl+Z, Shift+Cmd/Ctrl+Z | C |
| 25 | Cmd/Ctrl+D duplicate (offset 12 px) | O |
| 26 | Delete / Backspace removes the selection | O |
| 27 | Arrows nudge 1 px, Shift+arrows 10 px (one or many) | O |
| 28 | Escape closes any dialog | O |

## Below the canvas: when a page shows

| | What | How often |
|---|---|---|
| 29 | Tier: always in rotation / show only when active / urgent interruption (alert) | O |
| 30 | Condition: entity + is / is not / > / < / ≥ / ≤ + value, or raw Jinja | O |
| 31 | Alert hold, minutes | R |
| 32 | Condition kept in sync automatically for a device grid or a sports / flight widget with "only show when…" | O |

## Below the canvas: rotation

| | What | How often |
|---|---|---|
| 33 | Rotation order as pills: click opens the page, ‹ › move one step, × removes | O |
| 34 | Conditional pages show live / skipped; alert pages tagged | glance O |
| 35 | Add slot: the current page again (shows it more often) | R |
| 36 | Rotation interval 15 s – 5 min, or buttons only (saves at once) | R |
| 37 | Full strip (opens dialog) | O |

## Right rail

| | What | How often |
|---|---|---|
| 38 | Inspector (see below) | C |
| 39 | Add element: 16 types (value, text, icon, box, divider, gauge bar, sparkline, bar chart, QR, weather, device grid, month, agenda, flights, racing, match). A box goes to the back | O |
| 40 | Entities: filter chips (all, add-on's own, calendar, sensor, binary, climate, lock, person), search, state shown, drag or + to add | O |

## Inspector, any element

| | What | How often |
|---|---|---|
| 41 | Centre horizontally, centre vertically (in the safe area), full width | O |
| 42 | Show only if (raw Jinja) | R |
| 43 | Exact x, y, w, h (collapsed, remembered) | O |
| 44 | Layer up / down one step | O |
| 45 | Duplicate, remove | O |

## Inspector, multi-selection

| | What | How often |
|---|---|---|
| 46 | Align left / centre / right, top / middle / bottom (lines align by stroke centre) | O |
| 47 | Distribute horizontally / vertically (3+) | R |
| 48 | Duplicate all, remove all | O |

## Inspector, per element type

| | What | How often |
|---|---|---|
| 49 | Text / value: kind (text or number), source (entity or Jinja template), entity, show as (state, days until, date, attribute, last changed, last updated), attribute list from Home Assistant, date format (7), before / after text, decimals, if error, replacements ("say it differently") | C |
| 50 | Text / value / icon typography: size, font (Lato, DejaVu, Roboto Mono), weight, align, inverted, pill border, badge radius | C |
| 51 | Legibility chip: rendered px and mm at the chosen distance, verdict, overflow; "not a number" and "that's a list" warnings | C |
| 52 | Icon: visual picker, name field | O |
| 53 | Box: fill (outline, black, 50% screen, white mask), radius, border width | O |
| 54 | Gauge bar: entity, title, style (solid, segmented, vertical), segments, min, max, unit, decimals, show value | R |
| 55 | Sparkline: entity, hours | R |
| 56 | Bar chart: entity, title, hours, bars, min/max labels, border | R |
| 57 | QR: text / URL / entity, or Wi-Fi (network, password, security); caption; border | R |
| 58 | Divider: direction, length, thickness (kept pixel-centred) | O |
| 59 | Device grid: title, header icon, which state counts, layout, labels, icon size, secondary tag, hide page when all off, spots (entity, name, hide name, on icon, off icon; add / remove; name and icon suggested from the entity) | O |
| 60 | Month: calendar entity, first weekday, header, weekdays, highlight today, border | R |
| 61 | Agenda: calendar entity, title, max events, subtitles, border | R |
| 62 | Weather: entity, layout (5), days (3–5), humidity and wind, border | R |
| 63 | Flights: style (card, split, radar), airport code lookup, place label, latitude, longitude, saved places (Home + up to 4: save, forget), radius, only show when overhead, add-on sensor id, sub-units, border | R |
| 64 | Racing: series, entity, leaderboard size, only show around sessions, session or weekend window, hours before / after, sensor id, team names, time zone, border | R |
| 65 | Match: league, team, entity, only show on matchdays, hours before / after, sensor id, time zone, stats, scorers, border | R |
| 66 | Widgets: font scale (slider + 5 presets) | O |
| 67 | Widgets: break apart into plain elements (weather, flights, agenda, match, racing) | R |

## Dialogs

| | What | How often |
|---|---|---|
| 68 | Presets: 15 built-in + your own; pick one → name prompt → new page; delete your own (undo); save current page as preset | O |
| 69 | Quiet hours: on/off, window, presence entity, alerts may wake, sleep screen; publishes `sensor.epaper_quiet_hours` | R |
| 70 | Data sources: Jellyfin, any JSON API, long-term statistic; fields, test, remove, save | R |
| 71 | Panel setup: connection, entity and frame-protection problems, model, host, port, default refresh, device name, mount, Wi-Fi, encryption key (copy, regenerate), `!secret` option, generate YAML, copy / download YAML and secrets, install steps; writes into ESPHome | R |
| 72 | Full strip: the rendered strip, page list, re-render | O |
| 73 | Icon picker: search 7,000 MDI icons, 10 quick categories | O |

## Background behaviour

| | What |
|---|---|
| 74 | Status polled every 15 s |
| 75 | Appearance follows the system until you choose (remembered) |
| 76 | Undo toasts for page delete, duplicate, rename, reflow, preset delete |
| 77 | Reduced motion respected |

## Bugs found while reading (fix along the way)

- **"Save page as preset" is lost on the next save.** The editor stores
  `title`; `sanitize_layouts` keeps a preset only if it has `name`, so every
  saved preset disappears from `layouts.json` (confirmed with a direct call).
- `saveLayouts()` reads `$("esearch")`, which doesn't exist, so the entity
  list is never refreshed after a save (the error is swallowed).
- The light/dark menu item's label is replaced by a bare ☀️ / 🌙 on load.
- The editor's `@font-face` rules load `fonts/*.ttf`, which only the LAN app
  serves; on Ingress they 404, so the font menu can't show the faces.
- **Work is only saved by "Push to panel"**, but six other actions save the
  whole spec as a side effect (quiet hours, rotation interval, saved places,
  presets, Panel setup's model or mount, and simply opening Full strip). No
  unsaved-changes indicator and no warning on close.
- Model, orientation and refresh interval each have two controls in two
  places (canvas toolbar and Panel setup).
- Presets are built with `makeElements("")`, so every new page from a preset
  arrives unbound, though each preset was written to take an entity.

## Checked against 0.10.0

Every item above is reachable in the new editor. Where things went:

| Items | Now |
|---|---|
| 1–4, 29–37 | Page strip (pick, drag to reorder, right-click menu, + for a new page) and the page inspector (name, when it shows, condition, hold, rotation, duplicate, save as preset, delete) |
| 5, 7, 16 | Toolbar (undo, redo) and the canvas bar (guides, layers, fit or actual size) |
| 6, 8–10, 12–15, 69–71 | Settings (panel, install or update, quiet hours, data sources, editor) and Now on the panel at the head of the strip |
| 11 | Send to panel; edits save to a draft as you go |
| 17–28 | Canvas and keyboard, plus copy, cut, paste, paste and match, select all, layer order shortcuts, any-corner resize |
| 38–67 | Inspector; 39–40 moved into Insert (types and sensors in one search, drag a sensor onto the canvas) |
| 68, 72, 73 | New page sheet, See every page (from Now on the panel), icon picker sheet |

Deliberate changes: the resolution and "1-bit" badges and the frame's
maker logo are gone; the rotation's "Manual (buttons only)" choice is gone
(the server always saved it as 30 s); the seven browser prompts are gone.
