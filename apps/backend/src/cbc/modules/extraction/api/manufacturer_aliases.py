"""Normalize known OCR / schedule misreads of manufacturer names."""
from __future__ import annotations

import re
from typing import Any

# Architect / OCR strings → canonical commercial brand.
_ALIASES: dict[str, str] = {
    "ALARM CLOCK": "Alarm Lock",
    "ALARMCLOCK": "Alarm Lock",
    "ALARM LOCK": "Alarm Lock",
    "SCHLAGE LOCK": "Schlage",
    "VONDUPLIN": "Von Duprin",
    "VON DUPRIN": "Von Duprin",
    "IVES BY ALLEGION": "Ives",
    "LCN CLOSERS": "LCN",
    "PEMCO": "Pemko",
    "NATIONAL GUARD PRODUCTS": "National Guard",
    "NGP": "National Guard",
}


def normalize_manufacturer(raw: str | None) -> tuple[str | None, bool]:
    """Return (canonical_name, changed)."""
    if raw is None:
        return None, False
    text = str(raw).strip()
    if not text:
        return text, False
    key = re.sub(r"\s+", " ", text).upper()
    mapped = _ALIASES.get(key)
    if mapped and mapped.lower() != text.lower():
        return mapped, True
    # Compact form without spaces.
    compact = re.sub(r"[^A-Z0-9]", "", key)
    for alias, canon in _ALIASES.items():
        if re.sub(r"[^A-Z0-9]", "", alias) == compact and canon.lower() != text.lower():
            return canon, True
    return text, False


def apply_to_hardware_item(item: dict[str, Any]) -> dict[str, Any]:
    """Normalize manufacturer on specified/matched; flag when rewritten."""
    out = dict(item)
    flags = list(out.get("flags") or [])
    for key in ("specified", "matched"):
        block = out.get(key)
        if not isinstance(block, dict):
            continue
        mfr, changed = normalize_manufacturer(block.get("manufacturer"))
        if changed:
            block = dict(block)
            block["manufacturer"] = mfr
            out[key] = block
            if "manufacturer_normalized" not in flags:
                flags.append("manufacturer_normalized")
    if flags != list(out.get("flags") or []):
        out["flags"] = flags
    return out


def apply_to_priced_line(line: dict[str, Any]) -> dict[str, Any]:
    """Normalize manufacturer embedded in notes or part prefixes when present."""
    out = dict(line)
    mfr, changed = normalize_manufacturer(out.get("manufacturer"))
    if changed:
        out["manufacturer"] = mfr
        flags = list(out.get("flags") or [])
        if "manufacturer_normalized" not in flags:
            flags.append("manufacturer_normalized")
        out["flags"] = flags
    # Part strings like "ALARM CLOCK ETDL…"
    part = str(out.get("part_number") or "")
    upper = part.upper()
    for alias, canon in _ALIASES.items():
        if upper.startswith(alias + " ") or upper.startswith(alias):
            rest = part[len(alias) :].lstrip(" -")
            out["part_number"] = f"{canon} {rest}".strip()
            flags = list(out.get("flags") or [])
            if "manufacturer_normalized" not in flags:
                flags.append("manufacturer_normalized")
            out["flags"] = flags
            break
    return out
