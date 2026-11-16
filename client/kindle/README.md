# E-paper panel on a Kindle

A jailbroken Kindle shows your pages from the e-Paper Panel add-on, and sleeps
between updates. To the add-on it's a TRMNL: it speaks TRMNL's "bring your own
server" protocol over plain HTTP to the add-on's device port at home. In the
editor it's **Kindle** under Add new device.

Made for the **Kindle 4** (2011–2012, no touch, no keyboard), on firmware 4.0.0
to 4.1.4. The package is signed for the Kindle 4 only (device codes 0x0E and
0x23).

## Setting one up

1. **Jailbreak it.** MobileRead's [Kindle 4 jailbreak](https://wiki.mobileread.com/wiki/Kindle4NTHacking)
   (kindle-k4-jailbreak, from [its thread](https://www.mobileread.com/forums/showthread.php?t=191158)).
   Follow its README. Keep the Kindle's Wi-Fi off until it's done, so it can't
   update itself first. Success is a book called "You are Jailbroken".
2. In the e-Paper editor: **Add new device › Kindle › Add and pair**. Download
   the two files it gives you: the installer, and `epaper-panel.txt`, which
   has your Home Assistant's address in it.
3. Plug the Kindle into a computer and copy both files to the top level of its
   drive. Eject it, then on the Kindle: **Menu › Settings › Menu › Update Your
   Kindle**.
4. Join your Wi-Fi in the Kindle's settings if it hasn't already. It pairs
   within the editor's ten-minute window and shows your first page.

That's all. Nothing else is needed: not KUAL, not MKK, not USBNetwork.

**Amazon's updates are your call.** On Wi-Fi, Amazon can update a Kindle, and
an update replaces its system: this client and the jailbreak go with it. The
installer leaves the Kindle's network alone on purpose, because blocking
Amazon also stops the Kindle Store, syncing and registration. If you want to
block it, do it on your router, or on the Kindle with a tool from MobileRead
(for example [kindle-block-amazon](https://www.mobileread.com/forums/showthread.php?p=4545829),
made on a Kindle 4). The update servers include `todo-g7g.amazon.com` and
`firs-g7g.amazon.com`.

## Using it

- It wakes on the add-on's schedule (Update every), shows the page, and sleeps.
- **Always on** (Update every › 1 minute, for a Kindle on a charger): it never
  sleeps and keeps Wi-Fi on, pages turn on Rotate every, and the page-turn
  buttons, the 5-way and Home answer at any time. The add-on says so in each
  answer (`"stay_awake": true`).
- **Slide the power switch** for the next page, like a TRMNL's button. For a
  minute after that, the **page-turn buttons** flip pages too. (A sleeping
  Kindle 4 only wakes for its power switch.)
- **Home** gives you the Kindle back, until it next restarts.
- When something's wrong it says so in plain words at the bottom of the page
  that's showing (or on its own screen before it's paired), and tries again
  after 1, 2, 5, 10 and 30 minutes, then every 30 minutes. It never retries
  in a tight loop.
- To change the address, edit `epaper-panel.txt` on its drive.
- **The way back:** `Update_epaper-panel_uninstall.bin` (served by the add-on
  beside the installer), installed the same way, removes it all. Your
  `epaper-panel.txt` is left on the drive.

## What's in here

| | |
|---|---|
| `root/usr/local/epaper-panel/epaper-panel.sh` | The client. POSIX sh for the Kindle's BusyBox 1.7 ash |
| `root/etc/init.d/epaper-panel` | Starts it after the Kindle has started (`/etc/rc5.d/S99epaper-panel`) |
| `package/install.sh`, `uninstall.sh` | What Update Your Kindle runs, as root |
| `build.py` | Builds the signed packages into `addon/app/kindle/`, which the add-on serves. `--check` says whether they're up to date |
| `keys/jailbreak_updater_key.pem` | The jailbreak's package-signing key, as published in the jailbreak's own package. Its public half is what a jailbroken Kindle trusts |

After changing anything here, run `python client/kindle/build.py` and commit
the packages with it. `tests/test_kindle_client.py` fails until you do, and
runs this client on a computer against the real add-on, with fake Kindle
tools.

## The Kindle 4, as measured (16 Nov 2026, firmware 4.1.1)

- Linux 2.6.31, **BusyBox 1.7.2**. Its `timeout` segfaults, and so do `evtest`
  and `waitforkey`. There's no `od` and no `rtcwake`. `curl` 7.21.4 (OpenSSL
  0.9.8, too old for today's HTTPS), `awk`, `hexdump` and `dd` are there.
- **Screen:** 600 × 800, 8-bit grey framebuffer, 91 × 121 mm. `eips -f -g`
  draws an 8-bit grey PNG, and all 16 grey levels show cleanly.
- **Sleep:** write the seconds to `/sys/devices/platform/mxc_rtc.0/wakeup_enable`,
  then `mem` to `/sys/power/state`. It sleeps for real (about a second awake
  per minute asleep), even on a computer's USB, and wakes on time. **Only the
  power switch wakes it early**: the page-turn buttons don't.
- **Never run `powerd_test`**, not even for its help: any argument sends
  "power button held", and powerd goes to Shutdown until a restart.
- **Keys** (`/dev/input/event0` and `event1`, 16-byte `input_event`): page
  turn 104, 109, 191, 193 (104 bounces), Home 102, Menu 139, Back 158,
  Keyboard 29; 5-way left 105, right 106, up 103, down 108, middle 194.
- **Battery:** `gasgauge-info -v` (millivolts), `-c` (percent). **Wi-Fi:**
  `lipc-get-prop com.lab126.wifid macAddress` / `cmState`, and
  `lipc-set-prop com.lab126.cmd wirelessEnable 0|1`.
- **Start-up:** SysV scripts in `/etc/rc5.d`, the framework (the Kindle's own
  reader) at S95. `/` is read-only (`mntroot rw|ro`), `/var/local` is
  writable (the client keeps its key and last page there), and `/mnt/us` is
  the USB drive, gone from the Kindle while a computer has it.
- **Update packages:** SP01 envelope, FC04 package, scrambled tarball; how
  they're made is at the top of `build.py`. Checked against MobileRead's own
  Kindle 4 packages (MKK, USBNetwork): `build.py` reproduces their
  signatures byte for byte.
