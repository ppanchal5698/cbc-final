"""Worker entry: `python -m cbc.worker`.

The worker's composition root. ops runs the queue; what runs a claimed job - the
Claude pipeline in cbc.worker_kit, until the modules that own each job type take
theirs - is bound into it here, and only here.
"""
from __future__ import annotations

from cbc.worker_kit import runtime  # first: importing it applies .env before settings are read
from cbc.modules import ops
from cbc.modules.ops.api import worker as ops_worker


def main() -> int:
    ops_worker.bind(runtime.process, after_finish=runtime.after_finish, on_dead=runtime.dead_letter)
    return ops.run_worker()


if __name__ == "__main__":
    raise SystemExit(main())
