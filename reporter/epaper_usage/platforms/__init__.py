"""What differs between the computers the reporter runs on: where it keeps its files, where it keeps
its key, and what runs it every few minutes. One module per platform, each with the same parts:

    ID                           "macos", "linux" or "windows" (what the report says it is)
    data_dir(home) -> Path       its own folder: settings, caches, the saved Claude Code limits
    log_path(home) -> Path
    save_key(home, key) -> str   into the computer's own key store (never a plain file where there's a better
                                 place); says where, in words
    load_key(home) -> str | ""
    delete_key(home)
    schedule(home, python, script, minutes) -> str     runs `python script report` every so many minutes; says how
    unschedule(home) -> str
    scheduled(home) -> bool

Nothing else in the reporter asks which computer it's on.
"""
from __future__ import annotations

import sys

SERVICE = "e-Paper Usage Reporter"          # the key store's name for its key, the scheduler's for its job
LABEL = "local.epaper-panel.usage-reporter"


def current():
    if sys.platform == "darwin":
        from . import macos as mod
    elif sys.platform.startswith("win"):
        from . import windows as mod
    else:
        from . import linux as mod
    return mod
