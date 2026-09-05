# Human-in-the-Loop (NFR-1)

**No estimate or quotation is ever sent to a customer without explicit estimator approval.**

The copilot drafts, sources, and calculates — **it does not send**. Its job is to remove
manual re-keying and lookup, not to replace estimating judgment.

## What this forbids
- Sending email by any means (sendmail, mailx, mutt, msmtp, postfix, SMTP, curl to a mail API).
- Any MCP tool whose name contains send / email / mail.
- Posting a quotation to any external endpoint.
- Treating "the estimator asked me to run the pipeline" as approval to send. It is not.

## What this requires
- The delivery-agent **halts** at Phase 6 with the literal message
  "Draft ready for estimator review".
- The estimator approves through the review interface (FR-9) before any quotation is
  finalised or routed.
- The prepared email body is written to disk as a **draft artifact only**.

## Enforcement
- Hook: .claude/hooks/pre_send_quote.py (PreToolUse) — exit code 2 blocks the call.
- Permission deny list in .claude/settings.json.
- Agent instruction in .claude/agents/delivery-agent.md.

## Owner
CBC Estimating (Kevin, Rick, Shanna).
