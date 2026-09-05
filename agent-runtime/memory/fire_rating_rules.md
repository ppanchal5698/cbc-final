# Fire Rating and Labels — **STATUS: PENDING (Matrix 7.3 / Open Item 9)**

Openings carry fire ratings — commonly **20 / 45 / 60 / 90-minute, UL-labelled**.
The rating drives both **product selection** (rated door, frame, and hardware) and **price**.

## Hard rule
The rating is a **matching attribute** and must never be silently dropped.
**An unrated match on a rated opening is a defect.**

## What is confirmed
- Rating is present somewhere in the spec / schedule and must be carried per opening.
- It is extracted in Phase 2 (spec scoping) and Phase 3 (drawing take-off).
- Estimators review missing ratings in the Extraction UI before continue-to-quote.

## What is NOT yet answered — do not invent it
This item was **not covered** in the 14 Jul estimator session. Still needed from a
senior estimator:
1. **Where** the rating lives in CBC bid sets — door schedule column, frame schedule,
   or general notes?
2. **Which product categories are rating-sensitive for price**, and are there
   rating-specific vendors / product lines?
3. Should a **missing rating hard-stop** the line for review, or only flag it?

## Interim behaviour until answered (do not invent policy beyond this)
- Extract the rating wherever it appears; record `fire_rating: null` when absent.
- **Flag** — do **not** hard-stop — every opening with `fire_rating: null`, at
  severity "high" in `review/review_flags.json` and as `fire_rating_missing` on
  the opening / line item.
- Never fill a rating by inference from door type, location, or a neighbouring opening.
- Never invent a price adder or product-line rule from rating until Matrix 7.3 is answered.
- Never assume "no column on this sheet" means the opening is unrated for matching —
  leave null and flag.

Note: the Dutch Bros fixture door schedule carries **no rating column** — which is exactly
the ambiguous case this rule exists for.

See the accuracy-trust rule and [[manual_cutoff]].
