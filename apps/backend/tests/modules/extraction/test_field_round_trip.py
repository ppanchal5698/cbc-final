"""What the sheet said has to survive the trip to the screen.

The parser reads 26 fields off a schedule row. The Ops-Hub import is a
hand-written map, and eight of them were not in it - so `width`, `height`,
`size_notation`, `raw_row`, the per-cell geometry and the whole scope verdict
existed in `extracted/door_schedule.json` and then simply stopped.

Nothing reported a loss, because nothing compared the two.
"""
from __future__ import annotations

import pytest

from cbc.modules.extraction.api import door_schedule


CARRIED = (
    "width", "height", "sizeNotation", "rawRow", "inScope", "scopeRule", "scopeReason",
)


def _opening():
    return {
        "door_number": "05",
        "size": "3068",
        "width": "3'-0\"",
        "height": "6'-8\"",
        "size_notation": "explicit",
        "raw_row": "05 | UNISEX WRM | 3'-0\" | 6'-8\" | 1 3/4\" | 07",
        "in_scope": True,
        "scope_rule": "material_plastic_laminate",
        "scope_reason": None,
        "room_name": "UNISEX WRM",
        "hardware_set": "GROUP 07",
        "frame_type": "11",
        "wall_type": "drywall",
        "source_page": 16,
        "source_file": "uploads/raw/a.pdf",
        "bbox": [1.0, 2.0, 3.0, 4.0],
        "page_size": {"width": 100.0, "height": 200.0},
        "row_bbox": [1.0, 2.0, 3.0, 4.0],
        "cell_boxes": [[1.0, 2.0, 3.0, 4.0]],
        "evidence_note": "read from p16",
        "confidence": 0.76,
        "flags": [],
    }


def test_the_parsed_row_survives_the_import_map() -> None:
    """Each of these was dropped between the artifact and the collection."""
    fields = door_schedule._mongo_fields(_opening(), key="05", project_id="p", payload={})
    for name in CARRIED:
        assert name in fields, f"{name} is dropped on the way into Mongo"
    assert fields["rawRow"].startswith("05 | UNISEX WRM")
    assert (fields["width"], fields["height"]) == ("3'-0\"", "6'-8\"")
    assert fields["inScope"] is True


def test_cell_geometry_reaches_the_viewer() -> None:
    """Row-level bbox highlights a row; cell boxes highlight the column."""
    fields = door_schedule._mongo_fields(_opening(), key="05", project_id="p", payload={})
    evidence = fields["evidence"]
    assert evidence["bbox"] == [1.0, 2.0, 3.0, 4.0]
    assert evidence["rowBbox"] is not None
    assert evidence["cellBoxes"] is not None


def test_a_confirmed_export_does_not_drop_them_again() -> None:
    """The estimator's export is what the next phase reads.

    Carrying a field in and not back out loses it on the first confirm instead
    of the first import - later, quieter, and just as gone.
    """
    import inspect

    source = inspect.getsource(door_schedule.export_line_items)
    for snake in ("raw_row", "width", "height", "size_notation",
                  "in_scope", "scope_rule", "scope_reason",
                  "row_bbox", "cell_boxes"):
        assert snake in source, f"{snake} is not written back on export"


def test_the_ui_can_edit_what_the_parser_reads() -> None:
    """`frameType` reached Mongo and was rendered by no component at all."""
    from cbc.modules.extraction.domain.openings import LineItemUpdate

    fields = set(LineItemUpdate.model_fields)
    assert {"frameType", "wallType"} <= fields


def test_the_import_loop_holds_no_stale_names() -> None:
    """Lifting the map out left one branch reaching for a variable it no longer had.

    `evidence` was built inside the loop and moved into `_mongo_fields`, but the
    confirmed-row branch still named it - so the path every already-confirmed bid
    takes on its next import would raise NameError. The Mongo-backed test for that
    branch only runs where Mongo does; this one runs everywhere.
    """
    import ast
    import inspect
    import textwrap

    tree = ast.parse(textwrap.dedent(inspect.getsource(door_schedule.import_extraction)))
    assigned = {
        target.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    assigned |= {
        node.target.id for node in ast.walk(tree)
        if isinstance(node, (ast.For, ast.AsyncFor)) and isinstance(node.target, ast.Name)
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.For) and isinstance(node.target, ast.Tuple):
            assigned |= {e.id for e in node.target.elts if isinstance(e, ast.Name)}

    module = set(vars(door_schedule)) | set(dir(__builtins__))
    args = {a.arg for n in ast.walk(tree) if isinstance(n, ast.arguments) for a in n.args}
    used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}

    unresolved = used - assigned - module - args - set(dir(__builtins__))
    assert "evidence" not in unresolved, "import_extraction still reaches for `evidence`"
