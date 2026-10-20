"""The footer band: decided once in theme.py, and everyone else asks there.

The renderer draws the hairline at the top of the band; automatic placement
(arrange.py) keeps elements above it; the editor's dashed footer zone starts
on it. All three come from theme.band_height()."""
import json
import shutil
import subprocess
import unittest

from aiohttp.test_utils import TestClient, TestServer

import support
import web
from render import arrange, theme as T
from test_devices import fresh_data_dir

ORIENTATIONS = (0, 90, 180, 270)
CLOCK = "23:58"
WEB_APP = support.APP / "web" / "app"

# The band by canvas height, hairline included. Changing these is a design
# decision: the panel, placement and the editor all move with it.
BAND_BY_HEIGHT = {128: 25, 272: 32, 296: 32, 300: 32, 400: 36, 480: 36, 640: 36, 792: 36, 800: 36, 960: 36}


def every_canvas():
    for display in T.DISPLAYS:
        for deg in ORIENTATIONS:
            yield display, deg


class TestOneSource(unittest.TestCase):
    def test_the_band_on_every_canvas(self):
        for display, deg in every_canvas():
            cw, ch = T.canvas_dims(deg, display)
            with self.subTest(display=display, orientation=deg):
                band = T.footer_band(deg, display)
                self.assertEqual(band, BAND_BY_HEIGHT[ch])
                plan = T.footer_plan(clock=CLOCK, orientation=deg, display=display)
                self.assertEqual(plan["band"], band)
                self.assertEqual(plan["rule_y"], ch - band, "the hairline is the top of the band")
                geo = T.canvas_geometry(deg, display)
                self.assertEqual(geo, {"w": cw, "h": ch, "band": band, "margin": plan["margin"]})
                self.assertEqual(arrange.content_height(arrange.canvas_key(cw, ch)), ch - band)

    def test_the_hairline_is_drawn_where_the_plan_says(self):
        for display, deg in every_canvas():
            with self.subTest(display=display, orientation=deg):
                img, draw = T.new_canvas(deg, display)
                plan = T.footer_plan(clock=CLOCK, orientation=deg, display=display)
                T.footer(draw, plan, label="preview")
                cw, ch = img.size
                ink = [y for y in range(ch) if all(img.getpixel((x, y)) == T.BLACK
                                                    for x in range(plan["margin"], cw - plan["margin"]))]
                self.assertEqual(ink, [ch - T.footer_band(deg, display)])

    def test_the_editor_keeps_no_copy(self):
        for js in sorted(WEB_APP.glob("*.js")):
            src = js.read_text()
            with self.subTest(file=js.name):
                self.assertNotRegex(src, r"\*\s*1\.8\b", "the band is theme.band_height(), sent with api/devices")
                self.assertNotRegex(src, r"<\s*200\s*\?\s*14", "the footer size is theme's")
        self.assertFalse(hasattr(arrange, "FOOTER_BAND"))


class TestTheEditorGetsItFromTheServer(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        fresh_data_dir()
        _, editor = web.make_apps()
        self.ed = TestClient(TestServer(editor))
        await self.ed.start_server()

    async def asyncTearDown(self):
        await self.ed.close()
        support.use_test_data_dir()

    async def displays(self):
        r = await self.ed.get("/api/devices")
        self.assertEqual(r.status, 200)
        return (await r.json())["displays"]

    async def test_every_display_comes_with_its_canvases(self):
        got = await self.displays()
        self.assertEqual(list(got), list(T.DISPLAYS))
        for display, d in T.DISPLAYS.items():
            with self.subTest(display=display):
                self.assertEqual(got[display]["landscape"], T.canvas_geometry(0, display))
                self.assertEqual(got[display]["portrait"], T.canvas_geometry(90, display))
                self.assertEqual((got[display]["w"], got[display]["h"], got[display]["mm_w"]), (d["w"], d["h"], d["mm_w"]))

    @unittest.skipUnless(shutil.which("node"), "needs node to run the editor's own code")
    async def test_the_dashed_line_sits_on_the_hairline(self):
        """The editor's geometry(), run as the browser runs it, on the table the server sent."""
        displays = await self.displays()
        script = f"""
            import {{ setDisplays, geometry }} from {json.dumps((WEB_APP / "elements.js").as_uri())};
            import {{ reflowPageElements }} from {json.dumps((WEB_APP / "legacy.js").as_uri())};
            setDisplays({json.dumps(displays)});
            const out = [];
            for (const display of {json.dumps(list(T.DISPLAYS))})
              for (const orientation of {json.dumps(ORIENTATIONS)}) {{
                const g = geometry({{ display, orientation }});
                const page = {{ elements: [{{ type: "dynamic_grid", x: 0, y: 0, w: 10, h: 10 }}] }};
                reflowPageElements(page, [90, 270].includes(orientation), g.d);
                out.push({{ display, orientation, W: g.W, H: g.H, footer: g.footer, safeH: g.safeH,
                            margin: g.margin, grid: page.elements[0] }});
              }}
            console.log(JSON.stringify(out));
        """
        run = subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True, text=True, timeout=30)
        self.assertEqual(run.returncode, 0, run.stderr)
        for g in json.loads(run.stdout):
            display, deg = g["display"], g["orientation"]
            with self.subTest(display=display, orientation=deg):
                plan = T.footer_plan(clock=CLOCK, orientation=deg, display=display)
                self.assertEqual((g["W"], g["H"]), plan["canvas"])
                self.assertEqual(g["safeH"], plan["rule_y"], "the dashed line is the panel's hairline")
                self.assertEqual(g["footer"], plan["band"])
                self.assertEqual(g["margin"], plan["margin"])
                # "Rearrange this page" fills the area above the band (less its 16 + 8 px of air).
                self.assertEqual(g["grid"]["y"] + g["grid"]["h"], plan["rule_y"] - 8)


if __name__ == "__main__":
    unittest.main()
