# Status

The one place the project's state lives. The coordinator updates it after
every release and every finished piece of work. Last updated 20 Oct 2026.
Where we're going and why: [ROADMAP.md](ROADMAP.md).

## Released

Every release is tagged `v<version>` on GitHub. Older ones: see
[the changelog](../addon/CHANGELOG.md).

| Version | Date | What |
|---|---|---|
| 0.19.0 | 21 Oct | Race pages read each series' own calendar first (Formula E shows season 13) and say so between seasons; Scores says when a busy day won't fit an always-on panel; next year's racing calendar missing isn't a failure. Add-on only. |
| 0.18.0 | 21 Oct | The panel's clock is right within seconds (draws just after each minute, the panel fetches right after; sleeping devices wake just after a minute); icons from your own Home Assistant, custom sets included; condition suggestions from the add-on's one list. Firmware change. |
| 0.17.0 | 21 Oct | Any icon can change with a sensor (an icon and a look per state); From switches between any choices; no inspector switcher cuts off a choice. Add-on only. |
| 0.16.0 | 21 Oct | The editor shows what isn't sent yet, per page, with undo for each change; Duplicate and Delete on every page tile, larger strip sizes; a "changed in the last N minutes" condition for pages and alerts. Add-on only. |
| 0.15.0 | 21 Oct | New page on shelves with new presets (sunrise and sunset, energy, Now playing, On TV, your own weather station, world clock, Countdown and Bin day without a calendar, to-do lists); alerts that end on a condition; "device" everywhere; zoom; 12/24-hour time; a sleeping device shows the date for a clock; the framework review's 14 fixes; the Wi-Fi network name. Firmware change. |
| 0.14.0 | 21 Oct | The screen bar under the canvas, power first when adding a screen, rename in place, clearer refusals, Safari Fit; the integration sets itself up, Send to ESPHome, editable hotspot password; quiet-hours wake from Home Assistant fixed. Firmware change. |
| 0.13.0 | 20 Oct | Update every and Rotate every replace Low Power Mode; no flash after a wake (untried); the 4.2" and 2.9" build, the 7.5" and 10.2" aren't offered; sleep survives the add-on being down; audits #9 and #14; the classic editor removed. Firmware change. |
| 0.12.0 | 20 Oct | Low Power Mode for CrowPanels (untried on a real panel), TRMNL screens (untried on one), screens drawn ahead, footer and editor fixes, and the no-own-Wi-Fi compile fix. Firmware change. |
| 0.11.0 | 20 Oct | Several screens, away from home, Wi-Fi setup from a phone, a footer that fits every size, group styles. Firmware change. |
| 0.10.3 | 20 Oct | "Space evenly" spaces around the panel, not between left edges. |
| 0.10.2 | 20 Oct | A stepped-up unit can be left off after the number. |
| 0.10.1 | 19 Oct | Audit fixes: no secrets in the log, slow services hold nothing up, a problem sensor per service, 2 MB of pages. Firmware change. |
| 0.10.0 | 19 Oct | The redesigned editor (canvas and page strip, drafts, Send to panel). |

## In flight

| Work | Where | State |
|---|---|---|
| E-paper's own icon folder and prefix, and Iconify downloads of its own, so it stops depending on the Custom Icons integration (whose v1.0.2 "Download Iconify icons" breaks aiohttp for all of Home Assistant; upstream abandoned). Existing local: and Iconify references keep working; the Custom Icons path stays off as the way back (session "epaper-own-icons", started by the Eufy session at the user's request, 22 Oct) | branch `own-icons` | Done 22 Oct: 3 commits, add-on only; combined in `release-next` |
| Home Assistant's notifications (a widget, a page that shows only while there are any) and a badge counting updates waiting (session "ha-notifications") | branch `ha-notifications` from `release-next` | 6 commits, 914 tests pass; back for one change: no count entities in Home Assistant by default (on demand only), and a legible minimum badge size |
| A battery state preset: several batteries, a threshold each or for the group, shown only while below (charge it) or above (charged), page and alert (session "presets-015", from the user's Quick Settings pane) | branch `battery-preset` from `release-next` | Asked 22 Oct; designs with the user first |
| "Also notify my phone…" for alerts and when-pages: one Home Assistant entity created only when asked, withdrawn when no longer needed, plus a shipped notify blueprint (session "notify-blueprint") | branch `notify-blueprint` from `release-next` | Started 22 Oct; designs with the user first |
| Bin day's long "Close to the day" menu becomes two plain choices, "Bin day ends" and "Says" (session "icon-follows", asked by the user directly) | branch `close-to-wording` | Done 22 Oct; combined in `release-next` |

The next release (0.20.0) is put together in `release-next`: 883 tests pass, no
firmware change. Held by the user to add more (22 Oct).

Until it ships: keep Custom Icons installed, and don't press its "Download
Iconify icons" button.

Merged into local main, not pushed, for the next release
(user, 22 Oct): every inspector row moves its control under its label when they
don't fit side by side (the Countdown's squeezed "Close to the day").

