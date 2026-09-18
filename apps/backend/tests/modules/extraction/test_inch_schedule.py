"""Inch-layout / architectural-font door schedule parsing."""

from __future__ import annotations

import parse_schedule as ps


def test_parse_size_inches_pair() -> None:
    parsed = ps.parse_size('1 | 36" | 84" | HPL | C')
    assert parsed["notation"] == "inches"
    assert parsed["width"] == "3'-0\""
    assert parsed["height"] == "7'-0\""
    assert parsed["size"] == "3070"


def test_parse_size_partial_inches() -> None:
    parsed = ps.parse_size('28" | 60"')
    assert parsed["width"] == "2'-4\""
    assert parsed["height"] == "5'-0\""
    assert parsed["size"] == "2450"


def test_retail_inch_row_is_opening() -> None:
    row = {
        "text": '3 | 36" | 84" | HPL | E | ALUM | E, 2\'-8" | 7 | GLASS PROVIDED BY GC',
        "cells": [
            "3",
            '36"',
            '84"',
            "HPL",
            "E",
            "ALUM",
            "E, 2'-8\"",
            "7",
            "GLASS PROVIDED BY GC",
        ],
    }
    header = {
        "door_number": 0,
        "width": 1,
        "height": 2,
        "door_material": 3,
        "door_type": 4,
        "frame_material": 5,
        "frame_type": 6,
        "hardware_set": 7,
        "notes": 8,
    }
    assert ps._row_is_opening(row, header)


def test_retail_inch_opening_fields() -> None:
    row = {
        "source_page": 2,
        "text": '4 | 28" | 84" | HPL | E | ALUM | E, 2\'-8" | 8 | DOOR PRE-HUNG IN FRAME',
        "page_size": {"width": 1000.0, "height": 700.0},
        "bbox": [1, 2, 3, 4],
        "cells": [
            "4",
            '28"',
            '84"',
            "HPL",
            "E",
            "ALUM",
            "E, 2'-8\"",
            "8",
            "DOOR PRE-HUNG IN FRAME",
        ],
        "cell_boxes": [[0, 0, 1, 1]] * 9,
    }
    header = {
        "door_number": 0,
        "width": 1,
        "height": 2,
        "door_material": 3,
        "door_type": 4,
        "frame_material": 5,
        "frame_type": 6,
        "hardware_set": 7,
        "notes": 8,
    }
    opening = ps.parse_opening(row, header)
    assert opening["door_number"] == "4"
    assert opening["width"] == "2'-4\""
    assert opening["height"] == "7'-0\""
    assert opening["size"] == "2470"
    assert opening["door_material"] == "HPL"
    assert opening["frame_material"] == "AL"
    assert opening["door_type"] == "E"
    assert opening["frame_type"] == "E, 2'-8\""
    assert opening["hardware_set"] == "GROUP 8"
    assert "out_of_scope_storefront" not in (opening.get("flags") or [])


def test_letter_first_mark_a1() -> None:
    row = {
        "source_page": 1,
        "text": "A-1 | 3'-0\" | 7'-0\" | HM | A | GROUP 2",
        "page_size": {"width": 1000.0, "height": 700.0},
        "bbox": [1, 2, 3, 4],
        "cells": ["A-1", "3'-0\"", "7'-0\"", "HM", "A", "GROUP 2"],
        "cell_boxes": [[0, 0, 1, 1]] * 6,
    }
    header = {
        "door_number": 0,
        "width": 1,
        "height": 2,
        "door_material": 3,
        "door_type": 4,
        "hardware_set": 5,
    }
    assert ps._is_door_mark("A-1")
    assert ps._row_is_opening(row, header)
    opening = ps.parse_opening(row, header)
    assert opening["door_number"] == "A-1"
    assert opening["width"] == "3'-0\""
    assert opening["hardware_set"] == "GROUP 2"


def test_unknown_material_kept_when_header_maps_sizes() -> None:
    row = {
        "source_page": 1,
        "text": 'B-2 | 36" | 84" | FRP | C | 3',
        "page_size": {"width": 1000.0, "height": 700.0},
        "bbox": [1, 2, 3, 4],
        "cells": ["B-2", '36"', '84"', "FRP", "C", "3"],
        "cell_boxes": [[0, 0, 1, 1]] * 6,
    }
    header = {
        "door_number": 0,
        "width": 1,
        "height": 2,
        "door_material": 3,
        "door_type": 4,
        "hardware_set": 5,
    }
    assert ps._row_is_opening(row, header)
    opening = ps.parse_opening(row, header)
    assert opening["door_number"] == "B-2"
    assert opening["door_material"] == "FRP"
    assert opening["hardware_set"] == "GROUP 3"


def test_normalize_alum_and_hpl() -> None:
    assert ps._normalize_material("ALUM") == "AL"
    assert ps._normalize_material("HPL") == "HPL"
    assert ps._normalize_material("plam") == "HPL"


def test_title_only_detector() -> None:
    from cbc.shared import pdfrows

    assert pdfrows.text_looks_like_schedule_title_only("DOOR SCHEDULE\nA4.0", 4)
    assert not pdfrows.text_looks_like_schedule_title_only("DOOR SCHEDULE\n" + ("1 36 84 " * 20), 60)
