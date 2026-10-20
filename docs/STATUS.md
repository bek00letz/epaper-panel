# Status

The one place the project's state lives. The coordinator updates it after
every release and every finished piece of work. Last updated 20 Oct 2026.

## Released

Every release is tagged `v<version>` on GitHub. Older ones: see
[the changelog](../addon/CHANGELOG.md).

| Version | Date | What |
|---|---|---|
| 0.12.0 | 20 Oct | Low Power Mode for CrowPanels (untried on a real panel), TRMNL screens (untried on one), screens drawn ahead, footer and editor fixes, and the no-own-Wi-Fi compile fix. Firmware change. |
| 0.11.0 | 20 Oct | Several screens, away from home, Wi-Fi setup from a phone, a footer that fits every size, group styles. Firmware change. |
| 0.10.3 | 20 Oct | "Space evenly" spaces around the panel, not between left edges. |
| 0.10.2 | 20 Oct | A stepped-up unit can be left off after the number. |
| 0.10.1 | 19 Oct | Audit fixes: no secrets in the log, slow services hold nothing up, a problem sensor per service, 2 MB of pages. Firmware change. |
| 0.10.0 | 19 Oct | The redesigned editor (canvas and page strip, drafts, Send to panel). |

## In flight

| Work | Where | State |
|---|---|---|
| What breaks 0.12.0 (session "break-it") | branch `break-it` (5 commits), worktree `~/Documents/HA/epaper-worktrees/break-it` | Done: 5 add-on fixes, each with a test, held for 0.13.0 (user, 20 Oct). Findings in the coordinator's notes (`break-it-0.12.0.md`) |
| Feature roadmap (session "roadmap") | no code; a draft for `docs/ROADMAP.md` | Started 20 Oct, with the user |

`low-power-mode` was merged in 0.12.0 and deleted.

## Backlog, most important first

1. **Firmware for every size but the 5.79" doesn't build** (since 16 Oct,
   found 20 Oct). 4.2": wrong model name. 2.9", 7.5", 10.2": no `spi:` block,
   and a full-refresh call only the CrowPanel driver has. 10.2": no ESPHome
   driver at all. Needs a test that checks every size, and hardware answers.
   Decided 20 Oct: fix the sizes that can be made to compile (marked untried
   on hardware), hide the 10.2" until a driver exists.
2. **Low Power Mode stops sleeping while the add-on is down.** Any answer
   without the sleep header (a 502 during a restart) keeps the panel
   connected until the add-on is back. Firmware fix: only a 200 or 304
   without it means "stay connected".
3. **A blank Wi-Fi name makes firmware ESPHome refuses**, even with the
   panel's own Wi-Fi on. Fix: write a setup-only Wi-Fi block then; with
   neither, the editor says a network is needed. Also check Wi-Fi password
   length.
4. **Smaller, from the same check:** Waveshare sizes stay awake 6 s per wake
   for nothing; around clock changes a sleeping screen wakes an hour off;
   a stalled MQTT broker could slow every render; going back to 0.11.0 with a
   TRMNL breaks its screen list (say so in the changelog).
5. **Update every / Rotate every, and no flash after sleep** (decided 20 Oct,
   see Decisions). Editor, add-on and firmware.
6. **Sleeping on the real 5.79" panel:** sleep current with the display left
   powered, buttons waking it, first-press delay, the partial refresh after
   a wake.
7. **The 5.79" away from home** (built in 0.11.0, never tried): fetching
   over HTTPS through the tunnel, and joining a second Wi-Fi network.
8. **Audit #9, still open:** with no Reaching home set, a fresh Panel setup
   takes its address from the browser. Opened through a tunnel, the panel is
   told to fetch from the tunnel's name over plain HTTP. Fix: default to
   Home Assistant's own home address and ignore the browser's.
9. **Audit #14, still open:** the firmware doesn't check the footer
   positions in a frame file against the screen. Memory-safe, but a forged
   or broken file can freeze the panel for seconds. Fix: reject positions
   outside the screen when reading the file; keep the fuzzer as a test.
10. **Remove the classic editor** (`?classic=1`, decided 20 Oct): it predates
   several screens. The way back is any tag up to v0.11.0.

**Waiting on hardware:** a TRMNL (pairing, pictures, HTTPS, battery); a
second CrowPanel side by side; a battery reading on a CrowPanel (needs a
resistor divider soldered on).

The editor was checked by eye in Home Assistant on 19 Oct.

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
  not built yet). They replace the Low Power Mode switch, the wake interval
  and the panel's own refresh interval. Update every 1 minute = always on
  (rotation in seconds, instant buttons, alerts at once). 2 minutes or more =
  it sleeps between updates, and longer is lower power. Asleep, Rotate every
  is a multiple of Update every: each wake refreshes the page, every Nth wake
  moves on. Replaces "the panel's own refresh interval is the one source of
  truth" and, for CrowPanels, "how a screen is powered is never assumed"
  (AGENTS.md changes when it's built).
- **Sleeping panels avoid the full flash TRMNL's way** (20 Oct, not built
  yet): the display stays powered in its memory-keeping sleep, the first
  change after a wake is a partial refresh, a full one every 8th change and
  a fast full one at intervals of 30 minutes or more. Needs the real 5.79" to
  confirm and measure. The always-on panel's ghost clearing stays as it is.
- Only alerts, quiet hours and people wake a panel early.
- **Alerts show even over a panel put to sleep by hand** (the user's call, 0.10.1); no extra note in the editor (20 Oct).
- **A Home Assistant restart blanks values on purpose** (audit #4): blank
  tells you something is wrong.
- **One coordinator** merges, versions, tags and pushes, only after the user says
  yes to that release (20 Oct).
