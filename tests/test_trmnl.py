"""TRMNL: pairing, each wake, the picture, and the option that turns it on.

The requests here are built the way TRMNL's open-source firmware builds them
(usetrmnl/firmware at 383d6ff), and the answers are read the way it reads
them, so the protocol is pinned to the device rather than to our own idea of it:

  request_headers.cpp        buildSetupHeaders, buildDisplayHeaders, buildLogHeaders, buildImageHeaders
  parse_response_api_*.cpp   which fields it reads, and what a missing one becomes
  display_session.cpp        what each "status" does (0 shows, 202 polls every 5 s, 500 wipes it)
  bl.cpp, http_utils.cpp     the picture: Content-Type image/png, key sent only to its own server's addresses
  device_setup.cpp           a setup "status" of 404 shows our message; 200 stores the key
  logging_parsers.cpp        Update-Source names: "timer", "button", "powercycle", ...
"""
import io
import json
import time
import unittest
from datetime import datetime, timedelta
from unittest import mock

from aiohttp.test_utils import TestClient, TestServer, make_mocked_request
from PIL import Image

import support
import config
import devices
import frames
import kinds
import paging
import reach
import runtime
import web
from kinds import trmnl
from render import theme as T

MAC = "AA:BB:CC:DD:EE:FF"                   # the firmware's own test values (test_request_headers.cpp)
OTHER_MAC = "11:22:33:44:55:66"


def setup_headers(mac=MAC):
    """buildSetupHeaders: ID, Content-Type, FW-Version, Model."""
    return {"ID": mac, "Content-Type": "application/json", "FW-Version": "1.8.5", "Model": "og"}


def display_headers(key, source="timer", mac=MAC, width=800, height=480, volts="4.10", cached="false"):
    """buildDisplayHeaders, in its order, as an OG sends them (no X-only battery headers)."""
    return {"ID": mac, "Content-Type": "application/json", "Update-Source": source, "Access-Token": key,
            "Refresh-Rate": "900", "Battery-Voltage": volts, "FW-Version": "1.8.5", "FW-Commit": "383d6ff",
            "Model": "og", "Image-Cached": cached, "Wake-Time": "42", "RSSI": "-55", "WiFi-Band": "2.4",
            "Temperature-Profile": "true", "Width": str(width), "Height": str(height)}


def image_headers(key, mac=MAC):
    """buildImageHeaders: only ID and Access-Token, and only to addresses under its server's."""
    return {"ID": mac, "Access-Token": key}


def log_headers(key, mac=MAC):
    return {"ID": mac, "Accept": "application/json, */*", "Access-Token": key, "Content-Type": "application/json"}


def firmware_reads_setup(body: dict) -> dict:
    """parseResponse_apiSetup: status, message; the rest only when status is 200."""
    out = {"status": int(body.get("status") or 0), "message": body.get("message") or ""}
    if out["status"] == 200:
        out.update(api_key=body.get("api_key") or "", friendly_id=body.get("friendly_id") or "",
                   image_url=body.get("image_url") or "")
    return out


def firmware_reads_display(body: dict) -> dict:
    """parseResponse_apiDisplay: a missing number is 0, a missing string is ""."""
    return {"status": int(body.get("status") or 0), "image_url": body.get("image_url") or "",
            "filename": body.get("filename") or "", "refresh_rate": int(body.get("refresh_rate") or 0),
            "update_firmware": bool(body.get("update_firmware")), "reset_firmware": bool(body.get("reset_firmware")),
            "firmware_url": body.get("firmware_url") or ""}


def png_facts(data: bytes):
    """parsePNGHeader reads the signature and IHDR; PIL says the rest."""
    assert data[:8] == b"\x89PNG\r\n\x1a\n" and data[12:16] == b"IHDR", "not a PNG the firmware accepts"
    img = Image.open(io.BytesIO(data))
    return img.size, img.mode


