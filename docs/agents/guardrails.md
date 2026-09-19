# Guardrails

The pipeline runs unattended with `--dangerously-skip-permissions`, so it cannot
answer a permission prompt. The safety does not come from prompting. It comes
from hooks that run regardless of permission mode, and a deny list that runs
regardless of the allow list.

Two entry points, both registered in `.claude/settings.json` against the matcher
`Bash|Write|Edit|MultiEdit|NotebookEdit|Agent|mcp__.*`.

> `permissions.allow` in that file ends with `"*"`, which makes every preceding
> entry decorative. **Only the `deny` list and the hooks actually bite.** The
> deny list covers `mcp__p21-connector__{write,update,insert,create,delete,post}_*`,
> any access to `.env*`, `rm -rf`, `Remove-Item`, `del /s`, `git push`, and the
> mail commands.

---

## PreToolUse — `pre_tool_use.py`

Runs three checks in order and stops at the first non-zero exit. Exit 2 blocks
the tool call.

### 1. `pre_send_quote.py` — nothing is sent (NFR-1)

The copilot drafts, sources and calculates. It does not send. This hook is what
makes that true rather than aspirational.

It blocks two families:

- **`MAIL_COMMAND`** — `sendmail`, `mailx`, `mutt`, `msmtp`, `postfix`, `swaks`,
  `sendgrid`, `mailgun`, `postmark`, any `curl` to a mail API, and `smtp` as a
  **prefix** match so `smtplib`, `smtpd` and `smtp-cli` are all caught.
- **`MAIL_TOOL`** — any tool whose name matches `send`, `email` or `mail`. That
  covers MCP servers that do not exist yet.

`scripts/guardrails/test_no_auto_send.sh` pins it with 14 cases: ten that must
exit 2 (including `import smtplib`, `mcp__gmail__send_email` and
`mcp__outlook__mail_send`) and four that must exit 0 — rendering the quote,
writing the email draft, reading a price book, and `ls`. CI runs it.

### 2. The session guard — `cbc.worker_kit.tool_session`

Stops the orchestrator racing its own subagents. On an `Agent` call it records
which paths that subagent owns (`_DELEGATION_PATHS`); if the orchestrator then
reads one of those paths while the subagent is still running, the call is
blocked with `Do not duplicate subagent work`. Locks expire after 120 seconds
and are released by the PostToolUse side when the `Agent` call returns. A
duplicate read of the same path within 60 seconds warns but is allowed.

State lives in `.cbc_tool_session.json` at the project root (gitignored). The
import is wrapped so that a broken guard never fails a tool call.

### 3. `pre_delete_guard.py` — file safety

The largest hook, 634 lines. Every block names its rule tag in the message:

| Rule | Blocks |
|---|---|
| `protected-write-tool` · `protected-mcp-write` · `protected-bash-write` · `protected-python-write` | any write resolving inside `pricebooks/`, `reference-library/`, `data/pricebooks/`, `data/reference-library/` or `.claude/` |
| `checkpoint-save-artifact` | a bare `Write`/`Edit` to any checkpoint artifact |
| `checkpoint-propose-patch` | a whole-file `save_artifact` over an already-seeded `extracted/door_schedule.json` |
| `reference-library` | deletes touching reference data |
| `nfr-5` | any `mcp__p21-connector__*` tool whose name contains a write verb |
| `rm-rf-outside-projects` · `remove-item` · `erase-item` | recursive deletes outside `projects/` |
| `git-push` | `git push`, in any form |
| `inline-pdf-lib` | reimplementing PDF parsing instead of using `pdf-tools` |

The checkpoint artifacts are:

```
extracted/scope_metadata.json   extracted/frp_takeoff.json     priced/line_items.json
extracted/scope_summary.json    extracted/div10_takeoff.json
extracted/door_schedule.json    extracted/hardware_sets.json
```

