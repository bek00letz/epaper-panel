"""Shared test setup: the add-on's modules on the path, and a throwaway data folder.

Every test run gets its own data folder, made fresh here and removed when the
run ends. It is never the dev server's folder (or any DATA_DIR from the shell),
so nothing left behind by the server or an earlier run can change a result.
"""
import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "addon" / "app"
RUN_DIR = Path(tempfile.mkdtemp(prefix="epaper-tests-"))
atexit.register(shutil.rmtree, RUN_DIR, ignore_errors=True)
DATA_DIR = RUN_DIR / "data"
DATA_DIR.mkdir()
os.environ["DATA_DIR"] = str(DATA_DIR)
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

import config  # noqa: E402

config.DATA_DIR = DATA_DIR


def use_test_data_dir() -> Path:
    """Back to the run's shared data folder."""
    config.DATA_DIR = DATA_DIR
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    return config.DATA_DIR


def temp_dir() -> Path:
    """An empty folder inside the run's folder, removed with it."""
    return Path(tempfile.mkdtemp(dir=RUN_DIR))


def fresh_data_dir() -> Path:
    """An empty data folder for one test, with no devices remembered from before."""
    import runtime
    config.DATA_DIR = temp_dir()
    runtime.forget_devices_except([])
    runtime.ALERTS.clear()
    return config.DATA_DIR


def first_frames():
    """The current render of the first device (this install's panel)."""
    import devices
    import runtime
    return runtime.device(devices.primary()["id"]).frames
