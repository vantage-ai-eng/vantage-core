#!/usr/bin/env python3
"""Thin wrapper — fleet sim lives in the packaged module.

  python3 scripts/sim_center_busy.py [--out DIR]
  python -m vantage_core.center_sim [--out DIR]
"""

from __future__ import annotations

import sys
from pathlib import Path

# Prefer installed / editable package; fall back to sibling tree for bare script runs.
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from vantage_core.center_sim import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
