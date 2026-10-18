"""Integration tests for .epf binary endpoints in server.py without network sockets."""
import os
import tempfile
from pathlib import Path

# Ensure DATA_DIR is a writable local directory before server setup
if "DATA_DIR" not in os.environ:
    os.environ["DATA_DIR"] = "/tmp/epaper-data"

import unittest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request
from addon.app import server
from addon.app.render import epf

server.DATA_DIR = Path(os.environ["DATA_DIR"])
server.LAYOUTS_PATH = server.DATA_DIR / "layouts.json"
server.PANEL_SETUP_PATH = server.DATA_DIR / "panel_setup.json"
server.DATA_DIR.mkdir(parents=True, exist_ok=True)


class TestEpfServerEndpoints(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Trigger an in-memory frame refresh
        await server.refresh_frames(None)

    async def test_frames_epf_endpoint_and_etag(self):
        req = make_mocked_request("GET", "/frames.epf")
        resp = await server.frames_epf(req)

        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.headers.get("Content-Type"), "application/octet-stream")
        self.assertEqual(resp.headers.get("X-EPF-Version"), "3.0")

        etag = resp.headers.get("ETag")
        self.assertTrue(bool(etag))

        body = resp.body
        self.assertTrue(len(body) > 64)

        # Validate that the body decodes cleanly via epf
        stream = epf.decode_epf(body)
        self.assertEqual(stream.header.magic, epf.MAGIC)
        self.assertEqual(stream.header.version, 3)
        self.assertTrue(stream.header.page_count >= 1)

        # Test Conditional GET (304 Not Modified)
        req_304 = make_mocked_request("GET", "/frames.epf", headers={"If-None-Match": etag})
        with self.assertRaises(web.HTTPNotModified):
            await server.frames_epf(req_304)

    async def test_single_frame_epf_endpoint(self):
        req = make_mocked_request("GET", "/frame.epf?page=0")
        resp = await server.frame_epf(req)

        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.headers.get("Content-Type"), "application/octet-stream")

        body = resp.body
        stream = epf.decode_epf(body)
        self.assertEqual(stream.header.page_count, 1)
        self.assertEqual(stream.header.cat_count, 1)

        etag = resp.headers.get("ETag")
        req_304 = make_mocked_request("GET", "/frame.epf?page=0", headers={"If-None-Match": etag})
        with self.assertRaises(web.HTTPNotModified):
            await server.frame_epf(req_304)

    async def test_api_epf_client_h_endpoint(self):
        req = make_mocked_request("GET", "/api/epf_client.h")
        resp = await server.api_epf_client_h(req)
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.headers.get("Content-Type"), "text/x-c")
        self.assertIn("attachment", resp.headers.get("Content-Disposition", ""))


if __name__ == "__main__":
    unittest.main()

