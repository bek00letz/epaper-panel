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
        with mock.patch.object(reach.config, "HA_TOKEN", "t"):
            self.assertEqual(await reach.home_ip(Session(body)), "192.168.50.5")
            self.assertEqual(await reach.home_ip(Session({"data": {"interfaces": []}})), "")
        self.assertEqual(await reach.home_ip(Session(body)), "", "not under the Supervisor: nothing to ask")


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


if __name__ == "__main__":
    unittest.main()
