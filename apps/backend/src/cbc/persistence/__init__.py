"""Everything that knows the database exists.

Collection names, the audit envelope every document carries, soft delete,
effective dating, and the migrations that move a live database from one shape to
the next. Code above this layer asks for openings; it does not spell
`db["lineItems"]`.

The spec (`docs/collections.mongodb.md` §4.1) requires a data-access layer for a
reason beyond tidiness: every collection carries `orgId` and every query must
filter on it, "so the tenant filter is always index-covered and a missing filter
degrades to a scan that will be noticed in profiling rather than silently
returning another tenant's data". A rule like that cannot live at 160 call sites.
"""
