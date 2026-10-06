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
from dataclasses import dataclass, field, replace
from typing import Any

from cbc.modules.quoting.domain import frp
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
    # Who supplies it, never who installs it: CBC supplies, others install. A bare
    # "by owner" is left alone - "color selected by owner" says nothing of supply.
    r"\b(?:OFCI|O\.F\.C\.I|OFOI|O\.F\.O\.I|N\.I\.C|NIC|BY\s+OTHERS"
    r"|(?:OWNER|TENANT|LANDLORD)[\s-]+(?:FURNISHED|SUPPLIED|PROVIDED)"
    r"|(?:PROVIDED|FURNISHED|SUPPLIED)\s+BY\s+(?:THE\s+)?(?:OWNER|TENANT|LANDLORD|G\.?C|GENERAL\s+CONTRACTOR)"
    r"|(?:OWNER|TENANT|LANDLORD)\s+TO\s+(?:FURNISH|SUPPLY|PROVIDE)"
    r"|(?:PROVIDED|FURNISHED|SUPPLIED)\s+UNDER\s+SEPARATE\s+CONTRACT"
    # Hardware already on the door is not CBC's to supply either.
    r"|EXISTING\s+TO\s+(?:REMAIN|BE\s+RE-?USED)|RE-?USE\s+(?:THE\s+)?EXISTING)\b",
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


# Another party named without saying it supplies the item: "power supply by Div
# 28" may be the wiring, "cores by owner" the cores. A person or the model
# (classify_supply) reads these; "color selected by owner" is nobody's supply.
_OTHER_PARTY = re.compile(
    r"\bBY\s+(?:THE\s+)?(?:OWNER|TENANT|LANDLORD|G\.?C\b|GENERAL\s+CONTRACTOR|ELEC(?:TRICAL\b|\.)|SECURITY"
    r"|ACCESS\s+CONTROL|(?:FIRE\s+)?ALARM|DIV(?:ISION|\.)?\s*(?:2[5-8]|1[0-4])\b|OTHER\s+TRADES?)"
    r"|\bUNDER\s+SEPARATE\s+CONTRACT\b|\bOFE\b",
    re.I,
)
_JUDGED = re.compile(r"\b(?:SELECTED|APPROVED|CHOSEN|VERIFIED|DETERMINED|CONFIRMED|DIRECTED)\s*$", re.I)


