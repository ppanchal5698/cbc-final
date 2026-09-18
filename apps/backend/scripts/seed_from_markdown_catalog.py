#!/usr/bin/env python3
"""Wipe catalog/multiplier data and reload from catalog.md + multipliers.md.

    cd apps/backend
    PYTHONPATH=src python scripts/seed_from_markdown_catalog.py

Reads:
  data/pricebooks/catalog.md
  data/pricebooks/catalogs/catalog_*.md  (per-vendor product tables)
  data/pricebooks/multipliers.md

Writes seed JSON under data/reference-library/ and upserts Mongo:
  catalogItems, priceBooks, referenceData (vendor_tiers, hager_special_nets, margins)

Drops first: catalogItems, priceBooks, catalogPages, multiplierPages, pageIndex,
and the three referenceData families above (plus their revisions).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pymongo import MongoClient

from cbc.shared.mongo_uri import reachable_uri
from cbc.shared.paths import pricebook_dir, reference_dir, repo_root
from cbc.shared.persistence import names

ROOT = repo_root()
CATALOG_MD = pricebook_dir() / "catalog.md"
CATALOGS_DIR = pricebook_dir() / "catalogs"
MULTIPLIERS_MD = pricebook_dir() / "multipliers.md"

# Filename → (division code, vendor heading) for synthetic ## / ### wrappers.
_VENDOR_FILE_META: dict[str, tuple[str, str]] = {
    "catalog_hager.md": ("08 71 00", "Hager"),
    "catalog_ngp.md": ("08 71 00", "National Guard"),
    "catalog_pemko.md": ("08 71 00", "Pemko"),
    "catalog_rockwood.md": ("08 71 00", "Rockwood"),
    "catalog_bobrick.md": ("10 28 00", "Bobrick"),
    "catalog_gamco.md": ("10 28 00", "Gamco"),
    "catalog_asi.md": ("10 28 00", "ASI"),
    "catalog_bradley.md": ("10 28 00", "Bradley"),
    "catalog_world_dryer.md": ("10 28 13", "World Dryer"),
    "catalog_nudo.md": ("09 77 00", "Nudo"),
}

_KNOWN_VENDORS = {
    "hager",
    "national_guard",
    "pemko",
    "rockwood",
    "bobrick",
    "gamco",
    "bradley",
    "asi",
    "world_dryer",
    "nudo",
}

URI = "mongodb://cbc:cbc_local_dev@localhost:27017/cbc_opshub?authSource=admin"

_MONEY = re.compile(r"[,$]")
_BOLD = re.compile(r"\*\*([^*]+)\*\*")
_CODE = re.compile(r"`([^`]+)`")
_PCT = re.compile(r"([\d.]+)\s*%")
_MULT = re.compile(r"\.(\d{2,4})")
_DIVISION = re.compile(r"^##\s+\d+\.\s+Division\s+([\d\s/]+)", re.I)
_VENDOR_HEAD = re.compile(
    r"^###?\s+\d*(?:\.\d+)?\s*(.+?)(?:\s*\(|$)",
    re.I,
)


def now() -> datetime:
    return datetime.now(timezone.utc)


def _clean_cell(raw: str) -> str:
    text = raw.strip()
    text = _BOLD.sub(r"\1", text)
    text = _CODE.sub(r"\1", text)
    text = text.replace("*(Net)*", "").replace("(Net)", "").strip()
    text = re.sub(r"\s+", " ", text)
    return text


def _money(raw: str) -> float | None:
    text = _clean_cell(raw)
    if not text or text in {"—", "-", "–"}:
        return None
    text = _MONEY.sub("", text)
    # Drop trailing notes after space when purely numeric-ish
    token = text.split()[0] if text else ""
    try:
        return float(token)
    except ValueError:
        return None


def _pct(raw: str) -> float | None:
    text = _clean_cell(raw)
    match = _PCT.search(text)
    if not match:
        return None
    return float(match.group(1)) / 100.0


def _parse_tables(md: str) -> list[tuple[list[str], list[list[str]]]]:
    """Return list of (header_cells, data_rows) for every markdown table."""
    lines = md.splitlines()
    tables: list[tuple[list[str], list[list[str]]]] = []
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        if line.startswith("|") and i + 1 < len(lines) and re.match(r"^\|[\s:|-]+\|", lines[i + 1]):
            header = [_clean_cell(c) for c in line.strip("|").split("|")]
            i += 2
            rows: list[list[str]] = []
            while i < len(lines) and lines[i].startswith("|"):
                cells = [_clean_cell(c) for c in lines[i].strip("|").split("|")]
                if not all(re.fullmatch(r":?-{3,}:?", c.replace(" ", "")) for c in cells if c):
                    rows.append(cells)
                i += 1
            tables.append((header, rows))
            continue
        i += 1
    return tables


def _col(header: list[str], *needles: str) -> int | None:
    lower = [h.lower() for h in header]
    for needle in needles:
        for index, name in enumerate(lower):
            if needle in name:
                return index
    return None


def _vendor_key(name: str) -> str:
    blob = name.lower()
    # More specific needles first (Gamco is a Bobrick division; avoid false bobrick).
    mapping = [
        ("hager", "hager"),
        ("national guard", "national_guard"),
        ("ngp", "national_guard"),
        ("pemko", "pemko"),
        ("markar", "pemko"),
        ("rockwood", "rockwood"),
        ("gamco", "gamco"),
        ("bobrick", "bobrick"),
        ("bradley", "bradley"),
        ("asi", "asi"),
        ("american specialties", "asi"),
        ("world dryer", "world_dryer"),
        ("nudo", "nudo"),
    ]
    for needle, key in mapping:
        if needle in blob:
            return key
    return re.sub(r"[^a-z0-9]+", "_", blob).strip("_") or "unknown"


def _division_code(heading: str) -> str:
    match = re.search(r"(\d{2})\s+(\d{2})\s+(\d{2})", heading)
    if match:
        return f"{match.group(1)} {match.group(2)} {match.group(3)}"
    if "08 71" in heading or "door hardware" in heading.lower():
        return "08 71 00"
    if "08 11" in heading or "doors" in heading.lower():
        return "08 11 00"
    if "10 21" in heading or "partition" in heading.lower():
        return "10 21 13"
    if "10 28 13" in heading or "hand dryer" in heading.lower():
        return "10 28 13"
    if "10 28" in heading or "restroom accessor" in heading.lower():
        return "10 28 00"
    if "09 77" in heading or "frp" in heading.lower():
        return "09 77 00"
    return "08 71 00"


# ── multipliers.md → vendor_tiers + special nets + margins ───────────────────


def build_vendor_tiers() -> dict[str, Any]:
    """Authoritative vendor multiplier directory from multipliers.md §5–6."""
    return {
        "description": (
            "CBC / Hamilton Parker vendor multiplier tiers from "
            "data/pricebooks/multipliers.md (Operating Baseline 2026)."
        ),
        "rule": "The multiplier is a per-vendor account attribute (a tier), not a per-item value. MAP is not cost.",
        "phase_1_scope": "Top vendors covering ~90% of quote volume (catalog.md Phase 1 lines).",
        "owner": "UNASSIGNED - see .claude/rules/data-stewardship.md (NFR-10, OPEN)",
        "source": "pricebooks/multipliers.md",
        "vendors": [
            {
                "key": "hager",
                "name": "Hager",
                "share_of_volume": 0.75,
                "account": "HGR 17907",
                "tier": "Hager Advantage Program",
                "multiplier": None,
                "effective_date": "2026-03-02",
                "source": "pricebooks/multipliers.md",
                "price_book": "Price Book #18, effective 2026-02-02",
                "note": "Priced by product category — use the categories map, not a single multiplier.",
                "categories": {
                    "locks": 0.29,
                    "door_controls": 0.3,
                    "exit_devices": 0.3005,
                    "electrified_products": 0.41,
                    "auto_operators": 0.4,
                    "architectural_hinges": 0.21,
                    "roton_geared_hinges": 0.325,
                    "stainless_steel_hinges": 0.325,
                    "trim_and_auxiliary": 0.425,
                    "thresholds_weatherstrip": 0.4,
                    "sliding_door_hardware": 0.43,
                    "residential_hinges": 0.375,
                    # Aliases used by agents / older sheets
                    "l_dc_e_accessories": 0.3,
                },
                "discounts": {
                    "locks": "50/42%",
                    "door_controls": "50/40%",
                    "exit_devices": "50/40%",
                    "electrified_products": "50/18%",
                    "auto_operators": "50/20%",
                    "architectural_hinges": "50/58%",
                    "roton_geared_hinges": "50/35%",
                    "stainless_steel_hinges": "50/35%",
                    "trim_and_auxiliary": "50/15%",
                    "thresholds_weatherstrip": "50/20%",
                    "sliding_door_hardware": "50/14%",
                    "residential_hinges": "50/25%",
                },
                "program_terms": {
                    "prepaid_freight": 1500,
                    "prepaid_freight_drop_ship": 5000,
                    "minimum_order_charge": None,
                    "crating_charge": 50.0,
                    "itemization_tagging_charge": 175.0,
                },
            },
            {
                "key": "allegion",
                "name": "Allegion (Von Duprin, LCN, Schlage, Ives)",
                "multiplier": None,
                "tier": None,
                "note": (
                    "NOT bought direct. Purchased through Banner Solutions or SecLock — "
                    "MANUAL price entry required with a 'price may be out of date' prompt."
                ),
                "distributors": ["Banner Solutions", "SecLock"],
                "source": "pricebooks/multipliers.md",
            },
            {
                "key": "national_guard",
                "name": "National Guard Products",
                "multiplier": 0.45,
                "tier": ".45 multiplier",
                "effective_date": "2026-06-08",
                "source": "pricebooks/multipliers.md",
                "note": "Universal .450 across standard catalog products.",
            },
            {
                "key": "pemko",
                "name": "PEMKO / Markar",
                "multiplier": None,
                "tier": "Buying program account 4244636 / J03",
                "effective_date": "2026-02-02",
                "account": "4244636",
                "source": "pricebooks/multipliers.md",
                "note": "Per-category buying-program multipliers.",
                "categories": {
                    "standard": 0.48,
                    "continuous_hinges": 0.33,
                    "nylon_brush": 0.38,
                    "adhesive_gasketing": 0.34,
                },
                "discounts": {
                    "standard": "52.0%",
                    "continuous_hinges": "67.0%",
                    "nylon_brush": "62.0%",
                    "adhesive_gasketing": "66.0%",
                },
            },
            {
                "key": "rockwood",
                "name": "Rockwood",
                "multiplier": 0.55,
                "tier": ".55 accessories",
                "effective_date": "2022-08-15",
                "source": "pricebooks/multipliers.md",
                "note": "Accessories book .550. Architectural / lites books use catalog net or size tables.",
            },
            {
                "key": "asi",
                "name": "ASI / ASI Accurate Partitions",
                "multiplier": 0.375,
                "tier": ".375 multiplier",
                "effective_date": "2026-01-12",
                "source": "pricebooks/multipliers.md",
                "note": None,
            },
            {
                "key": "bobrick",
                "name": "Bobrick",
                "multiplier": 1.0,
                "tier": "2020 Distributor Net",
                "effective_date": "2020-01-01",
                "source": "pricebooks/multipliers.md",
                "note": "Priced from 2020 Distributor Net Price List (×1.000). Not list × discount.",
            },
            {
                "key": "gamco",
                "name": "Gamco",
                "multiplier": 1.0,
                "tier": "2020 Distributor Net (Bobrick Div.)",
                "effective_date": "2020-01-01",
                "source": "pricebooks/multipliers.md",
                "note": "Distributor net ×1.000. Cross-reference to Bobrick equivalents in catalog.md.",
            },
            {
                "key": "bradley",
                "name": "Bradley Corp",
                "multiplier": 0.53,
                "tier": "WAD .53",
                "effective_date": "2026-01-12",
                "source": "pricebooks/multipliers.md",
                "note": "Washroom Accessories Division.",
            },
            {
                "key": "world_dryer",
                "name": "World Dryer",
                "multiplier": 0.339,
                "tier": "Level 3 (L3)",
                "effective_date": "2022-09-19",
                "source": "pricebooks/multipliers.md",
                "note": "Confirmed L3 multiplier via Pricing Memo 2022-09-12.",
            },
            {
                "key": "nudo",
                "name": "NUDO / Marlite / Midwest-East Coast FRP",
                "multiplier": 1.0,
                "tier": "Distributor Direct Net",
                "effective_date": "2026-05-11",
                "source": "pricebooks/multipliers.md",
                "note": "FRP panels and vinyl moldings priced from net sheet (×1.000).",
            },
        ],
        "excluded": [
            {
                "name": "Scranton Products",
                "reason": "Access lost — would have to go through a costlier distributor. OUT OF SCOPE.",
            },
            {"name": "American Dryer", "reason": "No longer used. OUT OF SCOPE."},
        ],
    }


def build_margins() -> dict[str, Any]:
    return {
        "description": "CBC margin framework by product type from multipliers.md §2.2.",
        "formula": "sale_ea = cost / (1 - margin)",
        "overridable": True,
        "override_reason": "sourcing",
        "override_note": (
            "Margin is overridden on essentially every quote based on sourcing — "
            "distributor buys, special-customer margins, lead time, and custom first builds."
        ),
        "governance": (
            "Below-band lines are FLAGGED only. Approval routing is deferred "
            "(NFR-8 / Matrix 6.7)."
        ),
        "source": "pricebooks/multipliers.md",
        "bands": [
            {
                "key": "commodity",
                "name": "Commodity Door Hardware",
                "margin": 0.27,
                "divisor": 0.73,
                "examples": [
                    "locksets",
                    "closers",
                    "exit devices",
                    "hinges",
                    "thresholds",
                    "trim",
                    "FRP panels",
                ],
            },
            {
                "key": "restroom_partitions",
                "name": "Restroom Partitions",
                "margin": 0.35,
                "divisor": 0.65,
                "examples": ["toilet partitions", "urinal screens"],
            },
            {
                "key": "restroom_accessories",
                "name": "Restroom Accessories",
                "margin": 0.56,
                "divisor": 0.44,
                "examples": [
                    "grab bars",
                    "soap dispensers",
                    "towel dispensers",
                    "mirrors",
                    "hand dryers",
                ],
            },
            {
                "key": "specialty",
                "name": "Specialty Products",
                "margin": 0.4,
                "divisor": 0.6,
                "examples": ["specialty wood doors", "laminated doors", "custom preps"],
            },
            {
                "key": "custom_built",
                "name": "Outside Custom Fabrication",
                "margin": 0.25,
                "divisor": 0.75,
                "examples": ["custom fabrications via outside partner fabricators"],
            },
        ],
        "accessories_derived": 0.56,
        "accessories_note": (
            "Restroom accessories derive to about 56% from transaction data "
            "(originally recorded as 35%)."
        ),
        "removed": {
            "unit_weight": "Legacy column from truck-loading years ago. Not used — removed."
        },
    }


def parse_hager_special_nets(md: str) -> dict[str, Any]:
    """Parse §6.1 Special Net Pricing Items table from multipliers.md."""
    items: list[dict[str, Any]] = []
    section = "Hager special nets"
    in_special = False
    for line in md.splitlines():
        if "Special Net Pricing Items" in line:
            in_special = True
            continue
        if in_special and line.startswith("### 6.2"):
            break
        if in_special and line.startswith("**") and "Commercial Hinges" in line:
            section = "Commercial hinges"
            continue
        if in_special and line.startswith("**") and line.strip().startswith("**"):
            # Section banner rows inside the table markdown use bold labels
            label = _clean_cell(line.strip("|").split("|")[0]) if "|" in line else _clean_cell(line)
            if label and not re.match(r"^\d", label) and "Part #" not in label:
                section = label
            continue
        if not in_special or not line.startswith("|"):
            continue
        cells = [_clean_cell(c) for c in line.strip("|").split("|")]
        if len(cells) < 4:
            continue
        if cells[0].lower().startswith("part") or set(cells[0]) <= {":", "-"}:
            continue
        # Banner rows: first cell is category label, rest empty-ish
        if not re.match(r"^\d{5,6}$", cells[0].replace("`", "")) and not re.match(
            r"^\d{5,6}$", cells[0]
        ):
            if cells[0] and not _money(cells[-1]):
                section = cells[0]
            continue
        item_code = cells[0].strip("`")
        model_cell = cells[1]
        # Model is often "BB1279 4-1/2..." — take leading token(s) before size
        model = model_cell.split()[0] if model_cell else item_code
        # Prefer full model token including series letters
        model_match = re.match(r"^([A-Za-z0-9][A-Za-z0-9./-]*)", model_cell)
        if model_match:
            model = model_match.group(1)
        finish = cells[2] if len(cells) > 2 else ""
        net = _money(cells[3] if len(cells) > 3 else "")
        if net is None:
            continue
        items.append(
            {
                "item_code": item_code,
                "part_number": model,
                "description": f"{model_cell} {finish}".strip(),
                "net_price": net,
                "section": section,
                "source_page": None,
            }
        )

    # Deduplicate by item_code (last wins)
    by_code: dict[str, dict[str, Any]] = {}
    for row in items:
        by_code[row["item_code"]] = row

    return {
        "vendor": "hager",
        "account": "HGR 17907",
        "effective_date": "2026-03-02",
        "source": "pricebooks/multipliers.md",
        "description": (
            "Special net prices from the Hager multiplier sheet. These override "
            "list × category when lookup finds an exact part / model match."
        ),
        "items": sorted(by_code.values(), key=lambda r: r["item_code"]),
    }


# ── catalog.md → catalogItems ───────────────────────────────────────────────


def _default_margin_for_division(division: str, vendor_key: str) -> float:
    if division.startswith("10 28") or vendor_key in {
        "bobrick",
        "gamco",
        "asi",
        "bradley",
        "world_dryer",
    }:
        return 0.56
    if division.startswith("10 21"):
        return 0.35
    return 0.27


def _infer_category(vendor_key: str, section: str, description: str) -> str | None:
    blob = f"{section} {description}".lower()
    if vendor_key != "hager":
        if vendor_key == "pemko":
            if "continuous" in blob or "markar" in blob or "cfm" in blob or "fm300" in blob:
                return "continuous_hinges"
            if "brush" in blob:
                return "nylon_brush"
            if "adhesive" in blob or "silicon" in blob or "s88" in blob:
                return "adhesive_gasketing"
            return "standard"
        return None
    if "lock" in blob or "deadbolt" in blob or "passage" in blob or "storeroom" in blob:
        return "locks"
    if "closer" in blob or "door control" in blob or "5100" in blob or "5200" in blob:
        return "door_controls"
    if "exit" in blob or "4501" in blob or "4701" in blob:
        return "exit_devices"
    if "roton" in blob or "780-" in blob or "geared" in blob:
        return "roton_geared_hinges"
    if "hinge" in blob or "bb12" in blob or "bb11" in blob or "ecbb" in blob:
        return "architectural_hinges"
    if "threshold" in blob or "weather" in blob or "sweep" in blob or "gasket" in blob:
        return "thresholds_weatherstrip"
    if "trim" in blob or "pull" in blob or "push" in blob or "kick" in blob or "stop" in blob:
        return "trim_and_auxiliary"
    return None


def parse_catalog_products(md: str) -> list[dict[str, Any]]:
    """Walk catalog.md with heading context and extract priced product rows."""
    lines = md.splitlines()
    division = "08 71 00"
    vendor_name = "Hager"
    vendor_key = "hager"
    section = ""
    section_multiplier: float | None = None
    products: list[dict[str, Any]] = []
    i = 0

    while i < len(lines):
        line = lines[i].rstrip()

        # H1 vendor titles in per-vendor files (e.g. "# Pemko & Markar …").
        if line.startswith("# ") and not line.startswith("##"):
            heading = _clean_cell(line.lstrip("#").strip())
            key = _vendor_key(heading)
            if key in _KNOWN_VENDORS:
                vendor_name = heading.split("—")[0].split("(")[0].strip()
                vendor_key = key
                section = vendor_name
                section_multiplier = None
                if key in {"bobrick", "gamco", "asi", "bradley"}:
                    division = "10 28 00"
                elif key == "world_dryer":
                    division = "10 28 13"
                elif key == "nudo":
                    division = "09 77 00"
                else:
                    division = "08 71 00"
            i += 1
            continue

        if line.startswith("## "):
            if "Division" in line:
                division = _division_code(line)
            # Vendor sometimes only appears on the ## line (e.g. Nudo FRP).
            if "nudo" in line.lower() or "frp wall" in line.lower():
                vendor_name = "Nudo Products"
                vendor_key = "nudo"
                section = vendor_name
            if "Cross-Reference" in line:
                pass
            i += 1
            continue

        if line.startswith("### "):
            heading = _clean_cell(line.lstrip("#").strip())
            # e.g. "2.1 Hager Companies (Primary Line — ~75% Volume)"
            candidate = re.sub(r"^\d+(?:\.\d+)*\s*", "", heading)
            candidate = re.split(r"\s*[—(]", candidate)[0].strip()
            key = _vendor_key(candidate)
            # Only treat ### as a vendor switch when it names a known vendor.
            # Subsections like "6.1 FRP Wall Liner Panels" keep the parent vendor.
            if key in _KNOWN_VENDORS:
                vendor_name = candidate
                vendor_key = key
                section = vendor_name
                section_multiplier = None
            else:
                section = candidate
            i += 1
            continue

        if line.startswith("#### "):
            section = _clean_cell(line.lstrip("#").strip())
            section_multiplier = None
            i += 1
            continue

        if line.startswith("- **Account Multiplier:**") or line.startswith("- **Universal Multiplier:**"):
            match = _MULT.search(line)
            if match:
                section_multiplier = float(f"0.{match.group(1)}")
            if "1.000" in line or "`1.000`" in line:
                section_multiplier = 1.0
            i += 1
            continue
        if "Multiplier:**" in line or "Multipliers:**" in line:
            # Pemko multi-multiplier lines — leave null; category inferred later
            i += 1
            continue

        # Table start
        if line.startswith("|") and i + 1 < len(lines) and re.match(r"^\|[\s:|-]+\|", lines[i + 1]):
            header = [_clean_cell(c) for c in line.strip("|").split("|")]
            i += 2
            rows: list[list[str]] = []
            while i < len(lines) and lines[i].startswith("|"):
                cells = [_clean_cell(c) for c in lines[i].strip("|").split("|")]
                rows.append(cells)
                i += 1

            # Skip non-product tables (frame depths, notation, cross-ref without nets)
            idx_part = _col(header, "part #", "part / model", "product code", "profile code")
            idx_model = _col(
                header,
                "model number",
                "model #",
                "model series",
                "series & function",
                "part / model",
                "model",
            )
            idx_list = _col(header, "list ($)", "list price", "catalog list", "dealer list", "list")
            idx_net = _col(header, "cbc net", "tier 25", "unit net", "distributor net")
            idx_margin = _col(header, "default margin", "margin")
            idx_sale = _col(header, "unit sale")
            idx_desc = _col(
                header,
                "size & attributes",
                "length & mounting",
                "description",
                "category & description",
                "category & product",
                "product description",
                "profile description",
                "arm type",
                "width & operation",
                "dimension / profile",
                "cylinder type",
                "product family",
                "family",
                "mounting &",
                "category",
            )
            idx_finish = _col(header, "finish", "material", "base")
            idx_notes = _col(header, "application", "function &", "operating", "bobrick equivalent", "class /")
            idx_mult = _col(header, "multiplier used", "multiplier")

            if idx_net is None:
                continue  # not a priced product table

            for cells in rows:
                if not cells or len(cells) <= idx_net:
                    continue
                # Skip separator / banner rows
                if all(set(c) <= {":", "-", "–", " "} for c in cells):
                    continue

                part = ""
                model = ""
                if idx_part is not None and idx_part < len(cells):
                    part = cells[idx_part]
                if idx_model is not None and idx_model < len(cells):
                    model = cells[idx_model]
                # NGP / Pemko / Rockwood often put model in first column
                if not part and model:
                    part = model.split()[0]
                if not part and idx_desc is not None and idx_desc < len(cells):
                    part = cells[idx_desc].split()[0] if cells[idx_desc] else ""
                if not part:
                    continue
                # Skip category banner rows without prices
                net = _money(cells[idx_net])
                if net is None:
                    continue

                list_price = _money(cells[idx_list]) if idx_list is not None and idx_list < len(cells) else None
                margin = (
                    _pct(cells[idx_margin])
                    if idx_margin is not None and idx_margin < len(cells)
                    else _default_margin_for_division(division, vendor_key)
                )
                sale = _money(cells[idx_sale]) if idx_sale is not None and idx_sale < len(cells) else None
                desc_bits = []
                if model and model != part:
                    desc_bits.append(model)
                if idx_desc is not None and idx_desc < len(cells) and cells[idx_desc]:
                    desc_bits.append(cells[idx_desc])
                if idx_finish is not None and idx_finish < len(cells) and cells[idx_finish]:
                    desc_bits.append(cells[idx_finish])
                description = " — ".join(desc_bits) if desc_bits else part
                notes = (
                    cells[idx_notes]
                    if idx_notes is not None and idx_notes < len(cells)
                    else None
                )
                mult = section_multiplier
                if idx_mult is not None and idx_mult < len(cells):
                    m = _MULT.search(cells[idx_mult])
                    if m:
                        mult = float(f"0.{m.group(1)}")
                category = _infer_category(vendor_key, section, description)

                # Canonical part: prefer CBC item code when 5–6 digits, else model token
                part_key = part.strip()
                model_key = (model.split()[0] if model else part_key).strip()

                # Canonical manufacturer display names
                mfr_names = {
                    "hager": "Hager",
                    "national_guard": "National Guard",
                    "pemko": "Pemko",
                    "rockwood": "Rockwood",
                    "bobrick": "Bobrick",
                    "gamco": "Gamco",
                    "bradley": "Bradley",
                    "asi": "ASI",
                    "world_dryer": "World Dryer",
                    "nudo": "Nudo",
                }
                products.append(
                    {
                        "part": part_key,
                        "model": model_key if model_key != part_key else None,
                        "description": description[:500],
                        "manufacturer": mfr_names.get(vendor_key, vendor_name.split("(")[0].strip()),
                        "vendorKey": vendor_key,
                        "division": division,
                        "cost": net,
                        "listPrice": list_price,
                        "multiplier": mult,
                        "category": category,
                        "defaultMargin": margin,
                        "unitSale": sale,
                        "notes": notes,
                        "section": section,
                        "availability": "In stock",
                        "seedSource": "catalog.md + catalogs/ 2026 baseline",
                    }
                )
            continue

        i += 1

    # Deduplicate by (vendorKey, part) — vendor files win over Phase-1 samples.
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for row in products:
        by_key[(row["vendorKey"], row["part"])] = row
    return list(by_key.values())


def parse_cross_refs(md: str) -> dict[str, list[dict[str, str]]]:
    """Multi-brand cross-reference → bobrick part → xref list.

    Accepts either the §7 table in catalog.md (Bobrick / Gamco / ASI / Bradley)
    or catalog_cross_reference.md (Specification Model / Bobrick / ASI / Bradley).
    """
    xref: dict[str, list[dict[str, str]]] = {}
    lines = md.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        if not (
            line.startswith("|")
            and i + 1 < len(lines)
            and re.match(r"^\|[\s:|-]+\|", lines[i + 1])
        ):
            i += 1
            continue

        header = [_clean_cell(c) for c in line.strip("|").split("|")]
        header_l = [h.lower() for h in header]
        i += 2

        idx_bobrick = _col(header, "bobrick")
        idx_gamco = _col(header, "gamco")
        idx_asi = _col(header, "asi")
        idx_bradley = _col(header, "bradley")
        # Require a Bobrick column and at least one peer brand.
        if idx_bobrick is None or not any(
            x is not None for x in (idx_gamco, idx_asi, idx_bradley)
        ):
            while i < len(lines) and lines[i].startswith("|"):
                i += 1
            continue
        # Skip non-xref product tables that happen to mention brand names in notes.
        if not any("bobrick" in h for h in header_l):
            while i < len(lines) and lines[i].startswith("|"):
                i += 1
            continue

        while i < len(lines) and lines[i].startswith("|"):
            cells = [_clean_cell(c) for c in lines[i].strip("|").split("|")]
            i += 1
            if not cells or len(cells) <= idx_bobrick:
                continue
            bobrick = cells[idx_bobrick]
            if not bobrick or bobrick.lower().startswith("bobrick") or bobrick in {"—", "-", "–"}:
                continue
            entries: list[dict[str, str]] = []
            for mfr, idx in (
                ("Gamco", idx_gamco),
                ("ASI", idx_asi),
                ("Bradley", idx_bradley),
            ):
                if idx is None or idx >= len(cells):
                    continue
                part = cells[idx]
                if part and part not in {"—", "-", "–"}:
                    entries.append({"manufacturer": mfr, "part": part})
            if entries:
                xref[bobrick] = entries

    return xref


def load_catalog_corpus() -> tuple[str, str]:
    """Load per-vendor catalogs/*.md for products; master + cross-ref for xref.

    Products come from catalogs/ only (avoids Phase-1 sample pollution / mis-tagged
    rows in the master index). Returns (products_markdown, xref_markdown).
    """
    master = CATALOG_MD.read_text(encoding="utf-8") if CATALOG_MD.is_file() else ""
    product_parts: list[str] = []
    xref_parts: list[str] = [master]

    if CATALOGS_DIR.is_dir():
        for path in sorted(CATALOGS_DIR.glob("catalog_*.md")):
            text = path.read_text(encoding="utf-8")
            if "cross_reference" in path.name.lower():
                xref_parts.append(f"\n\n## Cross-Reference\n\n{text}\n")
                continue
            meta = _VENDOR_FILE_META.get(path.name)
            if meta:
                division, vendor = meta
                headed = f"\n\n## Division {division}\n### {vendor}\n\n{text}\n"
            else:
                headed = f"\n\n{text}\n"
            product_parts.append(headed)

    # Fallback: if catalogs/ is empty, use master Phase-1 tables.
    if not product_parts:
        product_parts = [master]

    return "\n".join(product_parts), "\n".join(xref_parts)


# ── persistence ──────────────────────────────────────────────────────────────


def wipe(db, *, processed_dir: Path) -> None:
    for name in (
        names.CATALOG_ITEMS,
        names.PRICE_BOOKS,
        names.CATALOG_PAGES,
        names.MULTIPLIER_PAGES,
        names.PAGE_INDEX,
    ):
        db[name].drop()
        print(f"  dropped {name}")

    ref = db[names.REFERENCE_DATA]
    revs = db.get_collection("referenceDataRevisions")
    for family in ("vendor_tiers", "hager_special_nets", "margins"):
        ref.delete_one({"_id": family})
        revs.delete_many({"family": family})
        print(f"  deleted referenceData/{family}")

    if processed_dir.is_dir():
        shutil.rmtree(processed_dir, ignore_errors=True)
        print(f"  cleared {processed_dir}")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"  wrote {path.relative_to(ROOT)}")


def put_family(db, family: str, data: dict[str, Any]) -> None:
    db[names.REFERENCE_DATA].replace_one(
        {"_id": family},
        {
            "_id": family,
            "family": family,
            "schemaVersion": 1,
            "updatedAt": now(),
            "updatedBy": "seed_from_markdown_catalog",
            "data": data,
        },
        upsert=True,
    )


def seed_price_books(db, vendors: list[dict[str, Any]]) -> int:
    count = 0
    for vendor in vendors:
        key = vendor["key"]
        if key == "allegion":
            continue
        categories = vendor.get("categories") or {}
        multiplier = vendor.get("multiplier")
        if multiplier is None and categories:
            multiplier = categories.get("locks") or next(iter(categories.values()), None)
        program = f"{vendor.get('name')} — Operating Baseline 2026"
        filename = f"{key}_catalog_baseline.md"
        db[names.PRICE_BOOKS].update_one(
            {"vendor": key, "filename": filename},
            {
                "$set": {
                    "vendor": key,
                    "displayName": vendor.get("name"),
                    "program": program,
                    "multiplier": multiplier,
                    "categories": categories or None,
                    "effective": vendor.get("effective_date"),
                    "protectedThrough": None,
                    "lastReviewed": vendor.get("effective_date"),
                    "steward": "Purchasing",
                    "kind": "catalog_baseline",
                    "filename": filename,
                    "path": f"pricebooks/catalog.md#{key}",
                    "account": vendor.get("account"),
                    "note": vendor.get("note"),
                    "seedSource": "multipliers.md + catalog.md",
                    "updatedAt": now(),
                },
                "$setOnInsert": {"partCount": 0, "createdAt": now()},
            },
            upsert=True,
        )
        count += 1
    return count


def seed_products(
    db,
    products: list[dict[str, Any]],
    xref: dict[str, list[dict[str, str]]],
) -> int:
    books = {b["vendor"]: b for b in db[names.PRICE_BOOKS].find()}
    count = 0
    for row in products:
        book = books.get(row["vendorKey"])
        part = row["part"]
        extras = xref.get(part) or xref.get(row.get("model") or "") or []
        db[names.CATALOG_ITEMS].update_one(
            {"manufacturer": row["manufacturer"], "part": part},
            {
                "$set": {
                    "part": part,
                    "model": row.get("model"),
                    "description": row["description"],
                    "manufacturer": row["manufacturer"],
                    "vendorKey": row["vendorKey"],
                    "division": row["division"],
                    "cost": row["cost"],
                    "listPrice": row.get("listPrice"),
                    "multiplier": row.get("multiplier"),
                    "category": row.get("category"),
                    "defaultMargin": row.get("defaultMargin"),
                    "unitSale": row.get("unitSale"),
                    "notes": row.get("notes"),
                    "section": row.get("section"),
                    "availability": row.get("availability") or "In stock",
                    "priceBookId": book["_id"] if book else None,
                    "priceBook": book.get("program") if book else None,
                    "priceBasis": "special_net"
                    if row["vendorKey"] == "hager" and row.get("listPrice")
                    else ("list_x_multiplier" if row.get("listPrice") else "net"),
                    "xref": extras,
                    "seedSource": row.get("seedSource") or "catalog.md 2026 baseline",
                    "updatedAt": now(),
                    "updatedBy": "seed_from_markdown_catalog",
                },
                "$setOnInsert": {"createdAt": now()},
            },
            upsert=True,
        )
        count += 1

    for book in books.values():
        db[names.PRICE_BOOKS].update_one(
            {"_id": book["_id"]},
            {
                "$set": {
                    "partCount": db[names.CATALOG_ITEMS].count_documents(
                        {"priceBookId": book["_id"]}
                    )
                }
            },
        )
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uri", default=None)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and write JSON only; do not touch Mongo",
    )
    args = parser.parse_args()

    if not CATALOG_MD.is_file():
        print(f"missing {CATALOG_MD}", file=sys.stderr)
        return 1
    if not MULTIPLIERS_MD.is_file():
        print(f"missing {MULTIPLIERS_MD}", file=sys.stderr)
        return 1

    catalog_text, xref_text = load_catalog_corpus()
    multipliers_text = MULTIPLIERS_MD.read_text(encoding="utf-8")
    vendor_files = (
        sorted(p.name for p in CATALOGS_DIR.glob("catalog_*.md"))
        if CATALOGS_DIR.is_dir()
        else []
    )

    print("parsing markdown…")
    if vendor_files:
        print(f"  vendor files     {len(vendor_files)} under catalogs/")
    else:
        print("  vendor files     (none — Phase-1 tables in catalog.md only)")
    vendor_tiers = build_vendor_tiers()
    margins = build_margins()
    special_nets = parse_hager_special_nets(multipliers_text)
    products = parse_catalog_products(catalog_text)
    xref = parse_cross_refs(xref_text)
    print(f"  vendors          {len(vendor_tiers['vendors'])}")
    print(f"  special nets     {len(special_nets['items'])}")
    print(f"  catalog products {len(products)}")
    print(f"  xref anchors     {len(xref)}")

    # Always refresh seed JSON so REFERENCE_DIR matches Mongo.
    write_json(reference_dir() / "multipliers" / "vendor_tiers.json", vendor_tiers)
    write_json(reference_dir() / "multipliers" / "hager_special_nets.json", special_nets)
    write_json(reference_dir() / "margins" / "margin_framework.json", margins)
    write_json(
        pricebook_dir() / "catalog_baseline_products.json",
        {
            "generated_at": now().isoformat(),
            "source": "pricebooks/catalog.md + pricebooks/catalogs/",
            "count": len(products),
            "products": products,
        },
    )

    if args.dry_run:
        print("dry-run — skipped Mongo wipe/seed")
        return 0

    uri = reachable_uri(args.uri or os.environ.get("MONGODB_URI", URI))
    client = MongoClient(uri, serverSelectionTimeoutMS=5000)
    db = client[os.environ.get("MONGODB_DB", "cbc_opshub")]
    client.server_info()

    print("wiping old catalog + multiplier data…")
    wipe(db, processed_dir=pricebook_dir() / "processed")

    print("seeding Mongo…")
    put_family(db, "vendor_tiers", vendor_tiers)
    put_family(db, "hager_special_nets", special_nets)
    put_family(db, "margins", margins)
    print(f"  price books  {seed_price_books(db, vendor_tiers['vendors']):>4}")
    print(f"  products     {seed_products(db, products, xref):>4}")

    # Invalidate in-process caches if imported from a long-lived worker — N/A for CLI.
    print("\ndone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
