"""The Kindle client (client/kindle/): its shell logic, run here against the real add-on.

client/kindle/root/usr/local/epaper-panel/epaper-panel.sh is the program a
Kindle runs. These tests run that same file with this computer's sh, talking to
the add-on's own device port (a test server), with the Kindle's tools replaced
by fakes that write down what they were asked: eips (the screen), lipc-get-prop
and lipc-set-prop (Wi-Fi, power), gasgauge-info (battery), iwconfig (signal),
and the framework (the Kindle's own reader). Its files under /sys, /proc and
/etc are a folder of their own (EPP_SYS). What was measured on a real Kindle 4
(key codes, the clock alarm, the framebuffer) is in client/kindle/README.md.

Also: the install package is what the sources build, signed with the jailbreak's
key, for the Kindle 4; and the script stays inside what BusyBox 1.7's ash runs.
"""
import asyncio
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import unittest
import zlib
from pathlib import Path

import support
import devices
import frames
from test_kindle import KINDLE_MAC, KindleBase

ROOT = support.APP.parents[1]
CLIENT = ROOT / "client" / "kindle"
SCRIPT = CLIENT / "root" / "usr" / "local" / "epaper-panel" / "epaper-panel.sh"
sys.path.insert(0, str(CLIENT))
import build  # noqa: E402

FAKES = {
    # Each fake writes its name and arguments, one line, to $CALLS.
    "eips": 'echo "eips $*" >> "$CALLS"',
    "lipc-set-prop": 'echo "lipc-set-prop $*" >> "$CALLS"',
    "lipc-get-prop": '''case "$2" in
  macAddress) echo "${FAKE_MAC:-e0:cb:1d:c1:b7:b6}" ;;
  cmState) echo "${FAKE_WIFI:-CONNECTED}" ;;
  *) echo "" ;;
esac''',
    "gasgauge-info": '[ "$1" = -v ] && echo "4170 mV" || echo "97%"',
    "iwconfig": 'echo "wlan0     IEEE 802.11bg  ESSID:\\"home\\"  Link Quality=80/100  Signal level=-58 dBm"',
}


def png(width, height, mode="L") -> bytes:
    """A small valid PNG of that size (for a fake server)."""
    raw = b"".join(b"\x00" + b"\xff" * width for _ in range(height))
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


