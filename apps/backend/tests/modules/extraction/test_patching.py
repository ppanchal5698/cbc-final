"""A rejected patch costs one field, never the run.

Three consecutive runs on the same bid died three different ways - `thickness`,
`page_size`, `flags` - each time throwing away everything the earlier phases had
produced, because a pass authored the whole artifact and one bad key failed the
write.

Each of these is a payload that used to be fatal.
"""
from __future__ import annotations

import pytest

from cbc.modules.extraction.api import patching


CITE = {"source_page": 16, "excerpt": "05 | UNISEX WRM | 3'-0\" | 6'-8\" | RH"}


@pytest.fixture
def artifact():
    return {
        "source_page": 16,
        "openings": [
            {"door_number": "05", "size": "3068", "handing": None,
             "fire_rating": None, "source_page": 16, "flags": []},
            {"door_number": "08", "size": "3068", "handing": None,
             "source_page": 16, "flags": []},
        ],
    }


# ── what a patch is allowed to do ───────────────────────────────────────────

def test_a_cited_value_lands(artifact) -> None:
    out, results = patching.apply_patches(
        artifact, [{"op": "set", "path": "openings/05/handing", "value": "RH", "evidence": CITE}]
    )
    assert results[0]["applied"] is True
    assert out["openings"][0]["handing"] == "RH"


def test_the_page_it_was_read_from_is_recorded_on_the_row(artifact) -> None:
    """NFR-3: a filled value with no citation is unauditable."""
    out, _ = patching.apply_patches(
        artifact, [{"op": "set", "path": "openings/05/handing", "value": "RH", "evidence": CITE}]
    )
    assert "p16" in out["openings"][0]["evidence_note"]


def test_a_patch_names_the_opening_not_its_position(artifact) -> None:
    """An index means a patch written for one run lands on a different opening
    in the next - a wrong value carrying a real page number."""
    out, results = patching.apply_patches(
        artifact, [{"op": "set", "path": "openings/08/handing", "value": "LH", "evidence": CITE}]
    )
    assert results[0]["applied"] is True
    assert out["openings"][0]["handing"] is None
    assert out["openings"][1]["handing"] == "LH"


def test_append_extends_a_list_field(artifact) -> None:
    out, results = patching.apply_patches(
        artifact, [{"op": "append", "path": "openings/05/flags", "value": "verified_on_sheet"}]
    )
    assert results[0]["applied"] is True
    assert out["openings"][0]["flags"] == ["verified_on_sheet"]


def test_the_input_artifact_is_never_mutated(artifact) -> None:
    patching.apply_patches(
        artifact, [{"op": "set", "path": "openings/05/handing", "value": "RH", "evidence": CITE}]
    )
    assert artifact["openings"][0]["handing"] is None


# ── what it refuses, and at what cost ───────────────────────────────────────

def test_an_invented_field_costs_that_field_only(artifact) -> None:
    """`thickness` as a top-level Opening key killed a run outright."""
    out, results = patching.apply_patches(artifact, [
        {"op": "set", "path": "openings/05/thickness", "value": "1 3/4\"", "evidence": CITE},
        {"op": "set", "path": "openings/05/handing", "value": "RH", "evidence": CITE},
    ])
    assert results[0]["applied"] is False
    assert "notes" in results[0]["reason"]
    assert results[1]["applied"] is True
    assert out["openings"][0]["handing"] == "RH", "the good patch still landed"
    assert "patch_rejected_thickness" in out["openings"][0]["flags"]


def test_a_value_the_contract_refuses_is_rejected(artifact) -> None:
    out, results = patching.apply_patches(
        artifact, [{"op": "set", "path": "openings/05/confidence", "value": 7.0}]
    )
    assert results[0]["applied"] is False
    assert out["openings"][0].get("confidence") != 7.0


def test_filling_a_value_without_a_page_is_refused(artifact) -> None:
    _, results = patching.apply_patches(
        artifact, [{"op": "set", "path": "openings/05/fire_rating", "value": "90"}]
    )
    assert results[0]["applied"] is False
    assert "evidence" in results[0]["reason"]


def test_evidence_needs_both_a_page_and_an_excerpt(artifact) -> None:
    _, results = patching.apply_patches(artifact, [
        {"op": "set", "path": "openings/05/fire_rating", "value": "90",
         "evidence": {"source_page": 16}},
    ])
    assert results[0]["applied"] is False


def test_a_flag_needs_no_citation(artifact) -> None:
    """Saying "I could not read this" is not a claim about the sheet."""
    _, results = patching.apply_patches(
        artifact, [{"op": "append", "path": "openings/05/flags", "value": "handing_missing"}]
    )
    assert results[0]["applied"] is True


