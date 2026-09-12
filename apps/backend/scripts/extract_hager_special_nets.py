#!/usr/bin/env python3
"""Extract Hager special net overrides from the multiplier PDF.

The multiplier sheet lists fixed net prices that override list × category for
specific parts (pp 2–4 of hager_multipliers.pdf).

    python scripts/extract_hager_special_nets.py
    python scripts/extract_hager_special_nets.py --write
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (
    ROOT
    / "final_pricebooks"
    / "HAGER"
    / "Hager Multipliers and Special Nets - Effective 3-2-26.pdf"
)
TARGET = ROOT / "reference-library" / "multipliers" / "hager_special_nets.json"

_ITEM_CODE = re.compile(r"^(\d{6})\s*$")
_PRICE = re.compile(r"^([\d.]+)\s*$")


def parse_pdf(path: Path) -> list[dict]:
    import fitz

    items: list[dict] = []
    section: str | None = None
    doc = fitz.open(path)
    try:
        for page_index in range(doc.page_count):
            lines = [
                line.strip()
                for line in doc[page_index].get_text().splitlines()
                if line.strip() and not line.startswith("Updated:")
            ]
            page_number = page_index + 1
            index = 0
            while index < len(lines):
                line = lines[index]
                if line.endswith(":") and len(line) < 60 and "Special Net" not in line:
                    section = line[:-1].strip()
                    index += 1
                    continue

                match = _ITEM_CODE.match(line)
                if not match:
                    index += 1
                    continue

                item_code = match.group(1)
                index += 1
                if index >= len(lines):
                    break

                part_line = lines[index]
                index += 1
                part_tokens = part_line.split(None, 1)
                part_number = part_tokens[0]
                description = part_tokens[1].strip() if len(part_tokens) > 1 else ""

                net_price: float | None = None
                while index < len(lines):
                    if _ITEM_CODE.match(lines[index]):
                        break
                    if lines[index].endswith(":"):
                        break
                    price_match = _PRICE.match(lines[index])
                    if price_match:
                        net_price = float(price_match.group(1))
                        index += 1
                        break
                    index += 1

                if net_price is None:
                    continue

                items.append(
                    {
                        "item_code": item_code,
                        "part_number": part_number.upper(),
                        "description": description,
                        "net_price": net_price,
                        "section": section,
                        "source_page": page_number,
                    }
                )
    finally:
        doc.close()

    # Last row wins when Hager repeats a part on a later page.
    by_part: dict[str, dict] = {}
    for row in items:
        by_part[row["part_number"]] = row
    return list(by_part.values())


def build_document(items: list[dict]) -> dict:
    return {
        "vendor": "hager",
        "account": "HGR 17907",
        "effective_date": "2026-03-02",
        "source": "pricebooks/hager_multipliers.pdf",
        "description": (
            "Special net prices from the Hager multiplier sheet. These override "
            "list × category when lookup_pricing finds an exact part match."
        ),
        "items": sorted(items, key=lambda row: row["part_number"]),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="write JSON to reference-library/")
    parser.add_argument("--source", type=Path, default=SOURCE)
    args = parser.parse_args()

    if not args.source.exists():
        print(f"missing source PDF: {args.source}", file=sys.stderr)
        return 1

    document = build_document(parse_pdf(args.source))
    print(json.dumps(document, indent=2))
    print(f"\n{len(document['items'])} special net item(s)", file=sys.stderr)

    if args.write:
        TARGET.parent.mkdir(parents=True, exist_ok=True)
        TARGET.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {TARGET}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
