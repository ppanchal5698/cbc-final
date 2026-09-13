"""Domain ownership of job types for microservice workers."""
from __future__ import annotations

DOMAIN_JOB_TYPES: dict[str, frozenset[str]] = {
    "intake": frozenset({"ingest_addendum"}),
    "extraction": frozenset({"extract_bid_set", "rerun_extraction"}),
    "pricing": frozenset({"match_and_price"}),
    "quoting": frozenset({"build_proposal"}),
    "catalog": frozenset({"index_catalog", "delete_catalog", "ingest_pricebook"}),
}


def claimable_types(domain: str) -> frozenset[str]:
    try:
        return DOMAIN_JOB_TYPES[domain]
    except KeyError as exc:
        raise ValueError(f"unknown domain: {domain}") from exc
