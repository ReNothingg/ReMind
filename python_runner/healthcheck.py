from __future__ import annotations

import os
import time
from pathlib import Path

heartbeat = Path(os.getenv("PYTHON_RUNNER_QUEUE", "/jobs")) / ".heartbeat"
try:
    age = time.time() - heartbeat.stat().st_mtime
except OSError:
    raise SystemExit(1) from None
raise SystemExit(0 if age < 20 else 1)
