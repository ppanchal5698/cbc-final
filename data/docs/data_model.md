# Data model — implemented vs specification

Source of truth for the intended schema: [collections.mongodb.md](collections.mongodb.md).

## Implemented (spec names in Mongo)

| Spec collection | Accessor | Notes |
|---|---|---|
| bidRequests | `db.projects` | Renamed via m001 |
| openings | `db.line_items` | + doorNumber unique identity (m004) |
| estimateLines | `db.quote_lines` | Four frozen snapshots on reprice |
| estimateVersions | `db.versions` | Chain fields + estimateVersionId stamp |
| catalogItems | `db.products` | |
| proposals | `db.proposals` | approvedBy required on create |
| auditLogs | `db.audit_log` | |
| takeoffs / vendorRfqs / rfis / feedbackEvents | matching accessors | Routers under quoting |
| documents, users, priceBooks | matching | |

## Deliberate deviations

| Item | Why |
|---|---|
| `calls` kept | Broader than `rfis` (call \| note \| rfi). RFI state machine is separate. |
| `quotes` kept | Totals/settings still live here; full move onto estimateVersions is a reshape. |
| `referenceData` family blobs | Spine collections created (m005); live reads still from blobs until data move. |
| Infra collections (`jobs`, `settings`, …) | Not in the workbook; LLM/auth runtime. |
| FRP `constantsUsed` null | Open Item 5 — CBC owes values. |
| Margin deviation routing | FR-15 / NFR-8 / NFR-9 out of scope; floor flag only. |
| NFR-10 stewardship owners | CBC owes the names; fields exist as UNASSIGNED. |

## Envelope

Every tenant document carries `orgId`, `schemaVersion`, timestamps (m002). Soft delete on the five collections named in §4.3. Repositories inject `orgId` on every query.
