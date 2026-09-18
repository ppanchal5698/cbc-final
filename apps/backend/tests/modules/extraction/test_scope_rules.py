"""What CBC quotes, decided in code rather than by a model reading a rule.

The same bid set, priced twice from the same inputs, produced 26 lines and then
12 - a different in/out split each run. Scope selection was the single largest
source of run-to-run variance in the pipeline.

Same contract as the rest of the take-off: **never silently wrong**. A row the
rules do not cover is left undecided and flagged, not guessed either way.
"""
from __future__ import annotations

import pytest

from cbc.modules.extraction.domain import scope_rules


# ── in scope ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "material,label",
    [("HM", "hollow metal"), ("HMD", "hollow metal"), ("WD", "wood"),
     ("SCWD", "solid core wood"), ("PL", "plastic laminate"), ("FRP", "FRP")],
)
def test_the_materials_cbc_quotes_are_in_scope(material, label) -> None:
    verdict = scope_rules.classify({"door_material": material})
    assert verdict.in_scope is True, (material, verdict)
    assert label.replace(" ", "_") in verdict.rule


def test_an_aluminium_frame_does_not_exclude_a_laminate_door() -> None:
    """The Wendy's restroom doors are laminate leaves in aluminium frames.

    CBC quotes the door. Excluding on the frame column would drop real work.
    """
    verdict = scope_rules.classify(
        {"door_material": "PL", "frame_material": "ALUM",
         "description": "UNISEX WRM - Type B Interior P.LAM"}
    )
    assert verdict.in_scope is True


# ── out of scope ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("frame", ["AL", "ALUM", None, ""])
def test_an_aluminium_leaf_is_storefront_whatever_the_frame_says(frame) -> None:
    """"Metal doors" means hollow metal and steel, never aluminium.

    Requiring the frame column to agree left four real storefront doors on one
    bid sitting undecided because their frame cell was blank.
    """
    verdict = scope_rules.classify({"door_material": "AL", "frame_material": frame})
    assert verdict.in_scope is False
    assert verdict.rule == "storefront"


@pytest.mark.parametrize(
    "text,rule",
    [
        ("ALUMINUM STOREFRONT ENTRANCE", "storefront"),
        ("COILING SERVICE DOOR", "coiling_door"),
        ("OVERHEAD DOOR, 12x14", "coiling_door"),
        ("ENGINEERED WOOD panel", "engineered_wood"),
        ("METAL SIDING at rear", "metal_siding"),
        ("ACOUSTICAL CEILING grid", "ceiling"),
        ("THIN BRICK veneer", "tile_masonry"),
        ("JL INDUSTRIES access door", "jl_industries"),
        ("SCRANTON partitions", "scranton"),
        ("AMERICAN DRYER hand dryer", "american_dryer"),
    ],
)
def test_every_out_of_scope_category_is_recognised(text, rule) -> None:
    verdict = scope_rules.classify({"description": text})
    assert verdict.in_scope is False, (text, verdict)
    assert verdict.rule == rule


def test_an_out_of_scope_rule_beats_an_in_scope_material() -> None:
    """A coiling door is a separate HP division however its leaf is built."""
    verdict = scope_rules.classify(
        {"door_material": "HM", "description": "COILING SERVICE DOOR"}
    )
    assert verdict.in_scope is False and verdict.rule == "coiling_door"


def test_the_reason_is_what_the_estimator_tells_the_gc() -> None:
    verdict = scope_rules.classify({"description": "SCRANTON partitions"})
    assert "access lost" in verdict.reason.lower()


# ── never guessed ───────────────────────────────────────────────────────────

def test_an_unknown_material_is_the_estimators_call() -> None:
    verdict = scope_rules.classify({"door_material": "XYZ"})
    assert verdict.in_scope is None
    assert "XYZ" in verdict.reason


def test_a_row_with_no_material_says_so_rather_than_deciding() -> None:
    verdict = scope_rules.classify({})
    assert verdict.in_scope is None
    assert verdict.reason


# ── applying it to a schedule ───────────────────────────────────────────────

def _rows() -> list[dict]:
    return [
        {"door_number": "01", "door_material": "AL", "frame_material": "AL"},
        {"door_number": "05", "door_material": "PL", "frame_material": "ALUM"},
        {"door_number": "99", "door_material": "XYZ"},
        {"door_number": "07", "door_material": "HM", "confirmed_by": "kevin@cbc.com"},
    ]


def test_each_row_is_stamped_with_its_verdict_and_flag() -> None:
    rows = _rows()
    counts = scope_rules.apply_to(rows)
    assert counts == {"in_scope": 1, "out_of_scope": 1, "undecided": 1, "preserved": 1}
    assert "out_of_scope_storefront" in rows[0]["flags"]
    assert "scope_undecided" in rows[2]["flags"]


def test_an_estimators_own_row_is_never_reclassified() -> None:
    """A confirmed or hand-added row is a decision, not an input."""
    rows = _rows()
    scope_rules.apply_to(rows)
    assert "in_scope" not in rows[3], rows[3]


def test_reapplying_is_idempotent() -> None:
    """A reseed must not accumulate flags or change its mind."""
    rows = _rows()
    scope_rules.apply_to(rows)
    first = [dict(row) for row in rows]
    scope_rules.apply_to(rows)
    assert rows == first


def test_the_out_of_scope_list_names_what_is_excluded_and_why() -> None:
    rows = _rows()
    scope_rules.apply_to(rows)
    items = scope_rules.out_of_scope_items(rows)
    assert [item["item"] for item in items] == ["01"]
    assert items[0]["rule"] == "storefront"
    assert items[0]["reason"]


def test_the_rules_match_the_written_rule_file() -> None:
    """`guides/takeoff.md` stays the human-readable owner of this list.

    If someone adds a category there and not here, the take-off silently keeps
    quoting it.
    """
    from tests.shared import ROOT

    rule_text = (ROOT / ".claude" / "guides" / "takeoff.md").read_text(
        encoding="utf-8"
    ).lower()
    for phrase in ("storefront", "coiling", "engineered wood", "metal siding",
                   "thin brick", "jl industries", "scranton", "american dryer"):
        assert phrase in rule_text, f"{phrase} left guides/takeoff.md"
        assert any(
            phrase.split()[0] in rule.key or phrase.split()[0] in rule.reason.lower()
            for rule in scope_rules.OUT_OF_SCOPE
        ), f"{phrase} is in the rule file but not in the code"
