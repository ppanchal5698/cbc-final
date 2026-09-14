# ADR-001: New tree, migrate logic

## Status

Accepted

## Decision

Build a clean spec-shaped package tree; move domain logic file-by-file with its
tests. Do not retype arithmetic, matching, freshness, or worker lease logic.

## Consequences

Green suite at every stage. Import shims (`schemas`↔`contracts`,
`worker_kit`↔`agents`) last one release.
