"""Icons from Home Assistant: the outlines the panel draws (render/vector), the sets it has
(render/icons: shipped, copied from Home Assistant, custom), the copy itself (iconsets), the
editor's routes and its picker (web/app/glyphs.js under node)."""
import asyncio
import gzip
import io
import json
import shutil
import subprocess
import time
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import support
import config
import hass as hass_api
import health
import iconsets
from render import icons, layout, vector
from render import theme as T
from test_editor_api import EditorClient

GLYPHS_JS = support.APP / "web" / "app" / "glyphs.js"
SQUARE = "M2,2H22V22H2Z"
CAT_OUTLINE = "M12,4C9,4 4,7 4,13C4,18 8,21 12,21C16,21 20,18 20,13C20,7 15,4 12,4M12,6A3,3 0 0,1 15,9A3,3 0 0,1 12,12A3,3 0 0,1 9,9A3,3 0 0,1 12,6Z"


def ink(img) -> int:
    """Black pixels in a page or mask (a page: 0 is ink; a mask: 255 is)."""
    return img.convert("L").histogram()[0]


def mask_ink(m) -> int:
    return sum(m.convert("L").histogram()[128:])


class FakeResponse:
    def __init__(self, body, status=200):
        self.body, self.status = body, status

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def raise_for_status(self):
        if self.status >= 400:
            import aiohttp
            raise aiohttp.ClientResponseError(None, (), status=self.status)

    async def json(self, content_type=None):
        return self.body


class FakeFrontend:
    """Home Assistant's frontend files: /static/mdi/iconMetadata.json and its chunks."""

    def __init__(self, version="7.5.0", icons_by_part=None, broken=(), hang=None, down=False):
        self.version, self.broken, self.hang, self.down = version, set(broken), hang, down
        # Home Assistant's set: everything shipped, and one icon more.
        self.parts = icons_by_part or [dict(icons.shipped()["icons"]), {"cat-outline": CAT_OUTLINE}]
        self.asked = []

    def get(self, url, **kw):
        self.asked.append(url)
        if self.down:
            import aiohttp
            raise aiohttp.ClientConnectionError("Cannot connect to host homeassistant:8123")
        path = url.split("8123", 1)[1]
        if self.hang is not None:
            return self._hanging()
        if path == "/static/mdi/iconMetadata.json":
            return FakeResponse({"version": self.version, "parts": [{"file": f"p{i}"} for i in range(len(self.parts))]})
        i = int(path.rsplit("/p", 1)[1].removesuffix(".json"))
        return FakeResponse(["not", "icons"] if i in self.broken else self.parts[i])

    def _hanging(self):
        hang = self.hang

        class Hanging:
            async def __aenter__(self):
                await hang.wait()
                raise asyncio.TimeoutError()

            async def __aexit__(self, *a):
                return False
        return Hanging()


class FakeHass(hass_api.Hass):
    """The add-on's own Home Assistant client, with its calls answered here."""

    def __init__(self, version="2026.11.0", active=None):
        super().__init__("http://supervisor/core", "token", lambda: object())
        self.version, self.active, self.asked = version, active, []

    async def rest(self, method, path, json=None, timeout=15):
        assert (method, path) == ("GET", "/config")
        return {"version": self.version}


class IconTest(unittest.TestCase):
    """A data folder of its own, and the sets as shipped."""

    def setUp(self):
        support.fresh_data_dir()
        self._sets = dict(icons._sets)
        icons._sets.clear()

    def tearDown(self):
        icons._sets.clear()
        icons._sets.update(self._sets)
        support.use_test_data_dir()


