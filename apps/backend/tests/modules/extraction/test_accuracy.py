"""Accuracy against a hand-checked reference.

The contract this enforces is not "100% correct" - that is not attainable when the
answer is sometimes not in the document. It is **never silently wrong**: a field is
either right, or blank. A blank is honest and costs coverage; a confidently wrong
value reaches a quote with nothing to signal that anyone should check it, and that
is the only class treated as a failure here.

These run the *deterministic* parser, not a model, so they execute on every push
and a change that starts misreading a sheet fails the build rather than being
discovered on a bid.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from tests.shared import FIXTURES, ROOT

sys.path.insert(0, str(ROOT / ".claude" / "skills" / "extract-door-schedule" / "scripts"))

GOLDEN_DIR = FIXTURES / "golden"
FIXTURE_DIR = FIXTURES / "pdfs"


def _resolve_golden_pdf(golden: dict) -> Path | None:
    """Prefer fixtures/pdfs, then bid_pdfs/ for layout-class corpus goldens."""
    name = golden.get("source_file")
    if not name:
        return None
    candidates = [
        FIXTURE_DIR / name,
        ROOT / "bid_pdfs" / name,
    ]
    corpus = golden.get("source_corpus")
    if corpus == "bid_pdfs":
        candidates.insert(0, ROOT / "bid_pdfs" / name)
    for path in candidates:
        if path.is_file():
            return path
    return None


def _references() -> list[Path]:
    """Door-schedule goldens only (pricing expectations share the golden/ folder)."""
    if not GOLDEN_DIR.exists():
        return []
    out: list[Path] = []
    for path in sorted(GOLDEN_DIR.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict) and "openings" in payload and "source_page" in payload:
            out.append(path)
    return out


def _ids(paths: list[Path]) -> list[str]:
    return [p.stem for p in paths]


REFERENCES = _references()


@pytest.mark.skipif(not REFERENCES, reason="no reference files in tests/fixtures/golden/")
@pytest.mark.parametrize("reference", REFERENCES, ids=_ids(REFERENCES))
def test_the_parser_is_never_silently_wrong(reference: Path) -> None:
    """The only unacceptable failure: a filled-in field that disagrees.

    Missing fields are not scored here. On the Dutch Bros fixture the schedule
    carries no handing, finish or fire rating at all, so the correct output is a
    blank - and scoring that as a miss would push the parser toward guessing,
    which is exactly what NFR-2 forbids.
    """
    import parse_schedule

    from scripts.score_extraction import score

    golden = json.loads(reference.read_text(encoding="utf-8"))
    pdf = _resolve_golden_pdf(golden)
    if pdf is None:
        pytest.skip(f"fixture not present: {golden.get('source_file')}")

    rows = parse_schedule.schedule_rows(str(pdf), golden["source_page"])
    result = score(rows, golden)

    assert not result["silent_errors"], (
        f"{reference.stem}: the parser asserted values that disagree with the "
        f"reference - {result['silent_errors'][:5]}"
    )


@pytest.mark.skipif(not REFERENCES, reason="no reference files in tests/fixtures/golden/")
@pytest.mark.parametrize("reference", REFERENCES, ids=_ids(REFERENCES))
def test_every_opening_is_found(reference: Path) -> None:
    """Losing a whole opening is not a silent error, but it is a lost door."""
    import parse_schedule

    from scripts.score_extraction import score

    golden = json.loads(reference.read_text(encoding="utf-8"))
    pdf = _resolve_golden_pdf(golden)
    if pdf is None:
        pytest.skip(f"fixture not present: {golden.get('source_file')}")

    result = score(parse_schedule.schedule_rows(str(pdf), golden["source_page"]), golden)

    assert not result["missing_openings"], f"openings not read: {result['missing_openings']}"
    assert not result["extra_openings"], f"openings invented: {result['extra_openings']}"


# ── the scorer itself has to be right, or the gate means nothing ───────────


GOLDEN = {
    "source_file": "x.pdf",
    "source_page": 14,
    "reviewed_by": "someone",
    "openings": [
        {
            "door_number": "01", "source_page": 14, "size": "3670",
            "hardware_set": "GROUP 1", "handing": None, "finish": None,
            "fire_rating": None, "door_type": None, "frame_type": None,
            "wall_type": None, "unknown": ["handing", "finish", "fire_rating"],
        }
    ],
}


def _one(**overrides):
    from scripts.score_extraction import score

    base = {"door_number": "01", "source_page": 14, "size": "3670", "hardware_set": "GROUP 1"}
    return score([{**base, **overrides}], GOLDEN)


def test_a_correct_read_scores_clean() -> None:
    result = _one()
    assert result["silent_errors"] == [] and result["coverage"] == 1.0


def test_a_wrong_value_is_a_silent_error() -> None:
    result = _one(size="3070")
    assert len(result["silent_errors"]) == 1
    assert "expected '3670', got '3070'" in result["silent_errors"][0]


def test_inventing_a_value_the_document_lacks_is_a_silent_error() -> None:
    """The worst case: a fire rating nobody wrote down, appearing on a quote."""
    result = _one(fire_rating="90 min")
    assert len(result["silent_errors"]) == 1
    assert "document says nothing" in result["silent_errors"][0]
    assert result["honesty"] < 1.0


def test_leaving_an_absent_field_blank_is_not_an_error() -> None:
    """A flagged blank is the correct answer, not a miss."""
    result = _one(handing=None, finish=None, fire_rating=None)
    assert result["silent_errors"] == []
    assert result["honesty"] == 1.0


def test_a_blank_where_the_document_has_a_value_costs_coverage_not_correctness() -> None:
    result = _one(size=None)
    assert result["silent_errors"] == [], "a blank never asserts anything wrong"
    assert result["coverage"] < 1.0


def test_a_missing_opening_is_reported() -> None:
    from scripts.score_extraction import score

    result = score([], GOLDEN)
    assert result["missing_openings"] == ["01"]
    assert result["silent_errors"] == [], "reading nothing asserts nothing"


def test_the_grouping_key_is_read_under_either_name() -> None:
    """Mongo calls it `mark`, the parser calls it `door_number`."""
    from scripts.score_extraction import score

    as_mark = score([{"mark": "01", "source_page": 14, "size": "3670",
                      "hardware_set": "GROUP 1"}], GOLDEN)
    assert as_mark["missing_openings"] == [] and as_mark["silent_errors"] == []


def test_a_provisional_reference_says_so() -> None:
    from scripts.score_extraction import score

    draft = {**GOLDEN, "reviewed_by": None}
    assert score([], draft)["provisional"] is True
    assert score([], GOLDEN)["provisional"] is False


# ── the artifact gate ──────────────────────────────────────────────────────


def test_every_job_type_is_either_gated_or_explicitly_unchecked() -> None:
    """The chain used to end in `else: return`, and a job type nobody remembered
    to add fell straight through it. That is how the autopilot run - the one path
    with no human checkpoints - ended up with no artifact checks either."""
    from typing import get_args

    from cbc.modules.ops.domain.jobs import JobType
    from cbc.modules.extraction.api.validation.artifacts import ARTIFACT_CHECKS, UNCHECKED_JOB_TYPES

    uncovered = set(get_args(JobType)) - set(ARTIFACT_CHECKS) - UNCHECKED_JOB_TYPES
    assert not uncovered, f"job types with no decision about validation: {uncovered}"


def test_an_unknown_job_type_fails_loudly() -> None:
    from cbc.modules.extraction.api.validation.artifacts import validate_job_artifacts

    with pytest.raises(ValueError, match="no entry in ARTIFACT_CHECKS"):
        validate_job_artifacts("something_new", "whatever")


def test_the_full_pipeline_runs_all_three_check_sets() -> None:
    from cbc.modules.extraction.api.validation.artifacts import ARTIFACT_CHECKS

    assert len(ARTIFACT_CHECKS["run_full_pipeline"]) == 3, (
        "one session produces extraction, pricing and proposal artifacts, so all "
        "three are checked"
    )


# ── a line has to say what it is ───────────────────────────────────────────


def _priced(tmp_path, lines) -> str:
    """Write a minimal project and return its slug, for check_pricing."""
    slug = "gate_fixture"
    root = tmp_path / "projects" / slug
    (root / "priced").mkdir(parents=True)
    (root / "extracted").mkdir(parents=True)
    (root / "extracted" / "hardware_sets.json").write_text("[]", encoding="utf-8")
    (root / "priced" / "line_items.json").write_text(
        json.dumps({"lines": lines}), encoding="utf-8"
    )
    return slug


BLANK_MANUAL = {
    "line_id": "door_01_0", "group": "GROUP 1", "group_type": "door",
    "quantity": 1, "cost_source": "MANUAL", "source_page": 14,
    "part_number": None, "description": None,
}


def test_a_line_with_no_identity_is_refused(tmp_path, monkeypatch) -> None:
    """A real run wrote 25 of these: nothing wrong in them, and useless - the
    estimator was handed blanks and no way to know what to price."""
    import cbc.modules.extraction.api.validation.artifacts as vp

    monkeypatch.setattr(vp, "ROOT", tmp_path)
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "projects"))
    slug = _priced(tmp_path, [BLANK_MANUAL])
    problems, _ = vp.check_pricing(slug, require_hardware_sets=True)

    assert any("neither part_number nor description" in p for p in problems)


def test_a_manual_line_that_names_the_item_passes(tmp_path, monkeypatch) -> None:
    import cbc.modules.extraction.api.validation.artifacts as vp

    monkeypatch.setattr(vp, "ROOT", tmp_path)
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "projects"))
    named = {**BLANK_MANUAL, "description": 'IVES 700 83", 630',
             "cost_source_detail": "Allegion - bought through Banner or SecLock"}
    slug = _priced(tmp_path, [named])
    problems, warnings = vp.check_pricing(slug, require_hardware_sets=True)

    assert problems == [], problems
    # An all-manual quote is legitimate, but it must not look finished.
    assert any("entirely manual" in w for w in warnings)


def test_a_manual_line_with_no_reason_is_refused(tmp_path, monkeypatch) -> None:
    """NFR-2: a manual line is an instruction to a human, so it says why."""
    import cbc.modules.extraction.api.validation.artifacts as vp

    monkeypatch.setattr(vp, "ROOT", tmp_path)
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "projects"))
    slug = _priced(tmp_path, [{**BLANK_MANUAL, "description": "IVES 700"}])
    problems, _ = vp.check_pricing(slug, require_hardware_sets=True)

    assert any("records no reason" in p for p in problems)


# ── the take-offs the door schedule gate never covered ──────────────────────
#
# `hardware_sets.json` and `div10_takeoff.json` are parsed deterministically now,
# and nothing was checking them. The same contract applies: a field is either
# right, or blank. These assert the properties that make a take-off safe to
# price, rather than pinning exact values a redraw would change.

HARDWARE_PAGE = (ROOT / "bid_pdfs" / "17037_Wendys_Acheson_A_DWG_IFT.pdf", 16)
DIV10_PAGES = (ROOT / "bid_pdfs" / "17037_Wendys_Acheson_A_DWG_IFT.pdf", [19, 18, 17])


def _skip_unless(pdf: Path):
    if not pdf.is_file():
        pytest.skip(f"fixture not present: {pdf.name}")


def test_the_hardware_legend_yields_parts_not_blank_manual_lines() -> None:
    """Two bid sets reached pricing with no manufacturer parts at all.

    The legend was never read, so every hardware line priced MANUAL at zero.
    """
    from cbc.modules.extraction.infrastructure import hardware_groups

    pdf, page = HARDWARE_PAGE
    _skip_unless(pdf)
    found = hardware_groups.groups_on_page(pdf, page)
    sets = found.get("sets") or []
    items = [i for s in sets for i in (s.get("items") or [])]
    assert len(sets) >= 10, f"only {len(sets)} hardware sets off a legend of 11"
    assert len(items) >= 70, f"only {len(items)} items"

    with_part = [i for i in items if i.get("part")]
    assert len(with_part) / len(items) >= 0.80, (
        f"only {len(with_part)}/{len(items)} items carry a part number"
    )
    # The parts that started this: they must survive to the artifact.
    parts = {str(i.get("part") or "").upper() for i in items}
    for expected in ("3580", "BB1279", "4501", "5100", "431S", "810S", "190S"):
        assert any(expected in p for p in parts), f"{expected} is not in the legend output"


def test_every_hardware_item_says_which_set_and_page_it_came_from() -> None:
    """NFR-3: a part with no set is unquotable, one with no page unauditable."""
    from cbc.modules.extraction.infrastructure import hardware_groups

    pdf, page = HARDWARE_PAGE
    _skip_unless(pdf)
    for entry in hardware_groups.groups_on_page(pdf, page).get("sets") or []:
        assert entry.get("hardware_set"), entry
        assert entry.get("source_page") == page, entry


def test_a_division_10_item_is_identified_or_it_is_only_a_mention() -> None:
    """Eighteen rows of which six were real read as data, and priced as data."""
    from cbc.modules.extraction.infrastructure import specialty_parser

    pdf, pages = DIV10_PAGES
    _skip_unless(pdf)
    envelope = specialty_parser.div10_envelope(pdf, pages)

    for item in envelope["items"]:
        assert item["manufacturer"] and item["specified_model"], item
        assert item["source_page"] in pages, item
    for mention in envelope["mentions"]:
        assert mention["why_not_an_item"], mention
    if envelope["mentions"]:
        assert "div10_mentions_need_review" in envelope["flags"]


def test_a_division_10_count_is_never_defaulted() -> None:
    """Counting accessories means reading elevations, not a schedule row.

    A default of 1 quotes one grab bar for a building, with nothing on the line
    to say the count was never read.
    """
    from cbc.modules.extraction.infrastructure import specialty_parser

    pdf, pages = DIV10_PAGES
    _skip_unless(pdf)
    for item in specialty_parser.div10_envelope(pdf, pages)["items"]:
        if item["qty"] is None:
            assert "qty_not_stated" in item["flags"], item
        else:
            assert item["qty"] > 0, item


def test_frp_geometry_is_blocked_rather_than_estimated() -> None:
    from cbc.modules.extraction.infrastructure import specialty_parser

    pdf, _ = DIV10_PAGES
    _skip_unless(pdf)
    found = specialty_parser.frp_findings(pdf, [23, 19, 18])
    if not found["frp_in_scope"]:
        pytest.skip("no FRP on this set")
    assert found["status"] == "NOT_MEASURED"
    assert found["quantity"] is None and found["areas"] == []
    assert found["blocked_on"]
    # A vendor named elsewhere on the sheet is not the FRP vendor.
    assert found["manufacturer"] != "Bobrick", "Bobrick do not make FRP"
