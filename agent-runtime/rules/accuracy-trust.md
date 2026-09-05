# Accuracy and Trust (NFR-2)

**Confidence scoring and review flags are visible from day one. Unmatched or low-confidence
items are never silently guessed.**

This mirrors how an estimator already searches P21: "here are 3 close matches — is it one of
these?" That behaviour is the target, not a fully automatic answer.

## Rules
1. Every matched line carries a **confidence score 0.0-1.0** and the reason for it.
2. Confidence below **0.75** is **flagged for review**, never auto-accepted.
3. A missing required attribute (size, handing, finish, fire rating, hardware set) is
   recorded as **null and flagged** — never filled by inference from a neighbouring row.
4. Unparsed or unreadable content is reported explicitly in review/review_flags.json.
   Silence is not an acceptable way to represent "I could not read this".
5. At the **manual cut-off** (see @.claude/memory/manual_cutoff.md) emit
   cost_source "MANUAL" with confidence 0.0 and a plain-language reason.
6. When proposing a direct-equal substitution, always attach a **substitution note**
   naming what was specified and what is being offered instead.

## Confidence bands
| Score | Meaning | Action |
|---|---|---|
| 0.95-1.00 | Exact part-number match, all attributes agree | accept |
| 0.75-0.94 | Series match, one soft attribute differs | accept with note |
| 0.40-0.74 | Plausible match, needs a human | **flag** |
| 0.00-0.39 | No usable match / manual cut-off | **flag, price manually** |

## Owner
CBC Estimating.
