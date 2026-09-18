"""Manufacturer OCR alias normalization."""
from __future__ import annotations

from cbc.modules.extraction.api.manufacturer_aliases import (
    apply_to_hardware_item,
    apply_to_priced_line,
    normalize_manufacturer,
)


def test_alarm_clock_becomes_alarm_lock() -> None:
    name, changed = normalize_manufacturer("ALARM CLOCK")
    assert changed is True
    assert name == "Alarm Lock"


def test_priced_line_part_prefix_normalized() -> None:
    line = apply_to_priced_line(
        {"part_number": "ALARM CLOCK ETDL27R1G/26DV", "cost": None, "flags": []}
    )
    assert line["part_number"].startswith("Alarm Lock")
    assert "manufacturer_normalized" in line["flags"]


def test_hardware_item_matched_manufacturer() -> None:
    item = apply_to_hardware_item(
        {
            "matched": {"manufacturer": "ALARM CLOCK", "part_number": "ETDL"},
            "flags": [],
        }
    )
    assert item["matched"]["manufacturer"] == "Alarm Lock"
    assert "manufacturer_normalized" in item["flags"]
