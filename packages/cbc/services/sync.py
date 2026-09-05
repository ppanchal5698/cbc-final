"""The bridge between Claude's JSON files and MongoDB.

The phases live in `sync_phases/`, one module each, and this aggregates them.
It was a single 740-line module covering extraction, pricing, the proposal and
the geometry measured off the sheet - four different jobs whose only shared
concern is that a pass writes JSON and the database has to end up agreeing with
it. That shared concern is `sync_phases/_common.py`; the rest are now separate.

This module stays because it is the name both applications import, and because
"which module is import_quote_lines in" is not a question a caller should have.
"""
from __future__ import annotations

from cbc.services.sync_phases._common import (  # noqa: F401
    door_number,
)
from cbc.services.sync_phases.extraction import (  # noqa: F401
    import_addendum,
    import_extraction,
    import_scope_metadata,
)
from cbc.services.sync_phases.geometry import (  # noqa: F401
    derive_frame_depths,
    measure_bboxes,
)
from cbc.services.sync_phases.pricing import (  # noqa: F401
    export_line_items,
    export_quote_lines,
    import_quote_lines,
)
from cbc.services.sync_phases.proposal import (  # noqa: F401
    import_proposal_artifacts,
)

__all__ = [
    "derive_frame_depths",
    "door_number",
    "export_line_items",
    "export_quote_lines",
    "import_addendum",
    "import_extraction",
    "import_proposal_artifacts",
    "import_quote_lines",
    "import_scope_metadata",
    "measure_bboxes",
]
