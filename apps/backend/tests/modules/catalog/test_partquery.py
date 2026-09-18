"""The part strings a schedule actually writes, and what they must resolve to.

Every case here is a real one. `PEMKO-275A-42` is the line a run priced at $12.41
off a PDF page while the catalog held Pemko 275A at $7.16; `10-645210A-00` is the
ASI part that a careless normaliser would shred.
"""
from __future__ import annotations

import pytest

from cbc.modules.catalog.domain import partquery

# What `catalogItems.distinct` returns today, near enough.
VENDORS = [
    "pemko",
    "asi",
    "national_guard",
    "world_dryer",
    "Pemko",
    "ASI",
    "National Guard",
    "Von Duprin",
    "ives",
    "zero",
    "Hager",
]


def test_a_composite_part_string_reaches_the_bare_part():
    """The $12.41 defect: the raw string missed, so the pass opened a PDF."""
    candidates = partquery.normalize("PEMKO-275A-42", VENDORS)
    assert candidates[0] == "PEMKO-275A-42", "the raw string is always tried first"
    assert "275A" in candidates


def test_a_real_part_number_is_never_shredded():
    """ASI writes `10-645210A-00`. Stripping its leading token loses an exact hit."""
    assert partquery.normalize("10-645210A-00", VENDORS)[0] == "10-645210A-00"


def test_a_bare_letter_is_never_offered_as_a_candidate():
    """`B-212` must not degrade to `B`, which prefix-matches a whole catalogue.

    It did. Bobrick B-212 and B-254 are not in `catalogItems` at all; both
    normalised to `B`, prefix-matched every Bobrick part, took the shortest
    (`B-165`) and were priced at its $113.80 and cited as a catalog baseline. A
    lookup that answers confidently about a part it does not hold is worse than
    one that misses (NFR-2).
    """
    for part in ("B-212", "B-254", "B-165"):
        assert partquery.normalize(part, VENDORS) == [part], part


def test_every_candidate_carries_a_digit_and_more_than_one_character():
    """What makes a candidate specific enough to be worth asking about."""
    for spec in ("B-212", "PEMKO-275A-42", "A-1", "X", "42", "10-645210A-00"):
        for candidate in partquery.normalize(spec, VENDORS):
            assert len(candidate) >= 2 and any(c.isdigit() for c in candidate), (spec, candidate)


@pytest.mark.parametrize(
    "specified,part",
    [
        ("4501-48-26D", "4501"),        # part, 48 inches, finish 26D
        ("5100-HDHOS-ALUM", "5100"),    # closer, arm option, aluminium
        ("190S-20X40-32D", "190S"),     # kick plate, 20x40, finish 32D
        ("431S-42-MIL", "431S"),        # threshold, 42 inches, mill finish
    ],
)
def test_a_qualified_part_reaches_the_bare_part(specified, part):
    """A schedule writes the part first and qualifies it afterwards.

    Picking "the longest token with a letter and a digit" chose the qualifier
    over the part: `4501-48-26D` offered the finish `26D`, `190S-20X40-32D`
    offered the size `20X40`, and `5100-HDHOS-ALUM` offered nothing. All three
    then missed a Hager special-net row that was there.
    """
    candidates = partquery.normalize(specified, VENDORS)
    assert candidates[0] == specified, "the raw string is still tried first"
    assert part in candidates, candidates


def test_a_short_leading_token_may_be_matched_exactly_but_never_as_a_prefix():
    """`10-645210A-00` reduces to `10`, which prefixes hundreds of ASI parts."""
    assert "10" in partquery.normalize("10-645210A-00", VENDORS)
    assert partquery.prefix_safe("10") is False
    assert partquery.prefix_safe("B") is False
    # The shortest real part numbers in the catalog still qualify.
    assert partquery.prefix_safe("33E") and partquery.prefix_safe("30S")
    assert partquery.prefix_safe("3580")


def test_a_part_that_is_only_a_size_asks_for_nothing():
    """`42` alone identifies no part, so it must not become a prefix query."""
    assert partquery.normalize("42", VENDORS) == ["42"]
    assert partquery.normalize("X", VENDORS) == []


