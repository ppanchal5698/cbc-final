"""Describing a catalog page without reading it wrongly.

The index this replaces pre-extracted every product row and got 37.8% of its
codes wrong - dates as part numbers, one vendor's sheet yielding nothing while
reporting success. PageIndex stores no prices at all, so the failure it must
avoid is different: sending a pricing pass to the wrong page, or citing a page
number an estimator cannot find in the book.
"""
from __future__ import annotations

import pytest

from cbc.pageindex.describe import describe_page, needs_a_second_look, page_lines
from cbc.pageindex.models import PageProfile

# The real Hager running header: printed number, date, url, then the section.
HAGER = PageProfile(
    title_source="line_index:3",
    printed_page_source="line_index:0",
    boilerplate=["www.hagerco.com", "03/01/2026"],
)

HAGER_PAGE = (
    "23\n03/01/2026\nwww.hagerco.com\nLocks - 3400 Series\n"
    "Strikes\nDescription\n"
    "3400 ANSI strike 1-1/4 x 4-7/8 US26D  $12.50\n"
    "3402 T-strike US10B  $14.75\n"
    "3400L lip strike  $16.00\n"
)


def test_the_profile_finds_the_section_title() -> None:
    assert describe_page(HAGER_PAGE, 297, HAGER).title == "Locks - 3400 Series"


def test_both_page_numbers_are_recorded() -> None:
    """The pair NFR-3 needs.

    Hager's PDF page 297 prints as "23" because numbering restarts per section.
    Across the real catalogs this is not an edge case - 775 of 1,216 pages print
    a number that differs from their PDF index. An estimator sent to "page 23" of
    a 744-page book cannot find the line without both.
    """
    entry = describe_page(HAGER_PAGE, 297, HAGER)
    assert entry.pdf_page == 297
    assert entry.printed_page == "23"
    assert entry.locator() == "PDF p297 (printed p23)"


def test_a_page_whose_numbers_agree_says_it_once() -> None:
    entry = describe_page("7\n03/01/2026\nwww.hagerco.com\nHinges\nBB1279  $9.00", 7, HAGER)
    assert entry.locator() == "p7"


def test_a_price_page_is_recognised_as_one() -> None:
    entry = describe_page(HAGER_PAGE, 297, HAGER)
    assert entry.has_prices
    assert entry.kind == "price_table"
    assert entry.confidence >= 0.9


def test_the_part_families_on_the_page_are_collected() -> None:
    """Routing, not reproduction: enough to know the 3400s live here."""
    assert "3400" in describe_page(HAGER_PAGE, 297, HAGER).code_prefixes


def test_finish_codes_are_not_part_families() -> None:
    """US26D is a finish (rule 7.5), and appears on nearly every price page.

    Left in, they crowd the real families out of the routing list entirely.
    """
    prefixes = describe_page(HAGER_PAGE, 297, HAGER).code_prefixes
    assert not [code for code in prefixes if code.startswith("US")], prefixes


def test_a_date_is_not_a_part_number() -> None:
    """183 dates were indexed as products by the extractor this replaces."""
    entry = describe_page("Effective 03/01/2026\n11/21/2019 revision\nNotes", 1, PageProfile())
    assert not [c for c in entry.code_prefixes if "/" in c or c in {"2026", "2019"}], entry.code_prefixes


def test_a_page_with_no_text_layer_is_not_described_as_read() -> None:
    """A scan gets a low score and a name that says so, not an invented summary."""
    entry = describe_page("", 5, HAGER)
    assert entry.kind == "diagram"
    assert entry.confidence <= 0.2
    assert needs_a_second_look(entry)


def test_a_well_read_page_needs_no_second_look() -> None:
    assert not needs_a_second_look(describe_page(HAGER_PAGE, 297, HAGER))


def test_boilerplate_is_kept_out_of_the_description() -> None:
    entry = describe_page(HAGER_PAGE, 297, HAGER)
    assert "hagerco.com" not in entry.description
    assert "03/01/2026" not in entry.description


def test_a_profile_that_does_not_fit_degrades_rather_than_lies() -> None:
    """Point a Hager profile at a page that is not Hager.

    It must not assert a title it did not find; the fallback is the page's own
    first line, and the score drops to say the title is inferred.
    """
    entry = describe_page("MODEL NUMBER\nASI WASHROOM ACCESSORIES\n0197  $210.00", 10, HAGER)
    assert entry.confidence <= 0.6