class TrmnlBase(unittest.IsolatedAsyncioTestCase):
    """The option on, one CrowPanel (device 1, as every install has) and a TRMNL added in the editor."""

    async def asyncSetUp(self):
        support.fresh_data_dir()
        kinds.WRONG_KEYS = kinds.WrongKeys()
        trmnl._PAIRING.clear()
        self._on = config.TRMNL
        config.TRMNL = True
        await frames.refresh_frames(None)
        panel, editor = web.make_apps()
        self.lan = TestClient(TestServer(panel))
        self.ed = TestClient(TestServer(editor))
        await self.lan.start_server()
        await self.ed.start_server()

    async def asyncTearDown(self):
        await self.lan.close()
        await self.ed.close()
        config.TRMNL = self._on
        trmnl._PAIRING.clear()
        kinds.WRONG_KEYS = kinds.WrongKeys()
        support.use_test_data_dir()

    async def add_trmnl(self, name="Desk", pages="new", **extra):
        r = await self.ed.post("/api/devices", json={"kind": "trmnl", "name": name, "display": "trmnl_og",
                                                     "pages": pages, "from": "1", **extra})
        self.assertEqual(r.status, 200, await r.text())
        return (await r.json())["device"]

    async def pair(self, dev_id, mac=MAC) -> dict:
        r = await self.ed.post(f"/api/devices/{dev_id}/pair")
        self.assertEqual(r.status, 200)
        r = await self.lan.get("/api/setup", headers=setup_headers(mac))
        self.assertEqual(r.status, 200)
        return firmware_reads_setup(await r.json())

    async def wake(self, key, **kw) -> tuple[int, dict]:
        r = await self.lan.get("/api/display", headers=display_headers(key, **kw))
        return r.status, (firmware_reads_display(await r.json()) if r.status == 200 else {})

    async def picture(self, url, key, mac=MAC) -> bytes:
        base = str(self.lan.make_url(""))
        self.assertTrue(url.startswith(base), "the firmware only sends its key to addresses under its server's")
        r = await self.lan.get(url[len(base):] if url.startswith(base) else url, headers=image_headers(key, mac))
        self.assertEqual(r.status, 200)
        self.assertEqual(r.headers["Content-Type"], "image/png", "bl.cpp decodes as PNG only for exactly this")
        return await r.read()


