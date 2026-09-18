"""Catalog module: products and price books, every operation pinned.

A price-book upload writes the file into `settings.pricebook_dir`, which in a
checkout is the real `data/pricebooks` - purchasing's directory, and one the
delete guard does not currently protect. The whole module runs with that setting
pointed at a temporary directory, and the upload test asserts the file landed
there.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from cbc.shared.config import settings
from tests.characterization._harness import pdf_bytes
from tests.shared import ROOT, opshub_client

TEST_DB = "cbc_opshub_char_catalog"


@pytest.fixture(scope="module")
def books_dir(tmp_path_factory) -> Path:
    return tmp_path_factory.mktemp("pricebooks")


@pytest.fixture(scope="module")
def client(books_dir):
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(settings, "pricebook_dir", books_dir)
        with opshub_client(TEST_DB, isolated_storage=True, role="admin") as test_client:
            yield test_client


@pytest.fixture(scope="module")
def state() -> dict:
    return {}


# ── products ─────────────────────────────────────────────────────────────────


def test_create_a_product(client, state, snapshots) -> None:
    op = "POST /api/catalog/products"
    body = {"part": "CHAR-1", "description": "Characterization hinge", "manufacturer": "Hager",
            "cost": 10.0, "division": "08", "productType": "commodity"}
    response = snapshots.pin(op, client.post("/api/catalog/products", json=body))
    state["product"] = response.json()["id"]
    snapshots.pin(op, client.post("/api/catalog/products", json={"part": "CHAR-1"}), variant="same part, no manufacturer")


def test_search_products(client, snapshots) -> None:
    snapshots.pin("GET /api/catalog/products", client.get("/api/catalog/products", params={"q": "CHAR-1", "limit": 5}))


def test_get_a_product(client, state, snapshots) -> None:
    op = "GET /api/catalog/products/{product_id}"
    snapshots.pin(op, client.get(f"/api/catalog/products/{state['product']}"))
    snapshots.pin(op, client.get("/api/catalog/products/" + "0" * 24), variant="missing product")


def test_update_a_product(client, state, snapshots) -> None:
    op = "PATCH /api/catalog/products/{product_id}"
    snapshots.pin(op, client.patch(f"/api/catalog/products/{state['product']}", json={"cost": 12.0}))


def test_delete_a_product(client, state, snapshots) -> None:
    op = "DELETE /api/catalog/products/{product_id}"
    snapshots.pin(op, client.delete(f"/api/catalog/products/{state['product']}"))
    snapshots.pin(op, client.delete(f"/api/catalog/products/{state['product']}"), variant="already deleted")


# ── price books ──────────────────────────────────────────────────────────────


def test_create_a_price_book(client, state, snapshots) -> None:
    body = {"vendor": "characterization", "program": "Test program", "multiplier": 0.5, "effective": "2026-01-01"}
    response = snapshots.pin("POST /api/price-books", client.post("/api/price-books", json=body))
    state["book"] = response.json()["id"]
    bare = client.post("/api/price-books", json={"vendor": "characterization-bare"})
    assert bare.status_code == 201, bare.text
    state["bare_book"] = bare.json()["id"]


def test_list_price_books(client, snapshots) -> None:
    snapshots.pin("GET /api/price-books", client.get("/api/price-books"))


def test_get_a_price_book(client, state, snapshots) -> None:
    op = "GET /api/price-books/{book_id}"
    snapshots.pin(op, client.get(f"/api/price-books/{state['book']}"))
    snapshots.pin(op, client.get("/api/price-books/" + "0" * 24), variant="missing book")


def test_update_a_price_book(client, state, snapshots) -> None:
    snapshots.pin("PATCH /api/price-books/{book_id}", client.patch(f"/api/price-books/{state['book']}", json={"note": "characterized"}))


def test_mark_a_price_book_reviewed(client, state, snapshots) -> None:
    snapshots.pin("POST /api/price-books/{book_id}/mark-reviewed", client.post(f"/api/price-books/{state['book']}/mark-reviewed"))


def test_upload_a_price_book_file(client, state, books_dir, snapshots) -> None:
    files = {"file": ("characterization_sheet.pdf", pdf_bytes(pages=1, label="PRICE SHEET"), "application/pdf")}
    snapshots.pin(
        "POST /api/price-books/{book_id}/file",
        client.post(f"/api/price-books/{state['book']}/file", files=files),
        # Both exist only when MinerU is reachable to parse the sheet.
        drop=("body.parseJob", "body.priceBook.parse"),
    )
    assert [p.name for p in books_dir.iterdir()] == ["characterization_sheet.pdf"]
    real = ROOT / "data" / "pricebooks"
    assert not any(p.name.startswith("characterization") for p in real.iterdir()), "upload leaked into data/pricebooks"


def test_download_a_price_book_file(client, state, snapshots) -> None:
    op = "GET /api/price-books/{book_id}/file"
    snapshots.pin(op, client.get(f"/api/price-books/{state['book']}/file"))
    snapshots.pin(op, client.get(f"/api/price-books/{state['bare_book']}/file"), variant="no file attached")


def test_delete_a_price_book(client, state, snapshots) -> None:
    op = "DELETE /api/price-books/{book_id}"
    snapshots.pin(op, client.delete(f"/api/price-books/{state['book']}"))
    snapshots.pin(op, client.delete(f"/api/price-books/{state['book']}"), variant="already deleted")