class TestOutlines(unittest.TestCase):
    def test_every_command_reads(self):
        d = "M2 2h4v4H2zM8,8 l2,0 0,2 -2,0z m4,0 c1,0 2,1 2,2 s-1,2 -2,2 q-1,0 -1,-1 t1,-1 Z M3 20a2 2 0 1 0 4 0a2 2 0 01 -4 0"
        segs = vector.segments(d)
        self.assertTrue(segs and all(s[0] in "MLCZ" for s in segs))
        self.assertTrue(vector.check(d))
        # arc flags run together ("01") read as two flags
        self.assertEqual(vector.segments("M0 0a1 1 0 012 0"), vector.segments("M0 0a1 1 0 0 1 2 0"))

    def test_a_hole_is_a_subpath_the_other_way_round(self):
        hole = vector.mask("M2,2H22V22H2ZM8,8V16H16V8Z", 24)      # inner square wound the other way
        same = vector.mask("M2,2H22V22H2ZM8,8H16V16H8Z", 24)      # the same way: no hole (non-zero)
        self.assertLess(hole.getpixel((12, 12)), 128)
        self.assertGreaterEqual(same.getpixel((12, 12)), 128)
        odd = vector.mask({"e": "M2,2H22V22H2ZM8,8H16V16H8Z"}, 24)  # even-odd: a hole either way
        self.assertLess(odd.getpixel((12, 12)), 128)
        self.assertGreaterEqual(odd.getpixel((4, 4)), 128)

    def test_a_view_box_is_fitted_and_centred(self):
        wide = vector.mask({"d": "M0,0H48V24H0Z", "v": [0, 0, 48, 24]}, 48)
        self.assertGreaterEqual(wide.getpixel((24, 24)), 128)
        self.assertLess(wide.getpixel((24, 4)), 128, "a 2:1 view box sits in the middle of the square")

    def test_a_stroke_draws_a_line(self):
        m = vector.mask({"s": [["M4,12L20,12", 2]]}, 24)
        self.assertGreaterEqual(m.getpixel((12, 12)), 128)
        self.assertLess(m.getpixel((12, 4)), 128)

    def test_normalize_keeps_the_shape(self):
        d = "M12,2A10,10 0 0,0 2,12A10,10 0 0,0 12,22A10,10 0 0,0 22,12A10,10 0 0,0 12,2Z"
        n = vector.normalize(d)
        self.assertNotRegex(n, r"[AaSsQqTtHhVv]")
        self.assertEqual(vector.cut(d, 48).tobytes(), vector.cut(n, 48).tobytes())
        moved = vector.normalize(d, (0.5, 0, 0, 0.5, 6, 6))           # half size, in the middle
        self.assertLess(mask_ink(vector.cut(moved, 48)), mask_ink(vector.cut(d, 48)) / 3)

    def test_bad_paths_are_refused_not_drawn(self):
        for bad in ("", "12 12", "M1", "Mx,y", {"d": SQUARE, "v": [0, 0, 0, 24]}, 42):
            self.assertFalse(vector.check(bad), repr(bad))

    def test_the_same_shapes_as_the_old_font(self):
        # Drawn from outlines, every icon matches what the font drew to within a few percent of its
        # ink at 48 px, an edge pixel here and there (the font's hinting differs most at small sizes).
        from PIL import Image, ImageChops, ImageDraw
        for name in ("cat", "paw", "radiator", "washing-machine", "door-open", "weather-partly-cloudy", "lightbulb-on", "fan"):
            rec = icons.get("mdi:" + name)
            mine = vector.cut(rec, 48)
            img = Image.new("L", (48, 48), 255)
            ImageDraw.Draw(img).text((24, 24), chr(layout.mdi_codepoint(name)), font=layout._mdi_font(48), fill=0, anchor="mm")
            font = img.point(lambda p: 255 if p < 128 else 0)
            off = sum(ImageChops.difference(mine, font).histogram()[1:])
            self.assertLess(off / max(1, mask_ink(font)), 0.10, name)


