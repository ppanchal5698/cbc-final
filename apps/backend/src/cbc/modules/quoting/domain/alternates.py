"""Alternate groups (FR-14): what an estimator may send, and how a base bid and its
alternates add up.

Requirements 6.4: additive, deductive and substitution alternates, ordered by the
bid form's priority; one base bid plus N alternates, each with its own lines and
total; the base and base-plus-alternate combinations shown; the base quantity,
the alternate quantity and the net difference; overlaps between combinations
checked.

One field says which group a line is in (`alternateGroup`); the group's kind says
what that means:

- additive: its lines are not in the base bid; accepting it adds them.
- deductive: its lines ARE in the base bid - the scope the alternate offers to
  delete - so the base keeps them and the alternate subtracts them.
- substitution: its lines are offered instead of the base lines that name it in
  `deductedBy` (the Allegion part as specified, instead of its Hager equal).
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Literal

from pydantic import BaseModel, Field

from cbc.modules.quoting.domain.ladder import ALLEGION_ALTERNATE, BY_OTHERS_ALTERNATE

PENDING_NOTE = (
    "Still CBC's to confirm (requirements 6.4, Matrix 4.1): how alternates print "
    "today, and whether tax and freight show per alternate - every alternate "
    "figure here is before both."
)

Kind = Literal["additive", "deductive", "substitution"]
KINDS: tuple[str, ...] = ("additive", "deductive", "substitution")


class AlternateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=60, description="e.g. 'Alternate 1'")
    kind: Kind = "additive"
    priority: int | None = Field(default=None, ge=1, le=99, description="its place on the bid form")
    description: str | None = Field(default=None, max_length=300)


class AlternateUpdate(BaseModel):
    kind: Kind | None = None
    priority: int | None = Field(default=None, ge=1, le=99)
    description: str | None = Field(default=None, max_length=300)


def specs(stored: Iterable[dict[str, Any]] | None, names: Iterable[str | None],
          form: Iterable[str] | None = None) -> list[dict[str, Any]]:
    """Every alternate on the bid, with its kind, in the bid form's order.

    `stored` is what the estimator said of each. The rest default: the Allegion
    part as specified is a substitution, any other alternate additive. "Supplied
    by others" is not an alternate at all - it is out of the bid, and the
    proposal says so in its qualifications.
    """
    said = {s["name"]: s for s in stored or () if isinstance(s, dict) and s.get("name")}
    form = [str(n) for n in form or ()]
    found = []
    for name in dict.fromkeys(n for n in names if n and n != BY_OTHERS_ALTERNATE):
        stated = said.get(name) or {}
        found.append({
            "name": name,
            "kind": stated.get("kind") or ("substitution" if name == ALLEGION_ALTERNATE else "additive"),
            "priority": stated.get("priority"),
            "description": stated.get("description"),
        })

    def on_form(spec: dict[str, Any]) -> tuple[int, str]:
        return (form.index(spec["name"]) if spec["name"] in form else len(form), spec["name"].lower())

    # A stated priority keeps its place; the rest take the free places in the bid
    # form's order, then by name.
    taken = {spec["priority"] for spec in found if spec["priority"] is not None}
    free = (place for place in range(1, len(found) + len(taken) + 1) if place not in taken)
    for spec in sorted((s for s in found if s["priority"] is None), key=on_form):
        spec["priority"] = next(free)
    return sorted(found, key=lambda spec: (spec["priority"], *on_form(spec)))


def in_base(alternates: Iterable[dict[str, Any]] | None) -> set[str]:
    """The groups whose lines the base bid counts: the deductive ones."""
    return {a["name"] for a in alternates or () if isinstance(a, dict) and a.get("kind") == "deductive"}


def counts_in_base(line: dict[str, Any], deductive: set[str] | frozenset[str] = frozenset()) -> bool:
    """Whether the base bid includes this line - the one rule for it."""
    return not line.get("alternateGroup") or line["alternateGroup"] in deductive


def _total(lines: Iterable[dict[str, Any]]) -> float:
    return round(sum(float(line.get("extended") or 0) for line in lines), 2)


def _stem(line: dict[str, Any]) -> str:
    """The take-off item a line is, whichever group it is in: `1:01@Alt 1` and
    `1:03:allegion` are `1:01` and `1:03`."""
    return str(line.get("lineKey") or line.get("_id") or "").split("@")[0].removesuffix(":allegion")


def _takeoff(base: list[dict[str, Any]], adds: list[dict[str, Any]],
             removes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Per item the alternate touches: the base quantity, the quantity with the
    alternate accepted, and the difference (requirements 6.4)."""
    rows: dict[str, dict[str, Any]] = {}
    for line in [*removes, *adds]:
        stem = _stem(line)
        named = next((b for b in base if _stem(b) == stem), line)  # the item as the base bid names it
        rows.setdefault(stem, {
            "item": named.get("description") or named.get("part"),
            "baseQty": sum(float(b.get("qty") or 0) for b in base if _stem(b) == stem),
            "removed": 0.0, "added": 0.0,
        })
    for line in removes:
        rows[_stem(line)]["removed"] += float(line.get("qty") or 0)
    for line in adds:
        rows[_stem(line)]["added"] += float(line.get("qty") or 0)
    return [
        {"item": row["item"], "baseQty": row["baseQty"],
         "withAlternateQty": row["baseQty"] - row["removed"] + row["added"],
         "netQty": row["added"] - row["removed"]}
        for row in rows.values()
    ]


