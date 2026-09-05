# Finish Nomenclature

**Two nomenclature systems are in active use and both must be interpreted** (NR-3).

| US code | Numeric (BHMA) | Description |
|---|---|---|
| US26D | **626** | Satin chrome |
| US19 | **619** | Satin nickel — **a different satin from 26D** |
| US15 | 619 | Satin nickel (US15 maps to the 619 family) |
| US26 | 625 | Bright chrome |
| US10B | 613 | Oil-rubbed bronze |
| US32D | 630 | Satin stainless steel |
| US3 | 605 | Bright brass |
| US4 | 606 | Satin brass |

## The trap
**US19 and US26D are not the same satin.** Do not treat them as interchangeable when
matching. A finish substitution changes both selection and price.

## Premium finishes
Some finishes are **premium and/or carry lead times**, and are priced as an **adder on top
of the base price** — they are not always shown cleanly in the price book (NR-4).
See reference-library/adders/manual_adders.json

Notes seen in Hager Price Book #18: split finish is **priced at the higher finish**;
levers prepped for SFIC cores are only available in US10B, US26D and BLK; anti-microbial is
26D-only.

Finish is a **required matching attribute** — carry it on every line.
Machine-readable form: reference-library/finishes/finish_crosswalk.json

## On import (extraction sync)
`normalize_finish_value` stores a canonical pair when the finish is uniquely
recognised — e.g. `US26D (626)` from `US26D`, `626`, or bare `26D`. Ambiguous
numerics (619) and unknown strings keep the raw text and add
`finish_ambiguous` / `finish_unrecognized` flags. Never invent a mapping.
