"""quoting's public surface - the only part of quoting another module may import.

- `quote` - reprice and roll up a bid (persist, totals_for), and quotes for the board.
- `lines` - a bid's quote lines, for a version snapshot and the matching gate.
- `priced_lines` - a pricing pass's lines loaded in; the approved quote written out.
- `proposal_artifacts` - what a proposal pass left on disk, recorded on the proposal.
"""
