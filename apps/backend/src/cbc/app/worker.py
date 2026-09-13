"""The worker's composition root: ops' claim loop, with every module's jobs plugged in.

The import order is load-bearing, as in main.py beside it: `envfile` writes `.env` into
`os.environ` before anything reads settings, and logging is set up before any
module logs. tests/architecture/test_composition_root.py checks the first.
"""
from __future__ import annotations

from cbc.shared import envfile, logs
from cbc.modules.ops.api import provider

envfile.apply_to_environ(skip=provider.MANAGED)
logs.configure("cbc.worker")

from cbc.modules import catalog, extraction, intake, ops, projects, quoting  # noqa: E402
from cbc.modules.ops.api import worker as ops_worker  # noqa: E402
from cbc.modules.projects.api import pipeline  # noqa: E402


def wire() -> None:
    """Register every module's jobs, what follows any job's end, and what projects hears. Idempotent."""
    ops_worker.bind(after_finish=pipeline.after_pass, on_dead=pipeline.dead_letter)
    for module in (catalog, extraction, intake, quoting):
        module.register_jobs()
    # A build_proposal pass ends the bid's saga through QUOTE_COMPLETED.
    projects.subscribe()


def main() -> int:
    wire()
    return ops.run_worker()


if __name__ == "__main__":
    raise SystemExit(main())