class Kindle:
    """A pretend Kindle on this computer: its folders, its fake tools, and a way to run the client."""

    def __init__(self):
        self.dir = Path(tempfile.mkdtemp(prefix="kindle-"))
        self.state, self.us, self.sys, self.bin = (self.dir / n for n in ("state", "us", "sys", "bin"))
        for d in (self.state, self.us, self.bin):
            d.mkdir()
        for rel, text in {"proc/usid": "B00E151021750DLR\n",
                          "etc/prettyversion.txt": "Kindle 4.1.1 (1813030025)\n",
                          "sys/class/graphics/fb0/virtual_size": "600,800\n",
                          "sys/devices/platform/mxc_rtc.0/wakeup_enable": "",
                          "sys/power/state": "",
                          "etc/init.d/framework": '#!/bin/sh\necho "framework $1" >> "$CALLS"\n'}.items():
            p = self.sys / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
        (self.sys / "etc/init.d/framework").chmod(0o755)
        (self.us / "DONT_HALT_ON_REPAIR").write_text("")
        for name, body in FAKES.items():
            self.fake(name, body)
        self.calls = self.dir / "calls"
        self.calls.write_text("")

    def fake(self, name, body):
        p = self.bin / name
        p.write_text("#!/bin/sh\n" + body + "\n")
        p.chmod(0o755)

    def settings(self, server):
        (self.us / "epaper-panel.txt").write_text(f"# test\r\nserver = {server}/\r\n")

    def env(self, **extra):
        return {**os.environ, "PATH": f"{self.bin}:{os.environ['PATH']}", "CALLS": str(self.calls),
                "EPP_STATE": str(self.state), "EPP_USERSTORE": str(self.us), "EPP_SYS": str(self.sys),
                "EPP_BOOT_SETTLE": "0", **extra}

    def shell(self, code: str, **env) -> subprocess.CompletedProcess:
        """Run sh code with the client's functions loaded (synchronously: for what talks to no server)."""
        return subprocess.run(["sh", "-c", f'. "{SCRIPT}" source; {code}'], env=self.env(**env),
                              capture_output=True, text=True, timeout=60)

    async def ashell(self, code: str, **env) -> tuple[int, str]:
        """The same, while this test's add-on keeps answering."""
        proc = await asyncio.create_subprocess_exec("sh", "-c", f'. "{SCRIPT}" source; {code}', env=self.env(**env),
                                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        out, _ = await asyncio.wait_for(proc.communicate(), 60)
        return proc.returncode, out.decode()

    async def wake(self, source="timer") -> tuple[int, dict]:
        """One wake_once; returns its status and what it left: NEXT, FAILED."""
        rc, out = await self.ashell(f'SOURCE={source}; wake_once; r=$?; echo "NEXT=$NEXT"; echo "FAILED=$FAILED"; exit $r')
        said = dict(line.split("=", 1) for line in out.splitlines() if re.match(r"^(NEXT|FAILED)=", line))
        return rc, said

    def get(self, name) -> str:
        p = self.state / name
        return p.read_text() if p.exists() else ""

    def took_calls(self) -> list[str]:
        lines = self.calls.read_text().splitlines()
        self.calls.write_text("")
        return lines

    def screen_text(self, calls) -> str:
        """The words it put on screen (eips <col> <row> <text>)."""
        return " ".join(c.split(" ", 3)[3].strip() for c in calls if re.match(r"^eips \d+ \d+ ", c))

    def drew(self, calls) -> list[str]:
        return [c for c in calls if c.startswith("eips -f -g ")]

    def close(self):
        shutil.rmtree(self.dir, ignore_errors=True)


class KindleClientBase(KindleBase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.kindle = Kindle()
        self.server = str(self.lan.make_url("")).rstrip("/")
        self.kindle.settings(self.server)

    async def asyncTearDown(self):
        self.kindle.close()
        await super().asyncTearDown()

    async def paired(self, **extra):
        """A Kindle added in the editor and paired by the client's first wake."""
        dev = await self.add_kindle(**extra)
        await self.ed.post(f"/api/devices/{dev['id']}/pair")
        await frames.refresh_frames(None)
        rc, said = await self.kindle.wake("powercycle")
        self.assertEqual(rc, 0, said)
        return dev


class TestPairingAndAWake(KindleClientBase):
    async def test_it_pairs_in_the_window_and_draws_its_page(self):
        dev = await self.paired()
        calls = self.kindle.took_calls()
        self.assertEqual((devices.get(dev["id"])["setup"] or {}).get("mac"), KINDLE_MAC, "its Wi-Fi MAC, upper case")
        self.assertTrue(self.kindle.get("key"))
        self.assertIn("Paired with e-Paper", self.kindle.screen_text(calls))
        self.assertEqual(self.kindle.drew(calls), [f"eips -f -g {self.kindle.state}/last.png"])
        st = devices.state(dev["id"])
        self.assertEqual((st["model"], st["battery_v"], st["rssi"]), ("Kindle 4", 4.17, -58))
        self.assertTrue(st["firmware"].startswith("1.0.0 / Kindle 4.1.1"))
        self.assertIn("lipc-set-prop com.lab126.cmd wirelessEnable 1", calls)
        self.assertEqual(calls.count("lipc-set-prop com.lab126.cmd wirelessEnable 0"), 1, "Wi-Fi off again")
        self.assertEqual(self.kindle.get("failures"), "0")
        self.assertGreaterEqual(int(self.kindle.get("refresh")), 60)

    async def test_nothing_new_means_no_download_and_no_flash(self):
        await self.paired()
        self.kindle.took_calls()
        name = self.kindle.get("last_name")
        rc, said = await self.kindle.wake("timer")
        self.assertEqual(rc, 0, said)
        self.assertEqual(self.kindle.get("last_name"), name)
        self.assertEqual(self.kindle.drew(self.kindle.took_calls()), [])

    async def test_a_press_goes_to_the_next_page(self):
        await self.paired(pages="copy")
        first = self.kindle.get("last_name")
        rc, _ = await self.kindle.wake("button")
        self.assertEqual(rc, 0)
        self.assertNotEqual(self.kindle.get("last_name"), first)

    async def test_its_key_replaced_means_pairing_again(self):
        dev = await self.paired()
        devices.rekey(dev["id"])
        self.kindle.took_calls()
        rc, said = await self.kindle.wake()
        self.assertEqual(rc, 1)
        self.assertEqual(self.kindle.get("key"), "")
        self.assertIn("isn't paired any more", said["FAILED"])


class TestWhenThingsGoWrong(KindleClientBase):
    async def test_outside_the_window_it_says_what_to_do_and_backs_off(self):
        await self.add_kindle()
        waits = []
        for _ in range(7):
            rc, said = await self.kindle.wake()
            self.assertEqual(rc, 1)
            waits.append(int(said["NEXT"]))
        self.assertEqual(waits, [60, 120, 300, 600, 1800, 1800, 1800], "never a tight loop, never endless retries")
        words = self.kindle.screen_text(self.kindle.took_calls())
        self.assertIn("add this screen as a device", words)
        self.assertIn("Trying again in 30 minutes.", words)
        self.assertEqual(self.kindle.get("key"), "")

    async def test_home_assistant_unreachable_keeps_the_page_and_says_so(self):
        await self.paired()
        page = (self.kindle.state / "last.png").read_bytes()
        self.kindle.settings("http://127.0.0.1:9")
        self.kindle.took_calls()
        rc, said = await self.kindle.wake()
        calls = self.kindle.took_calls()
        self.assertEqual(rc, 1)
        self.assertEqual(said["NEXT"], "60")
        self.assertEqual(self.kindle.drew(calls), [], "what's on screen stays")
        self.assertNotIn("eips -c", calls, "no blank screen")
        self.assertIn("Can't reach Home Assistant at http://127.0.0.1:9. Trying again in a minute.",
                      self.kindle.screen_text(calls))
        self.assertEqual((self.kindle.state / "last.png").read_bytes(), page)

    async def test_no_wifi(self):
        await self.paired()
        rc, said = await self.kindle.ashell('WIFI_WAIT=2; SOURCE=timer; wake_once; echo "FAILED=$FAILED"', FAKE_WIFI="PENDING")
        self.assertIn("FAILED=No Wi-Fi.", said)
        self.assertIn("wifi: not connected after 2s (state: PENDING)", self.kindle.get("log"))

    async def test_a_bad_picture_is_never_drawn(self):
        await self.paired()
        page = (self.kindle.state / "last.png").read_bytes()
        name = self.kindle.get("last_name")
        self.kindle.took_calls()
        for bad in (b"<html>busy</html>", png(800, 480)):
            # A pretend add-on: a new picture is named, and what arrives isn't one for this screen.
            (self.kindle.dir / "picture").write_bytes(bad)
            self.kindle.fake("curl", f'''for a; do last=$a; done
while [ $# -gt 0 ]; do [ "$1" = -o ] && out=$2; shift; done
case "$last" in
  */api/display) echo '{{"status": 0, "image_url": "{self.server}/api/image/ep-new", "filename": "ep-new", "refresh_rate": 600}}' > "$out" ;;
  *) cat "{self.kindle.dir}/picture" > "$out" ;;
esac
printf 200''')
            rc, said = await self.kindle.wake()
            self.assertEqual(rc, 1)
            self.assertEqual(said["FAILED"], "The new page didn't arrive whole.")
            self.assertEqual(self.kindle.drew(self.kindle.took_calls()), [])
            self.assertEqual((self.kindle.state / "last.png").read_bytes(), page)
            self.assertEqual(self.kindle.get("last_name"), name)

    async def test_its_key_goes_only_to_its_own_server(self):
        await self.paired()
        log = self.kindle.dir / "asked"
        self.kindle.fake("curl", f'''for a; do last=$a; done
echo "$last" >> "{log}"
while [ $# -gt 0 ]; do [ "$1" = -o ] && out=$2; shift; done
echo '{{"status": 0, "image_url": "http://elsewhere.example/x.png", "filename": "ep-x", "refresh_rate": 600}}' > "$out"
printf 200''')
        rc, said = await self.kindle.wake()
        self.assertEqual(rc, 1)
        self.assertIn("isn't this Home Assistant's", said["FAILED"])
        self.assertNotIn("elsewhere.example", log.read_text())

    async def test_an_error_from_home_assistant(self):
        await self.paired()
        self.kindle.fake("curl", 'while [ $# -gt 0 ]; do [ "$1" = -o ] && out=$2; shift; done\necho oops > "$out"\nprintf 503')
        rc, said = await self.kindle.wake()
        self.assertEqual((rc, said["FAILED"]), (1, "Home Assistant answered with an error (HTTP 503)."))


class TestSetUp(unittest.TestCase):
    def setUp(self):
        self.kindle = Kindle()

    def tearDown(self):
        self.kindle.close()

    def test_not_set_up_it_stays_a_kindle(self):
        r = self.kindle.shell("boot; echo done")
        self.assertIn("done", r.stdout)
        self.assertEqual(self.kindle.took_calls(), [], "the screen and the framework are left alone")
        self.assertIn("so the Kindle stays a Kindle", self.kindle.get("log"))

    def test_an_empty_address_is_not_set_up(self):
        (self.kindle.us / "epaper-panel.txt").write_text("server =\n")
        self.assertNotEqual(self.kindle.shell("read_settings").returncode, 0)

    def test_the_address_is_read_and_kept(self):
        self.kindle.settings("http://192.168.1.20:8099")
        r = self.kindle.shell('read_settings && echo "[$SERVER]"')
        self.assertEqual(r.stdout.strip(), "[http://192.168.1.20:8099]", "no carriage return, no trailing slash")
        (self.kindle.us / "epaper-panel.txt").unlink()       # the drive on a computer: the copy still knows
        self.assertEqual(self.kindle.shell('read_settings && echo "[$SERVER]"').stdout.strip(), "[http://192.168.1.20:8099]")

    def test_an_address_it_cant_use_is_said_plainly_and_nothing_is_fetched(self):
        for server, says in (("https://ha.example.com", "can't use https"), ("homeassistant.local:8099", "should start with http://"),
                             ("http://192.168.1.20:8099/api", "isn't one this Kindle can use")):
            r = self.kindle.shell(f'server_problem "{server}"')
            self.assertIn(says, r.stdout, server)
        self.kindle.settings("https://ha.example.com")
        self.kindle.fake("curl", 'echo "curl $*" >> "$CALLS"; printf 000')
        self.kindle.shell("SOURCE=timer; wake_once")
        calls = self.kindle.took_calls()
        self.assertFalse([c for c in calls if c.startswith("curl")])
        self.assertIn("can't use https", self.kindle.screen_text(calls))


class TestKeysAndSleep(unittest.TestCase):
    def setUp(self):
        self.kindle = Kindle()

    def tearDown(self):
        self.kindle.close()

    def wake_after(self, keys: list[tuple[int, int]], deadline=2, awake=0, extra="") -> str:
        lines = "".join(f"echo \"$(( $(now_s) + {dt} )) {code}\" >> \"$EPP_STATE/keys\"; " for dt, code in keys)
        r = self.kindle.shell(f'{extra} {lines} sleep_until $(( $(now_s) + {deadline} )) {awake}; echo "WAKE=$WAKE"')
        return r.stdout.strip().splitlines()[-1]

    def test_a_page_turn_button_or_the_5_way_goes_to_the_next_page(self):
        for code in (104, 109, 191, 193, 194):
            (self.kindle.state / "key_at").unlink(missing_ok=True)      # a press of its own, not a bounce
            self.assertEqual(self.wake_after([(0, code)]), "WAKE=button", code)

    def test_home_gives_the_kindle_back(self):
        self.assertEqual(self.wake_after([(0, 102)]), "WAKE=home")

    def test_other_keys_and_a_bounce_are_ignored(self):
        self.assertEqual(self.wake_after([(0, 139)]), "WAKE=timer", "Menu does nothing")
        self.kindle.shell('state_put key_at "$(now_s)"')
        self.assertEqual(self.wake_after([(0, 104)]), "WAKE=timer", "the same press bouncing")

    def test_the_power_switch_waking_it_early_is_a_press(self):
        self.assertEqual(self.wake_after([], deadline=100, extra="suspend_for() { return 0; };"), "WAKE=button")

    def test_it_stays_awake_after_a_press_then_sleeps(self):
        r = self.kindle.shell('suspend_for() { echo "suspend at $(now_s)"; return 1; }; start=$(now_s); '
                              'sleep_until $(( start + 26 )) $(( start + 2 )) & pid=$!; sleep 4; kill $pid; echo "start $start"')
        out = r.stdout.split()
        start = int(out[out.index("start") + 1])
        first = int(out[out.index("suspend") + 2])
        self.assertGreaterEqual(first - start, 2, "no sleep while it waits for the next press")

    def test_the_clock_alarm_is_set_before_it_suspends(self):
        r = self.kindle.shell("suspend_for 900; echo rc=$?")
        self.assertIn("rc=1", r.stdout, "here nothing suspends, so it says it couldn't (and waits awake)")
        self.assertEqual((self.kindle.sys / "sys/devices/platform/mxc_rtc.0/wakeup_enable").read_text().strip(), "900")
        self.assertEqual((self.kindle.sys / "sys/power/state").read_text().strip(), "mem")

    def test_taking_over_and_handing_back(self):
        self.kindle.shell("take_over; hand_back")
        calls = self.kindle.took_calls()
        self.assertEqual(calls, ["lipc-set-prop com.lab126.powerd preventScreenSaver 1", "framework stop",
                                 "lipc-set-prop com.lab126.powerd preventScreenSaver 0", "framework start"])
        self.assertTrue((self.kindle.state / "handed_back").exists())


class TestSmallParts(unittest.TestCase):
    def setUp(self):
        self.kindle = Kindle()

    def tearDown(self):
        self.kindle.close()

    def out(self, code):
        return self.kindle.shell(code).stdout.strip()

    def test_reading_the_add_ons_answers(self):
        (self.kindle.dir / "a.json").write_text('{"status": 0, "image_url": "http://h:8099/api/image/ep-1", '
                                                '"filename": "ep-1", "refresh_rate": 879, "update_firmware": false, '
                                                '"message": "Say \\"hi\\" \\u00e9", "api_key": ""}')
        got = {k: self.out(f'json_get {k} "{self.kindle.dir}/a.json"') for k in
               ("status", "image_url", "filename", "refresh_rate", "update_firmware", "message", "api_key", "nope")}
        self.assertEqual(got, {"status": "0", "image_url": "http://h:8099/api/image/ep-1", "filename": "ep-1",
                               "refresh_rate": "879", "update_firmware": "false", "message": 'Say "hi" ?',
                               "api_key": "", "nope": ""})

    def test_times_in_words_and_refresh_limits(self):
        self.assertEqual([self.out(f"in_words {s}") for s in (30, 300, 3600, 7200, 200000)],
                         ["in a minute", "in 5 minutes", "in an hour", "in 2 hours", "tomorrow"])
        self.assertEqual([self.out(f'clamp_refresh "{v}"') for v in ("900", "5", "", "abc", "999999")],
                         ["900", "60", "900", "900", "86400"])

    def test_a_picture_must_be_a_png_of_the_screens_size(self):
        for data, fits in ((png(600, 800), True), (png(800, 600), False), (b"GIF89a", False), (b"", False)):
            (self.kindle.dir / "p.png").write_bytes(data)
            self.assertEqual(self.kindle.shell(f'png_fits "{self.kindle.dir}/p.png"').returncode == 0, fits, data[:8])

    def test_what_it_says_about_itself(self):
        self.assertEqual(self.out("kindle_model; kindle_firmware; kindle_size; kindle_battery_volts; echo; kindle_rssi; kindle_mac").splitlines(),
                         ["Kindle 4", "1.0.0 / Kindle 4.1.1", "600 800", "4.17", "-58", "E0:CB:1D:C1:B7:B6"])

    def test_a_note_fits_the_kindles_font(self):
        self.kindle.shell('note "Can\'t reach Home Assistant at http://192.168.100.200:8099. Trying again in 10 minutes."')
        rows = [c for c in self.kindle.took_calls() if c.startswith("eips 0 ")]
        self.assertTrue(rows)
        for c in rows:
            row, text = c.split(" ", 3)[2:]
            self.assertLessEqual(len(text), 50, text)
            self.assertLessEqual(int(row), 39)


class TestThePackage(unittest.TestCase):
    def test_the_packages_the_add_on_serves_are_what_the_sources_build(self):
        self.assertEqual(build.main(["--check"]), 0, "run: python client/kindle/build.py")

    def test_signed_for_the_kindle_4_with_the_jailbreak_key(self):
        key = build.load_key(build.KEY.read_text())
        for name, files in build.PACKAGES.items():
            got = build.read_package((build.OUT / name).read_bytes(), key)
            self.assertEqual(got["devices"], [0x0E, 0x23], name)
            self.assertEqual(got["runs"], [n for n, _, runs in files if runs], name)
            for n, src, _ in files:
                self.assertEqual(got["files"][n], src.read_bytes(), n)

    def test_a_package_that_was_tampered_with_is_refused(self):
        key = build.load_key(build.KEY.read_text())
        data = bytearray((build.OUT / "Update_epaper-panel_install.bin").read_bytes())
        data[-100] ^= 1
        with self.assertRaises(ValueError):
            build.read_package(bytes(data), key)

    def test_the_install_script_copies_what_the_package_holds(self):
        script = (CLIENT / "package" / "install.sh").read_text()
        for n, _, runs in build.INSTALL:
            if not runs:
                self.assertIn(f"cp -f {n} ", script)
        self.assertIn("rc5.d/S99epaper-panel", script)
        self.assertIn("rc5.d/S99epaper-panel", (CLIENT / "package" / "uninstall.sh").read_text())


class TestBusyBoxAsh(unittest.TestCase):
    """The Kindle 4 has BusyBox 1.7.2 ash: what it lacks, or what crashes there, never appears."""

    def scripts(self):
        return [SCRIPT, CLIENT / "root/etc/init.d/epaper-panel", CLIENT / "package/install.sh", CLIENT / "package/uninstall.sh"]

    def test_every_script_parses(self):
        for p in self.scripts():
            self.assertEqual(subprocess.run(["sh", "-n", str(p)]).returncode, 0, p)

    def test_nothing_ash_lacks_or_that_crashes_on_the_kindle(self):
        for p in self.scripts():
            code = "\n".join(line for line in p.read_text().splitlines() if not line.lstrip().startswith("#"))
            for bad, why in ((r"(^|\s)\[\[\s", "bash's [["), (r"\bfunction\s", "bash's function"), (r"\$'", "bash's $'...'"),
                             (r"(^|[;&|]\s*)timeout\s", "BusyBox timeout segfaults on a Kindle 4"),
                             (r"\bevtest\b|\bwaitforkey\b", "they segfault on a Kindle 4"), (r"<<<", "here-strings"),
                             (r"\bod\b\s", "no od on a Kindle 4"), (r"printf\s+'%\*", "printf's * width")):
                self.assertIsNone(re.search(bad, code, re.M), f"{p.name}: {why}")


if __name__ == "__main__":
    unittest.main()
