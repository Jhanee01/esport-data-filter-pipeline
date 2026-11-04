"""The constants the original views import from `config`."""

from pathlib import Path

from ... import __version__

APP_VERSION = __version__
BASE_DIR = Path(__file__).resolve().parent.parent  # the ui package (assets live here)