class TestPagesLookAsBefore(unittest.TestCase):
    def test_an_icon_is_the_size_it_was_in_its_box(self):
        # Pages drawn before icons came from outlines: the same icons at the same sizes, give or take
        # an edge pixel (the old font measured an icon across by its whole square).
        spec = json.loads((support.APP / "default_layouts.json").read_text())
        from PIL import ImageChops
        try:
            for name, page in spec["pages"].items():
                icons.FROM_FONT = True
                old = T.to_1bit(layout.render_page(page, {})).convert("L")
                icons.FROM_FONT = False
                new = T.to_1bit(layout.render_page(page, {})).convert("L")
                off = sum(ImageChops.difference(old, new).histogram()[1:])
                self.assertLess(off, max(300, ink(old) * 0.02), name)
        finally:
            icons.FROM_FONT = False


class TestTheShippedSet(IconTest):
    def test_it_is_home_assistants_version_and_complete(self):
        s = icons.shipped()
        self.assertEqual(s["version"], "7.4.47")
        self.assertGreaterEqual(len(s["icons"]), 7447)
        font = json.loads((support.APP / "fonts" / "mdi-codepoints.json").read_text())
        self.assertEqual(set(font) - set(s["icons"]), {"blank"}, "everything the font drew, but its empty one")

    def test_every_shipped_icon_reads(self):
        bad = [n for n, d in icons.shipped()["icons"].items() if not vector.check(d)]
        self.assertEqual(bad, [])

    def test_names(self):
        self.assertEqual(icons.split("mdi:Cat"), ("mdi", "cat"))
        self.assertEqual(icons.split("cat"), ("mdi", "cat"))
        self.assertEqual(icons.split("phu:France2"), ("phu", "France2"), "a custom set's names keep their case")
        self.assertTrue(layout.can_draw_icon("mdi:cat") and layout.can_draw_icon("cat"))
        self.assertFalse(layout.can_draw_icon("mdi:cat-outline"), "not in Material Design 7.4.47")


