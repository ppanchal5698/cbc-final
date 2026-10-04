"""B-16: margin prose points at JSON; DEFAULT_BANDS stays the fallback."""
from __future__ import annotations

from cbc.modules.pricing.api.calc import DEFAULT_BANDS
from tests.shared import ROOT

PROSE = (
    ROOT / ".claude" / "agents" / "pricing-engineer.md",
    ROOT / ".claude" / "memory" / "margin_sheet.md",
    ROOT / ".claude" / "skills" / "apply-margin" / "SKILL.md",
    ROOT / ".claude" / "skills" / "apply-margin" / "references" / "margin_bands.md",
)

# The phase documents are gone; what an agent reads as the process flow is the
# memory pointer and the pricing guide. The rule is unchanged: neither may carry
# the band table.
PROCESS_FLOW = [
    ROOT / ".claude" / "memory" / "process_flow.md",
    ROOT / ".claude" / "guides" / "pricing.md",
]


def test_inlined_process_flow_has_no_commodity_margin_table() -> None:
    assert all(path.is_file() for path in PROCESS_FLOW), PROCESS_FLOW
    for path in PROCESS_FLOW:
        text = path.read_text(encoding="utf-8")
        assert "27%" not in text, path
        assert "0.27" not in text, path


# The single source moved: `margin_framework.json` is seed, and the live bands
# come from `referenceData` through the reference server. Prose may point at
# either, but it must point somewhere rather than carry its own copy.
POINTERS = ("margin_framework.json", "mcp__reference__get_margin_bands", "referenceData")


def test_margin_prose_points_at_the_json() -> None:
    for path in PROSE:
        body = path.read_text(encoding="utf-8")
        assert any(p in body for p in POINTERS), path


def test_default_bands_commodity_is_unchanged() -> None:
    assert DEFAULT_BANDS["commodity"] == 0.27
