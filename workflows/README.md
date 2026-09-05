# Workflows

Headless orchestration for the CBC Estimating Copilot. Every path ends the same
way: a draft quotation and the message **"Draft ready for estimator review"**.
Nothing is ever sent (NFR-1).

## Full pipeline

```bash
bash scripts/init_project.sh dutch_bros_macarthur_2026 tests/fixtures/pdfs/1_Architectural.pdf
```

```bash
bash workflows/run_full_pipeline.sh dutch_bros_macarthur_2026
```

This runs pre-flight checks, then invokes Claude Code headless
(`claude --print --dangerously-skip-permissions`) with an orchestrator prompt that
delegates Phase 0 through 6 to the sub-agents in `.claude/agents/`.

Outputs land in `projects/{name}/`:

| Path | Produced by |
|---|---|
| `extracted/scope_metadata.json` | intake-coordinator |
| `extracted/scope_summary.json` | spec-scope-analyst |
| `extracted/door_schedule.json` | takeoff-engineer |
| `extracted/frp_takeoff.json` | frp-specialist |
| `extracted/hardware_sets.json` | product-matcher |
| `priced/line_items.json`, `priced/margin_applied.json` | pricing-engineer |
| `quotation.html` | quote-builder |
| `review/review_flags.json`, `review/review_summary.html` | quality-reviewer |
| `uploads/final/`, `review/quotation_email_draft.md` | delivery-agent |
| `audit_trail.jsonl` | the `log_audit_trail.py` hook, on every tool call |

## Individual phases

Each phase runs independently against an existing project:

```bash
bash workflows/phase3_takeoff.sh dutch_bros_macarthur_2026
```

| Script | Phase | Agent |
|---|---|---|
| `phase0_intake.sh` | 0/1 - Intake and file setup | intake-coordinator |
| `phase2_spec_scope.sh` | 2 - Spec scoping | spec-scope-analyst |
| `phase3_takeoff.sh` | 3 - Drawing take-offs | takeoff-engineer |
| `phase3b_frp.sh` | 3b - FRP take-off | frp-specialist |
| `phase4_pricing.sh` | 4 - Pricing | pricing-engineer |
| `phase5_review.sh` | 5 - Judgment and review | quality-reviewer |
| `phase6_deliver.sh` | 6 - Deliver | delivery-agent |

They are thin wrappers over `_phase.sh`, which holds the shared headless
invocation and the constraint preamble. Edit the constraints in one place.

There is no `phase1_*.sh` - file setup is folded into `phase0_intake.sh`, matching
how intake actually works.

## Watching for new bid sets

```bash
bash workflows/watch_uploads.sh
```

Uses `inotifywait` when present. **It is not installed on this machine**, so the
script falls back to a portable polling loop (default 30s, `--interval N` to
change). Pre-existing files are seeded on start so they do not all fire at once.

### As a scheduled task on Windows

```bash
schtasks /create /tn "CBC Copilot Watcher" /tr "C:\\Program Files\\Git\\bin\\bash.exe -lc 'cd /c/path/to/cbc-copilot && bash workflows/watch_uploads.sh'" /sc onstart /ru SYSTEM
```

### As a systemd service on Linux

```ini
[Unit]
Description=CBC Estimating Copilot upload watcher
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/cbc-estimating-copilot
ExecStart=/usr/bin/bash workflows/watch_uploads.sh
Restart=on-failure
User=cbc

[Install]
WantedBy=multi-user.target
```

### As a cron job

```bash
*/15 * * * * cd /opt/cbc-estimating-copilot && bash workflows/watch_uploads.sh --interval 1 >> /var/log/cbc-copilot.log 2>&1
```

## Environment variables

| Variable | Purpose | Default |
|---|---|---|
| `CLAUDE_BIN` | Path to the Claude Code CLI | `claude` |
| `PRICEBOOK_DIR` | Where the pricebook server looks for price books | `pricebooks` |
| `P21_BASE_URL` | P21 read-only endpoint | unset - lookups return "manual entry required" |
| `P21_API_KEY` | P21 credential | unset |

Put credentials in `.claude/settings.local.json`, which is gitignored.

## About `--dangerously-skip-permissions`

The pipeline runs unattended, so it cannot answer permission prompts. The safety
does not come from prompting - it comes from the guardrail hooks, which run
regardless of the permission mode:

- `pre_send_quote.py` blocks every send/email path with exit code 2
- `pre_delete_guard.py` blocks deletes outside `projects/`, and any delete
  touching `pricebooks/` or `reference-library/`
- `log_audit_trail.py` records every tool call

Verify them before trusting an unattended run:

```bash
bash tests/test_guardrails/test_no_auto_send.sh && bash tests/test_guardrails/test_file_safety.sh
```
