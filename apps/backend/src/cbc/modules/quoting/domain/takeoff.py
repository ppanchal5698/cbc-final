"""A bid's take-off as the lines it is priced in - decided in code.

Every hardware set an in-scope opening cites becomes one line per item, and the
line's quantity is the item's quantity per opening times the openings citing the
set: three hinges on a set four doors use is twelve hinges, not three. A set the
openings cite that nobody itemised is one line to price by hand; a set in the
legend that no opening cites is left out and said so. Division 10 and FRP rows
are lines of their own, and a row the schedule says another party supplies is an
alternate - kept on the quote, never in its total.

Pure: the take-off in, line skeletons out. Nothing here prices anything.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from cbc.shared import fire_rating

DOOR_HARDWARE = "08 71 00"

_QTY = re.compile(
    r"^\s*(\d+(?:\.\d+)?)?\s*(?:[- ]\s*)?(?:(\d+)\s*/\s*(\d+))?\s*"
    r"(EA|EACH|PR|PRS|PAIR|PAIRS|SET|SETS|LF|LIN\.?\s*FT|FT|SF|SQ\.?\s*FT)?\.?\s*$",
    re.I,
)
_PAIR = {"PR", "PRS", "PAIR", "PAIRS"}

# Schedule wording for an item another party supplies - owner furnished,
# contractor installed, by others. Quoting it would put it in CBC's price.
_BY_OTHERS = re.compile(
    r"\b(?:OFCI|O\.F\.C\.I|N\.I\.C|NIC|BY\s+OTHERS"
    r"|OWNER[\s-]+(?:FURNISHED|SUPPLIED|PROVIDED)"
    r"|(?:PROVIDED|FURNISHED|SUPPLIED)\s+BY\s+(?:THE\s+)?(?:OWNER|TENANT|LANDLORD))\b",
    re.I,
)


def quantity(value: Any) -> tuple[float | None, str | None]:
    """How many of an item, each: `3`, `3 EA`, `1 1/2 PR` (three), `1-1/2`, `2PR`.

    A pair is two - hinges are written in pairs and priced each. A quantity that
    cannot be read is None, never 1: a guessed count is a wrong total.
    """
    if isinstance(value, bool):
        return None, None
    if isinstance(value, (int, float)):
        return (float(value), None) if value > 0 else (None, None)
    text = str(value or "").strip().strip("()").strip()
    match = _QTY.match(text)
    if not text or not match or not (match.group(1) or match.group(2)):
        return None, None
    whole, num, den, unit = match.groups()
    each = float(whole or 0)
    if num and den and float(den):
        each += float(num) / float(den)
    unit = (unit or "").upper().replace(" ", "").replace(".", "") or None
    if unit in _PAIR:
        return each * 2, "EA"
    return (each, unit) if each > 0 else (None, None)


_LETTER_SET = re.compile(r"(?<![A-Z0-9])([A-Z])([0-9]{1,3})([A-Z]?)(?![A-Z0-9])")
_SET_NUMBER = re.compile(r"(?<![0-9])([0-9]{1,3})([A-Z]?)(?![0-9A-Z])")


def set_key(text: Any) -> str | None:
    """`GROUP 1`, `SET 01`, `HW-1`, `HW1`, `GROUP 7: RESTROOM` and `1` are sets 1
    and 7; `07A` is not `07`. A letter-led legend's `E1` and `O1` are two sets -
    a standalone letter fused to the number is part of the name, a word's (`HW1`)
    is not. The first such name in the reference is the set's."""
    raw = str(text or "").strip().upper()
    found = [m for m in (_LETTER_SET.search(raw), _SET_NUMBER.search(raw)) if m]
    if not found:
        return None
    first = min(found, key=lambda m: m.start())
    if first.re is _LETTER_SET:
        return f"{first.group(1)}{int(first.group(2))}{first.group(3)}"
    return f"{int(first.group(1))}{first.group(2)}"


def supplied_by_others(*texts: Any) -> str | None:
    """The schedule's words saying someone else supplies it, if it says so."""
    for text in texts:
        found = _BY_OTHERS.search(str(text or ""))
        if found:
            return found.group(0)
    return None


@dataclass
class Line:
    """One line to price, with everything the pricer and the estimator need."""

    key: str  # stable across re-prices: set and item, or division and row
    group: str
    division: str
    description: str | None
    part: str | None
    manufacturer: str | None
    finish: str | None
    qty: float | None
    qty_per_opening: float | None = None
    unit: str | None = None
    openings: list[str] = field(default_factory=list)
    text: str = ""  # every other word the legend gave the item: size, options
    source_file: str | None = None
    source_page: int | None = None
    alternate: str | None = None  # why the line is not in the base total, when it is not
    flags: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _text(item: dict[str, Any], *keys: str) -> str:
    return " ".join(str(item.get(k)) for k in keys if item.get(k) not in (None, ""))


