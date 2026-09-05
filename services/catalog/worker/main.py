#!/usr/bin/env python3
"""catalog domain worker."""
from __future__ import annotations

import os

os.environ.setdefault("WORKER_DOMAIN", "catalog")

from cbc.worker_kit.runtime import main

if __name__ == "__main__":
    raise SystemExit(main())
