"""A Kindle on the add-on's side: a TRMNL in a family of its own, drawn in 16 greys.

The Kindle client (client/kindle/) speaks TRMNL's protocol, so the add-on serves
it with the TRMNL kind's code. What's its own: the "kindle" family (offered as
Kindle in Add new device, its sizes made from its own profile), and its
screen's 16 greys, which are a property of the display (theme.greys), so every
black-and-white screen's pictures stay exactly what they were.
The client itself is tests/test_kindle_client.py.
"""
import io
import unittest
from unittest import mock

from PIL import Image, ImageDraw

import support
import devices
import frames
import kinds
import reach
import web
from kinds import trmnl
from render import layout, theme as T
from render import words
from test_trmnl import TrmnlBase, firmware_reads_display, firmware_reads_setup, png_facts

KINDLE_MAC = "E0:CB:1D:C1:B7:B6"


def kindle_setup_headers(mac=KINDLE_MAC):
    """What client/kindle's pair() sends."""
    return {"ID": mac, "Model": "Kindle 4", "FW-Version": "1.0.0 / Kindle 4.1.1", "Content-Type": "application/json"}


def kindle_display_headers(key, source="timer", mac=KINDLE_MAC, width=600, height=800):
    """What client/kindle's display() sends."""
    return {"ID": mac, "Access-Token": key, "Refresh-Rate": "900", "Battery-Voltage": "4.17", "RSSI": "-58",
            "Width": str(width), "Height": str(height), "Model": "Kindle 4", "FW-Version": "1.0.0 / Kindle 4.1.1",
            "Update-Source": source, "Image-Cached": "false", "Wake-Time": "6000", "Content-Type": "application/json"}


class TestGreysAreTheDisplays(unittest.TestCase):
    def test_black_and_white_unless_the_profile_says(self):
        for key, disp in T.DISPLAYS.items():
            self.assertEqual(T.greys(key), disp.get("greys", 2), key)
        self.assertEqual(T.greys("kindle"), 16)
        self.assertEqual(T.greys("no_such_screen"), 2, "an unknown size is the default's, black and white")

    def test_black_and_white_screens_get_exactly_what_they_got_before(self):
        """for_screen is to_1bit, byte for byte, on every screen that isn't grey: a real page each."""
        page = {"elements": [{"type": "text", "value": "Kitchen 21.5°", "x": 16, "y": 16, "w": 360, "h": 80},
                             {"type": "icon", "icon": "mdi:weather-sunny", "x": 16, "y": 100, "w": 64, "h": 64}]}
        for key in [k for k in T.DISPLAYS if T.greys(k) == 2] + ["trmnl_1872x1404"]:
            img = layout.render_page(page, {}, clock="14:05", display=key)
            self.assertEqual(T.for_screen(img, key).tobytes(), T.to_1bit(img).tobytes(), key)
            self.assertEqual(T.for_screen(img, key).mode, "1", key)

    def test_sixteen_greys_keep_smooth_edges(self):
        img = Image.new("L", (200, 60), 255)
        ImageDraw.Draw(img).text((4, 4), "Smooth", fill=0, font=T.font(40))
        grey = T.for_screen(img, "kindle")
        shades = {v for _, v in grey.getcolors(256)}
        self.assertTrue(shades <= {round(i * 255 / 15) for i in range(16)}, "only the screen's 16 shades")
        self.assertIn(0, shades)
        self.assertIn(255, shades)
        self.assertGreater(len(shades), 4, "type edges keep their in-between shades")

    def test_nearest_shade_with_black_and_white_exact(self):
        ramp = Image.frombytes("L", (256, 1), bytes(range(256)))
        out = list(T.to_greys(ramp, 16).tobytes())
        self.assertEqual((out[0], out[255]), (0, 255))
        self.assertEqual(out[8], 0)
        self.assertEqual(out[9], 17)
        self.assertEqual(sorted(set(out)), [round(i * 17) for i in range(16)])


