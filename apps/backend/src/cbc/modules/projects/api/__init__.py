"""projects' public surface - the only part of projects another module may import.

- `lookup.load` - a bid by code, slug or id; raises `ProjectNotFound` on a miss.
- `lookup.project_id`, `lookup.summaries` - what ops' project lookup port is bound to.
- `saga` - the bid's chainState: `set_state`, and the start/success/fail tables.
- `autopilot` - start the domain chain, and advance it when a job in it succeeds.
- `bids` - what another module may record on a bid (its version, an alternate, a hand-off), and PROJECT_DELETED.
- `board_sources` - where modules that own part of the board bind what they supply.
"""