def hardware_lines(
    sets: list[dict[str, Any]],
    openings: list[dict[str, Any]],
) -> tuple[list[Line], list[str]]:
    """The door hardware lines, and what was left out and why.

    `sets`: {name, items: [{qty, part, manufacturer, finish, description, ...}],
    source_page}. `openings`: {mark, set, count, source_page}, in scope only -
    `count` is how many doors the row stands for (1 unless the schedule says).
    """
    cited: dict[str, dict[str, Any]] = {}
    for door in openings:  # the take-off's own rows, not extraction's documents
        key = set_key(door.get("set"))
        if key is None:
            continue
        entry = cited.setdefault(key, {"name": str(door["set"]).strip(), "marks": [], "doors": 0.0,
                                       "source_page": door.get("source_page"),
                                       "source_file": door.get("source_file")})
        entry["marks"].append(str(door.get("mark") or "?"))
        entry["doors"] += quantity(door.get("count"))[0] or 1.0
        entry["rated"] = entry.get("rated") or fire_rating.is_rated(door.get("rating"))

    lines: list[Line] = []
    notes: list[str] = []
    seen: set[str] = set()
    for hw_set in sets:
        name = str(hw_set.get("name") or "SET").strip() or "SET"
        key = set_key(name)
        if key not in cited:
            notes.append(f"{name} is in the hardware legend but no opening cites it - not priced")
            continue
        seen.add(key)
        marks, doors = cited[key]["marks"], cited[key]["doors"]
        page = hw_set.get("source_page") or cited[key]["source_page"]
        source_file = hw_set.get("source_file") or cited[key]["source_file"]
        items = [item for item in hw_set.get("items") or [] if isinstance(item, dict)]
        if not items:
            lines.append(Line(
                key=f"{key}:set", group=name, division=DOOR_HARDWARE,
                description=f"Hardware {name} - its items were not read from the legend",
                part=None, manufacturer=None, finish=None, qty=doors, unit="SET",
                openings=marks, source_file=source_file, source_page=page,
                flags=["hardware_set_not_itemised"],
            ))
            continue
        for index, item in enumerate(items, start=1):
            each, unit = quantity(item.get("qty"))
            # The legend's own "supplied by" (landlord, storefront supplier), else its wording.
            party = item.get("by_others")
            others = None if party else supplied_by_others(item.get("notes"), item.get("description"))
            line = Line(
                key=f"{key}:{index:02d}", group=name, division=DOOR_HARDWARE,
                description=item.get("description") or None,
                part=str(item.get("part") or "").strip() or None,
                manufacturer=str(item.get("manufacturer") or "").strip() or None,
                finish=str(item.get("finish") or "").strip() or None,
                qty=round(each * doors, 4) if each is not None else None,
                qty_per_opening=each, unit=unit or "EA", openings=marks,
                text=_text(item, "description", "notes", "size"),
                source_file=item.get("source_file") or source_file,
                source_page=item.get("source_page") or page,
            )
            if each is None:
                line.flags.append("quantity_unread")
            if cited[key].get("rated") and _EXIT_DEVICE.search(f"{line.text} {line.part or ''}"):
                # Panic hardware on a rated door has to be listed fire exit hardware
                # (CBC requirements 6.1): the estimator confirms the part is.
                line.flags.append("fire_exit_hardware_required")
            if party or others:
                line.alternate = (f"supplied by {party} per the legend" if party
                                  else f"the schedule says {others!r} - another party supplies it")
                line.flags.append("supplied_by_others")
            lines.append(line)

    for key, group in cited.items():
        if key not in seen:
            lines.append(Line(
                key=f"{key}:set", group=group["name"], division=DOOR_HARDWARE,
                description=f"Hardware {group['name']} - not in the hardware legend that was read",
                part=None, manufacturer=None, finish=None, qty=group["doors"], unit="SET",
                openings=group["marks"], source_file=group["source_file"],
                source_page=group["source_page"], flags=["hardware_set_not_in_legend"],
            ))
    return lines, notes


def specialty_lines(rows: list[dict[str, Any]]) -> list[Line]:
    """Division 10 and FRP rows: one line each, at the count the schedule gives.

    `rows`: {division, qty, part, manufacturer, description, notes, room,
    source_page}. A row with no count (an FRP run nobody has measured) is a line
    with no quantity - flagged, never priced at one.
    """
    lines: list[Line] = []
    used: set[str] = set()
    for index, row in enumerate(rows, start=1):
        division = str(row.get("division") or "").strip()
        each, unit = quantity(row.get("qty"))
        base = f"{division[:2]}:{row.get('mark') or row.get('part') or index}"
        key, n = base, 2
        while key in used:
            key, n = f"{base}-{n}", n + 1
        used.add(key)
        accessory = division.startswith("10")
        others = supplied_by_others(row.get("notes"), row.get("description"))
        line = Line(
            key=key, group=row.get("room") or ("Division 10" if accessory else "FRP"),
            division=division, description=row.get("description") or row.get("part"),
            part=str(row.get("part") or "").strip() or None,
            manufacturer=str(row.get("manufacturer") or "").strip() or None,
            finish=str(row.get("finish") or "").strip() or None,
            qty=each, qty_per_opening=None, unit=unit or row.get("unit"),
            text=_text(row, "description", "notes"),
            source_file=row.get("source_file"), source_page=row.get("source_page"),
        )
        if each is None:
            line.flags.append("quantity_unread")
        if others:
            line.alternate = f"the schedule says {others!r} - another party supplies it"
            line.flags.append("supplied_by_others")
        lines.append(line)
    return lines