Worker notes are in the notes folders (`break-it-0.12.0.md`,
`timers-addon.md`, `firmware-013.md`, `fixes-0131.md`, `editor-polish.md`,
`alerts-todo.md` in the first coordinator's; `widgets-015.md`,
`presets-015.md`, `framework-review.md`, `checklist-0.15.0.md`,
`unsent-changes.md`, `icon-follows.md`, `ha-icons.md`, `clock-align.md`, `racing-calendars.md` in this one's).
Merged worktrees kept until the user OKs removing them: `release-next`,
`presets-015`, `widgets-015`, `editor-zoom`, `unsent-changes`,
`changed-condition`, `icon-follows`, `ha-icons`, `clock-align`, `scores-fit`,
`racing-calendars`.

## Framework review

Last review: v0.12.0 to e8e65c2 (21 Oct); all 14 findings fixed in 0.15.0.
Next one when a good amount of work has piled up since v0.15.0.

## Backlog, most important first

1. **0.15.0 and 0.16.0 by hand**: the checklists (`checklist-0.15.0.md`, and the
   0.16.0 steps in the coordinator's reply of 21 Oct); almost all of
   it is tested by code, little has met the real Home Assistant or an eye.
2. **The world clock on the 4.2"** sits in a band a third of the height
   (Fit scales by width); a full-height box would read larger.
3. **Sleeping on the real 5.79" (since 0.13).** Always on first (nothing should change), then
   sleeping: sleep current through the USB meter (an upper bound), the
   change after a wake without a flash, a full refresh every 8th change,
   buttons waking it, a power cut. Steps in `firmware-013.md`. Way back if it
   misbehaves: `firmware_gen.KEEP_DISPLAY_ASLEEP = False` and a release.
   First observation (20 Oct): always on, through Home Assistant's address,
   on an Anker power bank for 5+ hours with no visible drop (its time-left
   readout isn't reliable at this draw). Overnight 20–21 Oct: no outage in
   12+ hours, battery still at 100%. Sub-second drops of Home Assistant's
   connection at 00:00:20 and 06:00:22, as quiet hours started and ended;
   harmless, watch whether they grow.
   After 24 hours (21 Oct): still 100% on the Anker. Its app shows ~0.5 W for
   1–2 s each minute (the fetch and redraw) and nothing it can measure in
   between (the bank's floor is roughly 0.1 W; an ESP32 idling on Wi-Fi is
   ~0.05–0.15 W). Estimate: ~1.5–3.5 Wh/day, so weeks, not months, always on;
   the USB meter or the days from 99% to 90% will tell. The bank stays on at
   that draw thanks to its trickle-charge mode; many banks switch off.
4. **The editor's new parts by eye**, in Safari and inside Home Assistant:
   the screen bar, Add a screen with power first, rename in place, and Fit
   in Safari (reasoned from screenshots, not reproduced).
5. **The 5.79" away from home:** fetching over HTTPS through Home
   Assistant's address and a Cloudflare tunnel works (20 Oct, once the
   integration's entry existed). Still untried: a second Wi-Fi network, and
   "Through your own address".
6. **Setup from the browser** (next month, large, firmware): a design pass
   with the user first on how the panel keeps its Home Assistant actions and
   entities without a per-panel key (ROADMAP, open question).
7. **The rest of next month** (ROADMAP): the screen's words in Home
   Assistant's language (which languages first is open), share a page, to-do
   lists, a "how it went" report, TRMNL-compatible screens.

The New page presets plan shipped in 0.15.0.
9. **The add-on's icon set is older than Home Assistant's**: `mdi:cat-outline`
   (Home Assistant's icon for "Outdoor Cat") isn't in it, so such icons are
   left out. Fix: bundle the same Material Design Icons version Home
   Assistant uses, and keep it in step.
10. **One more editor copy of a server table**: the page conditions' value
   suggestions (`KNOWN_STATES` in `inspector.js`); read the catalog instead.

**ESPHome 2026.10.0 (checked 21 Oct):** our firmware builds with it, 5.79" and
2.9", no new warnings. It switches off TLS a device doesn't need, but ours
keeps HTTPS (client only; ECDHE kept; plain-RSA key exchange and session
tickets dropped), so tunnels like Cloudflare and Home Assistant Cloud still
work; a very old proxy offering only RSA key exchange wouldn't. Release checks
use 2026.10.0 from 21 Oct (`.esphome-venv`; the way back is
`pip install esphome==2026.9.1` there); every offered size passes its
`esphome config` test with it.
`.esphome-venv` is a link to `~/.local/share/epaper-panel/esphome-venv`
(21 Oct): ~/Documents syncs with iCloud Drive, which made 7,469 "file 2"
duplicates inside the old folder after an in-place upgrade and broke a
compile. Keep tool folders and builds outside ~/Documents. Worth a look: devices that dial Home
Assistant themselves (#18919, could let a panel away from home keep its
Home Assistant link and be woken), the device onboarding wizard (#19966, the
browser setup's open question), suspend_loop / loop_interval (#18136, power),
and ESPHome's own epaper_spi driver (could replace the unlicensed ESPBoards
driver where it supports our controllers).

**Waiting on hardware:** a TRMNL (pairing, pictures, HTTPS, battery); a
second CrowPanel side by side; a 4.2" or 2.9" CrowPanel (they build, untried;
the 4.2"'s UC8276 revision isn't supported); a battery reading on a CrowPanel
(needs a resistor divider soldered on).

The editor was checked by eye in Home Assistant on 19 Oct; the 0.13 power
settings and 0.14 screen bar were first seen by the user on 21 Oct.

## Decisions

- **The add-on never sends notifications itself** (22 Oct). Home Assistant stays
  the one place for automations: an alert can get a Home Assistant entity, made
  only on demand, and a shipped blueprint does the notifying.
- **MQTT is the only way the add-on creates entities.** Never `POST
  /api/states`: writing both made every sensor exist twice in 0.8.x.
- **The server owns overlay geometry.** The frame file carries footer
  positions (`theme.footer_plan()`); the firmware never hard-codes them.
- **The frame token switches on when the panel first uses it**, so a
  reinstall never leaves the panel blank. Actions always need a key.
- **Over-the-air updates are secured by the API key** (ESPHome's encryption
  key), with no separate password.
- **Only an answer from the add-on puts a panel to sleep.** One firmware for
  both modes.
- **Two timers per screen, "Update every" and "Rotate every"** (20 Oct,
  shipped in 0.13.0). They replace the Low Power Mode switch, the wake interval
  and the panel's own refresh interval. Update every 1 minute = always on
  (rotation in seconds, instant buttons, alerts at once). 2 minutes or more =
  it sleeps between updates, and longer is lower power. Asleep, Rotate every
  is a multiple of Update every: each wake refreshes the page, every Nth wake
  moves on. Replaces "the panel's own refresh interval is the one source of
  truth" and, for CrowPanels, "how a screen is powered is never assumed"
  (AGENTS.md changes when it's built).
  Defaults: always on. New screens start at 1 minute and on upgrade a panel
  with Low Power Mode off goes to 1 minute; first-time users must see plainly
  that there's a choice to make (how: the user decides on a design).
- **Sleeping panels avoid the full flash TRMNL's way** (20 Oct, shipped in
  0.13.0, untried):
  the display stays powered in its memory-keeping sleep, the first
  change after a wake is a partial refresh, a full one every 8th change and
  a fast full one at intervals of 30 minutes or more. Needs the real 5.79" to
  confirm and measure. The always-on panel's ghost clearing stays as it is.
  Done with small hooks on the pinned ESPBoards display driver: it has no
  license, so no copy or fork.
- Only alerts, quiet hours and people wake a panel early.
- **Alerts show even over a panel put to sleep by hand** (the user's call, 0.10.1); no extra note in the editor (20 Oct).
- **A Home Assistant restart blanks values on purpose** (audit #4): blank
  tells you something is wrong.
- **One coordinator** merges, versions, tags and pushes, only after the user says
  yes to that release (20 Oct).
