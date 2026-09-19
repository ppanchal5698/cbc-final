# CBC Process Flow

The canonical Phase 0-6 workflow lives in **`docs/pipeline/README.md`**, with
one document per phase beside it. Read those for phase-by-phase activities,
tools, outputs, and agent assignments.

`DELEGATION_RULE` in `apps/backend/src/cbc/worker_kit/prompts.py` is the source
of truth for the order the orchestrator runs them in.

This memory file is a pointer only - do not treat it as a second source of truth.
