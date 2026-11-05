"""The constants the original views import from `config`."""

from pathlib import Path

from ... import __version__

APP_VERSION = __version__
BASE_DIR = Path(__file__).resolve().parent.parent  # the ui package (assets live here)

# League tokens the original views pass around as "CSV paths" (see h2h_reader).
MATCH_RESULTS_CSV = "matches:8min"
MATCH_RESULTS_12_CSV = "matches:12min"
