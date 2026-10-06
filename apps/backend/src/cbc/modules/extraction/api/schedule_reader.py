"""The door-schedule reader, for callers outside extraction - the pdf-tools MCP
server, the scripts and the skill's command line - which may reach a module only
through its `api`."""
from __future__ import annotations

from cbc.modules.extraction.infrastructure.schedule_parser import (  # noqa: F401
    cluster_rows,
    find_schedule_pages,
    main,
    openings_envelope,
    parse_size,
    schedule_rows,
)
