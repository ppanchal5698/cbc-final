# Door Handing and Swing

Hardware selection depends on **handing**. Capture it per opening so handed hardware
(locks, closers, exit devices) matches correctly. **Matrix 7.4 — Confirmed.**

| Code | Meaning |
|---|---|
| **LH** | Left Hand — hinges on left viewed from outside, swings away from you |
| **RH** | Right Hand — hinges on right viewed from outside, swings away from you |
| **LHR** | Left Hand Reverse — hinges on left, swings toward you |
| **RHR** | Right Hand Reverse — hinges on right, swings toward you |

## How a real estimator resolves it (mandatory order)

1. **Door schedule HAND / HANDING / SWING column** — when present, copy the code
   (`LH` / `RH` / `LHR` / `RHR`, including `L.H.` forms).
2. **Floor plan** — when the schedule has no handing column (common on
   hardware-matrix sheets such as Taco Bell A1.1), read the swing arc and hinge
   side on the plan and map to LH/RH/LHR/RHR.
3. **Flag only after both fail on the PDF** — open the schedule page and the
   floor-plan page(s) with `search_blocks` / `extract_tables` /
   `get_page_image` before leaving `handing: null` and `handing_missing`.
   Cite pages searched in `evidence_note`. **Never default to LH.**
   Skipping the floor-plan check because the schedule has no HAND column is a
   defect (Matrix 7.4).

Handing **appears per opening in the schedule on many CBC sample bids** (estimator
session 14 Jul). Absence of a column is not permission to skip the floor-plan step.

Swing angle matters for clearance notes (90 degree vs full swing) but not for
hardware matching.

See [door_notation](door_notation.md), [fire_rating_rules](fire_rating_rules.md).
