"""A priced row is a specified item only when model, finish and size agree - and
several prices left is a question, never the first row."""
from __future__ import annotations

import pytest

from cbc.modules.quoting.domain import matcher

CROSSWALK = {"626": "US26D", "630": "US32D", "652": "US26D"}


def resolve(text: str):
    text = text.upper()
    if text.startswith("US"):
        return {"us_code": text} if text[2:].isalnum() else None
    return {"us_code": CROSSWALK[text]} if text in CROSSWALK else None


def finish(text):
    return matcher.finish_key(text, resolve)


@pytest.mark.parametrize(("text", "sizes"), [
    ('4-1/2" x 4-1/2"', (4.5, 4.5)), ("4.5 X 4.5", (4.5, 4.5)), ('36"', (36.0,)), ("42 in", (42.0,)),
    ("3'-0\" x 7'-0\"", (36.0, 84.0)), ("190S-20X40-32D", (20.0, 40.0)), ('10" x 34" (for 36" Door)', (10.0, 34.0, 36.0)),
    ("BB1279", ()), ("1 1/2 PR", ()), ("B-5806.99x48", (48.0,)),
])
def test_sizes_are_read_in_inches_and_part_numbers_are_not_sizes(text, sizes) -> None:
    assert matcher.dimensions(text) == sizes


@pytest.mark.parametrize(("written", "key"), [
    ("626", "26D"), ("US26D", "26D"), ("26D/626", "26D"), ("US26D (626) - Satin Chrome", "26D"),
    ("652", "26D"), ("ALM", "ALM"), ("689", "ALM"), ("693", "BLK"), ("Satin Chrome", None), ("", None),
])
def test_one_finish_whichever_way_it_is_written(written, key) -> None:
    assert finish(written) == key


def test_allegion_is_found_by_word_not_by_substring() -> None:
    assert matcher.is_allegion("IVES 5BB1 4.5 x 4.5")
    assert matcher.is_allegion("closer", manufacturer="Falcon")
    assert not matcher.is_allegion("FRP adhesives, 3.5 gal")  # "ives" inside a word
    assert not matcher.is_allegion("LOCKNET SECURITY DOOR")  # a door maker, not Locknetics


BOOK = [
    {"model": "BB1279", "size": '4-1/2" x 4-1/2"', "finish": "US26D", "listPrice": 23.76},
    {"model": "BB1279", "size": '4-1/2" x 4-1/2"', "finish": "US10B", "listPrice": 43.62},
    {"model": "BB1279", "size": '5" x 4-1/2"', "finish": "US26D", "listPrice": 31.10},
    {"model": "3553", "size": None, "finish": "US26D", "listPrice": 256.31, "description": "Entry"},
    {"model": "3553", "size": None, "finish": "US3", "listPrice": 275.53, "description": "Entry"},
]
NETS = [
    {"part_number": "431S", "description": '431S Commercial Saddle Threshold 36" Mill Finish', "net_price": 32.49},
    {"part_number": "431S", "description": '431S Commercial Saddle Threshold 48" Mill Finish', "net_price": 43.33},
    {"part_number": "3553", "description": "3553 Entrance Lock US26D WTN SCC KD ASA", "net_price": 64.58},
    {"part_number": "3553", "description": "3553 Entrance Lock IC US26D WTN NC ASA IC", "net_price": 56.49},
]


def book(spec, models):
    return matcher.choose(spec, BOOK, models=models, model_of=lambda r: r["model"], finish_of=lambda r: r["finish"],
                          size_of=lambda r: r["size"], price_of=lambda r: r["listPrice"],
                          describe=lambda r: r.get("description"), finish=finish)


def nets(spec, models):
    return matcher.choose(spec, NETS, models=models, model_of=lambda r: r["part_number"],
                          finish_of=lambda r: None, size_of=lambda r: r["description"],
                          price_of=lambda r: r["net_price"], describe=lambda r: r["description"], finish=finish)


def test_the_row_is_the_one_whose_finish_and_size_the_legend_gave() -> None:
    hit = book(matcher.Spec(part="BB1279", finish="626", text='HINGE 4-1/2" x 4-1/2"'), ["BB1279"])
    assert hit.row["listPrice"] == 23.76
    assert book(matcher.Spec(part="BB1279", finish="US10B", text="4.5 x 4.5"), ["BB1279"]).row["listPrice"] == 43.62


def test_several_prices_left_is_a_question_not_the_first_row() -> None:
    open_question = book(matcher.Spec(part="BB1279"), ["BB1279"])
    assert open_question.row is None and open_question.ambiguous and len(open_question.candidates) == 3


def test_a_finish_or_size_the_rows_do_not_have_is_a_miss_the_next_source_may_answer() -> None:
    miss = book(matcher.Spec(part="BB1279", finish="US32D"), ["BB1279"])
    assert miss.row is None and not miss.ambiguous and "finish" in miss.reason
    assert not book(matcher.Spec(part="BB1279", finish="626", text='6" x 6"'), ["BB1279"]).ambiguous


def test_the_legends_own_words_settle_a_variant() -> None:
    assert nets(matcher.Spec(part="431S", text='THRESHOLD 48"'), ["431S"]).row["net_price"] == 43.33
    assert nets(matcher.Spec(part="3553", text="ENTRY LOCK IC"), ["3553"]).row["net_price"] == 56.49
    assert nets(matcher.Spec(part="3553", text="ENTRY LOCK"), ["3553"]).ambiguous


def test_a_series_matches_its_sizes_past_a_separator_and_never_by_length() -> None:
    rows = [{"part": "B-5806.99x48", "cost": 30.0, "description": 'Grab Bar 48" Length'},
            {"part": "B-5806.99x36", "cost": 26.0, "description": 'Grab Bar 36" Length'},
            {"part": "B-580616x18", "cost": 12.0, "description": 'Vinyl Grab Bar 18" Length'}]

    def choose(text):
        return matcher.choose(matcher.Spec(part="B-5806", text=text), rows, models=["B-5806"],
                              model_of=lambda r: r["part"], finish_of=lambda r: None,
                              size_of=lambda r: r["description"], price_of=lambda r: r["cost"], finish=finish)

    assert choose('GRAB BAR 36"').row["part"] == "B-5806.99x36"
    unsized = choose("GRAB BAR")
    assert unsized.ambiguous and {r["part"] for r in unsized.candidates} == {"B-5806.99x48", "B-5806.99x36"}


def test_a_rating_is_compared_in_minutes_however_it_is_written() -> None:
    """`1-1/2 HR` was 112 minutes to the matcher and `3 HR` was 3."""
    from cbc.modules.quoting.domain.matching import rating_conflict

    assert not rating_conflict("1-1/2 HR", "90 MIN")
    assert rating_conflict("3 HR", "20")
    assert not rating_conflict("NR", None) and not rating_conflict(None, None)
    assert rating_conflict("90", None), "a rated door takes only an item that says it is rated"
