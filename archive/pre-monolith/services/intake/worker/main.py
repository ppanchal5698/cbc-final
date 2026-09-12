#!/usr/bin/env python3
"""intake domain worker."""
from __future__ import annotations

import os

os.environ.setdefault("WORKER_DOMAIN", "intake")

from cbc.worker_kit.runtime import main

if __name__ == "__main__":
    raise SystemExit(main())
