"""catalogPages / multiplierPages helpers."""
from __future__ import annotations

from datetime import datetime, timezone

from cbc.modules.catalog.api import catalog_parse


def test_remap_blocks_drops_bid_keys_and_keeps_blocks():
    rows = [
        {
            "projectId": None,
            "documentId": None,
            "contentSha": "sha256:abc",
            "page": 3,
            "pageSize": {"width": 100, "height": 200},
            "blocks": [{"n": 1, "type": "text", "text": "3510", "bbox": [1, 2, 3, 4]}],
            "verified": 0.9,
            "parser": {"name": "mineru"},
            "parsedAt": datetime.now(timezone.utc),
        }
    ]
    out = catalog_parse.remap_blocks(
        rows,
        extras={
            "priceBookId": "book1",
            "catalogId": "hager_price_book_18",
            "vendor": "hager",
            "filePath": "data/pricebooks/hager.pdf",
        },
    )
    assert len(out) == 1
    assert out[0]["page"] == 3
    assert out[0]["catalogId"] == "hager_price_book_18"
    assert out[0]["blocks"][0]["text"] == "3510"
    assert "projectId" not in out[0]
    assert "documentId" not in out[0]
