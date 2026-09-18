# PDF verify before present (NFR-2 / NFR-3)

**If a value is unclear, incomplete, or about to be flagged missing — open the
specific PDF page and check it before presenting the result.** Guessing from
memory, neighbouring rows, or the parser summary alone is forbidden.

## When this applies

Any agent that writes openings, scope, review flags, or priced lines must follow
this gate when:

1. A required FR-2 field is null and you are about to emit `*_missing`
2. Confidence would fall below **0.75**
3. Two sources disagree (parser vs sheet, schedule vs type schedule, HW legend vs row)
4. A schedule cell exists but was not mapped (glass, materials, detail codes, notes)
5. You are unsure of a size, handing, finish, rating, group, or wall/frame type

## Mandatory check (do this before saving or presenting)

1. **Name the page.** Use `source_page` / sheetmap / `search_pdf` /
   `search_blocks` — never invent a page number.
2. **Read that page.** If the page appears in `extracted/_visual_pages.json`,
   start with the pre-rendered image (`Read` `image_path`, or
   `get_page_image` full page if the cache file is missing) — not bid-docs /
   extract_text. Otherwise prefer `get_page_blocks` / `extract_tables` /
   `extract_text` on that page. Crop with
   `get_page_image(region=bbox)` when the text layer is ambiguous.
3. **Record what you checked** in `evidence_note` (or the review flag `note`):
   tool used, page, and a short excerpt or "not found after search of pages …".
4. **Only then** fill the value, leave null + flag, or raise an RFI.

A flag without a PDF check is a process defect. A filled value without a page
citation is unauditable (NFR-3).

## Minute details

Every non-empty schedule cell belongs somewhere:

| Cell content | Where it goes |
|---|---|
| Mark, size, type, materials, glass, HW group, keying object | Allowlisted Opening fields |
| Thickness, detail refs, note numbers | `notes` (never invent new keys) |
| Door / frame type schedule callouts | Cross-read those pages; fill rating / construction when stated |
| Floor-plan swing | `handing` (Matrix 7.4) — required search when schedule has no HAND column |

Do not drop TEMP. glass, HM/HMD, frame-type digits, or note letters because the
parser left them in `raw_row` only.

## Owner

CBC Estimating.
