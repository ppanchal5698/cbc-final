"""The price-book reader: list prices read off the real Hager book by geometry.

Each expected value was read off the page by eye. The layouts differ in exactly
the ways that broke earlier versions: a part printed beside the middle of its
finish block (closers), sizes centred on their block (hinges), a part printed
above its first size (pull plates), one price block shared by several lock
functions, and two tables side by side on one header line.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from cbc.modules.catalog.api import products as catalog_products
from cbc.modules.catalog.features import IndexCatalog
from cbc.modules.catalog.infrastructure import pricebook_reader
from cbc.shared.persistence import names
from tests.shared import mongo_client, require_mongo

BOOK = Path(__file__).resolve().parents[5] / "data" / "pricebooks" / "hager_price_book_18.pdf"

EXPECTED = [
    # page, model, size (or None), finish, list
    (297, "3933", '1-1/8" x 2-3/4"', "US4", 10.98),
    (297, "2-669-0389", None, "NF", 8.53),
    (297, "2-300-0041", None, "US26/US26D", 15.69),
    (67, "BB1279", '3-1/2" x 3-1/2"', "US26D", 54.84),
    (67, "BB1279", '4" x 4"', "US26D", 46.99),
    (68, "BB1279", '4-1/2" x 4-1/2"', "US26D", 23.76),
    (139, "5106", None, "ALM", 126.34),
    (139, "5107", None, "ALM", 98.28),
    (605, "32G", '3-1/2" x 15"', "US26D", 150.48),
    (294, "3410", None, "US26D", 369.48),
    (294, "3453", None, "US3", 515.32),
    (294, "3482", None, "US26D", 569.57),
]


@pytest.fixture(scope="module")
def pages():
    if not BOOK.is_file():
        pytest.skip(f"price book not present: {BOOK}")
    read = pricebook_reader.read_book(BOOK, sorted({page for page, *_ in EXPECTED}))
    return {result.page: result for result in read["pages"]}


@pytest.mark.parametrize("page,model,size,finish,price", EXPECTED)
def test_a_list_price_is_read_where_the_book_prints_it(pages, page, model, size, finish, price):
    rows = [r for r in pages[page].rows if r.model == model and r.finish == finish and r.size == size]
    assert [r.list_price for r in rows] == [price], [
        (r.model, r.size, r.finish, r.list_price) for r in pages[page].rows if r.model == model
    ]


def test_a_row_carries_where_it_came_from(pages):
    page = pages[297]
    assert page.effective == "2026-03-01" and page.printed_page == "23"
    row = next(r for r in page.rows if r.model == "3933" and r.finish == "US4")
    assert row.table == "Strikes" and "T-Strike" in row.description
    x0, y0, x1, y1 = row.bbox
    assert x0 < x1 and y0 < y1


def test_lock_functions_get_their_own_names_not_the_next_table(pages):
    row = next(r for r in pages[294].rows if r.model == "3453")
    assert row.description == "Entry"


# ── into priceBookEntries ─────────────────────────────────────────────────────

TEST_DB = "cbc_opshub_test_pricebook_entries"


@pytest.fixture()
def db():
    from cbc.shared import mongo as db_module
    from cbc.shared.config import settings

    raw = mongo_client()
    require_mongo(raw)
    previous, settings.mongodb_db = settings.mongodb_db, TEST_DB
    db_module._client = None
    raw.drop_database(TEST_DB)
    try:
        yield raw[TEST_DB]
    finally:
        raw.drop_database(TEST_DB)
        raw.close()
        settings.mongodb_db = previous
        db_module._client = None


def run(coro):
    from cbc.shared import mongo as db_module

    db_module._client = None
    try:
        return asyncio.run(coro)
    finally:
        db_module._client = None


def test_entries_are_versioned_by_file_and_only_the_current_one_prices(db, tmp_path, monkeypatch):
    if not BOOK.is_file():
        pytest.skip(f"price book not present: {BOOK}")
    real = pricebook_reader.read_book
    monkeypatch.setattr(pricebook_reader, "read_book", lambda path: real(path, [139]))
    book_id = db[names.PRICE_BOOKS].insert_one({"vendor": "Hager", "effective": "2026-03-01"}).inserted_id
    book = db[names.PRICE_BOOKS].find_one({"_id": book_id})

    summary = run(IndexCatalog.read_entries(book, BOOK, "hager"))
    assert summary.startswith("40 list price(s) read")
    again = run(IndexCatalog.read_entries(db[names.PRICE_BOOKS].find_one({"_id": book_id}), BOOK, "hager"))
    assert again.startswith("40 ")  # the same file is not read twice
    assert db[names.PRICE_BOOK_ENTRIES].count_documents({}) == 40

    found = run(catalog_products.list_prices(["5106", "NOPE"], vendor="Hager"))
    alm = [r for r in found["5106"] if r["finish"] == "ALM"]
    assert [(r["listPrice"], r["page"], r["printedPage"]) for r in alm] == [(126.34, 139, "8")]
    assert found["NOPE"] == []

    # A superseded sheet's rows stay as history but are never priced from.
    db[names.PRICE_BOOKS].update_one({"_id": book_id}, {"$set": {"entries.fileSha": "newer-file"}})
    assert run(catalog_products.list_prices(["5106"]))["5106"] == []
    assert db[names.PRICE_BOOK_ENTRIES].count_documents({}) == 40


def test_a_table_page_the_reader_misses_is_read_off_its_picture(db, tmp_path, monkeypatch):
    """The plan's read_price_row: the model transcribes, every row says it is the
    model's, and the first page it does not answer ends the asking."""
    from cbc.modules.catalog.domain.questions import PriceRow, PriceTable
    from cbc.shared import ai

    image = tmp_path / "page.png"
    image.write_bytes(b"png")
    monkeypatch.setattr(pricebook_reader, "read_book", lambda path: {"pages": [], "unread_pages": [18, 19, 65]})
    monkeypatch.setattr(IndexCatalog.pdfpages, "page_image", lambda *a, **k: {"image_path": str(image)})
    monkeypatch.setattr(IndexCatalog.pdfpages, "page_text", lambda *a, **k: "")
    answers = {18: [PriceRow(model="BB1191", size='4-1/2" x 4"', finish="US26D", list_price=41.2)],
               19: [PriceRow(model="bb1199", finish="US10B", list_price=38.0)]}
    asked: list[str] = []

    async def model(question, prompt, images=()):
        asked.append(prompt)
        page = int(prompt.split("page ")[1].rstrip("."))
        return ai.Asked(PriceTable(rows=answers[page]) if page in answers else None, error=None)

    monkeypatch.setattr(IndexCatalog.ops_ai, "ask", model)
    book_id = db[names.PRICE_BOOKS].insert_one({"vendor": "Hager", "effective": "2026-03-01"}).inserted_id

    book_file = tmp_path / "hager_book.pdf"
    book_file.write_bytes(b"%PDF-1.4 a book whose pages are faked above")
    summary = run(IndexCatalog.read_entries(db[names.PRICE_BOOKS].find_one({"_id": book_id}), book_file, "hager"))

    assert len(asked) == 3 and summary.endswith("1 table page(s) not read")
    rows = list(db[names.PRICE_BOOK_ENTRIES].find({}, {"_id": 0, "page": 1, "model": 1, "listPrice": 1, "readBy": 1}))
    assert sorted((r["page"], r["model"], r["listPrice"], r["readBy"]) for r in rows) == [
        (18, "BB1191", 41.2, "model"), (19, "BB1199", 38.0, "model")]
    assert db[names.PRICE_BOOKS].find_one({"_id": book_id})["entries"]["unreadPages"] == [65]