def supply_unclear(*texts: Any) -> str | None:
    """The words naming another party when they do not say who supplies it."""
    for text in texts:
        text = str(text or "")
        for found in _OTHER_PARTY.finditer(text):
            if not _JUDGED.search(text[: found.start()]):
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
    # The bid alternate its doors are in (FR-14): their own line, never the base's.
    alternate_group: str | None = None
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
    source_page}. `openings`: {mark, set, count, source_page, alternate_group}, in
    scope only - `count` is how many doors the row stands for (1 unless the
    schedule says). Doors in a bid alternate are their own lines, keyed `@` the
    alternate, so the base keeps only the base's doors (FR-14).
    """
    cited: dict[tuple[str, str | None], dict[str, Any]] = {}
    for door in openings:  # the take-off's own rows, not extraction's documents
        key = set_key(door.get("set"))
        if key is None:
            continue
        group = door.get("alternate_group") or None
        entry = cited.setdefault((key, group), {"name": str(door["set"]).strip(), "marks": [], "doors": 0.0,
                                                "source_page": door.get("source_page"),
                                                "source_file": door.get("source_file")})
        entry["marks"].append(str(door.get("mark") or "?"))
        entry["doors"] += quantity(door.get("count"))[0] or 1.0
        entry["rated"] = entry.get("rated") or fire_rating.is_rated(door.get("rating"))
        entry["smoke"] = entry.get("smoke") or bool(door.get("smoke"))
        note = str(door.get("notes") or "").strip()
        if note:
            entry.setdefault("said", {}).setdefault(note, []).append(str(door.get("mark") or "?"))

    lines: list[Line] = []
    notes: list[str] = []
    seen: set[str] = set()
    for hw_set in sets:
        name = str(hw_set.get("name") or "SET").strip() or "SET"
        key = set_key(name)
        groups = [group for (cited_key, group) in cited if cited_key == key]
        if not groups:
            notes.append(f"{name} is in the hardware legend but no opening cites it - not priced")
            continue
        seen.add(key)
        for group in groups:
            lines += _set_lines(hw_set, name, key, group, cited[(key, group)])

    for (key, group), entry in cited.items():
        if key not in seen:
            lines.append(Line(
                key=_keyed(f"{key}:set", group), group=entry["name"], division=DOOR_HARDWARE,
                # The customer reads the description; why it is priced by hand is the flag's.
                description=f"Hardware {entry['name']} as scheduled",
                part=None, manufacturer=None, finish=None, qty=entry["doors"], unit="SET",
                openings=entry["marks"], source_file=entry["source_file"],
                source_page=entry["source_page"], alternate_group=group, flags=["hardware_set_not_in_legend"],
                # Priced by hand: what the schedule says the doors need is the brief.
                text=_said(entry.get("said") or {}),
            ))
    return lines, notes


def _keyed(key: str, alternate: str | None) -> str:
    """A line's key in its alternate: stable across re-prices, apart from the base's."""
    return f"{key}@{alternate}" if alternate else key


def _set_lines(hw_set: dict[str, Any], name: str, key: str, group: str | None,
               cited: dict[str, Any]) -> list[Line]:
    """The lines of one hardware set, for the doors of one group that cite it."""
    marks, doors = cited["marks"], cited["doors"]
    page = hw_set.get("source_page") or cited["source_page"]
    source_file = hw_set.get("source_file") or cited["source_file"]
    items = [item for item in hw_set.get("items") or [] if isinstance(item, dict)]
    if not items:
        return [Line(
            key=_keyed(f"{key}:set", group), group=name, division=DOOR_HARDWARE,
            description=f"Hardware {name} as scheduled",
            part=None, manufacturer=None, finish=None, qty=doors, unit="SET",
            openings=marks, source_file=source_file, source_page=page, alternate_group=group,
            flags=["hardware_set_not_itemised"], text=_said(cited.get("said") or {}),
        )]
    lines: list[Line] = []
    for index, item in enumerate(items, start=1):
        each, unit = quantity(item.get("qty"))
        # The legend's own "supplied by" (landlord, storefront supplier), else its wording.
        party = item.get("by_others")
        others = None if party else supplied_by_others(item.get("notes"), item.get("description"))
        line = Line(
            key=_keyed(f"{key}:{index:02d}", group), group=name, division=DOOR_HARDWARE,
            description=item.get("description") or None,
            part=str(item.get("part") or "").strip() or None,
            manufacturer=str(item.get("manufacturer") or "").strip() or None,
            finish=str(item.get("finish") or "").strip() or None,
            qty=round(each * doors, 4) if each is not None else None,
            qty_per_opening=each, unit=unit or "EA", openings=marks,
            text=_text(item, "description", "notes", "size"),
            source_file=item.get("source_file") or source_file,
            source_page=item.get("source_page") or page,
            alternate_group=group,
        )
        if each is None:
            line.flags.append("quantity_unread")
        if cited.get("rated") and _EXIT_DEVICE.search(f"{line.text} {line.part or ''}"):
            # Panic hardware on a rated door has to be listed fire exit hardware
            # (CBC requirements 6.1): the estimator confirms the part is.
            line.flags.append("fire_exit_hardware_required")
        if cited.get("smoke") and _GASKETING.search(f"{line.text} {line.part or ''}"):
            line.flags.append("smoke_label")  # a smoke door's seals are listed for smoke (6.1)
        if party or others:
            line.alternate = (f"supplied by {party} per the legend" if party
                              else f"the schedule says {others!r} - another party supplies it")
            line.flags.append("supplied_by_others")
        elif supply_unclear(item.get("notes"), item.get("description")):
            line.flags.append("supply_unclear")
        lines.append(line)
    if cited.get("smoke") and lines and not any("smoke_label" in line.flags for line in lines):
        # A smoke-labeled door needs listed seals, and this set names none.
        lines[0].flags.append("smoke_gasketing_missing")
    if cited.get("rated") and lines:
        # Requirements 6.1, rules 2 and 3: rated doors take listed hardware, and the
        # library records no listings - so the set says it once, for a person to confirm.
        next((line for line in lines if not line.alternate), lines[0]).flags.append("rated_set")
    return lines


def specialty_lines(rows: list[dict[str, Any]], frp_constants: dict[str, Any] | None = None) -> list[Line]:
    """Division 10 and FRP rows: one line each, at the count the schedule gives.

    `rows`: {division, qty, part, manufacturer, description, notes, room,
    source_page, geometry}. A row with no count (an FRP run nobody has measured) is
    a line with no quantity - flagged, never priced at one. A measured FRP area,
    once CBC's conversion constants are set, is the panels, adhesive and trim it
    takes (FR-12).
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
            alternate_group=row.get("alternate_group") or None,
        )
        if each is None:
            line.flags.append("quantity_unread")
        if others:
            line.alternate = f"the schedule says {others!r} - another party supplies it"
            line.flags.append("supplied_by_others")
        elif supply_unclear(row.get("notes"), row.get("description")):
            line.flags.append("supply_unclear")
        converted = frp.convert(row["geometry"], frp_constants) if row.get("geometry") and frp_constants else None
        lines += _frp_lines(line, converted, frp_constants) if converted else [line]
    return lines


