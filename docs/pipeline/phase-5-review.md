# Phase 5 — Review

Decides what a human needs to look at. This is the phase that makes the whole
pipeline safe to run unattended: everything uncertain surfaces here rather than
arriving silently in a quotation.

| | |
|---|---|
| **Agent** | `quality-reviewer` (haiku) |
| **Job type** | part of `build_proposal` |
| **Script** | `bash workflows/phase5_review.sh <project>` |
| **Command** | `/review` |
| **Skills** | `validate-extraction`, `reuse-prior-quote` |
| **Writes** | `review/review_flags.json`, `review/review_summary.html` |

## It cannot write what it reviews

`quality-reviewer` gets `artifact-storage` **read-only** — `get_artifact` and
`list_project_files`, no `save_artifact` and no `propose_patch`. A reviewer that
can rewrite the thing it is reviewing is not a reviewer. It writes its own
outputs with plain `Write`, and `review/` is not in the checkpoint set.

## What gets flagged

`review/review_flags.json` is seeded by
`extraction/api/validation/review.py` and then extended by the agent:

| Flag | Severity |
|---|---|
| match confidence below **0.75** | high |
| a required FR-2 field null — size, handing, finish, fire rating, hardware set | high |
| a missing fire rating on an opening the spec rates | high |
| `cost_source: MANUAL` — needs a distributor quote | high |
| margin below its product-type band | medium |
| a lapsed price (see below) | medium |
| unparsed or unreadable content | medium |
| an out-of-scope item found in the set | informational |

**Silence is not an acceptable way to represent "I could not read this."**
Unparsed content is reported explicitly. An extraction that quietly returns
fewer openings than the schedule has is the failure mode this phase exists to
catch.

## Verify before flagging

The same gate as Phase 3, and it applies to the reviewer too. Before writing a
flag that says a value is missing, open the page and check — the flag should say
"not found after search of pages 412–418", not "not found". That is why this
agent has `bid-docs` and `pdf-tools` at all.

A flag without a PDF check is a process defect.

## Lapsed prices

`quoting/domain/freshness.py::is_lapsed()` is the single rule, shared by the
quote grid and the proposal gate so the two cannot disagree about what "stale"
means. A lapsed line **blocks the proposal hand-off** until it is acknowledged —
`proposal_view.readiness.blocking` is `bool(lapsed) and not acknowledged`.

This is a different window from the ~24-month price-sheet staleness the
price-books screen shows, and from P21's 6-month freshness rule. Moving one must
not move the others.

## Prior quotes

`reuse-prior-quote` searches for the closest prior quote to the current bid —
same customer, same programme, similar scope — and surfaces it so the estimator
can compare rather than re-deriving a number they already priced last quarter.
Prior quotes live under `data/reference-library/prior_quotes/`.

## Output

- `review/review_flags.json` — the machine-readable queue. The Ops-Hub review
  screen and the rail badge read this.
- `review/review_summary.html` — the human-readable summary, including the
  out-of-scope list the estimator will send to the GC.

## Handoff

[Phase 6](phase-6-delivery.md) prepares the email draft. **It does not wait for
the flags to be cleared** — the estimator clears them through the review
interface (FR-9), and nothing is finalised or routed until they do.
