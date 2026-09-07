# Requirements traceability

Each requirement maps to a module and a test. A rot test walks this table and
fails if a named path is missing (`tests/pipeline/test_traceability_doc.py`).

| ID | Requirement | Module | Test |
|---|---|---|---|
| FR-1 | Email / RFP / phone intake | `packages/cbc/schemas/projects.py` | `tests/pipeline/test_traceability_doc.py` |
| FR-2 | Door schedule extraction | `packages/cbc/services/sync_phases/extraction.py` | `tests/pipeline/test_extraction.py` |
| FR-3 | Spec scope | `packages/cbc/services/sync_phases/extraction.py` | `tests/pipeline/test_extraction.py` |
| FR-4 | Match rating/handing/finish | `packages/cbc/domain/matching.py` | `tests/pipeline/test_matching_rules.py` |
| FR-5 | Catalog / page index | `packages/cbc/pageindex/` | `tests/catalog/` |
| FR-6 | Three cost paths | `packages/cbc/services/pricing.py` | `tests/pipeline/test_pricing.py` |
| FR-7 | Per-door quote layout | `packages/cbc/domain/quote_layout.py` | `tests/pipeline/test_quote_layout.py` |
| FR-8 | Margin bands | `packages/cbc/domain/calc.py` | `tests/pipeline/test_pricing.py` |
| FR-9 | Proposal draft | `services/quoting/api/routers/proposal.py` | `tests/pipeline/test_proposal_approval.py` |
| FR-10 | No send from copilot | `packages/cbc/persistence/proposals.py` | `tests/pipeline/test_proposal_approval.py` |
| FR-11 | Reuse prior quote | `packages/cbc/services/reuse.py` | `tests/pipeline/test_traceability_doc.py` |
| FR-12 | FRP take-off (blocked) | `packages/cbc/schemas/operational.py` | `tests/pipeline/test_operational_collections.py` |
| FR-13 | Estimator feedback | `packages/cbc/services/feedback.py` | `tests/pipeline/test_feedback_capture.py` |
| FR-14 | Addenda versions | `packages/cbc/persistence/versioning.py` | `tests/pipeline/test_version_chain.py` |
| FR-15 | Margin governance (OOS) | `packages/cbc/domain/calc.py` | `tests/pipeline/test_pricing.py` |
| FR-16 | Vendor RFQ loop | `services/quoting/api/routers/operational.py` | `tests/pipeline/test_operational_collections.py` |
| NFR-1 | Human approval | `packages/cbc/persistence/proposals.py` | `tests/pipeline/test_proposal_approval.py` |
| NFR-2 | Estimator judgment | `packages/cbc/domain/matching.py` | `tests/pipeline/test_matching_rules.py` |
| NFR-3 | Audit / snapshots | `packages/cbc/services/quote.py` | `tests/pipeline/test_cost_snapshots.py` |
| NFR-4 | Soft delete / envelope | `packages/cbc/persistence/envelope.py` | `tests/pipeline/test_envelope.py` |
| NFR-5 | P21 read-only | `mcp-servers/p21-connector/server.py` | `tests/pipeline/test_p21_connector.py` |
| NFR-6 | Minutes not hours | `packages/cbc/services/runmetrics.py` | `tests/pipeline/test_nfr6_budget.py` |
| NFR-7 | Multi-tenant orgId | `packages/cbc/persistence/repository.py` | `tests/pipeline/test_repository.py` |
| NFR-8 | Margin floor flag only | `packages/cbc/domain/calc.py` | `tests/pipeline/test_pricing.py` |
| NFR-9 | No approval routing (OOS) | `docs/data_model.md` | `tests/pipeline/test_traceability_doc.py` |
| NFR-10 | Stewardship (CBC owes) | `docs/data_model.md` | `tests/pipeline/test_traceability_doc.py` |
| NFR-11 | Adoption / rollout | `docs/rollout.md` | `tests/pipeline/test_traceability_doc.py` |
