"""Intake module: documents and versions, every operation pinned."""
from __future__ import annotations

import pytest

from tests.characterization._harness import finish_pipeline_jobs, pdf_bytes
from tests.shared import opshub_client

TEST_DB = "cbc_opshub_char_intake"
DOCS = "/api/projects/{code}/documents"
VERSIONS = "/api/projects/{code}/versions"


@pytest.fixture(scope="module")
def client():
    with opshub_client(TEST_DB, isolated_storage=True) as test_client:
        yield test_client


@pytest.fixture(scope="module")
def bid(client) -> dict:
    response = client.post("/api/projects", json={"name": "Characterization - intake", "state": "OH"})
    assert response.status_code == 201, response.text
    return {"code": response.json()["code"]}


def _url(template: str, bid: dict, **ids) -> str:
    return template.format(code=bid["code"], **ids)


def test_list_documents_on_an_empty_bid(client, bid, snapshots) -> None:
    snapshots.pin("GET /api/projects/{code}/documents", client.get(_url(DOCS, bid)))


def test_upload_a_bid_set(client, bid, snapshots) -> None:
    op = "POST /api/projects/{code}/documents"
    data = pdf_bytes(pages=2)
    response = snapshots.pin(op, client.post(_url(DOCS, bid), files={"file": ("plans.pdf", data, "application/pdf")}))
    assert response.json()["document"]["pages"] == 2
    bid["document"] = response.json()["document"]["id"]
    snapshots.pin(
        op,
        client.post(_url(DOCS, bid), files={"file": ("again.pdf", data, "application/pdf")}),
        variant="identical bytes",
    )
    snapshots.pin(
        op,
        client.post(_url(DOCS, bid), files={"file": ("notes.pdf", b"not a pdf at all", "application/pdf")}),
        variant="not a pdf",
    )
    finish_pipeline_jobs(TEST_DB, bid["code"])


def test_download_the_original_file(client, bid, snapshots) -> None:
    url = _url(DOCS + "/{document_id}/file", bid, document_id=bid["document"])
    snapshots.pin("GET /api/projects/{code}/documents/{document_id}/file", client.get(url))


def test_render_a_page(client, bid, snapshots) -> None:
    op = "GET /api/projects/{code}/documents/{document_id}/page/{page_number}"
    snapshots.pin(op, client.get(_url(DOCS + "/{document_id}/page/1", bid, document_id=bid["document"]), params={"dpi": 72}))
    snapshots.pin(op, client.get(_url(DOCS + "/{document_id}/page/99", bid, document_id=bid["document"])), variant="no such page")


def test_page_size(client, bid, snapshots) -> None:
    url = _url(DOCS + "/{document_id}/page/1/size", bid, document_id=bid["document"])
    snapshots.pin("GET /api/projects/{code}/documents/{document_id}/page/{page_number}/size", client.get(url))


def test_page_blocks(client, bid, snapshots) -> None:
    """MinerU blocks for one page. Empty until a parse has run, which is the
    normal state on a freshly uploaded bid - and the answer must still be a
    shaped 200, because extraction falls back to pdf-tools on an empty read."""
    op = "GET /api/projects/{code}/documents/{document_id}/pages/{page_number}/blocks"
    url = _url(DOCS + "/{document_id}/pages/1/blocks", bid, document_id=bid["document"])
    snapshots.pin(op, client.get(url))
    snapshots.pin(
        op,
        client.get(_url(DOCS + "/{document_id}/pages/99/blocks", bid, document_id=bid["document"])),
        variant="no such page",
    )


def test_list_versions_before_any_snapshot(client, bid, snapshots) -> None:
    snapshots.pin("GET /api/projects/{code}/versions", client.get(_url(VERSIONS, bid)))


def test_snapshot_a_version(client, bid, snapshots) -> None:
    response = snapshots.pin("POST /api/projects/{code}/versions", client.post(_url(VERSIONS, bid), json={"reason": "Addendum 1"}))
    bid["version"] = response.json()["version"]["version"]


def test_get_a_version(client, bid, snapshots) -> None:
    op = "GET /api/projects/{code}/versions/{version}"
    snapshots.pin(op, client.get(_url(VERSIONS + "/{version}", bid, version=bid["version"])))
    snapshots.pin(op, client.get(_url(VERSIONS + "/999", bid)), variant="no such version")


def test_diff_a_version(client, bid, snapshots) -> None:
    snapshots.pin("GET /api/projects/{code}/versions/{version}/diff", client.get(_url(VERSIONS + "/{version}/diff", bid, version=bid["version"])))


def test_reconcile_a_version(client, bid, snapshots) -> None:
    op = "POST /api/projects/{code}/versions/{version}/reconcile"
    snapshots.pin(op, client.post(_url(VERSIONS + "/{version}/reconcile", bid, version=bid["version"])))
    second = client.post(_url(VERSIONS, bid), json={"reason": "Addendum 2"})
    assert second.status_code == 201, second.text
    snapshots.pin(
        op,
        client.post(_url(VERSIONS + "/{version}/reconcile", bid, version=bid["version"])),
        variant="superseded version",
    )


def test_detach_a_document(client, bid, snapshots) -> None:
    op = "DELETE /api/projects/{code}/documents/{document_id}"
    url = _url(DOCS + "/{document_id}", bid, document_id=bid["document"])
    snapshots.pin(op, client.delete(url))
    snapshots.pin(op, client.delete(url), variant="already detached")
