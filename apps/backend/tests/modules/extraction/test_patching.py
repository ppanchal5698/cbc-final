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
        "extracted/door_schedule.json", json.dumps(out)
    )
    assert problems == [], problems
