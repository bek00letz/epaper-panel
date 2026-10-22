"""Times of day go through render/clock.py, so the whole panel follows one 12/24-hour setting.

Nothing else enforced it, and two slipped past (framework review 2, #2): the Countdown's
"Fri, 14:00" and the starter page's sunrise line. This fails on an hour pattern anywhere a
renderer, a source or a shipped design could put a time on the panel."""
import re
import unittest

import support

HOUR = re.compile(r"%-?[HIl]")
APP = support.APP
# Where an hour pattern is right, and why.
ALLOWED = {
    "render/clock.py": "the one place that formats a time of day",
    "render/binding.py": "TIME_FORMATS: a format a person picks by name; time and datetime go through clock",
    "render/clocktime.py": "recognises clocks written in templates; formats nothing",
}
# Attributes of the add-on's own sensors, read by automations: data, not something drawn.
ATTRIBUTE_LINES = ("_ko_local = ", "win_start_local = ", "win_end_local = ")


class TestEveryTimeOfDayFollowsTheSetting(unittest.TestCase):
    def files(self):
        yield from (APP / "render").glob("*.py")
        yield from (APP / "sources").glob("*.py")
        yield from APP.glob("*.json")                     # the shipped designs
        yield from (APP / "render").glob("*.json")

    def test_no_hour_pattern_outside_clock(self):
        found = []
        for path in self.files():
            rel = path.relative_to(APP).as_posix()
            if rel in ALLOWED:
                continue
            for n, line in enumerate(path.read_text(errors="replace").splitlines(), 1):
                if HOUR.search(line) and not (rel.startswith("sources/") and any(a in line for a in ATTRIBUTE_LINES)):
                    found.append(f"{rel}:{n}: {line.strip()[:100]}")
        self.assertEqual(found, [], "a time of day that skips render/clock.py (use clock.hm or clock.pattern)")


if __name__ == "__main__":
    unittest.main()
