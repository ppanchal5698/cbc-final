"""extraction's public surface - the only part of extraction another module may import.

- `openings` - a bid's openings for the passes, the syncs, the matching gate, a
  version snapshot and the proposal; counts for the board; failed payloads.
- `feedback` - record an estimator's correction (FR-13), from any screen.
- `door_schedule` - the door schedule on disk, both ways: a pass's openings loaded in,
  the estimator's confirmed ones written back down.
- `passes` - what every pass over a bid does on disk: seed the tree, check the output,
  follow the progress.
- `documents` - a port: the bid's documents an extract marks, plugged in by intake.
"""
