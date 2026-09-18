# Fire Rating and Labels

Openings carry fire ratings — commonly **20 / 45 / 60 / 90-minute, UL-labelled**.
The rating drives **product selection** (rated door, frame, and hardware) and
downstream pricing. It is a **mandatory extraction field**.

## Hard rule
The rating must never be silently dropped.
**An unrated match on a rated opening is a defect.**

Exact bid-page location varies across sets (door-schedule column, frame
schedule, notes, or Div 08 text). Always search; when absent or uncertain after
PDF verify, leave `fire_rating: null` with a **visible** `fire_rating_missing`
review flag — never invent and never hard-stop the pipeline solely for a null.

## How a real estimator looks for it (mandatory search order)

1. **Door schedule** — FIRE / RATING / LABEL column when present.
2. **Door type / frame type schedule** on the same sheet or adjacent sheets.
3. **Division 08 specs / general notes** — rated assembly callouts, "1 HR", UL labels.
4. If still absent **after opening those PDF pages** → `fire_rating: null` +
   `fire_rating_missing` (high), with `evidence_note` naming pages searched.
   Do **not** invent. Do **not** copy a neighbour. Do **not** flag from the
   parser summary alone.

Also accept **NR / N/R / NON-RATED / UNRATED** as an explicit unrated value (`"NR"`)
when the sheet says so — that is not the same as "column missing".

## What is confirmed
- Rating must be carried per opening when present (FR-2).
- Extracted in Phase 2 (presence) and Phase 3 (per opening).
- Estimators review missing ratings in the Extraction UI before continue-to-quote.
- Missing rating → high review flag; do not assume unrated for matching.

## Behaviour
- Extract wherever it appears; null + flag when absent or uncertain.
- Never fill by inference from door type, location, or neighbour.
- Never invent a price adder from rating during extraction (pricing is Phase 4).
- Never assume "no column on this sheet" means unrated for matching —
  leave null and flag (unless the sheet explicitly says NR).

Hardware-matrix schedules (butts/locks/closers X columns, no FIRE column) are
exactly the ambiguous case — flag every opening and keep searching the type
schedule / specs before finishing Phase 3.

See the accuracy-trust rule and [manual_cutoff](manual_cutoff.md).