class TestTheKindleFamily(unittest.TestCase):
    def test_its_own_profile_and_name(self):
        k = T.get_display("kindle")
        self.assertEqual((k["kind"], k["w"], k["h"], T.family("kindle")), ("trmnl", 600, 800, "kindle"))
        self.assertEqual(T.family_name("kindle", default="TRMNL"), "Kindle")
        self.assertEqual(T.family("trmnl_og"), "trmnl")
        self.assertEqual(T.family_name("trmnl", default="TRMNL"), "TRMNL")
        self.assertEqual(T.family("crowpanel_579"), "crowpanel")

    def test_a_reported_size_stays_in_its_family(self):
        self.assertEqual(T.sized_display("trmnl", 600, 800, family="kindle"), "kindle")
        self.assertEqual(T.sized_display("trmnl", 600, 800), "trmnl_600x800", "a TRMNL that size stays a TRMNL")
        pw = T.get_display(T.sized_display("trmnl", 758, 1024, family="kindle"))
        self.assertEqual((pw["id"], pw["kind"], pw["greys"], pw["name"]), ("kindle_758x1024", "trmnl", 16, "Kindle"))
        diagonal = (pw["mm_w"] ** 2 + pw["mm_h"] ** 2) ** 0.5
        self.assertAlmostEqual(diagonal, 152.4, delta=1.5, msg="a Kindle of another size is still about 6 inches")
        self.assertIsNone(T.sized_display("crowpanel", 600, 800, family="kindle"), "never another kind's family")
        self.assertNotIn("greys", T.get_display("trmnl_600x800"))

    def test_the_trmnl_kind_offers_two_choices(self):
        got = [(c["family"], c["name"], c["displays"]) for c in trmnl.KIND.choices()]
        self.assertEqual(got[:2], [("trmnl", "TRMNL", ["trmnl_og"]), ("kindle", "Kindle", ["kindle"])])

    def test_what_it_says_on_a_screen_before_pairing_names_no_device(self):
        for key in ("trmnl.not_paired", "trmnl.already"):
            for lang in words.LANGUAGES:
                with words.speaking(lang, ""):
                    self.assertNotIn("TRMNL", words.say(key, name="Desk"), (key, lang))


class KindleBase(TrmnlBase):
    async def add_kindle(self, name="Hall", **extra):
        r = await self.ed.post("/api/devices", json={"kind": "trmnl", "name": name, "display": "kindle",
                                                     "pages": "new", "from": "1", **extra})
        self.assertEqual(r.status, 200, await r.text())
        return (await r.json())["device"]

    async def pair_kindle(self, dev_id) -> dict:
        self.assertEqual((await self.ed.post(f"/api/devices/{dev_id}/pair")).status, 200)
        r = await self.lan.get("/api/setup", headers=kindle_setup_headers())
        return firmware_reads_setup(await r.json())