class TestCopyingHomeAssistantsSet(IconTest):
    def copy(self, frontend, hass=None):
        return asyncio.run(iconsets.copy_home_assistant(frontend, hass or FakeHass()))

    def test_an_icon_missing_from_the_shipped_set_draws_once_copied(self):
        page = {"elements": [{"type": "icon", "icon": "mdi:cat-outline", "x": 10, "y": 10, "w": 120, "h": 120}]}
        self.assertFalse(layout.can_draw_icon("mdi:cat-outline"))
        self.assertEqual(ink(layout.render_page(page, {})), ink(layout.render_page({"elements": []}, {})))
        said = self.copy(FakeFrontend())
        self.assertEqual(said, f"copied {len(icons.shipped()['icons']) + 1} icons (7.5.0)")
        self.assertTrue(layout.can_draw_icon("mdi:cat-outline"))
        self.assertGreater(ink(layout.render_page(page, {})), ink(layout.render_page({"elements": []}, {})) + 500)
        # Kept in the add-on's data and used again at the next start, before anything is drawn.
        icons._sets.clear()
        self.assertFalse(layout.can_draw_icon("mdi:cat-outline"))
        iconsets.load_copies()
        self.assertTrue(layout.can_draw_icon("mdi:cat-outline"))

    def test_only_when_home_assistants_version_changes(self):
        fe = FakeFrontend()
        self.copy(fe)
        asked = len(fe.asked)
        self.assertEqual(self.copy(fe), "unchanged")
        self.assertEqual(len(fe.asked), asked, "nothing fetched while Home Assistant's version is the same")
        self.assertIn("already copied", self.copy(fe, FakeHass("2026.12.0")))

    def test_the_same_set_as_shipped_isnt_copied(self):
        fe = FakeFrontend(version=icons.shipped()["version"])
        self.assertIn("the same as the add-on's", self.copy(fe))
        self.assertEqual(len(fe.asked), 1, "only the list, never the chunks")
        self.assertFalse((iconsets.icon_dir() / "mdi.json.gz").exists())
        self.assertIs(icons.set_for("mdi"), icons.shipped())

    def test_all_or_nothing(self):
        fe = FakeFrontend(icons_by_part=[dict(icons.shipped()["icons"]), {"cat-outline": CAT_OUTLINE}], broken={1})
        with self.assertRaises(ValueError):
            self.copy(fe)
        self.assertIs(icons.set_for("mdi"), icons.shipped())
        fe = FakeFrontend(icons_by_part=[dict(icons.shipped()["icons"]), {"cat-outline": "M1 nonsense"}])
        with self.assertRaises(ValueError):
            self.copy(fe)
        self.assertFalse(layout.can_draw_icon("mdi:cat-outline"))
        self.assertFalse((iconsets.icon_dir() / "mdi.json.gz").exists())

    def test_too_few_icons_is_not_a_set(self):
        with self.assertRaises(ValueError):
            iconsets._checked_mdi({"cat": SQUARE}, "7.5.0", shipped_count=7447)

    def test_home_assistant_unreachable_falls_back_to_the_shipped_set(self):
        health._services.pop(iconsets.HEALTH, None)

        async def go():
            with mock.patch.object(iconsets, "CHECK_EVERY", 3600), mock.patch.object(iconsets, "copy_custom", lambda: "unchanged"):
                task = asyncio.create_task(iconsets.keep_in_step(FakeFrontend(down=True), FakeHass()))
                await asyncio.sleep(0.05)
                task.cancel()
        asyncio.run(go())
        self.assertIsNotNone(health._services[iconsets.HEALTH]["failing_since"], "shown in the problem sensors")
        self.assertIs(icons.set_for("mdi"), icons.shipped())
        self.assertTrue(layout.can_draw_icon("mdi:cat"))
        page = {"elements": [{"type": "icon", "icon": "mdi:cat", "x": 10, "y": 10, "w": 120, "h": 120}]}
        self.assertGreater(ink(layout.render_page(page, {})), ink(layout.render_page({"elements": []}, {})) + 500)

    def test_a_render_never_waits_on_the_copy(self):
        page = {"elements": [{"type": "icon", "icon": "mdi:cat", "x": 10, "y": 10, "w": 120, "h": 120}]}

        async def go():
            hang = asyncio.Event()
            task = asyncio.create_task(iconsets.copy_home_assistant(FakeFrontend(hang=hang), FakeHass()))
            await asyncio.sleep(0.01)                      # the copy is waiting on Home Assistant
            t = time.monotonic()
            img = layout.render_page(page, {})
            took = time.monotonic() - t
            self.assertFalse(task.done())
            hang.set()
            with self.assertRaises(asyncio.TimeoutError):
                await task
            return img, took
        img, took = asyncio.run(go())
        self.assertLess(took, 2.0)
        self.assertGreater(ink(img), ink(layout.render_page({"elements": []}, {})) + 500, "drawn from the shipped set meanwhile")

    def test_drawing_never_reaches_out(self):
        for f in ("render/icons.py", "render/vector.py", "render/layout.py"):
            text = (support.APP / f).read_text()
            for word in ("aiohttp", "iconsets", "urllib", "requests"):
                self.assertNotIn(f"import {word}", text, f"{f} imports {word}")


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def custom_icons_entry(cfg: Path, on: dict):
    write(cfg / ".storage" / "core.config_entries", json.dumps({"data": {"entries": [
        {"domain": "custom_icons", "data": on, "disabled_by": None}]}}))


CAT_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">
  <g transform="translate(16 16)"><circle r="12"/></g>
  <rect x="2" y="2" width="6" height="6" rx="1" fill="currentColor" style="fill:#000"/>
  <path d="M4 28H28" stroke="black" stroke-width="2" fill="none"/>
