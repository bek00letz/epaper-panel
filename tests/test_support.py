"""The tests' own data folder: fresh for every run, never the dev server's."""
import os
import tempfile
import unittest
from pathlib import Path

import support
import config


class TestDataFolder(unittest.TestCase):
    def test_a_run_uses_a_folder_of_its_own(self):
        self.assertEqual(support.DATA_DIR.parent, support.RUN_DIR)
        self.assertTrue(support.RUN_DIR.name.startswith("epaper-tests-"))
        self.assertEqual(Path(tempfile.gettempdir()), support.RUN_DIR.parent)
        self.assertEqual(os.environ["DATA_DIR"], str(support.DATA_DIR), "even when the shell sets DATA_DIR")
        self.assertNotEqual(support.DATA_DIR, Path("/tmp/epaper-data"))

    def test_back_to_the_runs_folder_after_a_fresh_one(self):
        fresh = support.fresh_data_dir()
        self.assertEqual(fresh.parent, support.RUN_DIR)
        self.assertEqual(list(fresh.iterdir()), [])
        self.assertEqual(support.use_test_data_dir(), support.DATA_DIR)
        self.assertEqual(config.DATA_DIR, support.DATA_DIR)


if __name__ == "__main__":
    unittest.main()