# What one measured FRP area takes, in the order an estimator lists it.
_FRP_ITEMS = (
    ("panels", "FRP PANEL {size}"), ("adhesive", "FRP ADHESIVE"),
    ("insideCornerSticks", "INSIDE CORNER TRIM"), ("outsideCornerSticks", "OUTSIDE CORNER TRIM"),
    ("dividerSticks", "DIVIDER BAR"), ("capSticks", "CAP TRIM"),
)


def _frp_lines(line: Line, converted: dict[str, Any], constants: dict[str, Any]) -> list[Line]:
    """One measured FRP area as its materials, each saying what it was computed from."""
    basis = (f"{converted['netSqft']:g} SF net; panel {constants['panel_size']}, waste {constants['waste_pct']}, "
             f"trim in {constants['trim_stick_length']:g} ft sticks")
    out = []
    for field_name, name in _FRP_ITEMS:
        count = converted[field_name]
        if not count:
            continue
        item = name.format(size=str(constants["panel_size"]).upper())
        out.append(replace(
            line, key=f"{line.key}:{field_name}",
            description=f"{item} - {line.description}" if line.description else item,
            part=None, qty=float(count), unit="EA", text=f"{line.text} {basis}".strip(),
            openings=list(line.openings), notes=[basis],
            flags=[*(f for f in line.flags if f != "quantity_unread"), "frp_converted"],
        ))
    return out


# What seals a door for smoke: gasketing, seals, a sweep or an astragal.
_GASKETING = re.compile(r"\b(?:GASKET\w*|SEALS?|SMOKE\s+SEAL|SWEEP|ASTRAGAL|DOOR\s+BOTTOM)\b", re.I)

# An exit device by any of the names a legend gives one.
_EXIT_DEVICE = re.compile(
    r"\b(?:EXIT\s+DEVICES?|PANIC|RIM\s+EXIT|MORTISE\s+EXIT|(?:CONCEALED|SURFACE)\s+VERTICAL\s+ROD|CVR|SVR)\b",
    re.I,
)

# The door and its frame, as CBC quotes them (requirements 1.1): hollow metal and
# wood doors, hollow metal frames. Storefront glass and aluminum leaves are out of
# scope already (`scope_rules`); a material the schedule did not give is flagged.
# Every material `scope_rules.IN_SCOPE_MATERIALS` puts in scope, as a line describes it.
_MATERIALS = {
    **dict.fromkeys(("HM", "HMD", "ST", "STL", "STEEL", "MTL", "METAL"), ("hollow metal", "08 11 13")),
    **dict.fromkeys(("WD", "W", "WOOD", "SC", "SCWD", "HC"), ("wood", "08 14 16")),
    **dict.fromkeys(("HPL", "PL", "P.LAM", "PLAM"), ("plastic laminate faced wood", "08 14 16")),
    "FRP": ("FRP", "08 16 13"),  # fiberglass doors - Special-Lite is a phase 1 door vendor
}
# Standard stock sizes end at 4'-0" x 8'-0": a 9-ft door is a vendor quote
# (requirements 5.2 and 7.2), and a leaf over 4'-0" wide is usually a pair.
_TALLEST_STOCK_IN = 96.0
_WIDEST_LEAF_IN = 48.0
_FEET_INCHES = re.compile(r"""^\s*(\d+)\s*'\s*-?\s*(\d+(?:\.\d+)?)?(?:\s+(\d+)/(\d+))?\s*"?\s*$""")


