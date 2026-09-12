"""Collection names, spelled once.

`docs/collections.mongodb.md` specifies the vocabulary, derived cell by cell from
`docs/CBC_Req_Validation_v1_3.xlsx`. The database grew its own instead - a bid was
a `project`, an opening was a `lineItem`, a priced line was a `quoteLine` - so a
reader holding the specification could not find anything, and neither could a
reviewer asking whether the implementation matches it.

Renaming is cheap here only because `cbc.db.Collections` already resolved every
name in one class. The names live here now, the migration in
`migrations/m001_rename_to_specification.py` moves the data, and the accessors in
`cbc.db` read from this module.

Names deliberately NOT changed, with the reason:

- `calls` is broader than the spec's `rfis` - it stores call | note | rfi
  (`CallKind`). Splitting the RFI workflow out is FR-13/Phase 5 work with its own
  state machine, not a rename.
- `quotes` holds quote-level settings and totals. The spec puts those on
  `estimateVersions.totals` and `.taxSnapshot`, which is a reshape, not a rename.
- `jobs`, `settings`, `counters`, `authAttempts`, `oauthSessions`, `runMetrics`,
  `failedExtractions`, `pageIndex` have no spec entry at all. They are the
  LLM-runtime and auth infrastructure the schema document never contemplated, and
  inventing spec names for them would be worse than leaving them alone.
- `referenceData` collapses ten specified reference collections into one document
  per family. Unpicking that is S4.
"""
from __future__ import annotations

# ── the specification's names ───────────────────────────────────────────────
ORGANIZATIONS = "organizations"
USERS = "users"
BID_REQUESTS = "bidRequests"          # was: projects
DOCUMENTS = "documents"
OPENINGS = "openings"                 # was: lineItems
TAKEOFFS = "takeoffs"
ESTIMATES = "estimates"
ESTIMATE_VERSIONS = "estimateVersions"
ESTIMATE_LINES = "estimateLines"      # was: quoteLines
CATALOG_ITEMS = "catalogItems"        # was: products
HARDWARE_SETS = "hardwareSets"
PRICE_BOOKS = "priceBooks"
PRICE_BOOK_ENTRIES = "priceBookEntries"
VENDOR_RFQS = "vendorRfqs"
RFIS = "rfis"
PROPOSALS = "proposals"
FEEDBACK_EVENTS = "feedbackEvents"
AUDIT_LOGS = "auditLogs"              # was: auditLog

# ── infrastructure the specification does not describe ──────────────────────
JOBS = "jobs"
QUOTES = "quotes"
CALLS = "calls"
COUNTERS = "counters"
SETTINGS = "settings"
AUTH_ATTEMPTS = "authAttempts"
OAUTH_SESSIONS = "oauthSessions"
RUN_METRICS = "runMetrics"
FAILED_EXTRACTIONS = "failedExtractions"
REFERENCE_DATA = "referenceData"
PAGE_INDEX = "pageIndex"
SCHEMA_MIGRATIONS = "schemaMigrations"

# What migration 1 renames, old -> new. Kept beside the constants so the two
# cannot disagree, and read by the migration itself.
RENAMED_IN_M001: dict[str, str] = {
    "projects": BID_REQUESTS,
    "lineItems": OPENINGS,
    "quoteLines": ESTIMATE_LINES,
    "products": CATALOG_ITEMS,
    "auditLog": AUDIT_LOGS,
}
