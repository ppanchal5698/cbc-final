"""Worker entry: `python -m cbc.worker`."""
from __future__ import annotations

from cbc.worker_kit.runtime import main as worker_kit_main


def main() -> int:
    return worker_kit_main()


if __name__ == "__main__":
    raise SystemExit(main())
