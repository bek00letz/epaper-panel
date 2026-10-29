# Status

The one place the project's state lives. The coordinator updates it after
every release and every finished piece of work. Last updated 29 Oct 2026.
Where we're going and why: [ROADMAP.md](ROADMAP.md).

## Released

Every release is tagged `v<version>` on GitHub. Older ones: see
[the changelog](../addon/CHANGELOG.md).

| Version | Date | What |
|---|---|---|
| 0.22.1 | 29 Oct | Sleeping panels no longer stack their pages: the first refresh after a wake drives every pixel, still without a flash (every CrowPanel size). **Firmware change**. Seen on the 5.79" (29 Oct, 4–5 rotations asleep): no stacking, only faint ghosting. |
| 0.22.0 | 28 Oct | Share a page as a file (nothing private in it, opens in New page with your own sensors); the screen's words in English, Romanian, Spanish, German and French, per device ("Same as Home Assistant" by default); no key to paste: Home Assistant sets the panel's key, updates keep their own key. **Firmware change**; needs Home Assistant 2026.8. |
| 0.21.2 | 26 Oct | Race pages name their session in the badge ("QUALIFYING · LIVE") for every series, show only that session's order, and move on to the next session's time after the page's Hours after; no made-up tyres; the race sensor says "Race", not "gp". Add-on only. |
| 0.21.1 | 22 Oct | Batteries page fixed (it fetched the power grid since 0.20.2); a battery silent for 12 hours shows as "No answer since…", one line per integration when they drop together; leftover sensors are no batteries; a page's Shows is the one place: its widget's part AND your own condition. Add-on only. |
| 0.21.0 | 22 Oct | Outside services in the editor: the status card lists failing ones; Settings › Services with Try again; another address behind an Advanced switch, checked by the add-on's own reader; racing, scores and flights can be filled by your own data source or a Home Assistant sensor's attributes. Add-on only. |
| 0.20.2 | 22 Oct | Review 2's findings 3-8: Batteries as a rule (battery-low sensors count), units follow their sensor, page gating from widget descriptors, "changed" stored as data, notify groups listed, each kind's shortest sleep (TRMNL fix); a racing calendar in the wrong shape keeps its problem sensor on. Add-on only. |
| 0.20.1 | 22 Oct | Clock alignment reaches panels behind Home Assistant's address; Iconify is its own service; no 24-hour leaks (with a test); a used notify sensor is never withdrawn; absurd SVG strokes refused; a failing icon copy backs off. Add-on only; restart Home Assistant once. |
| 0.20.0 | 22 Oct | Own icons and Iconify sets without Custom Icons; Home Assistant notifications, an Updates page and a count badge (no entities in Home Assistant); a Batteries preset; "Also notify my phone…" via an on-demand entity and a shipped blueprint; Bin day wording; no squeezed inspector rows. Add-on only. |
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
| Nothing in flight | | |

