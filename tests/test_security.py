"""What the LAN port and the editor will and won't answer."""
import unittest

from aiohttp.test_utils import TestClient, TestServer

import support
import config
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
        body = await (await self.lan.get("/status")).json()
        self.assertTrue(body["ok"])
        for key in ("quiet_reason", "quiet_active", "cat_names"):
            self.assertNotIn(key, body)

    async def test_lan_actions_are_off_without_a_token(self):
        config.FRAME_TOKEN = ""
        r = await self.lan.post("/api/action/refresh")
        self.assertEqual(r.status, 403)
        self.assertIn("frame_token", await r.text())
        r = await self.lan.get("/api/action/refresh")         # a link preview can't trigger it
        self.assertEqual(r.status, 405)

    async def test_lan_actions_need_the_right_token(self):
        config.FRAME_TOKEN = "s3cret"
        r = await self.lan.post("/api/action/page", headers={"Authorization": "Bearer wrong"})
        self.assertEqual(r.status, 401)

    async def test_frames_carry_only_caching_headers(self):
        r = await self.lan.get("/frames.epf")
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
