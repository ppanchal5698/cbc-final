"""memory's public surface - the only part of memory another module may import.

- `curator` - the agent that keeps the graph: `sync_all` mirrors the record,
  `learn_bid` records an approved bid.
- `steward` - the agent that checks the graph: `review` records each problem as
  a `Finding`, resolves the fixed ones and explains the new ones; `dismiss`.
- `historian` - the agent that counts what customers' bids show: `reflect`
  writes BUYS and MARGIN_IN links and a customer `Insight`.
- `recall` - what the graph gives back: `summary`, `similar_bids`, `resolutions`
  (what a specification was priced as and confirmed to mean), `customer_insights`,
  `prompt_block`.
"""