Worker notes are in the notes folders (`break-it-0.12.0.md`,
`timers-addon.md`, `firmware-013.md`, `fixes-0131.md`, `editor-polish.md`,
`alerts-todo.md` in the first coordinator's; `widgets-015.md`,
`presets-015.md`, `framework-review.md`, `checklist-0.15.0.md`,
`unsent-changes.md`, `icon-follows.md`, `ha-icons.md`, `clock-align.md`, `racing-calendars.md` in this one's; `own-icons.md`, `ha-notifications.md`,
`notify-blueprint.md` in the first coordinator's).
No worktrees: the project moved to `~/Developer/HomeAssistant/e-PaperPanel`
on 23 Oct as a fresh clone, and the old, fully merged worktrees were deleted
with the user's OK. New work starts new worktrees.

## Framework review

Last review: e8e65c2 to v0.20.0 (22 Oct; framework-review-2.md in the
coordinator's notes). 8 findings: 1 and 2 go into 0.20.1. For 0.20.2 (the user,
22 Oct; released in 0.20.2): units followed rather than copied (3), page gating from
widget descriptors (4), Batteries as a rule (5; the user chose a rule: every
battery of its kind below the threshold, minus the unticked, binary
battery-low sensors included), "changed" stored structured (6), phones grouped
in YAML (7), a kind's shortest sleep (8).

Last review: v0.12.0 to e8e65c2 (21 Oct); all 14 findings fixed in 0.15.0.
Next one when a good amount of work has piled up since v0.15.0.

## Backlog, most important first

1. **Hands-on checks done** (the user, 26 Oct): the 0.15.0, 0.16.0 and 0.21
   checklists (Settings › Services, Batteries, Shows).
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
   **Result (26 Oct): the Anker was at 4% after about 6 days** always on
   (from 20 Oct). Far worse than the estimate: always on drains a power bank
   in under a week, so sleeping between updates is what a battery needs. The
   USB meter arrived broken; a replacement is on its way, so current
   readings wait. Meanwhile the days a full bank lasts asleep (Update every
   5 minutes or more) can be counted the same way.
   **USB meter working (29 Oct):** an FNIRSI FNAC-28 (its PC port needs a
   USB-A to USB-C cable; C to C never connects), read on the Mac by
   `~/Developer/HomeAssistant/tools/fnirsi-logger` (`./fnirsi-log`; CSV with
   per-second average, min and max current). First 15 s, always on: 5.14 V,
   54 mA average (36 mA floor, 123 mA peaks), 0.28 W, about 6.7 Wh a day,
   which matches the Anker emptying in about 6 days. 10 minutes always on
   (Update every minute): 51.9 mA average, 6.4 Wh a day. Each update is a
   2 s burst at ~100 mA (peaks ~200 mA); between updates it sits at ~50 mA,
   Wi-Fi up with ESPHome's default light power save. Updates are about 2% of
   the energy: the awake idle is the cost, so sleeping is the whole lever.
   **Asleep, 50 minutes (Update every 5 minutes):** 8.0 mA average, 0.04 W,
   about 1.0 Wh a day, 6.5 times less than always on (roughly 5–6 weeks on
   the same Anker, if it stays on at that draw). Asleep it's a flat 6.27 mA;
   each wake is 7–11 s at ~65 mA (~0.16 mAh). The sleep current is about
   three quarters of the energy, so it's the next lever: an ESP32 in deep
   sleep is ~0.02 mA, so most of the 6 mA is the rest of the board (power
   LED, regulator, USB chip, or the display kept powered). The full refresh
   costs ~2 s more (12:27's wake, 11 s), ~0.03 mAh: small.
   **Found on the way:** after a wake, the partial refresh doesn't clear the
   old picture, so pages stack up at full black (the first real try of
   keeping the picture through sleep). **Fixed in 0.22.1** (the controller's
   memory of the picture is reset as the board sleeps; the first refresh after
   a wake now writes it inverted first). Seen on the panel (29 Oct): no
   stacking over 4–5 rotations, faint ghosting only (the every-8th full
   refresh clears it). Its cost, measured (50 min asleep on 0.22.1): none
   that shows, wakes 0.148 mAh median against 0.159 on 0.22.0, 7.93 mA
   average, sleep 6.28 mA, the full refresh at 14:20 (10 s, 0.197 mAh). Next
   lever was the 6.27 mA asleep, and it's the board's own: with the display
   switched off in sleep (`power_begin(-1)`, 29 Oct) it sleeps at 6.21 mA,
   no lights are on, and the build already has ESP-IDF's PSRAM and flash
   leakage workarounds. Most likely the always-on regulator. Settled as the
   CrowPanel's draw (the user, 29 Oct): about 1 Wh a day at 5 minutes, about
   10 days on a 2000 mAh battery, 2 weeks at most whatever the interval.
   Nothing left to gain in firmware; keeping the display powered stays.
4. **The editor's new parts by eye**, in Safari and inside Home Assistant:
   the screen bar, Add a screen with power first, rename in place, and Fit
   in Safari (reasoned from screenshots, not reproduced).
5. **The 5.79" away from home:** fetching over HTTPS through Home
   Assistant's address and a Cloudflare tunnel works (20 Oct, once the
   integration's entry existed). Still untried: a second Wi-Fi network, and
   "Through your own address".
6. **Setup from the browser: parked** (the user, 26 Oct). Researched
   (`docs/design/browser-setup.md`, with the user's answers): the key is
   solved by Home Assistant 2026.8, but owning a whole install line is a lot
   to carry. Instead today's route drops the key paste, and the decision
   waits for the Seeed 7.5" on TRMNL's firmware.
7. **Shipped in 0.22.0:** share a page, the screen's words in five languages,
   no key paste. Found on the way, for later: the days-until " days" suffix
   ("1 days"; Romanian "20 de zile" needs plurals), Scores, Planes and stacked
   Weather spilling out of their box on the 2.9" in every language, accents
   in page names. Still to come: a "how it went" report,
   TRMNL-compatible screens (a Seeed 7.5" reTerminal arrives in days or
   weeks, so they can be tried).

The New page presets plan shipped in 0.15.0.
9. **The shipped fallback icon set is older than Home Assistant's** (7.4.47,
   no `mdi:cat-outline`). Since 0.18.0 the add-on copies Home Assistant's own
   set at start, so this only matters until that copy works or while it
   keeps failing. Refresh `addon/app/icons/mdi.json.gz` the way its README
   says, at a release that touches icons anyway.

Done since the backlog was written: the editor's condition suggestions come
from the add-on (0.18.0, `b14a961`; a test stops an editor copy coming back),
and icons follow Home Assistant's own set (0.18.0, `3d98341`).

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

**Waiting on hardware:** a Seeed 7.5" (TRMNL firmware; on its way, 26 Oct);
a TRMNL (pairing, pictures, HTTPS, battery); a
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
- **Home Assistant sets each panel's encryption key; updates over Wi-Fi need
  a separate update key** (the user, 26 Oct; 0.22). Nobody pastes or sees a
  key. The add-on makes one update key per panel (`setup.ota_key`) and writes
  it under `ota: encryption: key:`, because ESPHome 2026.10 can't require
  encryption with a key set at runtime: without its own key, the panel would
  accept an update from anyone on the network. A panel set up before keeps
  its old key as its update key. No separate password. Replaces "updates are
  secured by the API key" (ROADMAP, Later: drop it when ESPHome can).
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
