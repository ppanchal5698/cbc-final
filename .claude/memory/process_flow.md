# CBC Process Flow

`DELEGATION_RULE` in `apps/backend/src/cbc/worker_kit/prompts.py` is the source
of truth for the Phase 0-6 order the orchestrator runs. Each phase's activities,
tools and outputs are in its agent definition under `.claude/agents/`, and the
per-job prompt templates beside `DELEGATION_RULE` say what a run must produce.

This memory file is a pointer only - do not treat it as a second source of truth.
