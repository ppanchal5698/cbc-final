# Rollout (NFR-11)

Adoption plan for CBC estimators. This is the deliverable NFR-11 names; it is
not a code change.

## Phases

1. **Pilot** — one estimator (Kevin / one-off mode) on two live bids beside the
   existing process. Success = reviewable draft inside the NFR-6 budget with
   every line carrying page, bbox, cost source, and margin basis.
2. **Templated** — Shanna's repeat-customer flow using FR-11 prior-quote reuse.
3. **Broaden** — remaining desk once feedbackEvents show corrections are being
   captured (FR-13) and vendor RFQs are usable from the UI (FR-16).

## Training

- Accuracy / trust rules (`.claude/guides/extraction.md`)
- When to mark VENDOR_RFQ vs MANUAL
- How hand-off works (nothing is sent)

## Explicit non-goals until CBC answers

- FRP conversion constants (Open Item 5)
- Data stewardship owners (NFR-10)
- Margin deviation approval routing (FR-15 / NFR-8 / NFR-9)
