"""The firmware against the server, without a panel.

* Footer geometry the server sends matches the footer it draws, in every orientation.
* The firmware core (components/epf/epf_core.h), compiled on this machine,
  parses the server's real frame files, maps pixels exactly as the server's
  rotate-and-mirror pipeline does, refuses bad files, and keeps locks.
* The generated ESPHome YAML has no gaps, is pinned to the release, and the
  repository's copy is exactly what the generator produces.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("DATA_DIR", "/tmp/epaper-data")
sys.path.insert(0, str(ROOT / "addon" / "app"))

from PIL import Image  # noqa: E402

import firmware_gen  # noqa: E402
import server  # noqa: E402
from render import epf, theme as T  # noqa: E402

DISPLAY = "crowpanel_579"
CLOCK = "12:34"


def pipeline(logical: Image.Image, deg: int) -> Image.Image:
    """Exactly what build_frames + encode_epf do to a page before packing."""
    phys = T.orient_for_panel(T.to_1bit(logical), deg, display=DISPLAY)
    if DISPLAY in epf.MIRRORED_MODELS:
        phys = phys.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    return phys


def physical_of(points, deg):
    """Map logical points through the real pipeline, one Pillow image per point."""
    cw, ch = T.canvas_dims(deg, display=DISPLAY)
    out = []
    for x, y in points:
        img = Image.new("L", (cw, ch), 255)
        img.putpixel((x, y), 0)
        phys = pipeline(img, deg)
        black = [(i % phys.width, i // phys.width) for i, v in enumerate(phys.convert("L").tobytes()) if v == 0]
        assert len(black) == 1, (deg, x, y, black)
        out.append(black[0])
    return out


def in_rounded_box(px, py, x0, y0, x1, y1, r=4):
    if px < x0 or px > x1 or py < y0 or py > y1:
        return False
    cx = x0 + r if px < x0 + r else (x1 - r if px > x1 - r else px)
    cy = y0 + r if py < y0 + r else (y1 - r if py > y1 - r else py)
    return (px - cx) ** 2 + (py - cy) ** 2 <= r * r


def footer_page(deg, label="1/3  SOLAR"):
    fg = T.footer_geometry(clock=CLOCK, cat_label=label, orientation=deg, display=DISPLAY)
    img, draw = T.new_canvas(deg, display=DISPLAY)
    T.footer(draw, clock=CLOCK, cat_label=label, orientation=deg, display=DISPLAY)
    return img, fg


def blank(n):
    return [Image.new("1", (792, 272), 1) for _ in range(n)]


class TestGeometry(unittest.TestCase):
    def test_server_mapping_matches_its_own_pipeline(self):
        for q, deg in enumerate((0, 90, 180, 270)):
            cw, ch = T.canvas_dims(deg, display=DISPLAY)
            geo = server.panel_geometry(T.footer_geometry(clock=CLOCK, orientation=deg, display=DISPLAY), deg, DISPLAY)
            pts = [(0, 0), (cw - 1, 0), (0, ch - 1), (cw - 1, ch - 1), (cw // 3, ch // 5)]
            self.assertEqual([epf.to_physical(geo, x, y) for x, y in pts], physical_of(pts, deg), deg)

    def test_sent_geometry_is_where_the_pill_is_drawn(self):
        for deg in (0, 90, 180, 270):
            img, fg = footer_page(deg)
            mid = (fg["pill_y0"] + fg["pill_y1"]) // 2
            self.assertEqual(img.getpixel((fg["cat_x0"], mid)), 0, f"{deg}: left edge of the pill")
            self.assertEqual(img.getpixel((fg["cat_x1"], mid)), 0, f"{deg}: right edge of the pill")
            self.assertEqual(img.getpixel((fg["cat_x0"] + 2, fg["pill_y0"] - 2)), 255, f"{deg}: above the pill")

    def test_geometry_roundtrips_through_the_file(self):
        img, fg = footer_page(90)
        geo = server.panel_geometry(fg, 90, DISPLAY)
        data = epf.encode_epf([pipeline(img, 90)], [1], [0], [1], [fg["cat_w"]], [7], display_model=DISPLAY,
                              geometry=geo)
        self.assertEqual(epf.decode_epf(data).geometry, geo)


@unittest.skipUnless(shutil.which("c++"), "no C++ compiler")
class TestFirmwareCore(unittest.TestCase):
    def test_core_against_real_frame_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            for q, deg in enumerate((0, 90, 180, 270)):
                img, fg = footer_page(deg)
                geo = server.panel_geometry(fg, deg, DISPLAY)
                (tmp / f"orient{q}.epf").write_bytes(epf.encode_epf(
                    [pipeline(img, deg)], [11], [0], [1], [fg["cat_w"]], [21], display_model=DISPLAY,
                    orientation_180=(deg == 180), geometry=geo))
                cw, ch = T.canvas_dims(deg, display=DISPLAY)
                pts = [(0, 0), (cw - 1, ch - 1), (fg["cat_x0"], fg["pill_y0"]), (cw // 2, ch // 3)]
                (tmp / f"orient{q}.vectors").write_text(
                    "".join(f"{x} {y} {px} {py}\n" for (x, y), (px, py) in zip(pts, physical_of(pts, deg))))
                mask = Image.new("L", (cw, ch), 255)
                for y in range(fg["pill_y0"], fg["pill_y1"] + 1):
                    for x in range(fg["cat_x0"], fg["cat_x1"] + 1):
                        if in_rounded_box(x, y, fg["cat_x0"], fg["pill_y0"], fg["cat_x1"], fg["pill_y1"]):
                            mask.putpixel((x, y), 0)
                phys = pipeline(mask, deg)
                (tmp / f"orient{q}.pill").write_text("".join(
                    f"{i % phys.width} {i // phys.width}\n" for i, v in enumerate(phys.convert("L").tobytes()) if v == 0))

            (tmp / "legacy180.epf").write_bytes(epf.encode_epf(
                blank(1), [1], [0], [1], [110], [2], display_model=DISPLAY, orientation_180=True))
            (tmp / "nav_a.epf").write_bytes(epf.encode_epf(
                blank(5), [100, 200, 300], [0, 1, 4], [1, 3, 1], [110] * 3, [1, 21, 22, 23, 3], display_model=DISPLAY))
            (tmp / "nav_b.epf").write_bytes(epf.encode_epf(
                blank(6), [100, 150, 200, 300], [0, 1, 2, 5], [1, 1, 3, 1], [110] * 4, [1, 15, 21, 22, 23, 3],
                display_model=DISPLAY))
            (tmp / "nav_alert.epf").write_bytes(epf.encode_epf(
                blank(1), [900], [0], [1], [110], [90], display_model=DISPLAY, alert_interrupt=True))

            exe = tmp / "core_test"
            build = subprocess.run(["c++", "-std=c++17", "-O1", "-Wall", "-Wextra", "-o", str(exe),
                                    str(ROOT / "tests" / "firmware" / "core_test.cpp")],
                                   capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, build.stderr)
            run = subprocess.run([str(exe), str(tmp)], capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)


def reference_yaml():
    version = re.search(r'^version:\s*"([^"]+)"', (ROOT / "addon" / "config.yaml").read_text(), re.M).group(1)
    return firmware_gen.render(
        disp=T.get_display(DISPLAY), version=version, device_name="crowpanel-epaper",
        frames_url='"http://homeassistant.local:8099/frames.epf"', api_key="!secret api_encryption_key",
        ota_password="!secret ota_password", wifi_ssid="!secret wifi_ssid", wifi_password="!secret wifi_password",
        interval_min=5, orientation=180), version


class TestFirmwareYaml(unittest.TestCase):
    def test_pinned_to_the_release_and_complete(self):
        text, version = reference_yaml()
        self.assertIn(f"github://bek00letz/epaper-panel@v{version}\n", text)
        self.assertNotIn("@main", text)
        self.assertNotIn("refresh: 0s", text)
        self.assertIn(firmware_gen.CROWPANEL_COMPONENT, text)
        self.assertNotIn("online_image", text)
        self.assertNotRegex(text, r"@[A-Z][A-Z_]+@")

    def test_repository_copy_is_the_generator_output(self):
        text, _ = reference_yaml()
        self.assertEqual((ROOT / "esphome" / "crowpanel-epaper.yaml").read_text(), text,
                         "esphome/crowpanel-epaper.yaml is out of date; regenerate it with "
                         "`python tests/test_firmware.py --write-reference`")

    def test_mounting_upside_down_swaps_the_buttons(self):
        self.assertEqual(firmware_gen.button_pins(180)["NEXT_PIN"], 6)
        self.assertEqual(firmware_gen.button_pins(0)["NEXT_PIN"], 4)


if __name__ == "__main__":
    if "--write-reference" in sys.argv:
        (ROOT / "esphome" / "crowpanel-epaper.yaml").write_text(reference_yaml()[0])
        print("wrote esphome/crowpanel-epaper.yaml")
    else:
        unittest.main()
