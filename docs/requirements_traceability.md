# Requirements traceability

Each requirement maps to a module and a test. A rot test walks this table and
fails if a named path is missing (`apps/backend/tests/system/test_traceability_doc.py`).

| ID | Requirement | Module | Test |
|---|---|---|---|
| FR-1 | Email / RFP / phone intake | `apps/backend/src/cbc/modules/projects/features/CreateProject.py` | `apps/backend/tests/characterization/test_platform.py` |
| FR-2 | Door schedule extraction | `apps/backend/src/cbc/modules/extraction/api/door_schedule.py` | `apps/backend/tests/modules/extraction/test_extraction.py` |
| FR-3 | Spec scope | `apps/backend/src/cbc/modules/projects/api/scope_metadata.py` | `apps/backend/tests/modules/extraction/test_no_scope_bid.py` |
| FR-4 | Match rating/handing/finish | `apps/backend/src/cbc/modules/quoting/domain/matching.py` | `apps/backend/tests/modules/quoting/test_matching_rules.py` |
| FR-5 | Catalog / page index | `apps/backend/src/cbc/modules/catalog/api/pageindex/` | `apps/backend/tests/modules/catalog/` |
| FR-6 | Three cost paths | `apps/backend/src/cbc/modules/pricing/api/pricing.py` | `apps/backend/tests/modules/pricing/test_pricing.py` |
| FR-7 | Per-door quote layout | `apps/backend/src/cbc/modules/quoting/api/quote_layout.py` | `apps/backend/tests/modules/quoting/test_quote_layout.py` |
| FR-8 | Margin bands | `apps/backend/src/cbc/modules/pricing/domain/calc.py` | `apps/backend/tests/modules/pricing/test_pricing.py` |
| FR-9 | Proposal draft | `apps/backend/src/cbc/modules/quoting/features/RenderProposal.py` | `apps/backend/tests/modules/quoting/test_proposal_approval.py` |
| FR-10 | No send from copilot | `apps/backend/src/cbc/modules/quoting/features/MarkComplete.py` | `apps/backend/tests/modules/quoting/test_proposal_approval.py` |
| FR-11 | Reuse prior quote | `apps/backend/src/cbc/modules/projects/features/ReusePriorQuote.py` | `apps/backend/tests/characterization/test_platform.py` |
| FR-12 | FRP take-off (blocked) | `apps/backend/src/cbc/modules/extraction/features/CreateTakeoff.py` | `apps/backend/tests/system/test_operational_collections.py` |
| FR-13 | Estimator feedback | `apps/backend/src/cbc/modules/extraction/api/feedback.py` | `apps/backend/tests/modules/extraction/test_feedback_capture.py` |
| FR-14 | Addenda versions | `apps/backend/src/cbc/modules/intake/domain/versioning.py` | `apps/backend/tests/modules/intake/test_version_chain.py` |
| FR-15 | Margin governance (OOS) | `apps/backend/src/cbc/modules/pricing/domain/calc.py` | `apps/backend/tests/modules/pricing/test_pricing.py` |
| FR-16 | Vendor RFQ loop | `apps/backend/src/cbc/modules/quoting/features/CreateVendorRfq.py` | `apps/backend/tests/system/test_operational_collections.py` |
| NFR-1 | Human approval | `apps/backend/src/cbc/modules/quoting/features/MarkComplete.py` | `scripts/guardrails/test_no_auto_send.sh` |
| NFR-2 | Estimator judgment | `apps/backend/src/cbc/modules/pricing/api/confidence.py` | `apps/backend/tests/architecture/test_confidence_floor.py` |
| NFR-3 | Audit / snapshots | `apps/backend/src/cbc/modules/quoting/api/quote.py` | `apps/backend/tests/modules/quoting/test_cost_snapshots.py` |
| NFR-4 | Soft delete / envelope | `apps/backend/src/cbc/shared/persistence/envelope.py` | `apps/backend/tests/system/test_envelope.py` |
| NFR-5 | P21 read-only | `mcp-servers/p21-connector/server.py` | `apps/backend/tests/system/test_p21_connector.py` |
| NFR-6 | Minutes not hours | `apps/backend/src/cbc/modules/ops/api/runmetrics.py` | `apps/backend/tests/modules/ops/test_nfr6_budget.py` |
| NFR-7 | Multi-tenant orgId | `apps/backend/src/cbc/shared/persistence/repository.py` | `apps/backend/tests/system/test_repository.py` |
| NFR-8 | Margin floor flag only | `apps/backend/src/cbc/modules/pricing/domain/calc.py` | `apps/backend/tests/modules/pricing/test_pricing.py` |
| NFR-9 | No approval routing (OOS) | `docs/data_model.md` | `apps/backend/tests/system/test_traceability_doc.py` |
| NFR-10 | Stewardship (CBC owes) | `docs/data_stewardship.md` | `apps/backend/tests/system/test_traceability_doc.py` |
| NFR-11 | Adoption / rollout | `docs/rollout.md` | `apps/backend/tests/system/test_traceability_doc.py` |