def _inches(value: Any) -> float | None:
    """3'-0" -> 36, 5'-7 1/2" -> 67.5. A size the schedule printed some other way
    says nothing here."""
    match = _FEET_INCHES.match(str(value or ""))
    if not match:
        return None
    fraction = int(match.group(3)) / int(match.group(4)) if match.group(4) and int(match.group(4)) else 0.0
    return int(match.group(1)) * 12 + float(match.group(2) or 0) + fraction


def door_and_frame_lines(openings: list[dict[str, Any]]) -> list[Line]:
    """One line per door specification and one per frame specification, each
    naming the doors it covers - the same size, material, type and rating are one
    line, as a door supplier quotes them. `openings`: {mark, count, door_material,
    frame_material, door_type, frame_type, width, height, rating, frame_depth,
    source_page, source_file, undecided, smoke, no_hose_stream, temperature_rise}."""
    grouped: dict[str, Line] = {}
    door_notes: dict[str, dict[str, list[str]]] = {}  # line key -> the schedule's note -> its doors
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
            # A temperature-rise door is another door to its supplier (requirements 6.1).
            rise = kind == "door" and bool(door.get("temperature_rise"))
            spec = (material or "material unread", width, height, style, rating, depth) + (("TEMP RISE",) if rise else ())
            group = door.get("alternate_group") or None
            key = _keyed(f"{kind}:" + "|".join(str(part or "") for part in spec), group)
            line = grouped.get(key)
            if line is None:
                words = [f"{(material or '').upper()} {kind.upper()}".strip(),
                         f"{width} X {height}" if width and height else None,
                         f"TYPE {style}" if style else None,
                         f"{depth} DEPTH" if depth else None,
                         f"{rating} RATED" if rating and rating != "NOT RATED" else None,
                         "TEMPERATURE RISE" if rise else None]
                line = grouped[key] = Line(
                    key=key, group=f"{kind.capitalize()}s", division=division,
                    description=", ".join(w for w in words if w), part=None, manufacturer=None,
                    finish=None, qty=0.0, qty_per_opening=1.0, unit="EA",
                    source_file=door.get("source_file"), source_page=door.get("source_page"),
                    alternate_group=group,
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
                if rise:
                    line.flags.append("temperature_rise")
            # Requirements 6.1: the S label is the door's and the frame's, and a
            # 20-minute door tested without hose stream is the door's listing.
            for said, flag in ((door.get("smoke"), "smoke_label"),
                               (door.get("no_hose_stream") and kind == "door", "no_hose_stream")):
                if said and flag not in line.flags:
                    line.flags.append(flag)
            line.qty = (line.qty or 0) + count
            line.openings.append(str(door.get("mark") or "?"))
            note = str(door.get("notes") or "").strip()
            if note:
                door_notes.setdefault(key, {}).setdefault(note, []).append(str(door.get("mark") or "?"))
            if door.get("undecided") and "scope_undecided" not in line.flags:
                line.flags.append("scope_undecided")
    # What the schedule says of these doors - "GLASS PROVIDED BY GC", "PRE-HUNG IN
    # FRAME" - goes to whoever prices them from the supplier.
    for key, notes in door_notes.items():
        grouped[key].text = _said(notes)
    return list(grouped.values())


def _said(notes: dict[str, list[str]]) -> str:
    """What the schedule says of these doors: "doors 1, 2: DOOR PRE-HUNG IN FRAME"."""
    return "; ".join(f"door{'s' if len(marks) > 1 else ''} {', '.join(marks)}: {note}"
                     for note, marks in notes.items())