@pytest.mark.parametrize(
    "source, expected",
    [("line_index:3", "Locks - 3400 Series"), ("regex:^(Locks.*)$", "Locks - 3400 Series")],
)
def test_both_profile_grammars_resolve(source: str, expected: str) -> None:
    profile = PageProfile(title_source=source, boilerplate=HAGER.boilerplate)
    assert describe_page(HAGER_PAGE, 297, profile).title == expected


def test_an_unresolvable_rule_returns_nothing_rather_than_something() -> None:
    for bad in ("line_index:99", "line_index:not-a-number", "regex:([unclosed", "nonsense"):
        entry = describe_page(HAGER_PAGE, 297, PageProfile(title_source=bad))
        assert entry.title != "", "should fall back to the first line, not crash"
    assert describe_page("", 1, PageProfile(title_source="line_index:0")).title == ""


def test_a_spreadsheet_block_cites_its_sheet_and_rows() -> None:
    """Three of the fourteen catalogs are spreadsheets, where a page is a fiction."""
    entry = describe_page(
        "Program Net\nB-2888 Soap dispenser  $41.00",
        1,
        PageProfile(),
        sheet="Program Net",
        rows=[12, 260],
    )
    assert entry.locator() == "sheet Program Net rows 12-260"
    assert "B-2888" in entry.code_prefixes


def test_page_lines_drops_blanks_and_whitespace() -> None:
    assert page_lines("a\n\n   \n b \n") == ["a", "b"]


# ── the credential the catalog server is entitled to ────────────────────────


def test_the_catalog_server_never_reaches_the_writable_connection() -> None:
    """It runs inside the Claude subprocess, which is denied the root URI.

    An earlier cut had the server call the async query helper, which fetches
    through `cbc.db` - the application's writable client. That silently undid
    `provider.WITHHELD`: pymongo is in the image, so a run holding that string
    could write to any collection, straight past every read-only assertion the
    tools make about themselves.
    """
    from tests.shared import ROOT

    source = (ROOT / "mcp-servers" / "catalog" / "server.py").read_text(encoding="utf-8")
    assert "from cbc.db import" not in source
    assert "pageindex import store" not in source, "store writes; the server must not import it"
    assert "reader" in source, "the server reads through the read-only reader"


def test_the_reader_refuses_without_a_read_only_credential(monkeypatch) -> None:
    """No credential is not a reason to fall back to the writable one."""
    from cbc.pageindex import reader

    monkeypatch.delenv("MONGODB_READONLY_URI", raising=False)
    reader.reset()
    with pytest.raises(reader.ReadOnlyIndexUnavailable):
        reader.list_catalogs()
    reader.reset()


def test_the_read_only_uri_authenticates_where_the_user_was_made() -> None:
    """The two were built together and never run, so they had drifted apart.

    `ensure_readonly_user` creates the user in the application database while
    `readonly_uri` inherited `authSource=admin` from the root connection string.
    The first real connection failed authentication.
    """
    from cbc.config import settings
    from cbc.db import readonly_uri

    uri = readonly_uri()
    if not uri:
        pytest.skip("no mongodb configured here")
    assert f"authSource={settings.mongodb_db}" in uri
    assert "authSource=admin" not in uri


def test_a_hit_names_where_the_file_is_not_just_what_it_is_called() -> None:
    """A page nobody can open is a page nobody found.

    `find_pages` returned a bare filename, so a run had to guess the directory -
    and guessed the project's own uploads folder. The page was right; the file
    was not there; the line went MANUAL.
    """
    from cbc.pageindex.models import PageEntry, PageIndexDocument
    from cbc.pageindex.query import PRICEBOOK_DIR, rank_pages

    document = PageIndexDocument(
        catalog_id="hager_price_book_18",
        vendor="hager",
        file_name="hager_price_book_18.pdf",
        file_hash="sha256:x",
        pages=[
            PageEntry(
                pdf_page=297,
                printed_page="23",
                title="Locks - 3400 Series",
                code_prefixes=["3400"],
                has_prices=True,
                confidence=0.9,
            )
        ],
    )
    hit = rank_pages([document], "3400")["pages"][0]

    assert hit["file_path"] == f"{PRICEBOOK_DIR}/hager_price_book_18.pdf"
    assert "uploads" not in hit["file_path"]
    assert hit["pdf_page"] == 297


