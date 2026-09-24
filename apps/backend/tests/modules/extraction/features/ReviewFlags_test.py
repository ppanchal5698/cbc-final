"""GET /api/projects/{code}/review-flags: derived flags and the pass's own, both visible (NFR-2)."""
from __future__ import annotations

import json

from cbc.modules.pricing.api import reference_store
from cbc.shared import storage
from tests.shared import opshub_client

TEST_DB = "cbc_opshub_test_review_flags"


def test_derived_and_agent_flags_are_served_without_writing_and_an_unknown_bid_is_404() -> None:
    reference_store.use_memory({})  # the seed tier sheet, never a database
    try:
        with opshub_client(TEST_DB, isolated_storage=True) as client:
            created = client.post("/api/projects", json={"name": "Review flags route"})
            assert created.status_code == 201, created.text
            project = created.json()

            root = storage.project_dir(project["slug"])
            (root / "extracted").mkdir(parents=True, exist_ok=True)
            (root / "review").mkdir(parents=True, exist_ok=True)
            (root / "extracted" / "line_items.json").write_text(json.dumps({"openings": [
                {"door_number": "101", "source_page": 4, "bbox": [1, 2, 3, 4], "handing": "LH", "size": "3070"},
            ]}), encoding="utf-8")
            written = [{"opening": "Door 101", "field": "count_reconciliation", "severity": "medium",
                        "note": "A1.1 shows two doors at 101"}]
            (root / "review" / "review_flags.json").write_text(json.dumps(written), encoding="utf-8")

            response = client.get(f"/api/projects/{project['code']}/review-flags")
            assert response.status_code == 200, response.text
            fields = {(flag["opening"], flag["field"]) for flag in response.json()["flags"]}
            assert ("Door 101", "fire_rating") in fields, "the derived missing-rating flag"
            assert ("Door 101", "count_reconciliation") in fields, "the pass's own flag survives"
            saved = json.loads((root / "review" / "review_flags.json").read_text(encoding="utf-8"))
            assert saved == written, "reading the flags writes nothing"

            assert client.get("/api/projects/CBC-NO-SUCH-BID/review-flags").status_code == 404
    finally:
        reference_store.use_memory(None)