class TestAKindleOnTheAddOn(KindleBase):
    async def test_added_paired_and_drawn_in_sixteen_greys(self):
        dev = await self.add_kindle()
        self.assertEqual((dev["kind"], dev["family"], dev["kind_name"], dev["display"]), ("trmnl", "kindle", "Kindle", "kindle"))
        got = await self.pair_kindle(dev["id"])
        self.assertEqual(got["status"], 200)
        self.assertEqual(devices.state(dev["id"])["model"], "Kindle 4")
        await frames.refresh_frames(None)
        r = await self.lan.get("/api/display", headers=kindle_display_headers(got["api_key"]))
        body = firmware_reads_display(await r.json())
        self.assertGreaterEqual(body["refresh_rate"], 60)
        png = await self.picture(body["image_url"], got["api_key"], mac=KINDLE_MAC)
        size, mode = png_facts(png)
        self.assertEqual((size, mode), ((600, 800), "L"), "8-bit grey, what eips -g draws")
        shades = {v for _, v in Image.open(io.BytesIO(png)).getcolors(256)}
        self.assertTrue(shades <= {i * 17 for i in range(16)})
        state = devices.state(dev["id"])
        self.assertEqual((state["battery_v"], state["rssi"]), (4.17, -58))

    async def test_a_trmnl_beside_it_still_gets_one_bit(self):
        dev = await self.add_trmnl()
        got = await self.pair(dev["id"])
        await frames.refresh_frames(None)
        _, body = await self.wake(got["api_key"])
        self.assertEqual(png_facts(await self.picture(body["image_url"], got["api_key"])), ((800, 480), "1"))

    async def test_another_kindles_size_is_a_kindle_size(self):
        dev = await self.add_kindle()
        got = await self.pair_kindle(dev["id"])
        await frames.refresh_frames(None)
        r = await self.lan.get("/api/display", headers=kindle_display_headers(got["api_key"], width=758, height=1024))
        body = firmware_reads_display(await r.json())
        self.assertEqual(devices.get(dev["id"])["display"], "kindle_758x1024")
        size, mode = png_facts(await self.picture(body["image_url"], got["api_key"], mac=KINDLE_MAC))
        self.assertEqual((size, mode), ((758, 1024), "L"))
        listed = await (await self.ed.get("/api/devices")).json()
        kindle = next(k for k in listed["kinds"] if k["family"] == "kindle")
        self.assertIn("kindle_758x1024", [d["id"] for d in kindle["displays"]])
        trmnl_choice = next(k for k in listed["kinds"] if k["family"] == "trmnl")
        self.assertNotIn("kindle_758x1024", [d["id"] for d in trmnl_choice["displays"]])

    async def test_a_device_keeps_its_family(self):
        t = await self.add_trmnl(name="Desk")
        r = await self.ed.post(f"/api/arrange?device={t['id']}", json={"display": "kindle", "orientation": 0,
                                                                      "spec": {"pages": {}, "rotation": []}})
        self.assertEqual(r.status, 400, "a TRMNL's pages aren't placed for a Kindle's screen")
        view = await (await self.ed.get(f"/api/layouts?device={t['id']}")).json()
        r = await self.ed.put(f"/api/layouts?device={t['id']}", json={**view, "display": "kindle"})
        self.assertEqual(r.status, 400, "a TRMNL's pages can't be saved for a Kindle's screen")
        r = await self.ed.put(f"/api/layouts?device={t['id']}", json={**view, "display": "trmnl_og"})
        self.assertEqual(r.status, 200, await r.text())


class TestTheEditorGivesAKindleItsFiles(KindleBase):
    async def test_the_installer_and_the_way_back(self):
        for which, name in (("install", "Update_epaper-panel_install.bin"), ("uninstall", "Update_epaper-panel_uninstall.bin")):
            r = await self.ed.get(f"/api/kindle/{which}")
            self.assertEqual(r.status, 200)
            self.assertEqual(await r.read(), (trmnl.KINDLE_FILES / name).read_bytes())
            self.assertIn(f'filename="{name}"', r.headers["Content-Disposition"])
        self.assertEqual((await self.ed.get("/api/kindle/../config")).status, 404)
        self.assertEqual((await self.ed.get("/api/kindle/anything")).status, 404)

    async def test_its_address_file_and_pairing_say_home_by_ip_address(self):
        dev = await self.add_kindle()
        with mock.patch.object(kinds, "_home_host", mock.AsyncMock(return_value="homeassistant.local")), \
                mock.patch.object(reach, "home_ip", mock.AsyncMock(return_value="192.168.1.20")), \
                mock.patch.object(reach, "public_base", mock.AsyncMock(return_value="https://ha.example.com/api/epaper")):
            r = await self.ed.get(f"/api/devices/{dev['id']}/kindle-settings")
            self.assertEqual(r.status, 200)
            self.assertIn('filename="epaper-panel.txt"', r.headers["Content-Disposition"])
            text = await r.text()
            self.assertRegex(text, r"\nserver = http://192\.168\.1\.20:\d+\n", "it can't look up a .local name")
            info = await (await self.ed.post(f"/api/devices/{dev['id']}/pair")).json()
            self.assertEqual(info["family"], "kindle")
            self.assertEqual([a["where"] for a in info["addresses"]], ["home"], "its TLS is too old for the away address")
            t = await self.add_trmnl()
            info = await (await self.ed.post(f"/api/devices/{t['id']}/pair")).json()
            self.assertEqual([a["url"].split(":")[1] for a in info["addresses"]][0], "//homeassistant.local",
                             "a TRMNL keeps the name, and gets the away address")
            self.assertEqual(len(info["addresses"]), 2)
            self.assertEqual((await self.ed.get(f"/api/devices/{t['id']}/kindle-settings")).status, 404)

    async def test_without_its_ip_address_the_name_is_kept(self):
        dev = await self.add_kindle()
        with mock.patch.object(kinds, "_home_host", mock.AsyncMock(return_value="homeassistant.local")), \
                mock.patch.object(reach, "home_ip", mock.AsyncMock(return_value="")):
            text = await (await self.ed.get(f"/api/devices/{dev['id']}/kindle-settings")).text()
        self.assertIn("server = http://homeassistant.local:", text)
        self.assertIn("put Home Assistant's", text)


