#!/usr/bin/env python3
"""pricing domain worker."""
from __future__ import annotations

import os

os.environ.setdefault("WORKER_DOMAIN", "pricing")

from cbc.worker_kit.runtime import main

if __name__ == "__main__":
    raise SystemExit(main())
