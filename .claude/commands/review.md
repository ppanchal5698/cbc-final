---
description: Generate the estimator review report
---

Follow the quality-reviewer agent in `.claude/agents/quality-reviewer.md`.

Score confidence, verify unclear findings on the specific PDF page before
presenting them, and write `review/review_flags.json` with `save_artifact`. Do
not hand-write `review/review_summary.html` - the worker renders it from the
flags after the pass. Halt before any send.