class TestHomeIp(unittest.IsolatedAsyncioTestCase):
    async def test_the_supervisors_primary_ipv4_address(self):
        class Answer:
            status = 200
            def __init__(self, body): self.body = body
            async def json(self): return self.body
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False

        class Session:
            def __init__(self, body): self.body = body
            def get(self, url, **kw):
                assert url == "http://supervisor/network/info"
                return Answer(self.body)

        body = {"data": {"interfaces": [
            {"primary": False, "ipv4": {"address": ["172.30.32.1/23"]}},
            {"primary": True, "ipv4": {"address": ["192.168.50.5/24"]}}]}}
        class NoHass:
            available = False

        with mock.patch.object(reach.config, "HA_TOKEN", "t"):
            self.assertEqual(await reach.home_ip(NoHass(), Session(body)), "192.168.50.5")
            self.assertEqual(await reach.home_ip(NoHass(), Session({"data": {"interfaces": []}})), "")
        self.assertEqual(await reach.home_ip(NoHass(), Session(body)), "", "not under the Supervisor: nothing to ask")

    async def test_home_assistants_own_network_settings_first(self):
        """No Supervisor rights needed (the add-on has none): Home Assistant's `network` command."""
        class Hass:
            available = True
            async def ws(self, payload):
                assert payload == {"type": "network"}
                return {"adapters": [
                    {"name": "docker0", "enabled": True, "default": False, "ipv4": [{"address": "172.30.32.1"}]},
                    {"name": "end0", "enabled": True, "default": True, "ipv4": [{"address": "192.168.50.5"}]}]}
        self.assertEqual(await reach.home_ip(Hass(), None), "192.168.50.5")


class TestAlwaysOn(KindleBase):
    """A Kindle can stay on (its profile's `stays_on`), unlike a TRMNL: Update every 1 minute. Then the
    add-on tells it to stay awake and connected, and it asks as often as its pages turn."""

    async def wake_kindle(self, key, source="timer") -> dict:
        r = await self.lan.get("/api/display", headers=kindle_display_headers(key, source=source))
        return await r.json()

    async def test_offered_and_starts_asleep(self):
        listed = await (await self.ed.get("/api/devices")).json()
        by = {k["family"]: k for k in listed["kinds"]}
        self.assertEqual((by["kindle"]["update_choices"][0], by["kindle"]["starts_on"]), (1, False))
        self.assertEqual((by["trmnl"]["update_choices"][0], by["trmnl"]["starts_on"]), (5, False))
        self.assertTrue(by["crowpanel"]["starts_on"])
        dev = await self.add_kindle()
        self.assertEqual(dev["timing"]["update_minutes"], 15, "asleep unless asked: it may be on its battery")
        self.assertTrue(dev["timing"]["can_stay_on"])

    async def test_always_on_it_stays_awake_and_asks_as_often_as_pages_turn(self):
        dev = await self.add_kindle(pages="copy", update_minutes=1)
        self.assertTrue(dev["timing"]["always_on"])
        got = await self.pair_kindle(dev["id"])
        await frames.refresh_frames(None)
        names = []
        for _ in range(3):
            body = await self.wake_kindle(got["api_key"])
            self.assertIs(body.get("stay_awake"), True)
            self.assertEqual(body["refresh_rate"], 30, "Rotate every 30 seconds: it asks every 30")
            names.append(body["filename"])
        self.assertEqual(len(set(names)), 3, "a new page each time its pages turn")

    async def test_pages_turning_slower_than_a_minute(self):
        dev = await self.add_kindle(pages="copy", update_minutes=1, rotate_seconds=120)
        got = await self.pair_kindle(dev["id"])
        await frames.refresh_frames(None)
        bodies = [await self.wake_kindle(got["api_key"]) for _ in range(3)]
        self.assertTrue(all(0 < b["refresh_rate"] <= 65 for b in bodies), "about every minute, lined up to the minute")
        names = [b["filename"] for b in bodies]
        self.assertEqual((names[0] == names[1], names[1] == names[2]), (True, False), "a page shows for two wakes, then the next")

    async def test_asleep_it_isnt_told_to_stay_awake(self):
        dev = await self.add_kindle()
        got = await self.pair_kindle(dev["id"])
        await frames.refresh_frames(None)
        body = await self.wake_kindle(got["api_key"])
        self.assertNotIn("stay_awake", body)
        self.assertGreaterEqual(body["refresh_rate"], 60)

    async def test_a_trmnl_never_stays_on(self):
        t = await self.add_trmnl()
        r = await self.ed.patch(f"/api/devices/{t['id']}", json={"update_minutes": 1})
        self.assertEqual(r.status, 400)
        got = await self.pair(t["id"])
        await frames.refresh_frames(None)
        r = await self.lan.get("/api/display", headers=__import__("test_trmnl").display_headers(got["api_key"]))
        self.assertNotIn("stay_awake", await r.json(), "its answer is exactly what its firmware knows")


