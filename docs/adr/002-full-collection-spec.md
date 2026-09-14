# ADR-002: Full 32-collection data model

## Status

Accepted

## Decision

Adopt `docs/collections.mongodb.md` in full, including splits and
`vendorRfqs` / `rfis` / `feedbackEvents`, with forward-only migrations.

## Consequences

Python accessors may keep legacy names (`db.projects`) while Mongo uses spec
names. Deliberate deviations are listed in `docs/data_model.md`.
