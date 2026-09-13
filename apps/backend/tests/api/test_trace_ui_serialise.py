"""serialise keeps top-level job.traceId for ops UI."""
from __future__ import annotations

from bson import ObjectId

from cbc.shared.mongo import serialise


def test_serialise_preserves_trace_id() -> None:
    job = {
        "_id": ObjectId(),
        "type": "extract_bid_set",
        "traceId": "hop-trace-xyz",
        "status": "dead",
    }
    out = serialise(job)
    assert out["traceId"] == "hop-trace-xyz"
    assert "id" in out
