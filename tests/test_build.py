"""How the add-on's image and the test environment get their Python packages: from one list,
addon/requirements.txt, every package at an exact version. The image installs exactly that
(ready-built wheels only), and scripts/dev-env.sh builds the tests' environment from it with
the image's Python, so the tests draw pages with the Pillow that draws them in Home Assistant
(they had drifted: Pillow 11 in the image, 13 in the tests, found 16 Nov)."""
import re
import unittest

import support

ADDON = support.APP.parent
ROOT = ADDON.parent


class TestOneListOfPackages(unittest.TestCase):
    def test_every_package_is_at_an_exact_version(self):
        lines = [l.strip() for l in (ADDON / "requirements.txt").read_text().splitlines()
                 if l.strip() and not l.lstrip().startswith("#")]
        self.assertIn("pillow==13.0.0", lines)
        for line in lines:
            self.assertRegex(line, r"^[a-z0-9][a-z0-9._-]*==[0-9][0-9A-Za-z.]*$", line)

    def test_the_image_installs_that_list_and_nothing_else(self):
        docker = (ADDON / "Dockerfile").read_text()
        self.assertIn("COPY requirements.txt /tmp/requirements.txt", docker)
        self.assertIn("--only-binary=:all: -r /tmp/requirements.txt", docker)
        self.assertNotIn("py3-pillow", docker, "Pillow comes from the list, not from Alpine")
        self.assertEqual(len(re.findall(r"pip3? install", docker)), 1)

    def test_the_tests_build_from_the_same_list_with_the_images_python(self):
        script = (ROOT / "scripts" / "dev-env.sh").read_text()
        self.assertIn('-r "$HERE/addon/requirements.txt"', script)
        build = (ADDON / "build.yaml").read_text()
        alpine = set(re.findall(r"-base:(\d+\.\d+)", build))
        self.assertEqual(alpine, {"3.24"}, "both architectures on the same Alpine")
        # Alpine 3.24 ships Python 3.14: the two move together.
        self.assertIn("PYTHON=3.14\n", script)


if __name__ == "__main__":
    unittest.main()
