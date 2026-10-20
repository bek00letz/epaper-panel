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
| What breaks 0.12.0 (session "break-it") | branch `break-it`, worktree `~/Documents/HA/epaper-worktrees/break-it` | Started 20 Oct; findings go to the coordinator |
| Feature roadmap (session "roadmap") | no code; a draft for `docs/ROADMAP.md` | Started 20 Oct, with the user |

`low-power-mode` is merged and kept until the user OKs deleting it.

## Backlog, most important first

1. **Low Power Mode on the real 5.79" panel:** sleep current (a month or a
   year on 5,000 mAh), buttons waking it, first-press delay, and the full
   flash on every wake (avoiding it means keeping the display powered).
2. **The 5.79" away from home** (built in 0.11.0, never tried): fetching
   over HTTPS through the tunnel, and joining a second Wi-Fi network.
3. **Audit #9, still open:** with no Reaching home set, a fresh Panel setup
   takes its address from the browser. Opened through a tunnel, the panel is
   told to fetch from the tunnel's name over plain HTTP. Fix: default to
   Home Assistant's own home address and ignore the browser's.
4. **Audit #14, still open:** the firmware doesn't check the footer
   positions in a frame file against the screen. Memory-safe, but a forged
   or broken file can freeze the panel for seconds. Fix: reject positions
   outside the screen when reading the file; keep the fuzzer as a test.
5. **Remove the classic editor** (`?classic=1`, decided 20 Oct): it predates
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
  both modes; Low Power Mode is a setting of each screen, never a fact about
  a kind of device.
- **The user's refresh interval is the contract.** Only alerts, quiet hours and
  people wake a panel early.
- **Alerts show even over a panel put to sleep by hand** (the user's call, 0.10.1); no extra note in the editor (20 Oct).
- **A Home Assistant restart blanks values on purpose** (audit #4): blank
  tells you something is wrong.
- **One coordinator** merges, versions, tags and pushes, only after the user says
  yes to that release (20 Oct).
