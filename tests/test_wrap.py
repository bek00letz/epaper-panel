"""Text that wraps onto more lines instead of running out of its box."""
import unittest

import support  # noqa: F401
from render import layout, theme as T


LONG = "Point your phone camera at the QR code to connect automatically."


def draw(el):
    img, d = T.new_canvas()
    got = []
    layout._draw_text(img, d, el, el["value"], got)
    return img, got[0]


class TestWrap(unittest.TestCase):
    def test_lines_never_exceed_the_width(self):
        f = T.font(22, bold=False)
        lines = T.wrap_lines(LONG, f, 300)
        self.assertGreater(len(lines), 1)
        self.assertTrue(all(T.text_width(l, f) <= 300 for l in lines))
        self.assertEqual(" ".join(lines), LONG, "no words lost or cut")

    def test_wrapped_text_fits_its_box_and_says_so(self):
        box = {"type": "text", "value": LONG, "size": 22, "bold": False, "x": 132, "y": 94, "w": 300, "h": 100}
        _, plain = draw(dict(box))
        self.assertTrue(plain["overflow"], "on one line it runs out of the box")
        _, wrapped = draw(dict(box, wrap=True))
        self.assertFalse(wrapped["overflow"])
        self.assertGreater(wrapped["lines"], 1)

    def test_wrapped_text_fits_the_box_when_size_is_left_empty(self):
        _, m = draw({"type": "text", "value": LONG, "wrap": True, "x": 0, "y": 0, "w": 300, "h": 120})
        self.assertFalse(m["overflow"])
        self.assertGreater(m["size"], 18, "fills the box rather than shrinking to one line")

    def test_ink_stays_inside_the_box(self):
        el = {"type": "text", "value": LONG, "wrap": True, "x": 100, "y": 60, "w": 300, "h": 120}
        img, _ = draw(el)
        bw = T.to_1bit(img)
        box = bw.crop((0, 0, T.W, 230))
        ink = box.point(lambda p: 255 if p == 0 else 0).getbbox()
        self.assertGreaterEqual(ink[0], 100)
        self.assertLessEqual(ink[2], 401)
        self.assertGreaterEqual(ink[1], 60)
        self.assertLessEqual(ink[3], 181)

    def test_a_long_word_keeps_its_own_line(self):
        f = T.font(30)
        self.assertEqual(T.wrap_lines("a Supercalifragilistic b", f, 80), ["a", "Supercalifragilistic", "b"])


if __name__ == "__main__":
    unittest.main()