class TestPreviousPage(KindleBase):
    async def test_a_back_press_goes_to_the_previous_page(self):
        """Update-Source "back" (ours, a Kindle's previous-page buttons): the page before, as a CrowPanel's PRV."""
        dev = await self.add_kindle(pages="copy")
        got = await self.pair_kindle(dev["id"])
        await frames.refresh_frames(None)
        names = []
        for source in ("timer", "button", "button", "back", "back"):
            r = await self.lan.get("/api/display", headers=kindle_display_headers(got["api_key"], source=source))
            names.append((await r.json())["filename"])
        first, second, third, back1, back2 = names
        self.assertEqual(len({first, second, third}), 3)
        self.assertEqual((back1, back2), (second, first))

    async def test_a_refresh_shows_the_page_on_screen_again(self):
        """Update-Source "refresh" (ours, the 5-way's middle): the same page, and the rotation doesn't move."""
        dev = await self.add_kindle(pages="copy", rotate_updates=2)
        got = await self.pair_kindle(dev["id"])
        await frames.refresh_frames(None)
        names = []
        for source in ("timer", "refresh", "refresh", "timer", "timer"):
            r = await self.lan.get("/api/display", headers=kindle_display_headers(got["api_key"], source=source))
            names.append((await r.json())["filename"])
        self.assertEqual(names[:4], [names[0]] * 4, "a refresh doesn't count as a showing")
        self.assertNotEqual(names[4], names[0], "the rotation moves on as before")


MARKS_PROGRAM = r"""
#include <cstdio>
#include <cstdlib>
#include <vector>
#include "epf_core.h"
// argv: w h pill_y0 pill_y1 cat_x0 sub_x0 sub_x1 cat_pill_w has_sub highlight_sub cat_locked panel_locked
int main(int argc, char **argv) {
  if (argc != 13) return 2;
  int v[12];
  for (int i = 0; i < 12; i++) v[i] = std::atoi(argv[i + 1]);
  epf::Geometry g;
  g.logical_w = v[0]; g.logical_h = v[1]; g.quarter_turns = 0;
  g.pill_y0 = v[2]; g.pill_y1 = v[3]; g.cat_x0 = v[4]; g.sub_x0 = v[5]; g.sub_x1 = v[6];
  epf::OverlayState st;
  st.cat_pill_w = v[7]; st.has_sub = v[8]; st.highlight_sub = v[9]; st.cat_locked = v[10]; st.panel_locked = v[11];
  const int stride = (v[0] + 7) / 8;
  std::vector<uint8_t> buf((size_t) stride * v[1], 0xFF);
  epf::draw_overlays(buf.data(), v[0], v[1], g, st);
  for (int y = 0; y < v[1]; y++)
    for (int x = 0; x < v[0]; x++)
      if (!(buf[(size_t) y * stride + x / 8] & (1 << (7 - x % 8)))) std::printf("%d %d\n", x, y);
  return 0;
}
"""


