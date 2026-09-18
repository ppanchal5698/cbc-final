# Core constraints

**The two rules that apply to every task, in every phase.** Both are enforced by
PreToolUse hooks, so breaking either fails the tool call rather than the review.

Everything else in `.claude/rules/` is phase-specific — see
[README.md](README.md).

Merged from `file-safety.md` and `human-in-the-loop.md`.

---

## 1. Nothing is sent to a customer without an estimator (NFR-1)

**No estimate or quotation is ever sent to a customer without explicit estimator
approval.** The copilot drafts, sources and calculates — **it does not send**.
Its job is to remove manual re-keying and lookup, not to replace estimating
judgment.

### Forbidden

- Sending email by any means: sendmail, mailx, mutt, msmtp, postfix, SMTP, or
  curl to a mail API.
- Any MCP tool whose name contains **send** / **email** / **mail**.
- Posting a quotation to any external endpoint.
- Treating "the estimator asked me to run the pipeline" as approval to send.
  It is not.

### Required

- `delivery-agent` **halts** at Phase 6 with the literal message
  `Draft ready for estimator review`.
- The estimator approves through the review interface (FR-9) before any
  quotation is finalised or routed.
- The prepared email body is written to disk as a **draft artifact only**.

### Enforcement

`.claude/hooks/pre_send_quote.py` (PreToolUse, exit 2 blocks) · the permission
deny list in `.claude/settings.json` · the agent instruction in
`.claude/agents/delivery-agent.md`.

**Owner:** CBC Estimating (Kevin, Rick, Shanna).

---

## 2. File safety

### Writes

- Write **only** inside `projects/{current_project}/` during a pipeline run.
- **Never write to `pricebooks/` or `reference-library/` during a run.** They
  are read-only reference data. Updating them is a separate, deliberate,
  human-initiated act.
- Raw uploads in `projects/{project}/uploads/raw/` are **immutable**. Extraction
  output goes to `uploads/processed/` or `extracted/`, never back over the
  original.

**The Ops-Hub API is that deliberate act.** The FastAPI service writes
`pricebooks/` when purchasing uploads a sheet, and owns the `products` and
`priceBooks` collections. That is a human-initiated change made outside any
pipeline run, which is exactly what this rule permits. The constraint on an
agent is unchanged: during a job, those paths are read-only.

A pipeline run reads live catalog data through the **catalog MCP server**, which
is read-only by design and asserts it at import — the same guarantee
`p21-connector` makes (see [../guides/pricing.md](../guides/pricing.md)).

### Deletes

- **Never delete anything outside `projects/{project}/`.**
- Never delete anything in `pricebooks/` or `reference-library/`, ever.
- `rm -rf` outside `projects/` and `git push` are both blocked by
  `.claude/hooks/pre_delete_guard.py` (exit 2).

### Before overwriting

Read the target first. Checkpoint artifacts under `extracted/` and
`priced/line_items.json` **must** be written with
`mcp__artifact-storage__save_artifact` (schema validation + SHA-256 versions).
Bare Write/Edit to those paths is blocked by PreToolUse, rule
`checkpoint-save-artifact`. Prefer `save_artifact` for any other
estimator-facing file that needs version history.

### Enforcement

`.claude/hooks/pre_delete_guard.py` (PreToolUse, exit 2 blocks) · the permission
deny list in `.claude/settings.json`.
