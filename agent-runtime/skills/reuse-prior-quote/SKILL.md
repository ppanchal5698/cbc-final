---
name: reuse-prior-quote
description: >
  Finds the closest prior CBC quote - same brand, architect or GC - and offers it
  as a starting draft rather than building from scratch. This is the templated
  estimating mode (FR-11). Use at the start of Phase 1, and again in Phase 5 when
  applying judgment to a repeat customer.
---

# Reuse a Prior Quote

## Why this exists

Templated mode is how Shanna works: open a **previous job's workbook** - not a
clean template - save-as, and trim it down to the current job. Kevin builds
one-off from scratch, with McDonalds and Cava as templated exceptions. Rick works
from his own Excel. All three modes stay; this skill serves the templated one.

Clearing the previous job's residual rows is the first task, not an afterthought.

## Match priority

Search `reference-library/prior_quotes/` and score candidates:

| Signal | Weight | Note |
|---|---|---|
| Same **brand / franchise** | highest | Dutch Bros, McDonalds, Cava, Wendys - prototypes repeat almost verbatim |
| Same **architect** | high | Architects reuse their own schedules and hardware groups |
| Same **GC** | medium | Similar commercial terms and expectations |
| Same **prototype or store format** | high | e.g. "Dutch Bros new freestanding store" |
| Similar **opening count** | low | A 4-opening shop is nothing like a 40-opening build |
| Recency | low | An older quote for the same prototype beats a newer unrelated one |

Report the top 3 candidates with scores. Let the estimator pick - do not
auto-adopt one.

## Using the match

1. Copy its structure - groups, block order, standard notes.
2. **Re-price every line.** Never carry a cost forward. Prices move, multiplier
   sheets get reissued, and a copied stale cost is invisible in the output.
3. Re-verify every part number against the current bid's schedule. The new job's
   drawings are the authority, not the old quote.
4. Flag every line that came from the prior quote so the estimator can see what
   was inherited versus what was extracted fresh.
5. Delete residual rows that do not appear in this bid. Leftovers from the prior
   job are the classic templated-mode error.

## Reference data

- @.claude/memory/estimator_profiles.md
- @.claude/memory/process_flow.md - Phase 1 and Phase 5

## Current state

`reference-library/prior_quotes/` is empty. Until CBC supplies completed quotes,
this skill reports "no prior quotes available" and the pipeline builds one-off.
That is the correct behaviour, not a failure - and it is why the directory exists
now rather than later.

## Output

Write to `projects/{project}/review/prior_quote_candidates.json`: ranked
candidates with match scores, matched signals, and the reason each was proposed.
