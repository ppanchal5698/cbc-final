"""The ladder prices a line from the first source that is sure of it, and says
why when none is."""
from __future__ import annotations

from cbc.modules.pricing.api import pricing
from cbc.modules.pricing.domain.calc import cost_from_list
from cbc.modules.quoting.domain import ladder, matcher
from cbc.modules.quoting.domain.takeoff import Line


def finish(text):
    return matcher.finish_key(text, lambda raw: {"us_code": "US26D"} if raw in ("626", "US26D") else None)


def sources(**overrides) -> ladder.Sources:
    base = dict(
        models=lambda part: [part, part.split("-")[0]],
        finish=finish,
        lapsed=lambda effective: effective == "2019-01-01",
        cost_from_list=lambda price, multiplier: cost_from_list(price, multiplier)["cost"],
        multiplier_category=pricing.multiplier_category,
        special_nets=[
            {"item_code": "051455", "part_number": "431S", "net_price": 32.49,
             "description": '431S Commercial Saddle Threshold 36" Mill Finish', "section": "Thresholds"},
            {"item_code": "051456", "part_number": "431S", "net_price": 43.33,
             "description": '431S Commercial Saddle Threshold 48" Mill Finish', "section": "Thresholds"},
        ],
        special_net_effective="2026-03-02",
        catalog=[{"part": "346C", "manufacturer": "Pemko", "vendorKey": "pemko", "cost": 3.82, "listPrice": 7.96,
                  "multiplier": 0.48, "priceBookId": "pemko-book", "seedSource": "catalog.md + catalogs/ 2026 baseline"}],
        book=[{"vendor": "hager", "model": "BB1279", "size": '4-1/2" x 4-1/2"', "finish": "US26D", "listPrice": 23.76,
               "section": "Commercial Hinges", "file": "hager_price_book_18.pdf", "page": 68, "printedPage": "62",
               "effective": "2026-03-02", "priceBookId": "hager-book"},
              {"vendor": "hager", "model": "5100", "finish": "ALM", "listPrice": 440.71, "section": "Door Controls - 5100 Series",
               "file": "hager_price_book_18.pdf", "page": 136, "effective": "2026-03-02", "priceBookId": "hager-book"},
              {"vendor": "hager", "model": "5100", "finish": "ALM", "listPrice": 512.00, "section": "Door Controls - 5100 Series",
               "file": "hager_price_book_18.pdf", "page": 136, "effective": "2026-03-02", "priceBookId": "hager-book"},
              {"vendor": "hager", "model": "9999", "finish": "US26D", "listPrice": 10.0, "section": "Something Unmapped",
               "file": "hager_price_book_18.pdf", "page": 700, "effective": "2026-03-02", "priceBookId": "hager-book"}],
        books={"pemko-book": {"name": "PEMKO / Markar - Operating Baseline 2026", "effective": "2026-02-02"},
               "hager-book": {"name": "Hager Price Book #18", "effective": "2026-03-02"}},
        tiers={"hager": {"categories": {"architectural_hinges": 0.21, "door_controls": 0.30}, "effective_date": "2026-03-02"}},
        priced_at="2026-10-05T00:00:00+00:00",
    )
    return ladder.Sources(**{**base, **overrides})


def line(part, manufacturer="Hager", finish_=None, text="", **extra) -> Line:
    return Line(key="1:01", group="01", division="08 71 00", description=text or part, part=part,
                manufacturer=manufacturer, finish=finish_, qty=2.0, qty_per_opening=1.0, openings=["101", "102"],
                text=text, source_page=16, **extra)


def test_a_special_net_wins_and_is_cited() -> None:
    [row] = ladder.price(line("431S", text='THRESHOLD 48"'), sources())
    assert (row["cost"], row["cost_source"], row["price_status"]) == (43.33, "SPECIAL_NET", "PRICED")
    assert "item 051456" in row["cost_source_detail"] and row["multiplier_effective_date"] == "2026-03-02"
    assert row["openings"] == ["101", "102"] and row["quantity"] == 2.0 and row["division"] == "08 71 00"


def test_a_net_that_could_be_several_stops_the_ladder_for_a_person() -> None:
    [row] = ladder.price(line("431S", text="THRESHOLD"), sources())
    assert row["cost"] is None and "ambiguous_match" in row["flags"]
    assert "051455" in row["cost_source_detail"] and "051456" in row["cost_source_detail"]


