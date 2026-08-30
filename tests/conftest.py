"""Let the tests run from a fresh clone, with nothing installed."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
