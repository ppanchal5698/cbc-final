"""What the bid request itself says CBC is quoting (FR-1, FR-1a's scope notes).

A GC's email or a phoned-in request often puts the scope in a line - "hardware
only", "doors and frames by GC", "no Div 10" - and the drawings do not say it.
Read here, a part the request gives to someone else stays on the quote as
supplied by others: never in the total, listed in the proposal's
qualifications, and the estimator's to move back if the reading is wrong.
"""
from __future__ import annotations

import re
from typing import Any

# Who else supplies it, in the words a request uses.
_PARTY = (r"(?:(?:BY|FURNISHED\s+BY|PROVIDED\s+BY|SUPPLIED\s+BY)\s+(?:THE\s+)?"
          r"(?:OTHERS|OWNER|TENANT|LANDLORD|G\.?C\.?|GENERAL\s+CONTRACTOR|CONTRACTOR)"
          r"|N\.?I\.?C\.?|NOT\s+IN\s+CONTRACT|EXCLUDED|NOT\s+INCLUDED)")
_ARE = r"\s+(?:ARE\s+|IS\s+|TO\s+BE\s+)?"

# Each category, and the words that name it.
_NAMES = {
    "doors": r"DOORS?",
    "frames": r"(?:HM\s+|HOLLOW\s+METAL\s+)?FRAMES?",
    "division10": r"(?:DIV(?:ISION)?\.?\s*10|TOILET\s+ACCESSORIES|(?:RESTROOM\s+)?ACCESSORIES|(?:TOILET\s+)?PARTITIONS)",
    "frp": r"FRP",
}
# A door kind that is not CBC's anyway: "overhead doors by others" says nothing of CBC's doors.
_OTHER_DOORS = re.compile(r"\b(?:OVERHEAD|COILING|ROLLING|GARAGE|SLIDING|REVOLVING|BI-?FOLD|POCKET)\s+$", re.I)

_HARDWARE_ONLY = re.compile(r"\b(?:(?:DOOR\s+)?HARDWARE\s+ONLY|ONLY\s+(?:THE\s+)?(?:DOOR\s+)?HARDWARE)\b", re.I)
_ONE_PATTERNS = {
    category: [
        # "doors by others", "doors and frames by the GC", "Div 10 is N.I.C."
        re.compile(rf"\b{name}(?:\s*(?:,|AND|&|/)\s*{_NAMES['frames']})?{_ARE}{_PARTY}", re.I),
        # "no doors", "excluding FRP", "doors not included"
        re.compile(rf"\b(?:NO|EXCLUDING|EXCLUDE|LESS)\s+{name}\b", re.I),
    ]
    for category, name in _NAMES.items()
}


def excluded(notes: Any) -> dict[str, str]:
    """Each category the request gives to someone else, with the words that said so."""
    text = " ".join(str(notes or "").split())
    if not text:
        return {}
    out: dict[str, str] = {}
    only = _HARDWARE_ONLY.search(text)
    if only:
        for category in ("doors", "frames", "division10", "frp"):
            out[category] = only.group(0)
    for category, patterns in _ONE_PATTERNS.items():
        for pattern in patterns:
            for found in pattern.finditer(text):
                if category == "doors" and _OTHER_DOORS.search(text[: found.start()]):
                    continue
                out.setdefault(category, found.group(0))
                # "doors and frames by GC" gives the frames away with the doors.
                if category == "doors" and re.search(r"FRAMES?", found.group(0), re.I):
                    out.setdefault("frames", found.group(0))
    return out


def category_of(key: str, division: str) -> str | None:
    """Which part of the request's scope a take-off line is."""
    if key.startswith("door:"):
        return "doors"
    if key.startswith("frame:"):
        return "frames"
    if division.startswith("10"):
        return "division10"
    if division.startswith(("06", "09 77")):
        return "frp"
    return None