def test_a_catalog_row_prices_with_its_book_and_basis() -> None:
    [row] = ladder.price(line("346C", manufacturer="Pemko"), sources())
    assert (row["cost"], row["cost_source"]) == (3.82, "CATALOG_BASELINE")
    assert "list $7.96 x 0.48" in row["cost_source_detail"]
    assert row["price_book_version"] == "PEMKO / Markar - Operating Baseline 2026, effective 2026-02-02"


def test_a_price_book_row_is_list_times_its_sections_multiplier() -> None:
    [row] = ladder.price(line("BB1279", finish_="626", text='HINGE 4-1/2" x 4-1/2"'), sources())
    assert (row["cost"], row["cost_source"], row["multiplier_tier"]) == (4.99, "LIST_X_MULTIPLIER", "architectural_hinges")
    assert row["list_price"] == 23.76 and row["multiplier"] == 0.21
    assert "hager_price_book_18.pdf p.68" in row["cost_source_detail"]


def test_without_a_tier_for_its_section_a_book_row_is_not_priced_at_a_guess() -> None:
    [row] = ladder.price(line("9999", finish_="US26D"), sources())
    assert row["cost"] is None and "no hager multiplier covers its section" in row["cost_source_detail"]


def test_a_lapsed_sheet_is_skipped_and_said() -> None:
    [row] = ladder.price(line("431S", text='THRESHOLD 48"'), sources(special_net_effective="2019-01-01"))
    assert row["cost"] is None and "past review" in row["cost_source_detail"]


def test_a_finish_one_source_lacks_falls_through_to_the_next() -> None:
    catalog = [{"part": "BB1279", "manufacturer": "Hager", "vendorKey": "hager", "cost": 9.0,
                "description": "BB1279 4-1/2 x 4-1/2 US3", "priceBookId": "hager-book"}]
    [row] = ladder.price(line("BB1279", finish_="626", text='4-1/2" x 4-1/2"'), sources(catalog=catalog))
    assert row["cost_source"] == "LIST_X_MULTIPLIER"  # the catalog row is US3; the book has US26D


def test_several_book_prices_are_a_question() -> None:
    [row] = ladder.price(line("5100", finish_="ALM"), sources())
    assert row["cost"] is None and "2 rows at 2 prices" in row["cost_source_detail"]


def test_an_allegion_part_is_a_hager_equal_to_name_and_the_part_as_an_alternate() -> None:
    base, alternate = ladder.price(line("99EO", manufacturer="Von Duprin"), sources())
    assert base["manufacturer"] == "Hager" and base["part_number"] is None and "allegion_equal_needed" in base["flags"]
    assert base.get("alternate_group") is None and base["cost"] is None
    assert (alternate["line_id"], alternate["cost_source"], alternate["alternate_group"]) == (
        "1:01:allegion", "DISTRIBUTOR_MANUAL", ladder.ALLEGION_ALTERNATE)


def test_what_another_party_supplies_is_priced_as_an_alternate_and_allegion_is_not_split() -> None:
    [row] = ladder.price(line("431S", text='48"', alternate="the schedule says 'OFCI'"), sources())
    assert row["alternate_group"] == ladder.BY_OTHERS_ALTERNATE and row["cost"] == 43.33
    [allegion] = ladder.price(line("1792NL", manufacturer="Falcon", alternate="supplied by landlord"), sources())
    assert allegion["cost_source"] == "DISTRIBUTOR_MANUAL" and allegion["alternate_group"] == ladder.BY_OTHERS_ALTERNATE


def test_a_special_margin_rides_on_every_line_with_its_reason() -> None:
    [row] = ladder.price(line("346C", manufacturer="Pemko"), sources(special_margin=(0.20, "special customer margin: Wendys")))
    assert (row["margin"], row["margin_override_reason"]) == (0.20, "special customer margin: Wendys")


def test_no_part_and_nothing_found_say_what_is_owed() -> None:
    [no_part] = ladder.price(line(None, text="HINGES"), sources())
    assert "no part number" in no_part["cost_source_detail"] and "no_part_number" in no_part["flags"]
    [nothing] = ladder.price(line("ZZ123", manufacturer="Arrow"), sources())
    assert nothing["cost"] is None and "needs a distributor or vendor quote" in nothing["cost_source_detail"]


EQUALS = {
    "preferred_brands": ["Bobrick", "ASI", "Bradley"],
    "catalog_prefixes": {"Bobrick": "B-", "ASI": "10-", "Gamco": "G-", "Bradley": ""},
    "rows": [{"specified": "G-212", "Bobrick": "212", "ASI": "0714", "Bradley": "915"}],
}
EQUAL_ROWS = [
    {"part": "10-0714", "manufacturer": "ASI", "vendorKey": "asi", "cost": 21.5, "priceBookId": "asi-book",
     "seedSource": "catalog.md + catalogs/ 2026 baseline"},
    {"part": "915", "manufacturer": "Bradley", "vendorKey": "bradley", "cost": 19.0, "priceBookId": "bradley-book"},
]


