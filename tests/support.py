"""Shared test setup: the add-on's modules on the path, and a throwaway data folder."""
import os
import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "addon" / "app"
os.environ.setdefault("DATA_DIR", "/tmp/epaper-data")
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

import config  # noqa: E402


def use_test_data_dir() -> Path:
    config.DATA_DIR = Path(os.environ["DATA_DIR"])
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    return config.DATA_DIR


def first_frames():
    """The current render of the first device (this install's panel)."""
    import devices
    import runtime
    return runtime.device(devices.primary()["id"]).frames