class TestTheKindlesFooterMarksAreTheCrowPanels(unittest.TestCase):
    """theme.draw_footer_marks draws what the firmware's draw_overlays draws (epf_core.h), pixel for
    pixel, from the same footer plan: the highlighted pill and the padlocks, every combination."""

    @classmethod
    def setUpClass(cls):
        import shutil
        import subprocess
        import tempfile
        from pathlib import Path
        compiler = shutil.which("c++")
        if not compiler:
            raise unittest.SkipTest("no C++ compiler here")
        cls.tmp = Path(tempfile.mkdtemp(prefix="marks-"))
        src = cls.tmp / "marks.cpp"
        src.write_text(MARKS_PROGRAM)
        cls.exe = cls.tmp / "marks"
        built = subprocess.run([compiler, "-std=c++17", "-O1", "-I", str(support.APP.parents[1] / "components" / "epf"),
                                "-o", str(cls.exe), str(src), "-lz"], capture_output=True, text=True)
        if built.returncode != 0:
            raise AssertionError(built.stderr)

    def firmware(self, plan, w, h, pos, has_sub, sub, page_lock, item_lock):
        import subprocess
        cat_w = plan["pages"][pos]["w"]
        args = [w, h, plan["pill_y0"], plan["pill_y1"], plan["cat_x0"], plan["sub_x0"], plan["sub_x1"], cat_w,
                int(has_sub), int(sub), int(page_lock), int(item_lock)]
        out = subprocess.run([str(self.exe), *map(str, args)], capture_output=True, text=True, check=True).stdout
        return {tuple(map(int, line.split())) for line in out.splitlines()}

    def ours(self, plan, w, h, pos, has_sub, sub, page_lock, item_lock):
        img = Image.new("L", (w, h), 255)
        T.draw_footer_marks(img, plan, pos, has_sub=has_sub, sub=sub, page_lock=page_lock, item_lock=item_lock)
        data = img.tobytes()
        return {(i % w, i // w) for i, v in enumerate(data) if v == 0}

    def test_every_combination(self):
        for display, orientation in (("kindle", 0), ("kindle", 90), ("kindle_758x1024", 0)):
            w, h = T.canvas_dims(orientation, display)
            plan = T.footer_plan(clock="14:05", pages=[("solar", 1), ("scores", 5), ("weather", 1)],
                                 orientation=orientation, display=display)
            for pos, has_sub in ((0, False), (1, True)):
                for sub in (False, True):
                    for page_lock in (False, True):
                        for item_lock in (False, True):
                            with self.subTest(display=display, orientation=orientation, pos=pos, sub=sub,
                                              page_lock=page_lock, item_lock=item_lock):
                                want = self.firmware(plan, w, h, pos, has_sub, sub, page_lock, item_lock)
                                got = self.ours(plan, w, h, pos, has_sub, sub, page_lock, item_lock)
                                self.assertTrue(want, "the firmware drew something")
                                self.assertEqual(got, want)


class TestSubPagesAndLocks(KindleBase):
    """A Kindle's buttons, as a CrowPanel's (paging.ACTIONS): sub-page mode on a page with several
    items, the page lock (rotates its own items), the item lock (stays put), and their marks."""

    async def setup_kindle(self):
        dev = await self.add_kindle(pages="copy", rotate_updates=1)
        self.key = (await self.pair_kindle(dev["id"]))["api_key"]
        await frames.refresh_frames(None)
        self.dev = dev
        return dev

    async def press(self, source):
        r = await self.lan.get("/api/display", headers=kindle_display_headers(self.key, source=source))
        body = await r.json()
        cursor = devices.state(self.dev["id"])["cursor"]
        return body["filename"], cursor

    def plans(self):
        import paging
        ahead = paging.ahead_of(devices.get(self.dev["id"]))
        return paging._plans(ahead.spec, ahead.st)

    async def choose(self, dev, action, person=True):
        """paging._choose on a rotation of three pages, the middle one with three items."""
        import paging
        from datetime import datetime

        class St:
            alert = None
            live = ["a", "b", "c"]
            plans = [{"name": "a", "want": 1}, {"name": "b", "want": 3}, {"name": "c", "want": 1}]

        ahead = paging.Ahead("kindle", {"pages": {"a": {}, "b": {}, "c": {}}}, St(), False, "", {})
        key = paging._choose(devices.get(dev["id"]), ahead, datetime.now().astimezone(), person, action)
        return key, devices.state(dev["id"])["cursor"]

    async def test_sub_page_mode_steps_through_the_pages_items(self):
        dev = await self.add_kindle()
        devices.set_state(dev["id"], cursor={"pos": 1, "name": "b", "item": 0, "shown": 1})
        key, cursor = await self.choose(dev, "mode")
        self.assertEqual((cursor["mode"], cursor["name"], cursor["item"]), ("items", "b", 0))
        self.assertEqual(key, "b#0|s", "the item pill highlighted")
        _, cursor = await self.choose(dev, "next")
        self.assertEqual((cursor["name"], cursor["item"]), ("b", 1), "the next item, not the next page")
        _, cursor = await self.choose(dev, "back")
        _, cursor = await self.choose(dev, "back")
        self.assertEqual((cursor["name"], cursor["item"]), ("b", 2), "round its own items")
        key, cursor = await self.choose(dev, "mode")
        self.assertNotIn("mode", cursor)
        self.assertEqual(key, "b#2|p")
        _, cursor = await self.choose(dev, "next")
        self.assertEqual((cursor["name"], cursor["item"]), ("c", 0), "a page step again")

    async def test_sub_page_mode_needs_items(self):
        dev = await self.add_kindle()
        devices.set_state(dev["id"], cursor={"pos": 0, "name": "a", "item": 0, "shown": 1})
        _, cursor = await self.choose(dev, "mode")
        self.assertNotIn("mode", cursor, "a page with one item has no sub-pages")

    async def test_the_page_lock_keeps_rotating_through_its_own_items(self):
        dev = await self.add_kindle(rotate_updates=1)
        devices.set_state(dev["id"], cursor={"pos": 1, "name": "b", "item": 0, "shown": 1})
        key, cursor = await self.choose(dev, "lock")
        self.assertEqual((cursor["lock"], key), ("page", "b#0|pL"))
        items = []
        for _ in range(4):
            _, cursor = await self.choose(dev, None, person=False)
            self.assertEqual(cursor["name"], "b", "it stays on its page")
            items.append(cursor["item"])
        self.assertEqual(items, [1, 2, 0, 1])
        _, cursor = await self.choose(dev, "next")
        self.assertEqual((cursor["name"], cursor["lock"]), ("c", "page"), "a person still moves; the lock follows")
        _, cursor = await self.choose(dev, "lock")
        self.assertNotIn("lock", cursor)

    async def test_the_item_lock_stays_put(self):
        dev = await self.add_kindle(rotate_updates=1)
        devices.set_state(dev["id"], cursor={"pos": 1, "name": "b", "item": 1, "shown": 1, "mode": "items"})
        key, cursor = await self.choose(dev, "lock")
        self.assertEqual((cursor["lock"], key), ("item", "b#1|sl"))
        for _ in range(3):
            _, cursor = await self.choose(dev, None, person=False)
            self.assertEqual((cursor["name"], cursor["item"]), ("b", 1))

    async def test_a_lock_and_the_mode_show_in_the_footer(self):
        await self.setup_kindle()
        plain, _ = await self.press("refresh")
        locked, _ = await self.press("lock")
        self.assertNotEqual(plain, locked, "the padlock changes the picture")
        r = await self.lan.get(f"/api/image/{locked}", headers={"ID": KINDLE_MAC, "Access-Token": self.key})
        img = Image.open(io.BytesIO(await r.read())).convert("L")
        w, h = img.size
        footer = img.crop((0, h - 40, w, h))
        self.assertTrue(any(v == 0 for v in footer.tobytes()), "a dark badge in the footer")
        unlocked, _ = await self.press("lock")
        self.assertEqual(unlocked, plain, "unlocked, the same picture as before")

    async def test_a_trmnl_has_no_marks(self):
        import paging
        t = await self.add_trmnl()
        self.assertIsNone(paging.marks(devices.get(t["id"]), [{"name": "a", "want": 3}], 0))


if __name__ == "__main__":
    unittest.main()