def accessory(part, manufacturer) -> Line:
    return Line(key=f"10:{part}", group="Restroom", division="10 28", description="TOILET TISSUE DISPENSER",
                part=part, manufacturer=manufacturer, finish=None, qty=2.0, source_page=27)


def test_a_division_10_part_cbc_cannot_price_is_the_equal_it_buys_for_least() -> None:
    [row] = ladder.price(accessory("B-212", "Bobrick"), sources(equals=EQUALS, equal_rows=EQUAL_ROWS))
    # Bobrick is what was specified and unpriceable; of its equals, Bradley costs CBC least.
    assert (row["cost"], row["part_number"], row["manufacturer"]) == (19.0, "915", "Bradley")
    # The NOTE the quote prints says what is offered for what; why is CBC's own business.
    assert row["substitution_note"] == ("Bradley 915 is offered as a direct equal to the specified Bobrick B-212, "
                                        "subject to approval before ordering.")
    assert "Bobrick B-212 specified and unpriced" in row["cost_source_detail"]
    assert "direct_equal" in row["flags"] and row["cost_source"] == "CATALOG_BASELINE"
    assert row["flags"].count("direct_equal") == 1, "the brands not chosen leave nothing on the line"


def test_brand_order_breaks_a_tie_between_equals() -> None:
    tied = [{**EQUAL_ROWS[0], "cost": 19.0}, EQUAL_ROWS[1]]
    [row] = ladder.price(accessory("B-212", "Bobrick"), sources(equals=EQUALS, equal_rows=tied))
    assert row["manufacturer"] == "ASI"


def test_a_division_10_part_cbc_can_price_is_quoted_as_specified() -> None:
    catalog = [{"part": "G-212", "manufacturer": "Gamco", "vendorKey": "gamco", "cost": 9.0, "priceBookId": "gamco-book"}]
    [row] = ladder.price(accessory("G-212", "Gamco"), sources(catalog=catalog, equals=EQUALS, equal_rows=EQUAL_ROWS))
    assert (row["cost"], row["part_number"]) == (9.0, "G-212") and "substitution_note" not in row


def test_an_equal_is_only_ever_offered_for_division_10() -> None:
    [row] = ladder.price(line("212", manufacturer="Bobrick"), sources(equals=EQUALS, equal_rows=EQUAL_ROWS))
    assert row["cost"] is None and "substitution_note" not in row


def test_a_row_chosen_among_the_undecided_is_priced_through_its_rung_and_says_who_chose_it() -> None:
    [undecided] = ladder.price(line("5100", finish_="ALM"), sources())
    assert undecided[ladder.UNDECIDED]["rung"] == "price book" and len(undecided[ladder.UNDECIDED]["shown"]) == 2
    priced = ladder.price_choice(undecided, 1, "parallel arm", sources())
    assert (priced["cost"], priced["cost_source"]) == (153.6, "LIST_X_MULTIPLIER")  # 512.00 x door_controls 0.30
    assert "model_chose_match" in priced["flags"] and "ambiguous_match" not in priced["flags"]
    assert "chosen among 2 by the model (parallel arm) - an estimator confirms it" in priced["cost_source_detail"]
    assert ladder.price_choice(undecided, 5, "no such row", sources()) is None


def test_a_door_is_priced_from_its_supplier_and_a_size_past_stock_is_a_vendor_quote() -> None:
    door = Line(key="door:hollow metal|3'-0\"|7'-0\"|A|90 MIN|", group="Doors", division="08 11 13",
                description="HOLLOW METAL DOOR, 3'-0\" X 7'-0\"", part=None, manufacturer=None, finish=None, qty=2.0)
    [row] = ladder.price(door, sources())
    assert row["cost"] is None and row["cost_source"] == "MANUAL" and "door supplier" in row["cost_source_detail"]
    tall = Line(key="door:wood|3'-0\"|9'-0\"|B||", group="Doors", division="08 14 16",
                description="WOOD DOOR, 3'-0\" X 9'-0\"", part=None, manufacturer=None, finish=None, qty=1.0,
                flags=["custom_size"])
    [rfq] = ladder.price(tall, sources())
    assert rfq["cost_source"] == "VENDOR_RFQ" and "past stock" in rfq["cost_source_detail"]
