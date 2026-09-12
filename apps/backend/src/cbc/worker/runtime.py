"""Worker claim loop — delegates to worker_kit (legacy packages/cbc runtime)."""
from __future__ import annotations

from cbc.worker_kit.runtime import main as worker_kit_main


def run_forever() -> None:
    """Start the Mongo claim loop (blocks until signal / --once / --preflight)."""
    raise SystemExit(worker_kit_main())


__all__ = ["run_forever", "worker_kit_main"]
