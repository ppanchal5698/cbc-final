"""extraction's public surface - the only part of extraction another module may import.

- `openings` - a bid's openings for the passes, the syncs, the matching gate, a
  version snapshot and the proposal; counts for the board; failed payloads.
- `feedback` - record an estimator's correction (FR-13) from any screen, and drain
  the unconsumed queue (`unapplied`, `mark_applied`) for the learning pass.
- `door_schedule` - the door schedule on disk, both ways: a pass's openings loaded in,
  the estimator's confirmed ones written back down.
- `claude_output`, `artifact_schema`, `artifact_contracts` - the contract for what a pass
  writes: the models, the JSON Schemas generated from them (`artifacts/`), and the
  validator the Claude hook and the artifact-storage MCP server run on every write.
- `validation` - the artifact checks (`check_extraction`, `check_pricing`,
  `check_proposal`), the contract gate (`raise_if_invalid`) and the mechanical review
  flags (`write_flags`); the Claude hook and the validate scripts import it too.
- `passes` - what every pass over a bid does on disk: seed the tree, check the output,
  follow the progress.
- `documents` - a port: the bid's documents an extract marks, plugged in by intake.
- `visual_pages` - which pages a pass must look at rather than read, for the prompt
  builder and the readiness script.
"""
