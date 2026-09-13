"""extraction's public surface - the only part of extraction another module may import.

- `openings` - a bid's openings for the passes, the syncs, the matching gate, a
  version snapshot and the proposal; counts for the board; failed payloads.
- `feedback` - record an estimator's correction (FR-13), from any screen.
- `passes` - what every pass over a bid does on disk: seed the tree, check the output,
  follow the progress.
- `documents` - a port: the bid's documents an extract marks, plugged in by intake.
"""
