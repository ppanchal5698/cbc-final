"""The job vocabulary: every job type there is, and which of them one bid runs one at a time.

`POST /api/jobs` validates against `JobType`. The queue, the worker's
one-session-per-bid check and the partial index on `jobs` all read
`EXCLUSIVE_JOB_TYPES`, so they cannot disagree about which jobs exclude each other.
"""
from __future__ import annotations

from typing import Literal

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
    # Parse of one uploaded PDF via LlamaParse. Not exclusive: one job per
    # document, so a second upload never gets a 409.
    "parse_document",
    # Deprecated in cbc-copilot-final: kept so historical Mongo rows still
    # deserialise. New autopilot runs use orchestrate=true on extract_bid_set
    # and chain match_and_price → build_proposal across domain workers.
    "run_full_pipeline",
]

# One in-flight job of these types per project. A second "re-run extraction" click
# while the first is still running is a double-click, not a second job.
#
# `ingest_pricebook` is deliberately absent: it carries no project, so every one of
# them would share the key (null, "ingest_pricebook") and the second upload of the
# day would be silently handed back the first one's job. The database index in
# infrastructure/collections.py filters on this same set for that reason.
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
