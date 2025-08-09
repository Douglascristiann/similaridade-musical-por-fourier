
from __future__ import annotations
from pathlib import Path as _Path
import os

APP_NAME = "FourierMatch"
APP_VERSION = "4.0.0-new"

# Cookiefile fixo (YouTube)
COOKIEFILE_PATH = _Path("/home/jovyan/work/cache/cookies/cookies.txt")

# Pasta para downloads
DOWNLOADS_DIR = _Path(os.getenv("FM_DOWNLOADS_DIR", _Path.cwd() / "downloads"))
