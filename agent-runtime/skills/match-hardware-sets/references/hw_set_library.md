# Hardware Set Library

## There is no single standard CBC set

Confirmed in the 14 Jul estimator session. Sets are built around the **top-10
stock items per product type** (grade variants push it to roughly 20), plus a
**CUSTOM / OTHER** tab for the full option matrix.

Quote by **part number / series**, not by grade. Hager 3400 is grade 1 and 3500 is
grade 2 - the architect specifies the series, and that is what gets quoted.

## Typical set composition for one opening

| Position | Category | Common sources |
|---|---|---|
| 1 | Continuous or butt hinges | Hager BB1279 / BB1199 / AB700; Ives 700 |
| 2 | Lock or exit device | Hager 3400 / 3500 / 3800; Von Duprin 99 series |
| 3 | Closer | Hager 5100-5400; LCN 4040XP |
| 4 | Kick plate | Ives 8400; Hager Trim and Auxiliary |
| 5 | Threshold | PEMKO; National Guard |
| 6 | Door sweep | Zero 39A; PEMKO; NGP |
| 7 | Weatherstrip / smoke seal | Zero 188S; PEMKO; NGP |
| 8 | Floor stop / holder | Ives FS43; Rockwood |
| 9 | Silencers | Hager Trim and Auxiliary |
| 10 | Access control / alarm | Alarm Lock (e.g. ETDL27R1G/26DV) |

## Worked example - Dutch Bros GROUP 1 (fixture page 14)

| Item | Specified | Vendor | Cost path |
|---|---|---|---|
| Continuous hinge | `IVES 700, 83", 630` | Allegion | DISTRIBUTOR_MANUAL |
| Closer | `LCN 4040XP RW/PA, ALUM.` | Allegion | DISTRIBUTOR_MANUAL |
| Alarm | `ALARM LOCK ETDL27R1G/26DV` | Alarm Lock | MANUAL |
| Exit device | `VON DUPRIN 99EO, 42", 626` | Allegion | DISTRIBUTOR_MANUAL |
| Kick plate | `IVES 8400, 40"x30", 630` | Allegion | DISTRIBUTOR_MANUAL |
| Threshold | `PEMKO 275A, 42"` | PEMKO | LIST_X_MULTIPLIER |
| Door shoe / sweep | `ZERO 39A, 42"` | Zero | MANUAL (not a top-10 vendor) |
| Seal | `ZERO 188S BK, 18'` | Zero | MANUAL |
| Floor stop | `IVES FS43, 626` | Allegion | DISTRIBUTOR_MANUAL |

**Note what this example shows.** A perfectly ordinary quick-serve opening lands
mostly outside the automated path: Allegion is distributor-bought and Zero is not
a Phase-1 vendor. That is the manual cut-off working as designed, not a failure.
Match the parts, price what can be priced, and hand the rest to the estimator with
the reason attached.

## Vendor coverage in Phase 1

| Priced from a CBC price book | Manual price entry |
|---|---|
| Hager, National Guard, PEMKO/Markar, Rockwood, ASI, Bradley, Bobrick, Gamco, World Dryer, NUDO | Allegion (Banner / SecLock), Zero, Alarm Lock, Pionite / Wilsonart laminate, anything via J2 |

## Direct-equal substitution

When a specified line is unavailable, propose the closest of the top 2-3 brands
and attach a note explaining the substitution. The GC approves direct equals -
the copilot proposes, it does not decide.
