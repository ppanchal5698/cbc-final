"""The comparison harness: the estimators' line detail against the code engine's priced file.

The sheets arrive as the estimators keep them, so the columns are found by their
headers; the comparison is by part, all of a part's base-bid lines together.
"""
from __future__ import annotations

import pytest

from scripts import eval_bids

SHEET = [
    ["Dutch Bros Toledo - hardware", None, None, None, None, None],
    ["Door", "Mfr", "Part #", "Description", "Qty", "Unit Cost"],
    ["101", "Hager", "BB1279 4.5x4.5", "Hinge", "3", "$4.99"],
    ["102", "Hager", "BB1279 4.5x4.5", "Hinge", "3", "4.99"],
    ["101", "Hager", "5100-HDHOS", "Closer", "1", "$1,132.20"],
    ["", "", "", "Freight", "1", "250"],
    ["101", "Schlage", "L9080", "Lock", "1", "410.00"],
    ["", "", "", "Subtotal", "", "1,800.00"],
]


def test_the_columns_are_found_by_their_headers_under_a_title_row() -> None:
    header, columns = eval_bids.find_columns(SHEET)
    assert header == 1 and (columns["part"], columns["qty"], columns["cost"], columns["mark"]) == (2, 4, 5, 0)
    lines = eval_bids.estimator_lines(SHEET, header, columns)
    assert [(line["part"], line["qty"], line["cost"]) for line in lines] == [
        ("BB1279 4.5x4.5", 3.0, 4.99), ("BB1279 4.5x4.5", 3.0, 4.99), ("5100-HDHOS", 1.0, 1132.2),
        (None, 1.0, 250.0), ("L9080", 1.0, 410.0)]
    assert eval_bids.find_columns([["Catalog #", "Q"], ["BB1279", "2"]]) is None
    assert eval_bids.find_columns([["Catalog #", "Q"]], {"part": "Catalog #", "qty": "Q"}) == (0, {"part": 0, "qty": 1})


def test_parts_are_compared_with_all_their_lines_together() -> None:
    header, columns = eval_bids.find_columns(SHEET)
    theirs = eval_bids.estimator_lines(SHEET, header, columns) + [
        {"part": "10-0204", "qty": 2.0, "cost": 30.0}, {"part": "4040XP", "qty": 1, "cost": 200.0, "alternate": "Alt 1"}]
    ours = [
        {"part_number": "BB1279-4.5X4.5", "quantity": 6.0, "cost": 4.99},
        {"part_number": "5100", "quantity": 1.0, "cost": 1200.0},
        {"part_number": "L9080", "quantity": 1.0, "cost": None, "cost_source": "DISTRIBUTOR_MANUAL"},
        {"part_number": "10-645210A-00", "quantity": 2.0, "cost": 41.0},
        {"part_number": "4040XP", "quantity": 1.0, "cost": 150.0, "alternate_group": "Alt 1"},
        {"part_number": None, "quantity": 2.0, "cost": None, "line_id": "door:01"},
    ]
    result = eval_bids.compare(theirs, ours)
    assert result["counts"] == {"agree": 1, "qty": 0, "cost": 1, "unpriced": 1, "missing": 1, "extra": 1}
    [closer] = result["cost"]
    assert (closer["ours"], closer["match"], closer["cost"]) == ("5100", "model", [1132.2, 1200.0])
    assert result["missing"][0]["part"] == "10-0204", "ASI's leading 10 is no model in common"
    assert result["extra"][0]["part"] == "10-645210A-00"
    assert result["unnumbered"] == {"estimator": 1, "ours": 1}


def test_a_sheet_is_read_as_csv_or_as_every_worksheet(tmp_path) -> None:
    csv_file = tmp_path / "detail.csv"
    csv_file.write_text("Part,Qty\nBB1279,2\n", encoding="utf-8")
    assert eval_bids.read_sheet(csv_file) == [["Part", "Qty"], ["BB1279", "2"]]

    openpyxl = pytest.importorskip("openpyxl")
    book = openpyxl.Workbook()
    book.active.append(["Part", "Qty"])
    book.create_sheet("Div 10").append(["B-2111", 4])
    book.save(tmp_path / "detail.xlsx")
    assert eval_bids.read_sheet(tmp_path / "detail.xlsx") == [["Part", "Qty"], ["B-2111", 4]]
    (tmp_path / "locked.xlsx").write_bytes(b"not a zip")
    with pytest.raises(ValueError, match="password"):
        eval_bids.read_sheet(tmp_path / "locked.xlsx")
