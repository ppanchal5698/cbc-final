"""Read Division 10 accessories and FRP off the drawings, deterministically.

Both take-offs were placeholders: `seed_div10_takeoff` wrote `NOT_EXTRACTED` with
an empty `items`, `seed_frp_takeoff` wrote `NOT_MEASURED` with empty `areas`. So
every Div 10 and FRP field on a quote came from a model inventing it, and both
artifacts were among the ones quarantined for the wrong shape.

What is machine-readable here is the *schedule*: a Div 10 accessory schedule
names a manufacturer and a model per item, and an FRP spec names the product and
its manufacturer in prose. What is not machine-readable is geometry - perimeter
run, corner counts, wall height - which comes off scaled elevations. Those stay
null and flagged, because an invented linear-foot figure is a wrong quote with
nothing to signal it.

Same contract as the rest of the take-off: **never silently wrong**.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from cbc.modules.extraction.infrastructure.hardware_groups import KNOWN_MANUFACTURERS
from cbc.shared import pdfrows

# The Division 10 vendors CBC actually quotes. Narrower than the hardware list:
# a hinge maker on a door schedule is not a washroom accessory supplier.
DIV10_MANUFACTURERS = {
    name: label
    for name, label in KNOWN_MANUFACTURERS.items()
    if label in {"Bobrick", "ASI", "Bradley", "Gamco", "World Dryer", "Nudo"}
}

# What the accessory is, from how the schedule names it. Ordered: the first match
# wins, so the more specific phrases come first.
PRODUCT_TYPES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("toilet_tissue_dispenser", re.compile(r"\b(?:TOILET\s+(?:PAPER|TISSUE)|JUMBO\s+ROLL)\b.*DISPENSER|\bTISSUE\s+DISPENSER\b", re.I)),
    ("paper_towel_dispenser", re.compile(r"\b(?:PAPER\s+TOWEL|TOWEL)\s+DISPENSER\b", re.I)),
    ("soap_dispenser", re.compile(r"\bSOAP\s+DISPENSER\b", re.I)),
    ("hand_dryer", re.compile(r"\bHAND\s+DRYER\b", re.I)),
    ("grab_bar", re.compile(r"\bGRAB\s+BARS?\b", re.I)),
    ("mirror", re.compile(r"\bMIRROR\b", re.I)),
    # "FINAL HOOK-UPS" is an electrical note, not a coat hook.
    ("coat_hook", re.compile(r"\b(?:COAT\s+|ROBE\s+)?HOOKS?\b(?!\s*-?\s*UPS?\b)", re.I)),
    ("napkin_disposal", re.compile(r"\bNAPKIN\s+(?:DISPOSAL|RECEPTACLE)\b", re.I)),
    ("seat_cover_dispenser", re.compile(r"\bSEAT\s+COVER\b", re.I)),
    ("baby_change_station", re.compile(r"\b(?:BABY\s+CHANG|DIAPER)\w*\b", re.I)),
    ("waste_receptacle", re.compile(r"\b(?:WASTE|TRASH)\s+RECEPTACLE\b", re.I)),
    ("shelf", re.compile(r"\bSHELF\b", re.I)),
    ("toilet_partition", re.compile(r"\b(?:TOILET\s+)?(?:PARTITION|COMPARTMENT)S?\b", re.I)),
    ("robe_hook", re.compile(r"\bROBE\s+HOOK\b", re.I)),
)

# A model number on these sheets: B-3974, 0042, 9114-0000000, B-580616x18.
MODEL = re.compile(r"\b([A-Z]{0,3}-?\d[\dA-Z./x-]{2,})\b")
QTY = re.compile(r"^\s*(\d{1,3})\s*(?:EA\.?|PR\.?)?\b")

# FRP, and what kind.
FRP_PRESENT = re.compile(r"\bFRP\b|FIBERGLASS\s+REINFORCED\s+POLYESTER", re.I)
FRP_KIND = (
    ("textured", re.compile(r"\bTEXTURED\b", re.I)),
    ("non_tile", re.compile(r"\bNON[\s-]?TILE\b", re.I)),
    ("embossed", re.compile(r"\bEMBOSSED\b", re.I)),
)
# Geometry a drawing carries but prose does not.
_MEASURED_FIELDS = ("perimeter_lf", "wall_height_ft", "inside_corners", "outside_corners")


def _text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _rows(doc: Any, page_number: int) -> list[dict[str, Any]]:
    shift = pdfrows.detect_shift(doc, str(getattr(doc, "name", "")))
    return pdfrows.rows_from_words(doc[page_number - 1], shift=shift)


def _product_types(line: str) -> list[str]:
    """Every accessory type this row names, most specific first.

    A clustered row often carries two columns of a schedule plus a note, so
    "SURFACE MOUNTED JUMBO ROLL TOILET" and a neighbouring grab-bar note land on
    one line. Returning only the first match made that row a grab bar. Returning
    all of them lets the caller flag the row instead of guessing.
    """
    return [name for name, pattern in PRODUCT_TYPES if pattern.search(line)]


def _product_type(line: str) -> str | None:
    found = _product_types(line)
    return found[0] if found else None


def _manufacturer_in(line: str) -> tuple[str, str] | None:
    """(canonical name, the token as written), or None."""
    upper = line.upper()
    for token, label in DIV10_MANUFACTURERS.items():
        if re.search(rf"\b{re.escape(token)}\b", upper):
            return label, token
    return None


def _model_after(line: str, vendor_token: str) -> str | None:
    """The model number printed after the manufacturer, e.g. `BOBRICK B-3974`."""
    upper = line.upper()
    index = upper.find(vendor_token)
    tail = line[index + len(vendor_token):] if index >= 0 else line
    tail = re.sub(r"^\s*(?:MODEL|MODEL\s+NO\.?|NO\.?|#)\s*", " ", tail, flags=re.I)
    match = MODEL.search(tail)
    return match.group(1).strip(".,;:") if match else None


def div10_items_on_page(pdf: Path, page_number: int) -> list[dict[str, Any]]:
    """Accessory rows on one sheet. A row naming no product type is not one."""
    import fitz

    doc = fitz.open(pdf)
    try:
        rows = _rows(doc, page_number)
        page_size = {
            "width": round(doc[page_number - 1].rect.width, 2),
            "height": round(doc[page_number - 1].rect.height, 2),
        }
    finally:
        doc.close()

    items: list[dict[str, Any]] = []
    for row in rows:
        line = _text(" | ".join(row.get("cells") or []))
        if not line:
            continue
        candidates = _product_types(line)
        if not candidates:
            continue
        product_type = candidates[0]
        vendor = _manufacturer_in(line)
        manufacturer, model = (None, None)
        if vendor:
            manufacturer, token = vendor
            model = _model_after(line, token)

        flags: list[str] = []
        if len(candidates) > 1:
            # Two schedule columns clustered onto one row. Which one this model
            # belongs to is a reading of the sheet, not of the text.
            flags.append("product_type_ambiguous")
        if manufacturer is None:
            flags.append("manufacturer_missing")
        if model is None:
            flags.append("specified_model_missing")
        # Counting accessories means reading interior elevations, not a schedule
        # row. Defaulting to 1 would quote one grab bar for a building.
        qty_match = QTY.match(line)
        qty = float(qty_match.group(1)) if qty_match else None
        if qty is None:
            flags.append("qty_not_stated")

        items.append({
            "product_type": product_type,
            "manufacturer": manufacturer,
            "specified_model": model,
            "qty": qty,
            "unit": "EA" if qty is not None else None,
            "location": None,
            "room": None,
            "drawing_ref": None,
            "finish": None,
            "notes": line[:300],
            "alternate": "/".join(candidates[1:]) or None,
            "source_page": page_number,
            "evidence_note": f"read from the Division 10 schedule on page {page_number}",
            "flags": flags,
            "confidence": round(max(0.3, 1.0 - 0.15 * len(flags)), 2),
            "_page_size": page_size,
        })
    return items


def div10_envelope(pdf: Path, pages: list[int]) -> dict[str, Any]:
    """Division 10 across the sheets tagged for it, split by what can be quoted.

    A schedule row identifies an accessory by manufacturer **and** model. A row
    that names an accessory and nothing else is a sentence about one, not a line
    to price: "CONTRACTOR MAKING FINAL HOOK-UPS" is not a coat hook, and
    "ANCHORAGE OF TOILET ACCESSORIES AND PARTITIONS" is not a partition. Eighteen
    rows of which six were real read as data and priced as data.

    So `items` carries what a schedule identified, and `mentions` carries every
    other row that named an accessory - reported, because silence is not an
    acceptable way to say "I could not read this" (accuracy-trust rule 4), but
    never priced.
    """
    items: list[dict[str, Any]] = []
    mentions: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    seen_mentions: set[tuple[Any, ...]] = set()
    read: list[int] = []
    for page_number in pages:
        found = div10_items_on_page(pdf, page_number)
        if found:
            read.append(page_number)
        for item in found:
            item.pop("_page_size", None)
            if item["manufacturer"] is None or item["specified_model"] is None:
                # One entry per type per page. The question a mention answers is
                # "does this sheet talk about an accessory we found no row for?",
                # and three copies of MIRROR from three prose rows answer it once.
                mention_key = (item["product_type"], item["source_page"])
                if mention_key in seen_mentions:
                    continue
                seen_mentions.add(mention_key)
                mentions.append({
                    "product_type": item["product_type"],
                    "source_page": item["source_page"],
                    "excerpt": item["notes"],
                    "why_not_an_item": "no manufacturer and model on this row",
                })
                continue
            key = (item["product_type"], item["manufacturer"], item["specified_model"])
            if key in seen:
                continue
            seen.add(key)
            items.append(item)

    flags: list[str] = [] if items else ["no_div10_items_found"]
    if mentions:
        # The estimator decides whether a mention is a real accessory the
        # schedule did not carry. Nothing here is dropped quietly.
        flags.append("div10_mentions_need_review")
    return {
        "source_file": pdf.name,
        "pages_read": read,
        "status": "EXTRACTED" if items else "NOT_EXTRACTED",
        "items": items,
        "mentions": mentions,
        "flags": flags,
    }


def frp_findings(pdf: Path, pages: list[int]) -> dict[str, Any]:
    """What the drawings say about FRP, and what they cannot say.

    Product and manufacturer come off the specification. Perimeter, corners and
    wall height come off scaled elevations, which this does not read - they stay
    null with `NOT_MEASURED`, because a guessed linear-foot figure prices a wall
    that does not exist.
    """
    import fitz

    doc = fitz.open(pdf)
    try:
        evidence: list[dict[str, Any]] = []
        kinds: set[str] = set()
        manufacturer = None
        for page_number in pages:
            text = doc[page_number - 1].get_text()
            if not FRP_PRESENT.search(text):
                continue
            for name, pattern in FRP_KIND:
                if pattern.search(text):
                    kinds.add(name)
            # Only a vendor named on the same line as the FRP text. Scanning the
            # whole sheet attributed FRP to Bobrick because a washroom accessory
            # elsewhere on page 23 mentioned it - Bobrick does not make FRP.
            if manufacturer is None:
                for candidate in text.splitlines():
                    if not FRP_PRESENT.search(candidate):
                        continue
                    found = _manufacturer_in(candidate)
                    if found:
                        manufacturer = found[0]
                        break
            line = next(
                (
                    _text(candidate)
                    for candidate in text.splitlines()
                    if FRP_PRESENT.search(candidate)
                ),
                "",
            )
            evidence.append({"source_page": page_number, "excerpt": line[:200]})
    finally:
        doc.close()

    if not evidence:
        return {
            "frp_in_scope": False,
            "status": "NOT_FOUND",
            "areas": [],
            "flags": ["no_frp_on_the_sheets_tagged_for_it"],
        }

    return {
        "frp_in_scope": True,
        "status": "NOT_MEASURED",
        "product_type": "/".join(sorted(kinds)) or "FRP wall panel",
        "manufacturer": manufacturer,
        "areas": [],
        "quantities": None,
        "quantity": None,
        "geometry_notes": (
            "FRP is specified on "
            + ", ".join(f"p{item['source_page']}" for item in evidence)
            + ". Perimeter, corner counts and wall height come off scaled "
            "interior elevations and have not been measured."
        ),
        "evidence": evidence,
        "blocked_on": "measurement from scaled elevations",
        "flags": [f"{field}_not_measured" for field in _MEASURED_FIELDS]
        + ([] if manufacturer else ["manufacturer_missing"]),
    }


def _demo() -> None:
    """Runnable check on the row classification, with no PDF required."""
    assert _product_type("C | SURFACE MOUNTED JUMBO ROLL TOILET TISSUE DISPENSER") == "toilet_tissue_dispenser"
    assert _product_type("D | COAT HOOK | BRADLEY 9114-0000000") == "coat_hook"
    assert _product_type("GRAB BAR REQUIREMENT AS PER CODE") == "grab_bar"
    assert _product_type("ENSURE MODEL IS HARDWIRED") is None
    assert _product_type("CONTRACTOR MAKING FINAL HOOK-UPS.") is None

    vendor = _manufacturer_in("SCHEDULE ON | BOBRICK B-3974 | ENSURE")
    assert vendor == ("Bobrick", "BOBRICK"), vendor
    assert _model_after("BOBRICK B-3974 | ENSURE", "BOBRICK") == "B-3974"
    assert _model_after("ASI MODEL NO.0042 SURFACE", "ASI") == "0042"
    assert _model_after("BRADLEY 9114-0000000 STAIN", "BRADLEY") == "9114-0000000"

    # A hinge vendor is not a washroom accessory supplier.
    assert _manufacturer_in("HAGER 3580 lock") is None

    assert FRP_PRESENT.search("TEXTURED FIBERGLASS REINFORCED POLYESTER (FRP) PANELS")
    assert not FRP_PRESENT.search("HOLLOW METAL DOOR")
    print("specialty_parser demo OK")


if __name__ == "__main__":
    _demo()