</svg>"""


class TestCustomSets(IconTest):
    def setUp(self):
        super().setUp()
        self.cfg = support.temp_dir()

    def test_svg_shapes_become_one_outline(self):
        rec = iconsets.svg_record(CAT_SVG)
        self.assertEqual(rec["v"], [0, 0, 32, 32])
        self.assertIn("s", rec, "the stroked line")
        m = vector.mask(rec, 32)
        self.assertGreaterEqual(m.getpixel((16, 16)), 128, "the circle, moved by its group")
        self.assertGreaterEqual(m.getpixel((4, 4)), 128, "the rectangle")
        self.assertGreaterEqual(m.getpixel((16, 28)), 128, "the line")
        self.assertLess(m.getpixel((30, 4)), 128)

    def test_nothing_in_an_svg_runs_or_is_kept_as_it_is(self):
        evil = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" onload="alert(1)">
          <script>alert(1)</script><image href="http://example.invalid/x.png" width="24" height="24"/>
          <a href="javascript:alert(1)"><path d="M0 0H24V24H0Z"/></a><path d="M2 2H10V10H2Z" onclick="alert(1)"/></svg>"""
        rec = iconsets.svg_record(evil)
        self.assertEqual(set(rec), {"d", "v"})
        self.assertNotRegex(json.dumps(rec), r"alert|script|href|onload|onclick|example")
        self.assertIsNone(iconsets.svg_record('<?xml version="1.0"?><!DOCTYPE svg [<!ENTITY a "aaaa">]><svg>&a;</svg>'))
        self.assertIsNone(iconsets.svg_record("<svg xmlns='http://www.w3.org/2000/svg'><text>Hi</text></svg>"), "nothing to draw")
        self.assertIsNone(iconsets.svg_record("not svg"))
        self.assertIsNone(iconsets.svg_record("<svg>" + "<path d='M0 0H1V1Z'/>" * 40000 + "</svg>"), "too big")

    def test_custom_icons_local_folder(self):
        write(self.cfg / "custom_icons" / "cat-outside.svg", CAT_SVG)
        write(self.cfg / "custom_icons" / "pets" / "Dog.svg", CAT_SVG)
        write(self.cfg / "custom_icons" / "broken.svg", "<svg><path d='nonsense'/></svg>")
        write(self.cfg / "custom_icons" / "rpg-webfont.svg", CAT_SVG)
        custom_icons_entry(self.cfg, {"local": True})
        said = iconsets.copy_custom(self.cfg)
        self.assertEqual(said, "local: 2")
        self.assertTrue(layout.can_draw_icon("local:cat-outside") and layout.can_draw_icon("local:pets/Dog"))
        self.assertFalse(layout.can_draw_icon("local:broken") or layout.can_draw_icon("local:rpg-webfont"))
        page = {"elements": [{"type": "icon", "icon": "local:cat-outside", "x": 10, "y": 10, "w": 120, "h": 120}]}
        self.assertGreater(ink(layout.render_page(page, {})), ink(layout.render_page({"elements": []}, {})) + 500)

    def test_only_what_custom_icons_has_switched_on(self):
        write(self.cfg / "custom_icons" / "cat-outside.svg", CAT_SVG)
        self.assertEqual(iconsets.copy_custom(self.cfg), "none", "Custom Icons isn't set up")
        custom_icons_entry(self.cfg, {"local": False})
        self.assertEqual(iconsets.copy_custom(self.cfg), "none")
        custom_icons_entry(self.cfg, {"local": True})
        self.assertEqual(iconsets.copy_custom(self.cfg), "local: 1")

    def test_copied_whole_only_when_the_files_change(self):
        write(self.cfg / "custom_icons" / "a.svg", CAT_SVG)
        custom_icons_entry(self.cfg, {"local": True})
        self.assertEqual(iconsets.copy_custom(self.cfg), "local: 1")
        with mock.patch.object(iconsets, "read_custom_sets", side_effect=AssertionError("read again")):
            self.assertEqual(iconsets.copy_custom(self.cfg), "unchanged")
        write(self.cfg / "custom_icons" / "b.svg", CAT_SVG)
        self.assertEqual(iconsets.copy_custom(self.cfg), "local: 2")
        (self.cfg / "custom_icons" / "a.svg").unlink()
        (self.cfg / "custom_icons" / "b.svg").unlink()
        self.assertEqual(iconsets.copy_custom(self.cfg), "none")
        self.assertFalse(layout.can_draw_icon("local:a"), "a set that's gone isn't offered any more")

    def test_an_iconify_set_custom_icons_downloaded(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("icon-sets-master/json/ph.json", json.dumps({"prefix": "ph", "info": {"name": "Phosphor"}, "width": 256, "height": 256,
                "icons": {"cat": {"body": '<path fill="currentColor" d="M16 16H240V240H16Z"/>'}, "spin": {"body": "<path d='M0 0H9V9Z'/>", "rotate": 1}}}))
            zf.writestr("icon-sets-master/json/other.json", json.dumps({"prefix": "other", "icons": {"x": {"body": "<path d='M0 0H9V9Z'/>"}}}))
        write(self.cfg / "custom_icons" / "x.svg", CAT_SVG)
        (self.cfg / "custom_icons" / "iconify-icon-sets-master.zip").write_bytes(buf.getvalue())
        custom_icons_entry(self.cfg, {"ph": True, "other": False})
        self.assertEqual(iconsets.copy_custom(self.cfg), "ph: 1")
        self.assertTrue(layout.can_draw_icon("ph:cat"))
        self.assertEqual(icons.set_for("ph")["name"], "Phosphor")

    def test_a_script_set_like_brand_icons(self):
        js = """var icons = {
  "02tv":[0,0,24,24,"M2 2H22V22H2Z"],
  "Hydro-Québec":[0,0,48,24,"M0 0H48V24H0Z","M1 1H2V2Z"],
  "bad":[0,0,24,24,"M nonsense"],
};

window.customIcons = window.customIcons || {};
window.customIcons["phu"] = { getIcon, getIconList };
"""
        write(self.cfg / "www" / "community" / "custom-brand-icons" / "custom-brand-icons.js", js)
        write(self.cfg / "www" / "community" / "other-card" / "card.js", "customElements.define('x', class {});")
        write(self.cfg / "www" / "community" / "clash" / "clash.js", js.replace('"phu"', '"mdi"'))
        self.assertEqual(iconsets.copy_custom(self.cfg), "phu: 2")
        self.assertTrue(layout.can_draw_icon("phu:Hydro-Québec") and layout.can_draw_icon("phu:02tv"))
        self.assertFalse(layout.can_draw_icon("phu:bad"))
        self.assertEqual(icons.set_for("phu")["name"], "Custom brand icons")
        self.assertIs(icons.set_for("mdi"), icons.shipped(), "a set can't take Material Design's prefix")

    def test_a_bad_file_never_stops_the_loop(self):
        async def go():
            with mock.patch.object(iconsets, "copy_custom", side_effect=OSError("disk")), mock.patch.object(iconsets, "CHECK_EVERY", 3600):
                task = asyncio.create_task(iconsets.keep_in_step(None, None))
                await asyncio.sleep(0.02)
                self.assertFalse(task.done())
                task.cancel()
        asyncio.run(go())


class TestEditorRoutes(EditorClient):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self._sets = dict(icons._sets)

    async def asyncTearDown(self):
        icons._sets.clear()
        icons._sets.update(self._sets)
        icons.FROM_FONT = False
        await super().asyncTearDown()

    async def test_the_list_is_what_the_panel_can_draw(self):
        r = await self.ed.get("/api/icons")
        body = await r.json()
        self.assertEqual([s["prefix"] for s in body["sets"]], ["mdi"])
        self.assertIn("cat", body["names"]["mdi"])
        self.assertNotIn("cat-outline", body["names"]["mdi"])
        again = await self.ed.get("/api/icons", headers={"If-None-Match": r.headers["ETag"]})
        self.assertEqual(again.status, 304)
        icons.install("phu", {"name": "Custom brand icons", "icons": {"02tv": SQUARE}})
        icons.install("mdi", {"version": "7.5.0", "from": "home_assistant", "icons": {**icons.shipped()["icons"], "cat-outline": CAT_OUTLINE}})
        r2 = await self.ed.get("/api/icons", headers={"If-None-Match": r.headers["ETag"]})
        self.assertEqual(r2.status, 200, "a new set is a new list")
        body = await r2.json()
        self.assertEqual([s["prefix"] for s in body["sets"]], ["mdi", "phu"])
        self.assertIn("cat-outline", body["names"]["mdi"])
        self.assertEqual(body["names"]["phu"], ["02tv"])

    async def test_outlines_in_pages(self):
        icons.install("phu", {"icons": {"02tv": {"d": SQUARE, "v": [0, 0, 48, 24]}}})
        r = await self.ed.post("/api/icons/outlines", json={"names": ["mdi:cat", "phu:02tv", "mdi:nope", "custom:cat-sitting", 4]})
        got = (await r.json())["icons"]
        self.assertEqual(set(got), {"mdi:cat", "phu:02tv"})
        self.assertEqual(got["phu:02tv"]["v"], [0, 0, 48, 24])
        r = await self.ed.post("/api/icons/outlines", json={"names": ["mdi:cat"] * 601})
        self.assertEqual(r.status, 400)

    async def test_the_way_back_lists_the_fonts_icons(self):
        icons.install("phu", {"icons": {"02tv": SQUARE}})
        icons.FROM_FONT = True
        body = await (await self.ed.get("/api/icons")).json()
        self.assertEqual([s["prefix"] for s in body["sets"]], ["mdi"])
        font = json.loads((support.APP / "fonts" / "mdi-codepoints.json").read_text())
        self.assertEqual(set(body["names"]["mdi"]), set(font) - {"blank"})


@unittest.skipUnless(shutil.which("node"), "no node to run the editor's icons")
class TestThePicker(unittest.TestCase):
    def run_js(self, body):
        script = f"import * as G from {json.dumps(str(GLYPHS_JS))};\n{body}"
        return json.loads(subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True, text=True, check=True).stdout)

    def test_search_across_sets_and_one_set(self):
        got = self.run_js("""
const names = { mdi: ["cat", "cat-outline", "paw", "television", "radiator"], phu: ["France2", "catalan-tv", "02tv"], local: ["pets/cat-outside"] };
console.log(JSON.stringify([
  G.search(names, "cat"),
  G.search(names, "cat", { only: "phu" }),
  G.search(names, "tv"),
  G.search(names, "phu:fr"),
  G.search(names, "pets", { terms: { pets: ["cat", "paw"] } }),
  G.search(names, "", { popular: ["paw"] }).slice(0, 2),
  [G.fullName("Cat"), G.fullName("mdi:Cat"), G.fullName("phu:France2"), G.fullName(""), G.prefixOf("x"), G.shortName("local:pets/a")],
  G.layersOf({ d: "M0 0Z", e: "M1 1Z", s: [["M2 2L3 3", 2]], v: [0, 0, 48, 24] }),
]));""")
        cat, cat_phu, tv, phu_fr, pets, popular, names, layers = got
        self.assertEqual(cat[:2], ["mdi:cat", "mdi:cat-outline"])
        self.assertIn("phu:catalan-tv", cat)
        self.assertIn("local:pets/cat-outside", cat)
        self.assertEqual(cat_phu, ["phu:catalan-tv"])
        self.assertEqual(set(tv), {"phu:catalan-tv", "phu:02tv"}, "found by its words, in any set")
        self.assertEqual(phu_fr, ["phu:France2"], "a prefix in the search picks the set")
        self.assertEqual(pets[:2], ["mdi:cat", "mdi:paw"], "a shortcut's own icons first")
        self.assertEqual(popular[0], "mdi:paw")
        self.assertEqual(names, ["mdi:cat", "mdi:cat", "phu:France2", "", "mdi", "pets/a"])
        self.assertEqual(layers, {"view": [0, 0, 48, 24], "layers": [{"d": "M0 0Z", "rule": "nonzero"}, {"d": "M1 1Z", "rule": "evenodd"}, {"d": "M2 2L3 3", "width": 2}]})

    def test_an_icon_that_didnt_arrive_is_asked_for_again(self):
        # The add-on restarting while the picker is open: no icon stays blank for good.
        got = self.run_js("""
const made = [];
globalThis.document = { createElementNS: (ns, t) => { const n = { t, a: {}, kids: [], isConnected: true, classList: { add() {} },
  setAttribute(k, v) { this.a[k] = v; }, getAttribute(k) { return this.a[k]; }, replaceChildren(...k) { this.kids = k; } }; made.push(n); return n; } };
let calls = 0, listCalls = 0;
const post = async (path, body) => { calls++; if (calls === 1) throw new Error("Failed to fetch"); return { icons: Object.fromEntries(body.names.map((n) => [n, "M0 0H24V24H0Z"])) }; };
const get = async () => { listCalls++; if (listCalls === 1) throw new Error("Failed to fetch"); return { sets: [{ prefix: "phu", count: 2 }], names: { phu: ["ARD", "Kika"] } }; };
const g = new G.Glyphs(get, post);
const a = g.node("phu:ARD"), b = g.node("phu:Kika"), gone = g.node("phu:Kika");
await g.load();                                   // the list fails: not ready, asked again
const readyAfterFail = g.ready();
await new Promise((r) => setTimeout(r, 2100));    // ... and arrives
gone.isConnected = false;
await new Promise((r) => setTimeout(r, 50));      // the outlines fail once
const blankAfterFail = a.kids.length === 0;
await new Promise((r) => setTimeout(r, 2100));    // asked again
console.log(JSON.stringify({ readyAfterFail, ready: g.ready(), blankAfterFail, a: a.kids.length, b: b.kids.length, gone: gone.kids.length, calls }));""")
        self.assertEqual(got, {"readyAfterFail": False, "ready": True, "blankAfterFail": True, "a": 1, "b": 1, "gone": 0, "calls": 2})

    def test_the_editor_draws_from_outlines_only(self):
        web = support.APP / "web"
        for f in [*sorted((web / "app").glob("*.js")), web / "index.html", web / "editor.css"]:
            text = f.read_text()
            self.assertNotIn("api/mdi", text, f"{f.name} still uses the old icon font")
            self.assertNotIn("mdiGlyph", text, f.name)
            if f.name != "glyphs.js":
                self.assertNotRegex(text, r"innerHTML\s*=.*(icon|glyph|outline)", f.name)
        pickers = (web / "app" / "pickers.js").read_text()
        self.assertIn("app.searchIcons(", pickers)
        self.assertIn("setRow.hidden = sets.length < 2", pickers, "set chips only when there's more than one set")


class TestEverySize(unittest.TestCase):
    def test_icons_draw_at_every_offered_size(self):
        # An icon element filling a box, on every screen size the add-on offers, from 24 px to the
        # whole height: ink in it, and none outside its box.
        names = ["mdi:cat", "mdi:radiator", "mdi:weather-partly-cloudy", "mdi:door-open"]
        for key, disp in T.DISPLAYS.items():
            w, h = disp["w"], disp["h"]
            for side in sorted({24, 48, 96, min(w, h) - 20}):
                page = {"elements": [{"type": "icon", "icon": n, "x": 10 + i * (side + 4), "y": 10, "w": side, "h": side}
                                     for i, n in enumerate(names) if 10 + (i + 1) * (side + 4) <= w]}
                img = layout.render_page(page, {}, display=key)
                blank = layout.render_page({"elements": []}, {}, display=key)
                self.assertGreater(ink(img), ink(blank), f"{key} at {side}")


if __name__ == "__main__":
    unittest.main()