def test_a_two_word_vendor_is_stripped_before_the_one_word_pass_sees_it():
    """`VON` alone is not a vendor; `VON DUPRIN` is."""
    assert "99EO" in partquery.normalize("VON-DUPRIN-99EO-42-626", VENDORS)


def test_trailing_size_and_finish_come_off_but_the_part_stays():
    candidates = partquery.normalize("ZERO-39A-42", VENDORS)
    assert "39A" in candidates
    assert "42" not in candidates, "a size is not a candidate part number"


def test_an_empty_part_asks_for_nothing():
    """A query built from an empty string would match the whole catalog."""
    assert partquery.normalize("", VENDORS) == []
    assert partquery.normalize("   ", VENDORS) == []


@pytest.mark.parametrize(
    "left,right",
    [
        ('IVES 700 83", 630', "ives-700-83-630"),
        ("Hager 3510  US26D", "hager 3510 us26d"),
    ],
)
def test_spec_key_ignores_case_separators_and_inch_marks(left, right):
    """A key that tells `83"` from `83` recalls nothing on the next bid."""
    assert partquery.spec_key(left) == partquery.spec_key(right)
    assert partquery.spec_key(left)  # and is not empty


def test_spec_key_flattens_a_dict_spec():
    key = partquery.spec_key({"part": "275A", "finish": None, "size": "42"})
    assert key == "275a 42"


def test_ingest_rows_are_excluded_unless_asked_for():
    """OCR extracts may be matched against; they may not be quoted."""
    assert partquery.trust_clause()["$and"][0] == {
        "seedSource": {"$ne": partquery.INGEST_SEED}
    }
    assert partquery.trust_clause(include_ingest=True) == {}


def test_vendor_clause_bridges_the_underscore_in_vendor_key():
    """`vendorKey` is `national_guard`; a caller says "National Guard"."""
    clause = partquery.vendor_clause("National Guard")
    assert {"vendorKey": "national_guard"} in clause["$or"]
    assert partquery.vendor_clause(None) is None
    assert partquery.vendor_clause("  ") is None


def test_text_filter_uses_the_search_index_and_regex_filter_does_not():
    """The regex shape is the fallback, not the default: it scans all 6,579 rows."""
    assert "$text" in str(partquery.text_filter("paper towel dispenser"))
    assert "$text" not in str(partquery.regex_filter("2752"))


def test_the_same_spec_written_two_ways_still_recalls():
    """The same opening gets written differently on the next bid.

    Character-sequence similarity scores these ~0.6, which would mean the learned
    table only ever answered a spec typed identically - the exact-match case it
    already had.
    """
    spec = partquery.spec_key("Threshold, PEMKO 275A, 42 inches")
    for reworded in ("pemko 275a threshold 42in", "PEMKO-275A-42", "275A threshold 36inch"):
        assert partquery.similarity(spec, partquery.spec_key(reworded)) >= 0.75, reworded


def test_a_different_part_number_is_not_a_near_miss():
    """275A and 2750A are different parts, however alike the prose reads.

    This is the one that has to hold: a learned answer recalled onto the wrong
    part is a wrong price with a name and a date attached to it.
    """
    spec = partquery.spec_key("Threshold, PEMKO 275A, 42 inches")
    assert partquery.similarity(spec, partquery.spec_key("Threshold, PEMKO 2750A, 42 inches")) == 0.0
    assert partquery.similarity(spec, partquery.spec_key("hand dryer, World Dryer")) == 0.0


def test_a_measurement_is_not_a_part_number():
    """`42in` has a letter and a digit, and is a size."""
    assert partquery.part_tokens("pemko 275a threshold 42in") == {"275a"}
    assert partquery.part_tokens("door 36inch 7ft 1200mm") == set()
    assert "99eo" in partquery.part_tokens("von duprin 99eo 42 626")


def test_similarity_of_nothing_is_zero():
    assert partquery.similarity("", "anything") == 0.0
    assert partquery.similarity("anything", "") == 0.0


def test_identity_filter_escapes_user_input():
    """A part number is data, never a pattern."""
    built = partquery.identity_filter("A.B*C")
    pattern = built["$and"][-1]["$or"][0]["part"]["$regex"]
    assert pattern == r"^A\.B\*C$"
