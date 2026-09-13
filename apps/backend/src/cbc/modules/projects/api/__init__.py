"""projects' public surface - the only part of projects another module may import.

- `lookup.load` - a bid by code, slug or id; raises `ProjectNotFound` on a miss.
- `lookup.get` - a bid by id, or None.
- `lookup.project_id`, `lookup.summaries` - what ops' project lookup port is bound to.
- `saga` - the bid's chainState: `set_state`, and the start/success/fail tables.
- `autopilot` - start the domain chain, and advance it when a job in it succeeds.
- `bids` - what another module may record on a bid (its version, an alternate, a hand-off, the pipeline's stage and phase), and PROJECT_DELETED.
- `scope_metadata` - a bid's empty create-form fields, filled from a pass's title block.
- `pipeline` - a Claude pass over a bid (`run_pass`), and what follows any job's end
  (`after_pass`, `dead_letter`).
- `board_sources` - where modules that own part of the board bind what they supply.
"""
