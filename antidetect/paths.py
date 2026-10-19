"""Local path configuration for antidetect."""
import os
from pathlib import Path

DATA_DIR = Path(
    os.environ.get("ANTIDETECT_HOME") or Path.home() / ".local" / "share" / "antidetect"
)
