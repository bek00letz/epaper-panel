"""What the LAN port and the editor will and won't answer."""
import unittest

from aiohttp.test_utils import TestClient, TestServer

import support
import config
import frame_token
import frames
import web


class TestEditorPeers(unittest.TestCase):
    def test_under_home_assistant_only_ingress_gets_in(self):
        self.assertTrue(web.editor_peer_allowed("172.30.32.2", under_supervisor=True))
        self.assertTrue(web.editor_peer_allowed("::ffff:172.30.32.2", under_supervisor=True))
        self.assertFalse(web.editor_peer_allowed("172.30.33.7", under_supervisor=True))   # another app
        self.assertFalse(web.editor_peer_allowed("127.0.0.1", under_supervisor=True))

    def test_locally_only_loopback_gets_in(self):
        self.assertTrue(web.editor_peer_allowed("127.0.0.1", under_supervisor=False))
        self.assertFalse(web.editor_peer_allowed("192.168.1.20", under_supervisor=False))


class TestRoutes(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        support.use_test_data_dir()
        await frames.refresh_frames(None)
        self.panel, self.editor = web.make_apps()
        self.lan = TestClient(TestServer(self.panel))
        self.ed = TestClient(TestServer(self.editor))
        await self.lan.start_server()
        await self.ed.start_server()
        self._saved = (config.FRAME_TOKEN, config.UNDER_SUPERVISOR)

    async def asyncTearDown(self):
        config.FRAME_TOKEN, config.UNDER_SUPERVISOR = self._saved
        await self.lan.close()
        await self.ed.close()

    async def test_lan_no_longer_serves_layouts_or_manifest(self):
        for path in ("/api/layouts", "/manifest.json", "/api/manifest"):
            r = await self.lan.get(path)
            self.assertEqual(r.status, 404, path)

    async def test_lan_status_says_nothing_about_presence_or_pages(self):
        config.FRAME_TOKEN = ""
        body = await (await self.lan.get(f"/status?token={frame_token.token()}")).json()
        self.assertTrue(body["ok"])
        for key in ("quiet_reason", "quiet_active", "cat_names"):
            self.assertNotIn(key, body)

    async def test_lan_actions_always_need_the_token(self):
        config.FRAME_TOKEN = ""
        r = await self.lan.post("/api/action/refresh")
        self.assertEqual(r.status, 401)
        r = await self.lan.get("/api/action/refresh")         # a link preview can't trigger it
        self.assertEqual(r.status, 405)

    async def test_switch_over_never_leaves_the_panel_blank(self):
        config.FRAME_TOKEN = ""
        (config.DATA_DIR / frame_token.SEEN_FILE).unlink(missing_ok=True)
        tok = frame_token.token()
        self.assertEqual(tok, frame_token.token(), "the generated token is kept")
        self.assertEqual((await self.lan.get("/frames.epf")).status, 200, "old firmware still gets frames")
        self.assertEqual((await self.lan.get("/frames.epf?token=nope")).status, 401)
        self.assertEqual((await self.lan.get(f"/frames.epf?token={tok}")).status, 200, "new firmware switches it on")
        self.assertEqual((await self.lan.get("/frames.epf")).status, 401, "from then on, no token no frames")
        self.assertEqual((await self.lan.get("/status")).status, 401)
        (config.DATA_DIR / frame_token.SEEN_FILE).unlink(missing_ok=True)

    async def test_an_explicit_token_is_required_from_the_start(self):
        config.FRAME_TOKEN = "chosen-by-you"
        self.assertEqual((await self.lan.get("/frames.epf")).status, 401)
        self.assertEqual((await self.lan.get("/frames.epf?token=chosen-by-you")).status, 200)

    async def test_the_panel_yaml_carries_the_token(self):
        config.FRAME_TOKEN = ""
        import panel_setup
        yaml_text, _ = panel_setup.generate_esphome_yaml(panel_setup.load_panel_setup())
        self.assertIn(f"/frames.epf?token={frame_token.token()}", yaml_text)
        self.assertIn("encryption: {}", yaml_text)
        self.assertNotIn("password: ", yaml_text.split("ota:")[1].split("wifi:")[0], "no OTA password")

    async def test_lan_actions_need_the_right_token(self):
        config.FRAME_TOKEN = "s3cret"
        r = await self.lan.post("/api/action/page", headers={"Authorization": "Bearer wrong"})
        self.assertEqual(r.status, 401)

    async def test_frames_carry_only_caching_headers(self):
        config.FRAME_TOKEN = ""
        r = await self.lan.get(f"/frames.epf?token={frame_token.token()}")
        self.assertEqual(r.status, 200)
        self.assertFalse([h for h in r.headers if h.lower().startswith("x-cat") or h.lower() == "x-quiet-hours"])

    async def test_editor_refuses_anything_but_ingress(self):
        config.UNDER_SUPERVISOR = True                          # test client connects from 127.0.0.1
        r = await self.ed.get("/api/status")
        self.assertEqual(r.status, 403)
        config.UNDER_SUPERVISOR = False
        r = await self.ed.get("/api/status")
        self.assertEqual(r.status, 200)


if __name__ == "__main__":
    unittest.main()
