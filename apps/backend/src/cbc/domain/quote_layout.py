"""How a quotation is laid out for a customer. One implementation.

FR-7: *a draft quote grouped by door with subtotals, a separate
restroom-accessories block, and a freight line.*

There were two renderers feeding one template, and they disagreed.
`generate-quotation/scripts/render_quote.py` grouped by door, as FR-7 asks. The
API path - the one behind `/render` and `/pdf`, which is what a customer actually
receives - collapsed each section into a single group named after the section, so
"grouped by door with subtotals" was true only of the path nobody sees.

It also dropped `substitution_note`. `_render_proposal_html` built each line dict
by hand and simply had no key for it, so a direct equal printed as the substituted
part with no mention that it was a substitution - while
`.claude/rules/accuracy-trust.md` requires the note "naming what was specified and
what is being offered instead" on every one. The template has always had a place
to print it; the API path never gave it one.

This module is that layout, once. Both callers normalise their own line shape
into `Line` and get the same document back.
"""
from __future__ import annotations

from typing import Any, Iterable

# Order is the order they print in. `other` exists because a division nobody
# mapped should appear at the end of the quote, not vanish from it.
SECTIONS: tuple[tuple[str, str], ...] = (
    ("door", "Doors, Frames & Hardware"),
    ("accessories", "Restroom Accessories & Washroom Equipment"),
    ("frp", "FRP Wall Panels"),
    ("other", "Other"),
)

SECTION_TITLES = dict(SECTIONS)


def section_of(division: str | None, group_type: str | None = None) -> str:
    """Which block a line belongs in.

    `group_type` is what the pricing pass declares; `division` is the CSI code.
    The declared type wins, because a Division 10 hand dryer priced as an
    accessory is an accessory whatever its code says.
    """
    if group_type in SECTION_TITLES:
        return group_type
    if not division:
        return "door"
    code = str(division).strip()
    if code.startswith("10"):
        return "accessories"
    if code.startswith("06"):
        return "frp"
    if code.startswith("08"):
        return "door"
    return "other"


def _money(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def blocks(lines: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sections in print order, each grouped by door, each group subtotalled.

    A line's `group` is the door it belongs to. Lines with no group - freight,
    a standalone accessory - fall into a group named for the section, which is
    the FR-7 shape too: the accessories block is one block, not one block per
    accessory.
    """
    out: list[dict[str, Any]] = []
    for key, title in SECTIONS:
        groups: dict[str, dict[str, Any]] = {}
        for line in lines:
            if section_of(line.get("division"), line.get("group_type")) != key:
                continue
            name = line.get("group") or title
            group = groups.setdefault(
                name,
                {
                    "name": name,
                    "opening_size": line.get("opening_size"),
                    "lines": [],
                    "subtotal": 0.0,
                },
            )
            group["lines"].append(line)
            group["subtotal"] = round(group["subtotal"] + _money(line.get("ext_price")), 2)
        if not groups:
            continue
        ordered = [groups[name] for name in sorted(groups)]
        out.append(
            {
                "key": key,
                "title": title,
                "groups": ordered,
                "lines": [line for group in ordered for line in group["lines"]],
                "subtotal": round(sum(group["subtotal"] for group in ordered), 2),
            }
        )
    return out


def line(
    *,
    description: str | None,
    part_number: str | None = None,
    quantity: Any = None,
    sale_ea: Any = None,
    ext_price: Any = None,
    group: str | None = None,
    group_type: str | None = None,
    division: str | None = None,
    substitution_note: str | None = None,
    opening_size: str | None = None,
    cost: Any = None,
    margin: Any = None,
    flags: list[str] | None = None,
    price_status: str | None = None,
) -> dict[str, Any]:
    """One printable line, in the shape the template reads.

    Keeping the constructor here means a caller cannot quietly omit a field the
    template knows how to print - which is exactly how the substitution note went
    missing from the customer-facing path.
    """
    return {
        "description": description or "",
        "part_number": part_number,
        "quantity": quantity,
        "sale_ea": sale_ea,
        "ext_price": ext_price,
        "group": group,
        "group_type": group_type,
        "division": division,
        "substitution_note": substitution_note,
        "opening_size": opening_size,
        "cost": cost,
        "margin": margin,
        "flags": flags or [],
        "price_status": price_status,
    }
