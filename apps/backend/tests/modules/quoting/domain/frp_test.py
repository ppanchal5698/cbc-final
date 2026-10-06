"""FRP quantities from measured geometry, by CBC's constants (FR-12, requirements 7.5)."""
from __future__ import annotations

from cbc.modules.quoting.domain import frp, takeoff

SET = {"status": "SET", "panel_size": "4 x 8", "waste_pct": 10, "trim_stick_length": 10,
       "adhesive_coverage_sqft_per_unit": 210}
AREA = {"perimeterLf": 120, "wallHeightFt": 8, "insideCorners": 4, "outsideCorners": 2}


def test_an_area_converts_by_the_requirements_rule() -> None:
    """120 LF x 8 ft is 960 SF; with 10% waste over 32 SF panels, 33; 210 SF a can, 5 cans."""
    assert frp.convert(AREA, SET) == {
        "netSqft": 960.0, "panels": 33, "adhesive": 5,
        "insideCornerSticks": 4, "outsideCornerSticks": 2, "dividerSticks": 26, "capSticks": 12,
    }
    assert frp.convert(AREA, {**SET, "waste_pct": 0.10})["panels"] == 33, "ten and 0.10 are both ten percent"
    assert frp.panel_area("4' x 10'") == 40.0


def test_nothing_converts_while_a_constant_or_a_measurement_is_missing() -> None:
    assert frp.convert(AREA, {**SET, "status": "PENDING"}) is None
    assert frp.convert({**AREA, "wallHeightFt": None}, SET) is None
    assert frp.convert(AREA, {**SET, "panel_size": "standard"}) is None


def test_a_measured_area_is_its_materials_once_the_constants_are_set() -> None:
    row = {"division": "06 64", "qty": None, "description": "MARLITE FRP", "room": "Kitchen", "geometry": AREA}
    [pending] = takeoff.specialty_lines([row])
    assert pending.qty is None and "quantity_unread" in pending.flags

    lines = takeoff.specialty_lines([row], SET)
    assert [(line.description, line.qty) for line in lines] == [
        ("FRP PANEL 4 X 8 - MARLITE FRP", 33.0), ("FRP ADHESIVE - MARLITE FRP", 5.0),
        ("INSIDE CORNER TRIM - MARLITE FRP", 4.0), ("OUTSIDE CORNER TRIM - MARLITE FRP", 2.0),
        ("DIVIDER BAR - MARLITE FRP", 26.0), ("CAP TRIM - MARLITE FRP", 12.0),
    ]
    assert all("frp_converted" in line.flags and "quantity_unread" not in line.flags for line in lines)
    assert lines[0].notes == ["960 SF net; panel 4 x 8, waste 10, trim in 10 ft sticks"]
