# FRP Conversion Constants - **PENDING**

## Status

**These constants do not exist yet.** Open Item 5: CBC (Shanna / Vu360) still owes
the geometry-to-quantity conversion values. Live values:
`mcp__reference__get_frp_constants` (Mongo). Seed placeholder:
reference-library/frp_constants/conversion_constants.json

## What is needed

| Constant | Meaning | Value |
|---|---|---|
| panel_size | Panel width x height in feet (e.g. 4 x 8, 4 x 10) | **null** |
| waste_pct | Waste factor applied after dividing area by panel coverage | **null** |
| trim_stick_length | Length in feet of one stick of trim | **null** |
| adhesive_coverage_sqft_per_unit | Square feet per pail or tube | **null** |
| opening_handling | Whether door/window openings are deducted, and above what size | **null** |

## Trim types to quantify

- inside corner
- outside corner
- division bar / H-mould
- cap / J-trim
- cove base

## What the copilot does until the constants arrive

Extract and report **geometry + product attributes**:

- product type and manufacturer (when named)
- location / room
- drawing scale and Vu360 / geometry notes
- perimeter linear feet
- inside corner count
- outside corner count
- wall height
- deducted opening areas, listed individually
- panel / trim / adhesive / special-condition text when stated

Then **stop**. Emit every material quantity as `null` with
`status: "PENDING_CONSTANTS"`. Do not invent a panel size, a waste factor, or an
adhesive coverage number - a wrong FRP quantity is a wrong quote, and this is
exactly the kind of gap `.claude/guides/extraction.md` exists to keep visible.

## Current manual process

Shanna sets the drawing scale in Vu360 and captures perimeter and corners. Vu360
gives geometry only; the conversion to material quantities is done by hand on a
calculator and typed in. Automating that conversion is the point of FR-12 - it
just cannot start until the constants land.

## Pricing (not this phase)

Vendor list prices and multipliers belong in Phase 4 (price books / P21 / RFQ).
Do not open NUDO or other FRP price PDFs during Phase 3b take-off.
