"""FR-4, decided in code rather than asked of a model.

Matrix 7.3: *"an unrated match on a rated opening is a defect."* Before this,
the only thing preventing that defect was prompt text - `match-hardware-sets`
told a model to respect rating, handing and finish, and nothing checked.

These tests are the requirement: rating, handing and finish are hard filters, a
rejected candidate says why it was rejected, and a rated opening with nothing
legal left reports a conflict rather than quietly picking the closest thing.
"""
from __future__ import annotations

from cbc.modules.quoting.domain import matching


def item(part: str, **fields):
    return {"part": part, **fields}


# ── the defect Matrix 7.3 names ─────────────────────────────────────────────


def test_an_unrated_item_cannot_match_a_rated_opening() -> None:
    verdict = matching.evaluate({"fire_rating": "90"}, item("A", fire_rating=None))
    assert verdict["eligible"] is False
    assert "fire_rating" in verdict["failedOn"]
    assert verdict["confidence"] == 0.0, "an illegal match is not a low-confidence one"


def test_a_lower_rating_cannot_carry_a_higher_opening() -> None:
    verdict = matching.evaluate({"fire_rating": "90"}, item("A", fire_rating="45"))
    assert verdict["eligible"] is False


def test_a_higher_rating_may_carry_a_lower_opening() -> None:
    """A 90-minute leaf on a 45-minute opening is over-specified, not wrong."""
    verdict = matching.evaluate({"fire_rating": "45"}, item("A", fire_rating="90"))
    assert verdict["eligible"] is True


def test_an_unrated_opening_takes_anything() -> None:
    assert matching.evaluate({}, item("A", fire_rating="90"))["eligible"]
    assert matching.evaluate({}, item("A", fire_rating=None))["eligible"]


def test_rating_is_read_from_the_ways_a_schedule_writes_it() -> None:
    for written in ("90", 90, "90 min", "90-minute", "90 MIN."):
        assert matching.rating_conflict(written, "90") is False, written
        assert matching.rating_conflict(written, "45") is True, written


def test_a_rated_opening_with_nothing_legal_reports_a_conflict() -> None:
    """The estimator is told the rating cannot be met, not handed a wrong door."""
    result = matching.candidates(
        {"fire_rating": "90"}, [item("A", fire_rating="45"), item("B", fire_rating=None)]
    )
    assert result["matchCandidates"] == []
    assert result["ratingConflict"] is True
    assert result["needsReview"] is True


def test_an_unrated_opening_is_flagged_as_missing_not_conflicting() -> None:
    """Matrix 7.3: a rating must never be silently dropped - but absent and
    contradicted are different findings."""
    result = matching.candidates({}, [item("A")])
    assert result["ratingMissing"] is True
    assert result["ratingConflict"] is False


# ── handing and finish ──────────────────────────────────────────────────────


def test_handing_must_agree_when_both_sides_state_it() -> None:
    assert not matching.evaluate({"handing": "LH"}, item("A", handing="RH"))["eligible"]
    assert matching.evaluate({"handing": "LH"}, item("A", handing="LH"))["eligible"]


def test_a_non_handed_item_fits_either_hand() -> None:
    for described in ("non-handed", "reversible", "ANY"):
        assert matching.evaluate({"handing": "LHR"}, item("A", handing=described))["eligible"]


def test_an_unstated_handing_contradicts_nothing() -> None:
    """A null is "not read", not "any" - it cannot be used to reject."""
    assert matching.evaluate({"handing": "LH"}, item("A"))["eligible"]
    assert matching.evaluate({}, item("A", handing="RH"))["eligible"]


def test_finish_equivalence_is_supplied_not_assumed() -> None:
    """US26D = 626 is reference data (NR-3), so the crosswalk is injected."""
    crosswalk = {"US26D": "626", "626": "626", "US19": "US19"}

    def equivalent(left, right):
        return crosswalk.get(left, left) == crosswalk.get(right, right)

    assert matching.evaluate(
        {"finish": "US26D"}, item("A", finish="626"), finish_equivalent=equivalent
    )["eligible"]
    assert not matching.evaluate(
        {"finish": "US19"}, item("A", finish="626"), finish_equivalent=equivalent
    )["eligible"]


# ── what reaches the estimator ──────────────────────────────────────────────


def test_three_close_matches_are_offered_not_one_answer() -> None:
    """NFR-2's target behaviour, quoted: "here are 3 close matches"."""
    catalog = [item(chr(65 + n), fire_rating="90", handing="LH") for n in range(6)]
    result = matching.candidates({"fire_rating": "90", "handing": "LH"}, catalog)
    assert len(result["matchCandidates"]) == matching.TOP_N


def test_a_rejected_candidate_says_why() -> None:
    """A silently shorter list teaches nobody anything."""
    result = matching.candidates(
        {"fire_rating": "90", "handing": "LH"},
        [item("A", fire_rating="45", handing="LH"), item("B", fire_rating="90", handing="RH")],
    )
    reasons = {row["part"]: row["failedOn"] for row in result["rejected"]}
    assert reasons["A"] == ["fire_rating"]
    assert reasons["B"] == ["handing"]


def test_a_full_agreement_scores_inside_the_accept_band() -> None:
    result = matching.candidates(
        {"fire_rating": "90", "handing": "LH", "finish": "626"},
        [item("A", fire_rating="90", handing="LH", finish="626")],
    )
    best = result["matchCandidates"][0]
    assert best["confidence"] >= matching.CONFIDENCE_FLOOR
    assert result["autoMatched"] is True


def test_a_partial_agreement_needs_a_human() -> None:
    result = matching.candidates(
        {"fire_rating": "90", "handing": "LH", "finish": "626"},
        [item("A", fire_rating="90")],
    )
    best = result["matchCandidates"][0]
    assert best["confidence"] < matching.CONFIDENCE_FLOOR
    assert result["needsReview"] is True
    assert result["autoMatched"] is False


def test_an_opening_that_specifies_nothing_never_auto_matches() -> None:
    """Nothing to agree with is not the same as agreement."""
    result = matching.candidates({}, [item("A")])
    assert result["autoMatched"] is False
    assert result["needsReview"] is True


def test_candidates_are_ordered_best_first_and_deterministically() -> None:
    catalog = [
        item("B", fire_rating="90"),
        item("A", fire_rating="90", handing="LH"),
        item("C", fire_rating="90"),
    ]
    result = matching.candidates({"fire_rating": "90", "handing": "LH"}, catalog)
    parts = [row["part"] for row in result["matchCandidates"]]
    assert parts[0] == "A", "the fuller agreement ranks first"
    assert parts[1:] == ["B", "C"], "ties break by part number, not by dict order"
