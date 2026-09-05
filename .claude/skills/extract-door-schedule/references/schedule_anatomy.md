# Door Schedule Anatomy

## Where the schedule lives

Not on the pages that mention it. Spec pages say "see Door Schedule"; the schedule
itself is on a details/schedules sheet. In the Dutch Bros fixture:

| Page | What is actually there |
|---|---|
| 1, 5, 6 | Specification text referencing the schedule |
| 6 | Hardware submittal requirements (Div 08 spec) |
| **14** | **Sheet A2.2 - the real DOOR SCHEDULE, DOOR TYPE SCHEDULE, DOOR FRAME TYPE SCHEDULE, HARDWARE GROUPS and WINDOW SCHEDULE** |
| 28 | Detail sheet cross-referencing the schedule |

Always search for the marker, then confirm the page actually holds tabular rows.

## Columns seen in practice

Column order varies by architect. Identify columns from the header row.

| Column | Example | Notes |
|---|---|---|
| Door number / mark | `01`, `101`, `A-1` | The grouping key for the whole quote |
| Width | `3' - 6"` or `3670` | Two notations, see below |
| Height | `7' - 0"` | |
| Door type | `A`, `B`, `C`, `D` | Cross-references the DOOR TYPE SCHEDULE |
| Frame type | `1`, `2` | Cross-references the DOOR FRAME TYPE SCHEDULE |
| Glass | `TEMP.` | Tempered / insulated; drives lite-kit pricing |
| Door material | `HM`, `WD`, `MFR` | Hollow metal, wood, by-manufacturer |
| Frame material | `HMD`, `MFR` | |
| Hardware group | `GROUP 1`, `HW-1` | Cross-references HARDWARE GROUPS |
| Alternate | `ALT-1`, `Alternate 1` | Bid alternate designation (FR-2); null = base bid. Reconciliation rules still Pending (Matrix 4.1) |
| Notes | `A,B,C,D,E,F` | Letter codes into a DOOR NOTES block |
| Fire rating | `90 MIN`, `45` | **Often absent entirely** — Matrix 7.3 still Pending; flag, do not invent |
| Handing | `LH`, `RHR` | Sometimes only on the plan |
| Finish | `US26D`, `626` | Usually in the hardware group, not the door row; dual nomenclature (NR-3) |

## The two size notations

**4-digit shorthand** - first two digits width, last two height, in feet-inches:

| Code | Width | Height |
|---|---|---|
| `3070` | 3'-0" | 7'-0" |
| `3670` | 3'-6" (42") | 7'-0" |
| `2868` | 2'-8" | 6'-8" |

**Explicit** - separate columns, e.g. `3' - 6"` and `7' - 0"`. The Dutch Bros
fixture uses this form. Normalise both to `width`, `height`, and `size` when the
4-digit code is derivable.

## Hardware group anatomy

A group for one opening commonly contains:

| Item | Example from the fixture |
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

- **Fire rating** - absent from the Dutch Bros door schedule entirely. Where it
  lives in CBC bid sets is still an open question (Matrix 7.3). Interim: flag
  `fire_rating_missing` at high severity; do **not** hard-stop or invent a rating.
- **Handing** - usually present, but sometimes only derivable from the floor plan
  swing arc.
- **Finish** - typically stated per hardware item in the group, not per door.
  Interpret both US and BHMA codes via `finish_crosswalk.json` (NR-3).
- **Alternate designation** - when present, set `alternate` on the opening so
  import can map it to `alternateGroup`. Formal base+alternate reconciliation
  is still Pending (Matrix 4.1 / Open Item 11).
- **Wall type** - read from the partition schedule or wall tags, then mapped to a
  frame depth via `mcp__reference__get_frame_depth`.

## Keying (Matrix 7.6)

There is **no separate keying-schedule workflow**. If the schedule or HW group
mentions IC / keyway / keyed alike, capture it in `notes` only — do not invent a
keying schema field.

## Out-of-scope items that appear in the same schedules

The fixture's WINDOW SCHEDULE specifies `KAWNEER 541T` aluminum storefront. Read
it, record it under `out_of_scope_items`, and do not quote it
(scope-boundaries project rule).
