# Fire Rating and Labels — **STATUS: PENDING (Matrix 7.3 / Open Item 9)**

Openings carry fire ratings — commonly **20 / 45 / 60 / 90-minute, UL-labelled**.
The rating drives both **product selection** (rated door, frame, and hardware) and **price**.

## Hard rule
The rating is a **matching attribute** and must never be silently dropped.
**An unrated match on a rated opening is a defect.**

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
- Rating must be carried per opening when present (FR-2 / Matrix 7.3 intent).
- Extracted in Phase 2 (presence) and Phase 3 (per opening).
- Estimators review missing ratings in the Extraction UI before continue-to-quote.

## What is NOT yet answered — do not invent policy beyond this
This item was **not covered** in the 14 Jul estimator session. Still needed:
1. **Where** the rating most often lives in CBC bid sets.
2. **Which product categories are rating-sensitive for price**.
3. Should a **missing rating hard-stop** the line, or only flag?

## Interim behaviour until answered
- Extract wherever it appears; null + flag when absent.
- Never fill by inference from door type, location, or neighbour.
- Never invent a price adder from rating until Matrix 7.3 is answered.
- Never assume "no column on this sheet" means unrated for matching —
  leave null and flag (unless the sheet explicitly says NR).

Hardware-matrix schedules (butts/locks/closers X columns, no FIRE column) are
exactly the ambiguous case — flag every opening and keep searching the type
schedule / specs before finishing Phase 3.

See the accuracy-trust rule and [[manual_cutoff]].
