"""A bid set with no Division 08 scope is an answer, not a failed read.

CBC-260004 (a Dunkin' remodel) was tile, paint and vinyl wall covering: no door
schedule, no hardware sets, no partitions on any of 28 sheets. The take-off was
correct and the estimator was shown "Automatic read didn't finish - something
went wrong", because an unwritten `door_schedule.json` and an empty one were
indistinguishable to the gate.

The schedule must still be written. What changed is that a schedule which says
*why* it is empty passes, and says so loudly in the review flags.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from cbc.core import pdfpages
from cbc.validation import artifacts, review


def _project(root: Path, slug: str, schedule: object) -> None:
    extracted = root / "projects" / slug / "extracted"
    extracted.mkdir(parents=True, exist_ok=True)
    (extracted / "door_schedule.json").write_text(
        json.dumps(schedule), encoding="utf-8"
    )


@pytest.fixture()
def project_root(tmp_path, monkeypatch):
    monkeypatch.setattr(artifacts, "ROOT", tmp_path)
    monkeypatch.setattr(review, "ROOT", tmp_path)
    return tmp_path


def test_an_empty_schedule_with_a_reason_passes(project_root) -> None:
    _project(
        project_root,
        "finishes_only",
        {
            "openings": [],
            "no_scope_reason": (
                "no door schedule, door type or hardware set on any of 28 sheets"
            ),
        },
    )

    problems, warnings = artifacts.check_extraction("finishes_only")

    assert not problems, problems
    assert any("no Division 08 openings" in w for w in warnings), warnings


def test_the_shape_a_real_take_off_wrote_is_accepted(project_root) -> None:
    """The exact artifact from CBC-260004's re-run.

    It said `door_schedule_found: false` with an empty `door_schedule_pages` and
    a list of existing-to-remain doors - unambiguous - and the first version of
    this gate rejected it for not using the word `no_scope_reason`. Read the
    finding; do not demand a spelling of it.
    """
    _project(
        project_root,
        "dunkin",
        {
            "door_schedule_found": False,
            "door_schedule_pages": [],
            "openings": [],
            "existing_doors_identified": [
                {"door_number": "100", "status": "existing_to_remain", "source_page": 3}
            ],
        },
    )

    problems, warnings = artifacts.check_extraction("dunkin")

    assert not problems, problems
    assert any("door_schedule_found: false" in w for w in warnings), warnings


def test_an_empty_schedule_with_no_reason_passes_but_is_flagged(project_root) -> None:
    """A hard failure here tells the estimator nothing and costs a whole re-run.

    A run that returns nothing over a set with no schedule markers has not
    necessarily failed, so it passes - and a high-severity flag says no reason
    was recorded, which is more alarming than a cryptic gate error, not less.
    """
    _project(project_root, "silent", {"openings": []})

    problems, warnings = artifacts.check_extraction("silent")
    flags = review.derive_flags("silent")

    assert not problems, problems
    assert any("no reason recorded" in w for w in warnings), warnings
    assert [f for f in flags if f.get("field") == "no_scope"]


def test_an_empty_take_off_over_a_set_that_has_a_schedule_fails(project_root) -> None:
    """The one case that genuinely is a missed read.

    The deterministic pre-pass found a schedule marker and the take-off returned
    nothing. That is not a no-scope bid, and it is the only empty schedule worth
    failing a job over.
    """
    _project(project_root, "missed", {"openings": [], "no_scope_reason": "none found"})
    (project_root / "projects" / "missed" / "extracted" / "_sheetmap.json").write_text(
        json.dumps(
            {
                "files": [
                    {
                        "path": "projects/missed/uploads/raw/set.pdf",
                        "schedule_pages": [14],
                        "has_schedule_markers": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    problems, _ = artifacts.check_extraction("missed")

    assert any("missed read" in p for p in problems), problems
    assert any("14" in p for p in problems), problems


def test_an_older_sheetmap_never_turns_a_correct_run_into_a_failure(project_root) -> None:
    """A map written before `schedule_pages` existed claims nothing either way."""
    _project(project_root, "legacy", {"openings": [], "door_schedule_found": False})
    (project_root / "projects" / "legacy" / "extracted" / "_sheetmap.json").write_text(
        json.dumps({"files": [{"path": "x", "pages": [{"source_page": 2, "kind": "ranked"}]}]}),
        encoding="utf-8",
    )

    problems, _ = artifacts.check_extraction("legacy")

    assert not problems, problems


def test_an_unwritten_schedule_still_fails(project_root) -> None:
    """The phase may not be skipped - only reported as empty."""
    (project_root / "projects" / "skipped" / "extracted").mkdir(parents=True)

    problems, _ = artifacts.check_extraction("skipped")

    assert any("not written" in p for p in problems), problems


def test_a_no_scope_bid_raises_a_high_severity_flag(project_root) -> None:
    """The run now passes, so without this the estimator sees a green run and an
    empty quote with nothing explaining the gap."""
    _project(
        project_root,
        "finishes_only",
        {"openings": [], "no_scope_reason": "Division 08 is existing-to-remain"},
    )

    flags = review.derive_flags("finishes_only")
    no_scope = [f for f in flags if f.get("field") == "no_scope"]

    assert len(no_scope) == 1, flags
    assert no_scope[0]["severity"] == "high"
    assert "existing-to-remain" in no_scope[0]["note"]


def test_a_normal_schedule_raises_no_no_scope_flag(project_root) -> None:
    _project(
        project_root,
        "has_doors",
        {"openings": [{"door_number": "101", "source_page": 4, "confidence": 0.9}]},
    )

    flags = review.derive_flags("has_doors")

    assert not [f for f in flags if f.get("field") == "no_scope"]


def test_a_no_scope_bid_does_not_fail_at_pricing_or_proposal(project_root) -> None:
    """Fixing this only at extraction left the same bug one layer down.

    A finishes-only bid passed its take-off and then failed the pipeline at
    pricing for the empty quote the take-off had correctly predicted.
    """
    _project(project_root, "finishes_only", {"openings": [], "door_schedule_found": False})

    priced, priced_warnings = artifacts.check_pricing(
        "finishes_only", require_hardware_sets=True
    )
    proposal, proposal_warnings = artifacts.check_proposal("finishes_only")

    assert not priced, priced
    assert not proposal, proposal
    assert any("nothing priced" in w for w in priced_warnings), priced_warnings
    assert any("no proposal" in w for w in proposal_warnings), proposal_warnings


def test_a_missed_schedule_still_fails_pricing(project_root) -> None:
    """The no-scope pass must not become a way to launder a missed read."""
    _project(project_root, "missed", {"openings": []})
    (project_root / "projects" / "missed" / "extracted" / "_sheetmap.json").write_text(
        json.dumps({"files": [{"path": "x", "schedule_pages": [14]}]}), encoding="utf-8"
    )

    problems, _ = artifacts.check_pricing("missed", require_hardware_sets=True)

    assert problems, "an empty quote over a set with a schedule must not pass"


def test_a_bid_with_openings_still_requires_a_quote(project_root) -> None:
    """The ordinary path is untouched."""
    _project(
        project_root,
        "has_doors",
        {"openings": [{"door_number": "101", "source_page": 4, "confidence": 0.9}]},
    )

    problems, _ = artifacts.check_pricing("has_doors")

    assert any("line_items.json not written" in p for p in problems), problems


# ── the typo that started it ────────────────────────────────────────────────


def test_a_missing_pdf_names_the_near_miss(tmp_path) -> None:
    """Three searches died on `dunkin_donots_remodel` and the error said only
    "PDF not found", so the run concluded the schedule was not there."""
    real = tmp_path / "projects" / "dunkin_donuts_remodel" / "uploads" / "raw"
    real.mkdir(parents=True)
    (real / "Bid Set .pdf").write_bytes(b"%PDF-1.4\n")

    typo = tmp_path / "projects" / "dunkin_donots_remodel" / "uploads" / "raw" / "Bid Set .pdf"
    with pytest.raises(FileNotFoundError) as caught:
        pdfpages._open(typo)

    assert "dunkin_donuts_remodel" in str(caught.value)


def test_a_missing_pdf_with_no_near_miss_says_nothing_extra(tmp_path) -> None:
    (tmp_path / "raw").mkdir()
    with pytest.raises(FileNotFoundError) as caught:
        pdfpages._open(tmp_path / "raw" / "totally-unrelated.pdf")

    assert "Did you mean" not in str(caught.value)
