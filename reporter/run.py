#!/usr/bin/env python3
"""Starts the reporter: `python3 run.py setup|report|show|status|uninstall` (epaper_usage/cli.py)."""
import sys

if sys.version_info < (3, 9):
    sys.exit("The reporter needs Python 3.9 or later.")

from epaper_usage.cli import main  # noqa: E402

sys.exit(main())
