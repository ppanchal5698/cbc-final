"""Allow `python -m cbc.worker`."""
from __future__ import annotations

from cbc.worker.main import main

if __name__ == "__main__":
    raise SystemExit(main())