def test_a_whole_part_number_finds_the_page_that_holds_its_family() -> None:
    """The index stores families; a bid asks for whole part numbers.

    Page 23 of the Pemko book carries the 4131 series. Querying `4131` found it
    and querying `4131CNBL36` - an actual code printed on that page - found
    nothing, because the match only ran family-starts-with-query. So the pricing
    pass got no page for the part it was asked to price, and invented a cost
    instead. Both directions have to match.
    """
    from cbc.pageindex.models import PageEntry, PageIndexDocument
    from cbc.pageindex.query import rank_pages

    document = PageIndexDocument(
        catalog_id="pemko_markar_price_book_2026",
        vendor="pemko",
        file_name="pemko_markar_price_book_2026.pdf",
        file_hash="sha256:x",
        pages=[
            PageEntry(
                pdf_page=23,
                printed_page="23",
                title="Pemko Thresholds and Weatherstripping",
                code_prefixes=["4131", "18041"],
                has_prices=True,
                confidence=0.9,
            )
        ],
    )

    for part in ("4131CNBL36", "18041BSPNB", "4131"):
        result = rank_pages([document], part)
        assert result["count"] == 1, f"{part} found no page"
        assert result["pages"][0]["pdf_page"] == 23


def test_a_part_from_another_family_still_does_not_match() -> None:
    """Matching both ways must not turn into matching anything."""
    from cbc.pageindex.models import PageEntry, PageIndexDocument
    from cbc.pageindex.query import rank_pages

    document = PageIndexDocument(
        catalog_id="pemko_markar_price_book_2026",
        vendor="pemko",
        file_name="pemko_markar_price_book_2026.pdf",
        file_hash="sha256:x",
        pages=[
            PageEntry(
                pdf_page=23,
                printed_page="23",
                title="Pemko Thresholds and Weatherstripping",
                code_prefixes=["4131"],
                has_prices=True,
                confidence=0.9,
            )
        ],
    )
    assert rank_pages([document], "8400")["count"] == 0


def test_a_page_with_two_money_columns_is_marked() -> None:
    """MAP is an advertising floor, not a cost basis.

    ASI heads its price tables "LIST PRICE | **MAP PRICING" on 33 pages, and MAP
    runs about 55% of list - 145.70 against 80.10 on page 35. A pass that takes
    the rightmost number on the row gets MAP, applies the vendor multiplier and
    quotes half what the part costs: the error that wins a bid and loses money.
    """
    from cbc.pageindex.describe import describe_page
    from cbc.pageindex.models import PageProfile

    text = "\n".join(
        [
            "WASHROOM ACCESSORIES",
            "MODEL NUMBER  DESCRIPTION  LIST PRICE  **MAP PRICING",
            "10-0210-41  Paper Towel Dispenser  145.70  80.10",
        ]
    )
    entry = describe_page(text, 35, PageProfile())
    assert entry.price_columns == ["LIST", "MAP"]


def test_an_ordinary_price_page_is_not_marked() -> None:
    """One money column is a price list, not a trap - Hager prints only list."""
    from cbc.pageindex.describe import describe_page
    from cbc.pageindex.models import PageProfile

    text = "\n".join(
        ["Locks - 3400 Series", "3453  Storeroom Lock  US26D  $256.31"]
    )
    assert describe_page(text, 297, PageProfile()).price_columns == []


def test_the_caution_reaches_the_run_that_opens_the_page() -> None:
    """Recorded in the index is not enough; it has to arrive with the page."""
    from cbc.pageindex.models import PageEntry, PageIndexDocument
    from cbc.pageindex.query import rank_pages

    document = PageIndexDocument(
        catalog_id="asi_price_list",
        vendor="asi",
        file_name="asi_price_list.pdf",
        file_hash="sha256:x",
        pages=[
            PageEntry(
                pdf_page=35,
                title="Washroom Accessories",
                code_prefixes=["10-0210"],
                has_prices=True,
                price_columns=["LIST", "MAP"],
                confidence=0.9,
            )
        ],
    )
    hit = rank_pages([document], "10-0210")["pages"][0]
    assert hit["price_columns"] == ["LIST", "MAP"]
    assert "MAP" in hit["caution"] and "not a" in hit["caution"]
