# Guardrails

- **NFR-1:** The copilot drafts; it does not send. Proposals require `approvedBy`.
- **NFR-3:** Frozen snapshots on estimate lines are never refreshed from live reference data.
- **NFR-5:** P21 is read-only. No write tools in `p21-connector`.
- **Accuracy:** Do not invent fire ratings, finishes, or FRP conversion constants.
- **Layering:** `cbc.domain` imports nothing above it.
- **Contracts:** JSON Schema under `schemas/artifacts/` is generated from Pydantic; drift fails CI.
- **Duplication:** `.claude/` is the only agent-runtime source tree.
