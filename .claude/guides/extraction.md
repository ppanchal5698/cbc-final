# Extraction and matching (NFR-2)

Applies during take-off, extraction and product matching. Not needed when
pricing, quoting or working outside the pipeline.

Merged from `accuracy-trust.md` and `pdf-verify-before-present.md`, which
already cross-referenced each other.

---

## Confidence and review flags

**Confidence scoring and review flags are visible from day one. Unmatched or
low-confidence items are never silently guessed.**

This mirrors how an estimator already searches P21: "here are 3 close matches —
is it one of these?" That behaviour is the target, not a fully automatic answer.

1. Every matched line carries a **confidence score 0.0–1.0** and the reason for it.
2. Confidence below **0.75** is **flagged for review**, never auto-accepted.
3. A missing required attribute (size, handing, finish, fire rating, hardware
   set) is recorded as **null and flagged** — never filled by inference from a
   neighbouring row.
4. Unparsed or unreadable content is reported explicitly in
   `review/review_flags.json`. Silence is not an acceptable way to represent
   "I could not read this".
5. At the **manual cut-off** (`.claude/memory/manual_cutoff.md`) emit
   `cost_source: MANUAL` with confidence `0.0` and a plain-language reason.
6. When proposing a direct-equal substitution, always attach a **substitution
   note** naming what was specified and what is being offered instead.

### Confidence bands

| Score | Meaning | Action |
|---|---|---|
| 0.95–1.00 | Exact part-number match, all attributes agree | accept |
| 0.75–0.94 | Series match, one soft attribute differs | accept with note |
| 0.40–0.74 | Plausible match, needs a human | **flag** |
| 0.00–0.39 | No usable match / manual cut-off | **flag, price manually** |

`0.75` is the review floor and is stated here once. `skills/match-hardware-sets`
and `skills/validate-extraction` restate it; this file is the source.

---

## Verify against the sheet before presenting (NFR-3)

**If a value is unclear, incomplete, or about to be flagged missing — open the
specific PDF page and check it before presenting the result.** Guessing from
memory, neighbouring rows, or the parser summary alone is forbidden.

Skipping the sheet and writing `*_missing` from the parser summary is a defect.
A flag without a PDF check is a process defect. A filled value without a page
citation is unauditable.

### When this gate applies

Any agent that writes openings, scope, review flags or priced lines must follow
it when:

1. A required FR-2 field is null and you are about to emit `*_missing`
2. Confidence would fall below **0.75**
3. Two sources disagree (parser vs sheet, schedule vs type schedule, HW legend
   vs row)
4. A schedule cell exists but was not mapped (glass, materials, detail codes, notes)
5. You are unsure of a size, handing, finish, rating, group, or wall/frame type

### The check, before saving or presenting

1. **Name the page.** Use `source_page` / sheetmap / `search_pdf` /
   `search_blocks` — never invent a page number.
2. **Read that page.** If it appears in `extracted/_visual_pages.json`, start
   with the pre-rendered image (`Read` `image_path`, or `get_page_image` full
   page if the cache file is missing) — not bid-docs / extract_text. Otherwise
   prefer `get_page_blocks` / `extract_tables` / `extract_text` on that page.
   Crop with `get_page_image(region=bbox)` when the text layer is ambiguous.
3. **Record what you checked** in `evidence_note` (or the review flag `note`):
   tool used, page, and a short excerpt or "not found after search of pages …".
4. **Only then** fill the value, leave null + flag, or raise an RFI.

---

## Minute details

Every non-empty schedule cell maps to an allowlisted field or into `notes` —
glass, materials, frame-type digits, detail and note codes must not be dropped
just because the deterministic pass left them in `raw_row`.

| Cell content | Where it goes |
|---|---|
| Mark, size, type, materials, glass, HW group, keying object | Allowlisted Opening fields |
| Thickness, detail refs, note numbers | `notes` (never invent new keys) |
| Door / frame type schedule callouts | Cross-read those pages; fill rating / construction when stated |
| Floor-plan swing | `handing` (Matrix 7.4) — required search when the schedule has no HAND column |

Do not drop TEMP. glass, HM/HMD, frame-type digits, or note letters because the
parser left them in `raw_row` only.

**Owner:** CBC Estimating.
