# Phase 6 — Delivery

Prepares everything needed to send the quotation, and then **stops**.

| | |
|---|---|
| **Agent** | `delivery-agent` (haiku) |
| **Job type** | part of `build_proposal` |
| **Script** | `bash workflows/phase6_deliver.sh <project>` |
| **Writes** | `review/quotation_email_draft.md` — a draft artifact, never sent |
| **Ends with** | `Draft ready for estimator review` |

## The halt is the point

NFR-1: **no estimate or quotation reaches a customer without explicit estimator
approval.** The copilot drafts, sources and calculates. It does not send. Its
job is to remove manual re-keying and lookup, not to replace estimating
judgment.

"The estimator asked me to run the pipeline" is **not** approval to send. Those
are different acts, and the second one happens through the review interface
(FR-9) after a human has looked at the flags from
[Phase 5](phase-5-review.md).

This agent has the narrowest tool list in the pipeline — `Read`, `Write` and the
four artifact-storage tools. No PDF tools, no catalog, no `Bash`. There is
nothing in its allow-list that could send anything, and
`pre_send_quote.py` blocks the attempt anyway, for every agent, at every phase.
See [`../agents/guardrails.md`](../agents/guardrails.md#1-pre_send_quotepy--nothing-is-sent-nfr-1).

## What it does

1. **Verify the review artifacts exist and are coherent** —
   `review/review_flags.json`, `review/review_summary.html`, the priced lines,
   and `quotation.html`.
2. **Write the email body** to `review/quotation_email_draft.md`, addressed back
   to the sales initiator (FR-10), from `templates/quotation_email.md`. It names
   the bid, the total, the count of open review flags, and the out-of-scope
   items the GC needs to be told about.
3. **Copy the deliverables** into `uploads/final/`.
4. **Halt** with the literal message `Draft ready for estimator review`.

The PDF render (`quotation.html` → `quotation.pdf`, WeasyPrint) is done by the
worker after the pass, not by this agent.

> `workflows/phase6_deliver.sh` still instructs the agent to "Export
> quotation.html to quotation.pdf". The agent definition says not to, and the
> agent definition won — the workflow instruction was never updated. Treat the
> script's line as stale.

## What the estimator does next

The draft sits on disk. The estimator opens the bid in the Ops-Hub, works the
review queue, and approves. Only then is the quotation finalised and routed —
by a person, through the proposal screen, with the lapsed-price gate from Phase
5 still standing in the way if a price has gone stale.

## Verifying the halt

```bash
bash scripts/guardrails/test_no_auto_send.sh
```

Fourteen cases: ten that must be blocked — `sendmail`, `mailx`, `mutt`,
`msmtp`, `postfix`, a `curl` to a mail API, Postmark, `import smtplib`,
`mcp__gmail__send_email`, `mcp__outlook__mail_send` — and four that must be
allowed, including *writing the email draft*. The distinction between composing
a message and transmitting it is the one this pipeline is built on. CI runs this
before the test suite.
