"""Shared literal types and evidence model."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

LineStatus = Literal["clear", "needs_look", "duplicate", "by_hand"]
Stage = Literal["intake", "extraction", "quote", "proposal"]
JobType = Literal[
    "extract_bid_set",
    "rerun_extraction",
    "match_and_price",
    "build_proposal",
    "ingest_pricebook",
    "ingest_addendum",
    # Catalog indexing. Builds the PageIndex document that says what each page of
    # a vendor sheet sells; the LLM `ingest_pricebook` pass stays as the adapter
    # of last resort.
    "index_catalog",
    "delete_catalog",
    # Deprecated in cbc-copilot-final: kept so historical Mongo rows still
    # deserialise. New autopilot runs use orchestrate=true on extract_bid_set
    # and chain match_and_price → build_proposal across domain workers.
    "run_full_pipeline",
]
JobStatus = Literal["queued", "running", "done", "failed", "cancelled", "dead"]

# One in-flight job of these types per project. A second "re-run extraction" click
# while the first is still running is a double-click, not a second job.
#
# `ingest_pricebook` is deliberately absent: it carries no project, so every one of
# them would share the key (null, "ingest_pricebook") and the second upload of the
# day would be silently handed back the first one's job. The database index in
# api/db.py filters on this same set for that reason.
EXCLUSIVE_JOB_TYPES = (
    "extract_bid_set",
    "rerun_extraction",
    "match_and_price",
    "build_proposal",
    "ingest_addendum",
    # One pipeline per bid: a second upload while one is running is more files for
    # the same run, not a second run over the same drawings.
    "run_full_pipeline",
)

# `run_full_pipeline` stays in EXCLUSIVE_JOB_TYPES - the partial index and the
# worker's one-run-per-bid check still have to cover jobs queued before it was
# retired - but POST /api/jobs refuses it now, so listing it as something an
# estimator may enqueue was a claim the API contradicts.
RETIRED_JOB_TYPES = frozenset({"run_full_pipeline"})

# Estimators enqueue pipeline work; catalog and price-book maintenance is admin-only.
ESTIMATOR_JOB_TYPES = frozenset(EXCLUSIVE_JOB_TYPES) - RETIRED_JOB_TYPES
ADMIN_JOB_TYPES = frozenset({"delete_catalog", "ingest_pricebook", "index_catalog"})
CostSource = Literal[
    "P21_LAST_PO",
    "LIST_X_MULTIPLIER",
    "SPECIAL_NET",
    "VENDOR_RFQ",
    "DISTRIBUTOR_MANUAL",
    "MANUAL",
    "BOOK_PRICE",
]
ProductType = Literal[
    "commodity", "restroom_partitions", "specialty", "custom_built", "accessories"
]
CallKind = Literal["call", "note", "rfi"]


class Evidence(BaseModel):
    """Why a line reads the way it does, and where it came from."""

    note: str | None = None
    sheet: str | None = None
    row: int | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    sourceFile: str | None = None
    sourcePage: int | None = None
    bbox: list[float] | None = None
    pageSize: dict[str, float] | None = None
