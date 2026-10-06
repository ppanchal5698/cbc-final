"""FRP wall panels from measured geometry, by CBC's conversion constants (FR-12).

Requirements 7.5: the area is perimeter times wall height, less openings; panels
are the net area plus waste over one panel's area, rounded up; adhesive goes by
its coverage; trim comes in sticks. The constants are CBC's (Open Item 5, entered
in Settings). Until every one is set, nothing converts - a quantity invented here
would be priced as if it were measured.
"""
from __future__ import annotations

import math
import re
from typing import Any

_SIZE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:'|ft|feet)?\s*[x×*]\s*(\d+(?:\.\d+)?)", re.IGNORECASE)


def panel_area(size: Any) -> float | None:
    """`4 x 8`, `4' x 10'`, `4x8` - one panel's square feet."""
    found = _SIZE.search(str(size or ""))
    return float(found.group(1)) * float(found.group(2)) if found else None


def _fraction(waste: Any) -> float:
    """Waste as a fraction: 10 and 0.10 both mean ten percent."""
    value = float(waste)
    return value / 100 if value > 1 else value


def convert(geometry: dict[str, Any], constants: dict[str, Any]) -> dict[str, Any] | None:
    """Panel, adhesive and trim counts for one measured FRP area, or None while the
    constants are pending or the area is not measured."""
    perimeter, height = geometry.get("perimeterLf"), geometry.get("wallHeightFt")
    area = panel_area(constants.get("panel_size"))
    waste = constants.get("waste_pct")
    stick = constants.get("trim_stick_length")
    coverage = constants.get("adhesive_coverage_sqft_per_unit")
    if constants.get("status") != "SET" or not all((perimeter, height, area, stick, coverage)) or waste is None:
        return None

    # ponytail: openings are not measured on the take-off, so none are deducted -
    # the count errs high, never low. Deduct once an opening area is recorded.
    net = float(perimeter) * float(height)
    panels = math.ceil(round(net * (1 + _fraction(waste)) / area, 6))
    per_height = math.ceil(float(height) / float(stick))
    inside, outside = int(geometry.get("insideCorners") or 0), int(geometry.get("outsideCorners") or 0)
    return {
        "netSqft": round(net, 2),
        "panels": panels,
        "adhesive": math.ceil(round(net / float(coverage), 6)),
        "insideCornerSticks": inside * per_height,
        "outsideCornerSticks": outside * per_height,
        # A seam is a divider unless a corner covers it. ponytail: one wall run per
        # corner; a run's own length would place them exactly.
        "dividerSticks": max(panels - 1 - inside - outside, 0) * per_height,
        "capSticks": math.ceil(float(perimeter) / float(stick)),
    }
