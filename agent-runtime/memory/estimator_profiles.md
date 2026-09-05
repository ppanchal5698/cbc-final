# Estimator Profiles — the three working styles

Two estimating modes coexist and **both stay**. Do not force one on the other.

## Kevin — one-off mode ("start blank, build up")
Builds each quote from scratch in a blank workbook, copying reference rows in.
Prices manually using vendor multiplier sheets, and calls vendors for parts that are
not in P21 or on a multiplier sheet.
**Exceptions**: McDonald's and Cava — Kevin works those templated.

## Rick — his own Excel
Works from his own spreadsheet rather than either shared workbook.
Occasionally includes **freight** for customers who demand an all-inclusive bottom line —
otherwise freight is not quoted at estimate stage (see [[process_flow]] Phase 6).

## Shanna — templated mode ("start full, delete down")
Opens a **previous job's workbook** (not a clean template), saves-as, and trims the
residual rows down to the current job. Clearing residual rows is therefore the first task
of every templated job. Shanna also runs the **FRP take-off** in Vu360 + calculator.

## Workbook facts
- Both shared Excel workbooks are password-protected: **estimator**.
- Adoption of the blank-quote workbook is uneven; the copilot must not disrupt anyone —
  "it only helps" (NFR-11).

## Implication for the copilot
Support **both** modes: build-from-scratch and start-from-closest-prior-quote
(FR-11, see the reuse-prior-quote skill). Phase 1 starts from Hager + the top-10 vendors
+ the stock list.