def test_an_opening_that_is_not_there_is_named(artifact) -> None:
    _, results = patching.apply_patches(
        artifact, [{"op": "set", "path": "openings/99/handing", "value": "LH", "evidence": CITE}]
    )
    assert results[0]["applied"] is False
    assert "99" in results[0]["reason"] and "05" in results[0]["reason"]


def test_an_estimators_decision_is_not_patchable(artifact) -> None:
    for field in ("confirmed_by", "added_by_hand"):
        _, results = patching.apply_patches(
            artifact, [{"op": "set", "path": f"openings/05/{field}", "value": "x"}]
        )
        assert results[0]["applied"] is False, field


@pytest.mark.parametrize(
    "path", ["", "openings/05", "handing", "openings/05/handing/extra", "junk/05/handing"]
)
def test_a_malformed_path_says_what_the_shape_is(artifact, path) -> None:
    _, results = patching.apply_patches(
        artifact, [{"op": "set", "path": path, "value": "RH", "evidence": CITE}]
    )
    assert results[0]["applied"] is False
    assert "openings/<door number>/<field>" in results[0]["reason"]


def test_an_unknown_op_is_refused(artifact) -> None:
    _, results = patching.apply_patches(
        artifact, [{"op": "delete", "path": "openings/05/handing", "value": None}]
    )
    assert results[0]["applied"] is False


# ── the whole point ─────────────────────────────────────────────────────────

def test_a_page_size_array_is_repaired_rather_than_refused(artifact) -> None:
    """`page_size: [w, h]` was one of the three shapes that killed a run.

    It is a known way for a pass to write the right numbers, so the contract
    repairs it into {width, height} instead of throwing the artifact away.
    """
    out, results = patching.apply_patches(artifact, [
        {"op": "set", "path": "openings/05/page_size", "value": [100, 200], "evidence": CITE},
    ])
    assert results[0]["applied"] is True
    assert out["openings"][0]["page_size"] == [100, 200]

    from cbc.modules.extraction.api.claude_output import Opening

    repaired = Opening.model_validate(out["openings"][0]).page_size
    assert (repaired["width"], repaired["height"]) == (100.0, 200.0)


def test_every_patch_failing_still_leaves_a_runnable_artifact(artifact) -> None:
    out, results = patching.apply_patches(artifact, [
        {"op": "set", "path": "openings/05/thickness", "value": "1 3/4\""},
        {"op": "set", "path": "openings/05/page_size", "value": "big", "evidence": CITE},
        {"op": "set", "path": "openings/99/handing", "value": "LH", "evidence": CITE},
    ])
    summary = patching.summarise(results)
    assert summary["applied"] == 0 and summary["rejected"] == 3
    assert summary["run_can_continue"] is True
    assert len(out["openings"]) == 2, "no opening was lost"


def test_the_patched_artifact_still_passes_its_schema_gate(artifact) -> None:
    import json

    from cbc.modules.extraction.api.artifact_schema import prepare_artifact_text

    out, _ = patching.apply_patches(artifact, [
        {"op": "set", "path": "openings/05/handing", "value": "RH", "evidence": CITE},
        {"op": "set", "path": "openings/05/thickness", "value": "1 3/4\"", "evidence": CITE},
    ])
    _, problems = prepare_artifact_text(
        "extracted/line_items.json", json.dumps(out)
    )
    assert problems == [], problems


def test_the_coverage_record_a_run_is_failed_for_can_actually_be_written():
    """`check_extraction` requires `visual_pages_checked` on line_items.json.

    `line_items.json` is seeded, so the prompts steer every correction
    through `propose_patch` — and a patch path had to read
    `openings/<door>/<field>`. `visual_pages_checked` is top-level, so there was
    no way to write the very field the artifact is failed for.

    Three real runs died on it. The recording shows the agent doing the work and
    then hitting the wall: 54 turns, 16 page images read, 13 patches applied,
    and "1 rejected as expected - top-level fields aren't patchable". It treated
    the refusal as normal and saved nothing.
    """
    from cbc.modules.extraction.api.patching import apply_patches

    seed = {"openings": [{"door_number": "01"}], "source": "pretakeoff"}
    rows = [
        {
            "path": "projects/x/uploads/raw/set.pdf",
            "source_page": 20,
            "image_path": "projects/x/extracted/_visual_pages/a.png",
            "finding": "roof plan, no door schedule",
        }
    ]

    updated, results = apply_patches(
        seed, [{"op": "set", "path": "visual_pages_checked", "value": rows}]
    )
    assert results[0]["applied"], results[0]["reason"]
    assert updated["visual_pages_checked"] == rows
    assert updated["openings"] == seed["openings"], "the rows are untouched"

    grown, _ = apply_patches(
        updated,
        [{"op": "append", "path": "visual_pages_checked", "value": [dict(rows[0], source_page=23)]}],
    )
    assert len(grown["visual_pages_checked"]) == 2


