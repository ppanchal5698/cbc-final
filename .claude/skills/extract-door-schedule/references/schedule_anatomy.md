# Door Schedule Anatomy

## Where the schedule lives

Not on the pages that merely *mention* it. Spec pages and drawing indexes say
"see Door Schedule"; the real table sits on a schedules / details sheet (often
A2.x, A4.0, A7.x, A9.x — **never assume a single sheet ID**).

| What you find | What it usually means |
|---|---|
| Index / cover "DOOR SCHEDULE" hit | Cross-reference only — keep searching |
| Page with tabular rows + WIDTH/HGT/GROUP or matrix X columns | The real schedule |
| Remodel / National Accounts set with no schedule sheet | Honest empty openings + `remodel_no_schedule` |
| Spec / project manual only | Honest empty — ask for drawings |

Always search for the marker, then confirm the page actually holds tabular rows.
Prefer ranked `door_schedule` / `door_schedule_candidate` pages from `_sheetmap.json`.

## Layout classes (not brand-specific)

**A. GROUP-style:** mark, size, type, materials, `GROUP n`.

**B. Hardware-matrix:** mark, room, W×H×thick, type, door/frame material, then
**X columns** for BUTTS / LOCKS / CLOSERS / KICK / THRESHOLD / STOP / MISC.
Often **no HANDING / FIRE RATING column** — resolve from plans / type schedule.

**C. Inch-layout:** mark, WIDTH as `36"`, HGT as `84"`, materials like `HPL` /
`ALUM`, bare HARDWARE GROUP digit. Body text may be outlined CAD lettering —
prefer vision / OCR when `get_text` only recovers the title.

**D. Remodel / no dedicated schedule:** door tags on plans; hardware "see National
Accounts." Parser returns empty openings with an honest reason — do not invent
rows.

## Columns seen in practice (FR-2)

Column order varies by architect. Identify columns from the header row.

| Column | Example | Notes |
|---|---|---|
| Door number / mark | `1`, `01`, `101`, `A-1` | Grouping key; single-digit marks are valid |
| Room name | `DINING`, `MEN` | Use in `description` as `{room} — Type {X}` |
| Width | `3' - 6"` or `3670` | Two notations, see below |
| Height | `7' - 0"` | |
| Thickness | `1 3/4"` | **Notes only** — never a top-level `thickness` key |
| Door type | `A`, `B`, `C`, `D` | Cross-references the DOOR TYPE SCHEDULE |
| Frame type | `1`, `2` | Cross-references the DOOR FRAME TYPE SCHEDULE |
| Glass | `TEMP.` | Tempered / insulated; drives lite-kit pricing |
| Door material | `HM`, `WD`, `AL`, `MFR` | `AL` + storefront → **out of scope** (Matrix 2.3) |
| Frame material | `HMD`, `HM`, `AL`, `MFR` | |
| Hardware group | `GROUP 1`, `HW-1` | Or matrix X columns → expand into `hardware` |
| Alternate | `ALT-1`, `Alternate 1` | FR-2; null = base bid (Matrix 4.1 still Pending) |
| Notes | `8, 10, 13` | Letter/number codes into DOOR NOTES |
| Fire rating | `90 MIN`, `45`, `NR` | Mandatory search; if absent/uncertain after PDF verify → null + `fire_rating_missing` (never invent) |
| Handing | `LH`, `RHR` | Often only on the plan (Matrix 7.4) |
| Finish | `US26D`, `626` | Sheet note "ALL HARDWARE SHALL BE US32D" applies to openings |

## The two size notations

**4-digit shorthand** - first two digits width, last two height, in feet-inches:

| Code | Width | Height |
|---|---|---|
| `3070` | 3'-0" | 7'-0" |
| `3670` | 3'-6" (42") | 7'-0" |
| `2868` | 2'-8" | 6'-8" |

**Explicit feet-inches** - separate columns, e.g. `3' - 6"` and `7' - 0"`. The Dutch Bros
fixture uses this form.

**Inch-only columns** - retail / QSR schedules (often CityBlueprint-style fonts)
print `36"` × `84"` under WIDTH / HGT. Normalise to feet-inches and a 4-digit
`size` when derivable (`36"`/`84"` → `3'-0"` / `7'-0"` / `3070`).

Also accept door materials `HPL` / `PLAM` and frame materials `ALUM` (→ `AL`),
and hardware groups written as a bare digit under a HARDWARE GROUP header.

Normalise both forms to `width`, `height`, and `size` when the
4-digit code is derivable.

## Hardware group anatomy

A group for one opening commonly contains:

| Item | Example |
|---|---|
| Continuous or butt hinges | `IVES 700, 83", 630` |
| Lock or exit device | `VON DUPRIN 99EO, 42", 626` |
| Closer | `LCN 4040XP RW/PA, ALUM.` |
| Kick plate | `IVES 8400, 40"x30", 630` |
| Threshold | `PEMKO 275A, 42"` |
| Door sweep | `ZERO 39A, 42"` |
| Weatherstrip / smoke seal | `ZERO 188S BK, 18'` |
| Floor stop / holder | `IVES FS43, 626` |
| Silencers | usually by the each |
| Alarm / access control | `ALARM LOCK ETDL27R1G/26DV` |

**There is no single standard CBC hardware list.** Architects specify by part
number and series, and CBC reconciles to its own stock list. Grade is implied by
the series (Hager 3400 = grade 1, 3500 = grade 2) - quote the part number, not
the grade.

## Fields that are commonly missing

Record `null` and flag. Never infer from a neighbouring row.

- **Fire rating** - often absent from the door schedule (GROUP-style and matrix
  layouts). Search type schedule + Div 08 before finishing. Interim: flag
  `fire_rating_missing` at high severity; do **not** hard-stop or invent.
- **Handing** - when the schedule has no HAND column, **must** try the floor-plan
  swing before leaving `handing_missing` (Matrix 7.4). Never default LH.
- **Finish** - sheet-level note ("ALL HARDWARE SHALL BE US32D") or per HW item.
  Interpret both US and BHMA codes (NR-3).
- **Hardware set id** - matrix sheets have X columns, not `GROUP n`. Flag
  `hardware_matrix_unexpanded` and fill `hardware` from the legend — do not invent
  a GROUP number.
- **Aluminum / storefront** - `AL`/`AL` or STOREFRONT → flag
  `out_of_scope_storefront` and list under `out_of_scope_items` (Matrix 2.3). Do
  not price as CBC HM/WD openings.
- **Alternate designation** - when present, set `alternate`. Matrix 4.1 still Pending.
- **Wall type** - partition schedule / wall tags → `mcp__reference__get_frame_depth`.

## Keying (Matrix 7.6)

There is **no separate keying-schedule workflow**. If the schedule or HW group
mentions IC / keyway / storeroom / keyed alike, capture a structured `keying`
object:

```json
"keying": {
  "coreType": "icSmallFormat",
  "keyway": "Schlage C",
  "lockFunction": "storeroom",
  "notes": null
}
```

`coreType` values: `icSmallFormat` | `icLargeFormat` | `conventional` | `none`.
Leave `keying` null when the sheets are silent — do not invent.

## Out-of-scope items that appear in the same schedules

The fixture's WINDOW SCHEDULE specifies `KAWNEER 541T` aluminum storefront. Read
it, record it under `out_of_scope_items`, and do not quote it
(`.claude/guides/takeoff.md`).