# An exit device by any of the names a legend gives one.
_EXIT_DEVICE = re.compile(
    r"\b(?:EXIT\s+DEVICES?|PANIC|RIM\s+EXIT|MORTISE\s+EXIT|(?:CONCEALED|SURFACE)\s+VERTICAL\s+ROD|CVR|SVR)\b",
    re.I,
)

# The door and its frame, as CBC quotes them (requirements 1.1): hollow metal and
# wood doors, hollow metal frames. Storefront glass and aluminum leaves are out of
# scope already (`scope_rules`); a material the schedule did not give is flagged.
_MATERIALS = {
    "HM": ("hollow metal", "08 11 13"), "STEEL": ("hollow metal", "08 11 13"), "STL": ("hollow metal", "08 11 13"),
    "MTL": ("hollow metal", "08 11 13"), "METAL": ("hollow metal", "08 11 13"),
    "WD": ("wood", "08 14 16"), "WOOD": ("wood", "08 14 16"), "SC": ("wood", "08 14 16"),
    "SCWD": ("wood", "08 14 16"), "HPL": ("plastic laminate faced wood", "08 14 16"),
    "PLAM": ("plastic laminate faced wood", "08 14 16"),
}
# Standard stock sizes end at 4'-0" x 8'-0": a 9-ft door is a vendor quote
# (requirements 5.2 and 7.2), and a leaf over 4'-0" wide is usually a pair.
_TALLEST_STOCK_IN = 96.0
_WIDEST_LEAF_IN = 48.0
_FEET_INCHES = re.compile(r"""^\s*(\d+)\s*'\s*-?\s*(\d+(?:\.\d+)?)?\s*"?\s*$""")


def _inches(value: Any) -> float | None:
    """3'-0" -> 36. A size the schedule printed some other way says nothing here."""
    match = _FEET_INCHES.match(str(value or ""))
    if not match:
        return None
    return int(match.group(1)) * 12 + float(match.group(2) or 0)


def door_and_frame_lines(openings: list[dict[str, Any]]) -> list[Line]:
    """One line per door specification and one per frame specification, each
    naming the doors it covers - the same size, material, type and rating are one
    line, as a door supplier quotes them. `openings`: {mark, count, door_material,
    frame_material, door_type, frame_type, width, height, rating, frame_depth,
    source_page, source_file, undecided}."""
    grouped: dict[str, Line] = {}
    for door in openings:
        width, height = door.get("width"), door.get("height")
        rating = fire_rating.label(door.get("rating"))
        count = quantity(door.get("count"))[0] or 1.0
        for kind in ("door", "frame"):
            written = str(door.get(f"{kind}_material") or "").strip().upper()
            material, division = _MATERIALS.get(written, (None, "08 11 13"))
            if written and material is None:
                continue  # a material CBC does not quote here: aluminum, glass, "by others"
            if kind == "frame" and material and material != "hollow metal":
                continue  # wood and laminate are door faces; CBC's frames are hollow metal
            style = door.get(f"{kind}_type")
            depth = door.get("frame_depth") if kind == "frame" else None
            spec = (material or "material unread", width, height, style, rating, depth)
            key = f"{kind}:" + "|".join(str(part or "") for part in spec)
            line = grouped.get(key)
            if line is None:
                words = [f"{(material or '').upper()} {kind.upper()}".strip(),
                         f"{width} X {height}" if width and height else None,
                         f"TYPE {style}" if style else None,
                         f"{depth} DEPTH" if depth else None,
                         f"{rating} RATED" if rating and rating != "NOT RATED" else None]
                line = grouped[key] = Line(
                    key=key, group=f"{kind.capitalize()}s", division=division,
                    description=", ".join(w for w in words if w), part=None, manufacturer=None,
                    finish=None, qty=0.0, qty_per_opening=1.0, unit="EA",
                    source_file=door.get("source_file"), source_page=door.get("source_page"),
                )
                if material is None:
                    line.flags.append(f"{kind}_material_unread")
                high, wide = _inches(height), _inches(width)
                if high is not None and high > _TALLEST_STOCK_IN:
                    line.flags.append("custom_size")
                if kind == "door" and wide is not None and wide > _WIDEST_LEAF_IN:
                    line.flags.append("pair_check")  # two leaves, or one oversize leaf?
                if rating and rating != "NOT RATED":
                    line.flags.append("fire_rated")
            line.qty = (line.qty or 0) + count
            line.openings.append(str(door.get("mark") or "?"))
            if door.get("undecided") and "scope_undecided" not in line.flags:
                line.flags.append("scope_undecided")
    return list(grouped.values())