def test_no_other_top_level_field_became_patchable():
    """The opening is the audited unit; a reading belongs on its row.

    Widening this to "any top-level key" would let a patch set `openings`
    wholesale and bypass every per-field contract the module exists to enforce.
    """
    from cbc.modules.extraction.api import patching

    assert patching.TOP_LEVEL_PATCHABLE == {"visual_pages_checked"}

    for path in ("no_scope_reason", "openings", "source"):
        _, results = patching.apply_patches(
            {"openings": []}, [{"op": "set", "path": path, "value": "x"}]
        )
        assert not results[0]["applied"], f"{path} must not be patchable"


# ── W5: priced lines are patched by line_id, priced by pricing evidence ──────

def _priced_line(**over):
    return {
        "line_id": "HW-1-00",
        "group": "HW-1",
        "group_type": "door",
        "quantity": 1,
        "cost_source": "MANUAL",
        "source_page": 4,
        **over,
    }


PRICE_CITE = {"cost_source": "DISTRIBUTOR_MANUAL", "cost_source_detail": "Banner quote 2026-09-01"}


def test_a_priced_line_is_patched_by_line_id() -> None:
    out, results = patching.apply_patches(
        {"lines": [_priced_line()]},
        [{"op": "set", "path": "lines/HW-1-00/cost", "value": 42.0, "evidence": PRICE_CITE}],
    )
    assert results[0]["applied"] is True
    assert out["lines"][0]["cost"] == 42.0


def test_a_patch_for_an_unknown_line_id_is_rejected_not_raised() -> None:
    """by_mark.get(...) returns None -> a legible rejection that names the missing
    key and lists the keys the artifact has, never a raise or a silent no-op."""
    out, results = patching.apply_patches(
        {"lines": [_priced_line()]},
        [{"op": "set", "path": "lines/NOPE-99/cost", "value": 42.0, "evidence": PRICE_CITE}],
    )
    assert results[0]["applied"] is False
    assert "NOPE-99" in results[0]["reason"]
    assert "HW-1-00" in results[0]["reason"], "it must list the keys it does have"


def test_a_cost_needs_pricing_evidence_not_a_drawing_page() -> None:
    """A cost has no drawing page; demanding {source_page, excerpt} invents one."""
    _, results = patching.apply_patches(
        {"lines": [_priced_line()]},
        [{"op": "set", "path": "lines/HW-1-00/cost", "value": 42.0,
          "evidence": {"source_page": 16, "excerpt": "a row"}}],
    )
    assert results[0]["applied"] is False
    assert "cost_source" in results[0]["reason"]


def test_a_quantity_still_takes_the_drawing_form() -> None:
    """A quantity is drawing-derived: it takes source_page + excerpt, not a cost source."""
    _, wrong = patching.apply_patches(
        {"lines": [_priced_line()]},
        [{"op": "set", "path": "lines/HW-1-00/quantity", "value": 3, "evidence": PRICE_CITE}],
    )
    assert wrong[0]["applied"] is False
    out, right = patching.apply_patches(
        {"lines": [_priced_line()]},
        [{"op": "set", "path": "lines/HW-1-00/quantity", "value": 3,
          "evidence": {"source_page": 4, "excerpt": "3 EA"}}],
    )
    assert right[0]["applied"] is True
    assert out["lines"][0]["quantity"] == 3


def test_a_lines_payload_via_openings_root_does_not_land_on_lines() -> None:
    """_rows picks by the path's root, so a lines row is not reachable as openings."""
    _, results = patching.apply_patches(
        {"lines": [_priced_line()]},
        [{"op": "set", "path": "openings/HW-1-00/handing", "value": "RH", "evidence": CITE}],
    )
    assert results[0]["applied"] is False  # there are no openings to resolve against


def test_a_div10_item_is_validated_against_div10_not_opening() -> None:
    """The live bug: items were gated against Opening. product_type is a Div10Item
    field and not an Opening field, so gating it correctly is what lets it land."""
    out, results = patching.apply_patches(
        {"items": [{"line_id": "D1", "product_type": "grab bar", "flags": []}]},
        [{"op": "set", "path": "items/D1/manufacturer", "value": "Bobrick",
          "evidence": {"source_page": 5, "excerpt": "Bobrick B-6806"}}],
    )
    assert results[0]["applied"] is True
    assert out["items"][0]["manufacturer"] == "Bobrick"
