"""Lets tests in the pack folders import the shared helpers in this folder (stores_param, ...)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
