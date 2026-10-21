# Status

The one place the project's state lives. The coordinator updates it after
every release and every finished piece of work. Last updated 20 Oct 2026.
Where we're going and why: [ROADMAP.md](ROADMAP.md).

## Released

Every release is tagged `v<version>` on GitHub. Older ones: see
[the changelog](../addon/CHANGELOG.md).

| Version | Date | What |
|---|---|---|
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
| Alerts that release on a condition, and to-do list pages from Home Assistant (session "alerts-todo") | branch `alerts-todo` (6 commits on `release-next`), worktree `~/Documents/HA/epaper-worktrees/alerts-todo` | Done 21 Oct: 7 commits, 415 tests pass, no firmware change. Three to-do row styles, By urgency the default (user's call). Not tried in the real Home Assistant or seen by eye |
| Editor: screen menu (Rename, Remove, Add new device) and zoom (−/+, Fit to 200%, pinch, ⌘+/⌘−/⌘0) (session "editor-polish", asked by the user directly) | branch `editor-zoom`, worktree `~/Documents/HA/epaper-worktrees/editor-zoom` | Done 21 Oct, 370 tests pass, not seen by eye; waiting for a release |

Merged into local main, not pushed, for the next release: a sleeping panel
is woken once when its sleep screen's words change (21 Oct). The editor-zoom
work and the "device everywhere" wording ship with it (user, 21 Oct).
0.14.1 is put together in `release-next` (worktree
`~/Documents/HA/epaper-worktrees/release-next`): 377 tests pass and the
5.79" compiles. It now also shows which Wi-Fi network the panel is on
(Connection, Settings › Device), a firmware change: one panel reinstall.
Held by the user ("not yet", 21 Oct).

Worker notes are in the coordinator's notes folder
(`break-it-0.12.0.md`, `timers-addon.md`, `firmware-013.md`,
`fixes-0131.md`, `editor-polish.md`).

## Backlog, most important first

1. **Three bugs found by the presets mockup (21 Oct).** NASCAR and IndyCar
   show Formula 1 data (`sources/racing.py` fetches only F1 and Formula E);
   the Guest Wi-Fi preset's text runs under its QR code (no wrap,
   `web/app/legacy.js`); New page thumbnails show "--" for every preset that
   needs a sensor (they should draw example values, never your data).
2. **Sleeping on the real 5.79" (since 0.13).** Always on first (nothing should change), then
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
3. **The editor's new parts by eye**, in Safari and inside Home Assistant:
   the screen bar, Add a screen with power first, rename in place, and Fit
   in Safari (reasoned from screenshots, not reproduced).
4. **The 5.79" away from home:** fetching over HTTPS through Home
   Assistant's address and a Cloudflare tunnel works (20 Oct, once the
   integration's entry existed). Still untried: a second Wi-Fi network, and
   "Through your own address".
5. **Setup from the browser** (next month, large, firmware): a design pass
   with the user first on how the panel keeps its Home Assistant actions and
   entities without a per-panel key (ROADMAP, open question).
6. **The rest of next month** (ROADMAP): the screen's words in Home
   Assistant's language (which languages first is open), share a page, to-do
   lists, a "how it went" report, TRMNL-compatible screens.

**Noted for the roadmap (21 Oct, from the roadmap session, not yet decided):**
the New page sheet on shelves (agreed) with new groups, renames and presets
(mockup: claude.ai/artifact/STc9a9gWKX7fgX511pmdE6); JellyHA, now on the
user's Home Assistant, could drive an Episode card and Now playing with no
setup, while the add-on's own Jellyfin source stays for New to watch.

**Waiting on hardware:** a TRMNL (pairing, pictures, HTTPS, battery); a
second CrowPanel side by side; a 4.2" or 2.9" CrowPanel (they build, untried;
the 4.2"'s UC8276 revision isn't supported); a battery reading on a CrowPanel
(needs a resistor divider soldered on).

The editor was checked by eye in Home Assistant on 19 Oct; the 0.13 power
settings and 0.14 screen bar were first seen by the user on 21 Oct.

## Decisions

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
