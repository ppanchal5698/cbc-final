"""memory's public surface - the only part of memory another module may import.

- `curator` - the agent that keeps the graph: `sync_all` mirrors the record,
  `learn_bid` records an approved bid.
- `recall` - what the graph gives back: `summary`, `similar_bids`, `resolutions`
  (what a specification was priced as and confirmed to mean), `prompt_block`.
"""
