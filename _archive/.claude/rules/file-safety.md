<!-- ARCHIVED 2026-09-18T12:31:10Z by the agent-config audit.
     Original location: .claude/rules/file-safety.md
     See CLEANUP_CHANGELOG.md for where its content went. -->

# File Safety

## Writes
- Write **only** inside projects/{current_project}/ during a pipeline run.
- **Never write to pricebooks/ or reference-library/ during a run** — they are read-only
  reference data. Updating them is a separate, deliberate, human-initiated act.

### The Ops-Hub API is that deliberate act
The FastAPI service writes `pricebooks/` when purchasing uploads a sheet, and owns
the `products` and `priceBooks` collections. That is a human-initiated change made
outside any pipeline run, which is exactly what this rule permits. The constraint
on an agent is unchanged: during a job, those paths are read-only.

A pipeline run reads live catalog data through the **catalog MCP server**, which is
read-only by design and asserts it at import — the same guarantee p21-connector makes.
- Raw uploads in projects/{project}/uploads/raw/ are **immutable**. Extraction output goes to
  uploads/processed/ or extracted/, never back over the original.

## Deletes
- **Never delete anything outside projects/{project}/.**
- Never delete anything in pricebooks/ or reference-library/, ever.
- rm -rf is blocked outside projects/ by .claude/hooks/pre_delete_guard.py (exit 2).
- git push is blocked by the same hook.

## Before overwriting
Read the target first. Checkpoint artifacts under `extracted/` and
`priced/line_items.json` **must** be written with
`mcp__artifact-storage__save_artifact` (schema validation + SHA-256 versions).
Bare Write/Edit to those paths is blocked by PreToolUse. Prefer `save_artifact`
for any other estimator-facing file that needs version history.

## Enforcement
- Hook: .claude/hooks/pre_delete_guard.py (PreToolUse, exit 2 blocks)
- Checkpoint Write block: same hook, rule `checkpoint-save-artifact`
- Permission deny list in .claude/settings.json