def rollup(lines: list[dict[str, Any]], alternates: list[dict[str, Any]]) -> dict[str, Any]:
    """The base bid and each alternate from priced lines (`extended` set), every
    figure before tax and freight.

    `cumulative` accepts the alternates in priority order, as a bid form reads
    them, counting a base line once however many accepted alternates take it out;
    `overlaps` names each base line two alternates both take out - accepted
    together, each alone would overstate the deduction.
    """
    deductive = in_base(alternates)
    base = [line for line in lines if counts_in_base(line, deductive)]
    base_total = _total(base)

    figures, removed_by = [], {}
    for alternate in alternates:
        name, kind = alternate["name"], alternate["kind"]
        adds = [] if kind == "deductive" else [line for line in lines if line.get("alternateGroup") == name]
        if kind == "deductive":
            removes = [line for line in base if line.get("alternateGroup") == name]
        elif kind == "substitution":
            # ponytail: only base lines - a substitution for a line inside another
            # alternate needs both accepted to mean anything, and nothing quotes that yet.
            removes = [line for line in base if name in (line.get("deductedBy") or [])]
        else:
            removes = []
        for line in removes:
            removed_by.setdefault(id(line), (line, []))[1].append(name)
        net = round(_total(adds) - _total(removes), 2)
        figures.append({
            **alternate,
            "added": _total(adds), "deducted": _total(removes), "net": net,
            "withBase": round(base_total + net, 2),
            "complete": all(line.get("extended") is not None for line in [*adds, *removes]),
            "lineIds": [line.get("_id") for line in [*adds, *removes]],
            "takeoff": _takeoff(base, adds, removes),
            "_adds": adds, "_removes": removes,
        })

    cumulative, added, gone = [], 0.0, {}
    for figure in figures:
        added += figure["added"]
        gone.update({id(line): line for line in figure["_removes"]})
        cumulative.append({"through": figure["name"],
                           "total": round(base_total + added - _total(gone.values()), 2)})

    overlaps = [
        {"line": line.get("description") or line.get("part"), "alternates": names}
        for line, names in removed_by.values() if len(names) > 1
    ]
    return {
        "base": base,
        "baseTotal": base_total,
        "alternates": [{k: v for k, v in f.items() if not k.startswith("_")} for f in figures],
        "lines": {f["name"]: {"adds": f["_adds"], "removes": f["_removes"]} for f in figures},
        "cumulative": cumulative,
        "overlaps": overlaps,
    }