They must be written with `mcp__artifact-storage__save_artifact`, which
validates against a schema and keeps SHA-256 versions. A bare `Write` skips
both, which is why it is blocked.

**Two things this hook is careful about.** Paths are *resolved*, never
substring-matched — the substring version blocked ordinary reads and unrelated
home directories. And it **never blocks a read**: a pricing pass exists to read
price books, and an earlier over-broad matcher made one run write MANUAL on 27
lines.

Command parsing is deliberately paranoid: segments are split on
`|| && | ; & newline ( )`, heredoc bodies are stripped, `rm -r -f` and
`--recursive --force` are normalised to the same thing, and inline `python -c`
and python heredocs are parsed for write calls. A comment containing
`projects/` no longer defeats it.

`scripts/guardrails/test_file_safety.sh` pins 15 cases, including the three
bypasses an audit found — a heredoc hiding its redirect, a separated `rm -r -f`,
and a long-form `--recursive --force` — each with a control case that must still
be allowed. CI runs it.

---

## PostToolUse — `post_tool_use.py`

Four steps, of which only one can block.

1. **`log_audit_trail.py`** — appends one JSONL record per tool call to
   `projects/{project}/audit_trail.jsonl`. This is NFR-3: months later, an
   estimator can answer "where did this number come from?". Always exits 0; a
   failure here must never fail the tool call.
2. **`tool_session.clear_active_agent`** — releases the lock on `save_artifact`,
   `Write` or `Agent`. For `Agent` it clears **only that subagent**, because
   take-off, FRP and Div 10 run concurrently and clearing all three when the
   first returns would unlock files the other two are still writing.
3. **`post_extraction_validate.py`** — the only PostToolUse step that can
   **block (exit 2)**. It does so when any of these fails
   `validate_artifact_text`:

   ```
   extracted/scope_metadata.json
   extracted/scope_summary.json
   extracted/door_schedule.json
   ```

   Everything else under `extracted/` or `priced/` runs `check_extraction` /
   `check_pricing(require_hardware_sets=True)` and only warns. Blocking here
   stops a malformed checkpoint from propagating into pricing.
4. **`post_quote_format.py`** — tidies `quotation.html`. Never blocks.

`_artifact_path.py` is the shared helper both entry points load first. It maps
either a `save_artifact` `{project, path}` pair or a `file_path` matching
`projects/([^/"\\]+)/(.+)` to `(project_slug, relative_path)`.

---

## The always-loaded rules

`.claude/rules/` is injected into **every** session, which is why it holds only
two files:

- **`00-core-constraints.md`** — NFR-1 (nothing reaches a customer without an
  estimator) and file safety. Both are hook-enforced, so breaking either fails
  the tool call rather than the review.
- **`auditability.md`** — NFR-3. The provenance every extracted record must
  carry (`source_file`, `source_page`, `bbox`, `page_size`, `extracted_at`) and
  every priced line must carry (`cost_source`, `cost_source_detail`,
  `multiplier_tier`, `multiplier_effective_date`, `price_book_version`,
  `priced_at`).

Phase-specific guidance lives in `.claude/guides/` and is **not** auto-loaded.
`.claude/rules/README.md` states the routing policy: true for every task and
harmful if broken → `rules/` plus a hook; one phase only → `guides/`; reference
data → `memory/`; project status → `docs/`.

## Verifying the guardrails

```bash
bash scripts/guardrails/test_no_auto_send.sh && bash scripts/guardrails/test_file_safety.sh
```

Both scripts find the repo root by walking up for `.mcp.json` or
`requirements.txt`, and probe `python3`, `python` and `py -3` in turn, so they
run the same on Windows and Linux. CI runs them before the test suite, on the
reasoning that a guardrail regression should fail faster than a unit test.

## See also

- Who the subagents are and what they may touch: [`pipeline-agents.md`](pipeline-agents.md)
- The artifacts these rules protect: [`../operations/running.md`](../operations/running.md#the-project-directory)