class TestOffByDefault(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        support.fresh_data_dir()
        self._on = config.TRMNL

    async def asyncTearDown(self):
        config.TRMNL = self._on
        support.use_test_data_dir()

    async def test_the_option_starts_off(self):
        with mock.patch.dict("os.environ", {}, clear=False):
            import importlib
            import os
            os.environ.pop("TRMNL", None)
            self.assertFalse(importlib.reload(config).TRMNL)
            os.environ["TRMNL"] = "true"
            self.assertTrue(importlib.reload(config).TRMNL)
            os.environ.pop("TRMNL", None)
            importlib.reload(config)
        support.use_test_data_dir()

    async def test_off_its_routes_do_not_exist_and_the_editor_shows_nothing(self):
        config.TRMNL = True
        devices.add("trmnl", "Desk", "trmnl_og")              # paired while it was on
        config.TRMNL = False
        await frames.refresh_frames(None)
        panel, editor = web.make_apps()
        async with TestClient(TestServer(panel)) as lan, TestClient(TestServer(editor)) as ed:
            self.assertEqual((await lan.get("/api/setup", headers=setup_headers())).status, 404)
            self.assertEqual((await lan.get("/api/display", headers=display_headers("x"))).status, 404)
            body = await (await ed.get("/api/devices")).json()
            self.assertEqual([k["id"] for k in body["kinds"]], ["crowpanel"])
            self.assertEqual([d["kind"] for d in body["devices"]], ["crowpanel"])
            self.assertNotIn("trmnl_og", body["displays"])
            self.assertEqual((await ed.post("/api/devices", json={"kind": "trmnl", "name": "Two",
                                                                   "display": "trmnl_og"})).status, 400)
            self.assertEqual((await ed.post("/api/devices/2/pair")).status, 404)
            self.assertNotIn("trmnl_og", [d["id"] for d in (await (await ed.get("/api/displays")).json())["displays"]])
        self.assertNotIn("2", [d for d in runtime._DEVICES], "a switched-off kind isn't drawn")


class TestPairing(TrmnlBase):
    async def test_outside_the_window_a_trmnl_is_told_what_to_do_and_gets_no_key(self):
        await self.add_trmnl()
        r = await self.lan.get("/api/setup", headers=setup_headers())
        self.assertEqual(r.status, 200, "only a 200 lets the firmware read and show the message")
        got = firmware_reads_setup(await r.json())
        self.assertEqual(got["status"], 404, "device_setup.cpp: MacNotRegistered, then sleeps")
        self.assertIn("add this TRMNL", got["message"])
        self.assertNotIn("api_key", got)
        self.assertTrue(got["message"].isascii(), "its font is ASCII")

    async def test_add_pair_and_the_key_works(self):
        dev = await self.add_trmnl()
        self.assertEqual(dev["setup"], "pair")
        self.assertFalse(dev["info"]["paired"])
        r = await self.ed.post(f"/api/devices/{dev['id']}/pair")
        info = await r.json()
        self.assertGreater(info["pairing_left"], 590)
        self.assertTrue(info["addresses"][0]["url"].startswith("http://"))
        self.assertEqual(info["addresses"][0]["where"], "home")

        got = firmware_reads_setup(await (await self.lan.get("/api/setup", headers=setup_headers())).json())
        self.assertEqual(got["status"], 200)
        self.assertGreaterEqual(len(got["api_key"]), 32)
        self.assertRegex(got["friendly_id"], r"^[A-Z2-9]{6}$")
        self.assertEqual(got["image_url"], "", "no setup picture: it would replace the device's own logo")
        stored = devices.get(dev["id"])
        self.assertEqual(stored["setup"]["mac"], MAC)
        self.assertEqual(devices.key_of(stored), got["api_key"])
        self.assertEqual(devices.state(dev["id"])["model"], "og")

        info = await (await self.ed.get(f"/api/devices/{dev['id']}/pair")).json()
        self.assertTrue(info["paired"])
        self.assertEqual(info["pairing_left"], 0, "one TRMNL per window")
        status, body = await self.wake(got["api_key"])
        self.assertEqual(status, 200)

        # A second TRMNL in the same minute isn't let in.
        again = firmware_reads_setup(await (await self.lan.get("/api/setup", headers=setup_headers(OTHER_MAC))).json())
        self.assertEqual(again["status"], 404)

    async def test_the_window_closes_after_ten_minutes(self):
        dev = await self.add_trmnl()
        await self.ed.post(f"/api/devices/{dev['id']}/pair")
        trmnl._PAIRING["until"] = time.monotonic() - 1
        got = firmware_reads_setup(await (await self.lan.get("/api/setup", headers=setup_headers())).json())
        self.assertEqual(got["status"], 404)
        self.assertNotIn("mac", devices.get(dev["id"]).get("setup") or {})

    async def test_pairing_again_gives_a_new_key_and_the_old_one_stops(self):
        dev = await self.add_trmnl()
        first = await self.pair(dev["id"])
        second = await self.pair(dev["id"])
        self.assertNotEqual(first["api_key"], second["api_key"])
        self.assertEqual(first["friendly_id"], second["friendly_id"], "the same screen keeps its name")
        self.assertEqual((await self.wake(first["api_key"]))[0], 401)
        self.assertEqual((await self.wake(second["api_key"]))[0], 200)

    async def test_a_trmnl_paired_as_another_screen_is_not_taken_over(self):
        desk = await self.add_trmnl("Desk")
        await self.pair(desk["id"])
        hall = await self.add_trmnl("Hall")
        got = await self.pair(hall["id"])
        self.assertEqual(got["status"], 404)
        self.assertIn("Desk", got["message"])

    async def test_a_bad_id_is_refused(self):
        dev = await self.add_trmnl()
        await self.ed.post(f"/api/devices/{dev['id']}/pair")
        got = firmware_reads_setup(await (await self.lan.get("/api/setup", headers=setup_headers("not-a-mac"))).json())
        self.assertEqual(got["status"], 404)


class TestAWake(TrmnlBase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.dev = await self.add_trmnl()
        self.key = (await self.pair(self.dev["id"]))["api_key"]
        await frames.refresh_frames(None)

    async def test_the_answer_reads_as_the_firmware_wants(self):
        status, body = await self.wake(self.key)
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], 0, "202 polls every 5 s and 500 wipes its Wi-Fi: only 0")
        self.assertEqual(body["refresh_rate"], 15 * 60, "always sent: a missing one is stored as 0")
        self.assertFalse(body["update_firmware"])
        self.assertFalse(body["reset_firmware"])
        self.assertTrue(body["image_url"])
        self.assertRegex(body["filename"], r"^ep-[0-9a-f]{16}$")
        self.assertLessEqual(len(body["filename"]), 31, "filesystem_fix_filename keeps 31 characters")
        self.assertNotIn(body["filename"], ("empty_state", "screen_wiper.png"), "names the firmware treats specially")
        size, mode = png_facts(await self.picture(body["image_url"], self.key))
        self.assertEqual(size, (800, 480))
        self.assertEqual(mode, "1", "1-bit")

    async def test_an_unchanged_picture_keeps_its_name(self):
        _, a = await self.wake(self.key)
        _, b = await self.wake(self.key)
        self.assertEqual(a["filename"], b["filename"], "one page, nothing new: the device skips the download")

    async def test_updated_is_when_the_page_last_changed_not_when_it_woke(self):
        _, first = await self.wake(self.key)
        later = datetime.now() + timedelta(minutes=30)

        class Later(datetime):
            @classmethod
            def now(cls, tz=None):
                return later if tz is None else later.astimezone(tz)

        with mock.patch.object(paging, "datetime", Later), mock.patch.object(trmnl, "datetime", Later):
            _, same = await self.wake(self.key)
            self.assertEqual(same["filename"], first["filename"], "nothing changed: no download, no flash")
            spec = devices.view(self.dev["id"])
            page = next(iter(spec["pages"].values()))
            page["elements"].append({"id": "t_new", "type": "text", "value": "something new",
                                     "x": 40, "y": 300, "w": 400, "h": 60})
            devices.save_view(spec, self.dev["id"])
            await frames.refresh_frames(None)
            _, changed = await self.wake(self.key)
        self.assertNotEqual(changed["filename"], first["filename"])
        shown = devices.state(self.dev["id"])["updated"]
        label = next(v["label"] for k, v in shown.items() if not k.startswith("\x00"))
        self.assertEqual(label, paging.updated_label(later.astimezone(), later.astimezone()))

    async def test_its_key_comes_in_the_access_token_header_and_nowhere_else_is_needed(self):
        self.assertEqual((await self.wake("wrong-key"))[0], 401)
        r = await self.lan.get("/api/display", headers={k: v for k, v in display_headers(self.key).items()
                                                        if k != "Access-Token"})
        self.assertEqual(r.status, 401)

    async def test_its_key_from_another_device_is_refused(self):
        self.assertEqual((await self.wake(self.key, mac=OTHER_MAC))[0], 401)

    async def test_the_picture_needs_the_key(self):
        _, body = await self.wake(self.key)
        path = body["image_url"][len(str(self.lan.make_url(""))):]
        self.assertEqual((await self.lan.get(path)).status, 401)
        self.assertEqual((await self.lan.get(path, headers=image_headers("nope"))).status, 401)

    async def test_its_size_is_what_it_reports(self):
        _, body = await self.wake(self.key, width=1872, height=1404)
        self.assertEqual(devices.get(self.dev["id"])["display"], "trmnl_1872x1404")
        size, _ = png_facts(await self.picture(body["image_url"], self.key))
        self.assertEqual(size, (1872, 1404))
        await frames.refresh_frames(None)
        listed = await (await self.ed.get("/api/devices")).json()
        self.assertIn("trmnl_1872x1404", listed["displays"], "the editor gets that size's canvas")
        _, back = await self.wake(self.key)                    # and back to its own
        self.assertEqual(devices.get(self.dev["id"])["display"], "trmnl_og")
        self.assertEqual(png_facts(await self.picture(back["image_url"], self.key))[0], (800, 480))

    async def test_battery_and_wifi_reach_the_editor_and_home_assistant(self):
        await self.wake(self.key, volts="3.92")
        info = (await (await self.ed.get(f"/api/devices/{self.dev['id']}/pair")).json())
        self.assertEqual((info["battery"], info["battery_v"], info["rssi"]), (70, 3.92, -55))
        self.assertTrue(info["last_seen"])
        suffix = devices.get(self.dev["id"])["entity_suffix"]
        self.assertEqual(runtime.PUBLISHED[f"sensor.epaper_battery{suffix}"]["state"], "70")
        self.assertEqual(runtime.PUBLISHED[f"sensor.epaper_battery_voltage{suffix}"]["state"], "3.92")
        self.assertEqual(runtime.PUBLISHED[f"sensor.epaper_wifi_signal{suffix}"]["attributes"]["device_class"],
                         "signal_strength")
        self.assertEqual(kinds.of(devices.get(self.dev["id"])).entities(self.dev),
                         {"sensor.epaper_battery", "sensor.epaper_battery_voltage", "sensor.epaper_wifi_signal",
                          "sensor.epaper_last_seen"})

    async def test_the_wake_interval_is_its_own_setting(self):
        r = await self.ed.patch(f"/api/devices/{self.dev['id']}", json={"wake_minutes": 60})
        self.assertEqual(r.status, 200)
        self.assertEqual((await r.json())["device"]["info"]["wake_minutes"], 60)
        self.assertEqual((await self.wake(self.key))[1]["refresh_rate"], 3600)
        self.assertEqual((await self.ed.patch(f"/api/devices/{self.dev['id']}", json={"wake_minutes": 7})).status, 400)
        status = await (await self.ed.get(f"/api/status?device={self.dev['id']}")).json()
        self.assertEqual(status["panel_interval"], 60)

    async def test_its_log_is_accepted_and_kept_briefly(self):
        body = {"logs": [{"creation_timestamp": 1, "message": "Image download failed", "level": "error"}]}
        r = await self.lan.post("/api/log", data=json.dumps(body), headers=log_headers(self.key))
        self.assertEqual(r.status, 204, "submit_log.cpp takes 200, 204 or 301")
        info = await (await self.ed.get(f"/api/devices/{self.dev['id']}/pair")).json()
        self.assertEqual(info["log"], ["Image download failed"])
        self.assertEqual((await self.lan.post("/api/log", data="{}", headers=log_headers("nope"))).status, 401)

    async def test_before_the_first_render_it_asks_again_soon(self):
        paging.forget(self.dev)
        _, body = await self.wake(self.key)
        self.assertEqual((body["image_url"], body["filename"]), ("", ""), "nothing to download")
        self.assertEqual(body["refresh_rate"], paging.FIRST_RENDER_SECONDS)

    async def test_status_on_the_device_port_says_ok(self):
        r = await self.lan.get("/status", headers={"Access-Token": self.key})
        self.assertTrue((await r.json())["ok"])


class TestThePageEachWake(TrmnlBase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        # The first panel's pages (several), fitted to the TRMNL.
        self.dev = await self.add_trmnl(pages="copy")
        self.key = (await self.pair(self.dev["id"]))["api_key"]
        await frames.refresh_frames(None)
        self.plans = paging.ahead_of(self.dev).st.plans
        self.assertGreater(len(self.plans), 1, "needs a rotation of several pages")

    def cursor(self):
        return devices.state(self.dev["id"])["cursor"]

    async def test_a_timer_wake_moves_through_the_rotation(self):
        seen = []
        for _ in range(sum(max(1, p["want"]) for p in self.plans) + 1):
            await self.wake(self.key)
            seen.append((self.cursor()["name"], self.cursor()["item"]))
        expected = [(p["name"], i) for p in self.plans for i in range(max(1, p["want"]))]
        self.assertEqual(seen, expected + expected[:1], "every item of every page, then round again")

    async def test_a_button_wake_goes_to_the_next_page(self):
        await self.wake(self.key)
        first = self.cursor()["pos"]
        await self.wake(self.key, source="button")
        self.assertEqual(self.cursor(), {"pos": (first + 1) % len(self.plans), "name": self.plans[(first + 1) % len(self.plans)]["name"], "item": 0})

    async def test_pictures_differ_as_the_page_changes(self):
        names = {(await self.wake(self.key))[1]["filename"] for _ in range(3)}
        self.assertGreater(len(names), 1)


def hhmm(dt):
    return dt.strftime("%H:%M")


class TestQuietHoursAndAlerts(TrmnlBase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.dev = await self.add_trmnl()
        self.key = (await self.pair(self.dev["id"]))["api_key"]

    async def quiet(self, start, end, **extra):
        devices.update(self.dev["id"], quiet_hours={"enabled": True, "start": hhmm(start), "end": hhmm(end), **extra})
        await frames.refresh_frames(None)

    async def test_quiet_hours_show_the_sleep_page_until_they_end(self):
        now = datetime.now()
        await self.quiet(now - timedelta(hours=1), now + timedelta(hours=2))
        _, body = await self.wake(self.key)
        until_end = (now + timedelta(hours=2)).replace(second=0, microsecond=0) - now
        self.assertAlmostEqual(body["refresh_rate"], until_end.total_seconds() + paging.QUIET_MARGIN, delta=90)
        sleep_name = body["filename"]
        await frames.refresh_frames(None)
        _, again = await self.wake(self.key)
        self.assertEqual(again["filename"], sleep_name, "the same sleep page: no download, no flash")

    async def test_a_button_press_during_quiet_hours_shows_a_page_briefly(self):
        now = datetime.now()
        await self.quiet(now - timedelta(hours=1), now + timedelta(hours=2))
        _, asleep = await self.wake(self.key)
        _, glance = await self.wake(self.key, source="button")
        self.assertNotEqual(glance["filename"], asleep["filename"])
        self.assertEqual(glance["refresh_rate"], paging.GLANCE_SECONDS)
        _, back = await self.wake(self.key)
        self.assertEqual(back["filename"], asleep["filename"], "the next timer wake is the sleep page again")

    async def test_it_wakes_for_the_start_of_quiet_hours(self):
        now = datetime.now()
        await self.quiet(now + timedelta(minutes=5), now + timedelta(hours=8))
        _, body = await self.wake(self.key)
        self.assertLessEqual(body["refresh_rate"], 6 * 60 + paging.QUIET_MARGIN)
        self.assertGreater(body["refresh_rate"], 3 * 60)

    async def test_an_alert_shows_through_quiet_hours_when_they_allow_it(self):
        now = datetime.now()
        await self.quiet(now - timedelta(hours=1), now + timedelta(hours=2))
        _, asleep = await self.wake(self.key)
        ahead = paging.ahead_of(self.dev)
        alerting = frames.DesignState("alert", ahead.st.live, ahead.st.plans)

        async def cycle():                               # the cycle, with an alert on
            await paging.draw_ahead(devices.get(self.dev["id"]), devices.view(self.dev["id"]), alerting,
                                    ahead.quiet, ahead.reason, trmnl.ART)
        await cycle()
        _, alert = await self.wake(self.key)
        self.assertNotEqual(alert["filename"], asleep["filename"])
        self.assertEqual(alert["refresh_rate"], 15 * 60)
        devices.update(self.dev["id"], quiet_hours={**devices.get(self.dev["id"])["quiet_hours"], "allow_alerts": False})
        await cycle()
        _, held = await self.wake(self.key)
        self.assertEqual(held["filename"], asleep["filename"])


class TestReachingHome(TrmnlBase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.dev = await self.add_trmnl()
        self.key = (await self.pair(self.dev["id"]))["api_key"]
        await frames.refresh_frames(None)

    async def via(self, peer, headers):
        transport = mock.Mock()
        transport.get_extra_info = lambda key, default=None: (peer, 40000) if key == "peername" else default
        req = make_mocked_request("GET", "/api/display", headers={**display_headers(self.key), **headers},
                                  transport=transport)
        return json.loads((await trmnl.api_display(req)).body)

    async def test_through_home_assistant_the_picture_is_under_its_address(self):
        reach.save("ha")
        body = await self.via("172.30.32.1", {"Host": "172.30.33.5:8099", "X-Forwarded-For": "203.0.113.9",
                                              "X-Forwarded-Host": "ha.example.com",
                                              "X-Forwarded-Proto": "https", "X-Forwarded-Prefix": "/api/epaper"})
        self.assertTrue(body["image_url"].startswith("https://ha.example.com/api/epaper/api/image/"),
                        "it starts with the server address the TRMNL was given, so its key goes along")

    async def test_through_your_own_tunnel(self):
        reach.save("own", "https://panel.example.com")
        body = await self.via("172.30.33.7", {"Host": "panel.example.com", "CF-Connecting-IP": "203.0.113.9",
                                              "X-Forwarded-For": "203.0.113.9", "X-Forwarded-Proto": "https"})
        self.assertTrue(body["image_url"].startswith("https://panel.example.com/api/image/"))

    async def test_on_the_home_network(self):
        body = await self.via("192.168.1.40", {"Host": "192.168.1.5:8099"})
        self.assertTrue(body["image_url"].startswith("http://192.168.1.5:8099/api/image/"))

    async def test_a_strange_host_is_not_put_into_an_address(self):
        from aiohttp import web as aioweb
        with self.assertRaises(aioweb.HTTPBadRequest):
            await self.via("192.168.1.40", {"Host": "evil.example.com/../x"})


class TestBatteryCurve(unittest.TestCase):
    def test_percent_from_volts(self):
        self.assertEqual(trmnl.battery_percent(4.25), 100)
        self.assertEqual(trmnl.battery_percent(4.10), 90)
        self.assertEqual(trmnl.battery_percent(3.80), 50)
        self.assertEqual(trmnl.battery_percent(3.775), 45)
        self.assertEqual(trmnl.battery_percent(3.10), 0)
        self.assertIsNone(trmnl.battery_percent(None))
        self.assertIsNone(trmnl.battery_percent(0.0), "no reading isn't an empty battery")


class TestSizes(unittest.TestCase):
    def test_the_og_and_any_other_size(self):
        self.assertEqual(T.sized_display("trmnl", 800, 480), "trmnl_og")
        made = T.get_display(T.sized_display("trmnl", 1872, 1404))
        self.assertEqual((made["kind"], made["w"], made["h"]), ("trmnl", 1872, 1404))
        self.assertEqual(T.canvas_dims(90, made["id"]), (1404, 1872))
        self.assertIsNone(T.sized_display("crowpanel", 1872, 1404), "a CrowPanel doesn't report sizes")
        self.assertIsNone(T.sized_display("trmnl", 10, 10))
        self.assertEqual(T.get_display("trmnl_99999x5")["id"], T.DEFAULT_DISPLAY)


if __name__ == "__main__":
    unittest.main()
