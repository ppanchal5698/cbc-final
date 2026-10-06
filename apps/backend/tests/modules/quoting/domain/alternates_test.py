"""A base bid and its alternates (FR-14, requirements 6.4).

Additive adds its own lines; deductive takes base scope out; a substitution is
offered instead of the base lines that name it. Every combination is computed
from the same priced lines, and a base line two alternates take out is reported,
not deducted twice.
"""
from __future__ import annotations

from cbc.modules.quoting.domain import alternates


def line(key: str, extended: float | None, *, group: str | None = None, qty: float = 1.0,
         replaced_by: list[str] | None = None, description: str | None = None) -> dict:
    return {"_id": key, "lineKey": key, "extended": extended, "qty": qty, "alternateGroup": group,
            "deductedBy": replaced_by or [], "description": description or key}


def test_alternates_default_to_additive_in_the_bid_forms_order() -> None:
    specs = alternates.specs(
        [{"name": "Alt B", "kind": "deductive"}],
        ["Alt C", "Alt B", "Allegion as specified", "Supplied by others", "Alt A", None],
        form=["Alt A", "Alt B"],
    )
    assert [(s["name"], s["kind"], s["priority"]) for s in specs] == [
        ("Alt A", "additive", 1), ("Alt B", "deductive", 2),
        ("Allegion as specified", "substitution", 3), ("Alt C", "additive", 4),
    ]


def test_a_stated_priority_orders_the_alternates() -> None:
    specs = alternates.specs([{"name": "Alt 2", "priority": 1}], ["Alt 1", "Alt 2"], form=["Alt 1", "Alt 2"])
    assert [s["name"] for s in specs] == ["Alt 2", "Alt 1"]


def test_each_kind_adds_up_its_own_way() -> None:
    lines = [
        line("1:01", 100.0),                                   # base
        line("1:02", 50.0, group="Alt 2"),                     # deductive: base scope
        line("1:03", 80.0, replaced_by=["Allegion as specified"]),  # the Hager equal
        line("1:03:allegion", 120.0, group="Allegion as specified"),
        line("1:01@Alt 1", 40.0, group="Alt 1"),               # additive: its own doors
    ]
    specs = alternates.specs([{"name": "Alt 2", "kind": "deductive"}],
                             ["Alt 1", "Alt 2", "Allegion as specified"], form=["Alt 1", "Alt 2"])
    rolled = alternates.rollup(lines, specs)

    assert rolled["baseTotal"] == 230.0  # 100 + 50 (deductive scope stays in) + 80
    by_name = {a["name"]: a for a in rolled["alternates"]}
    assert (by_name["Alt 1"]["net"], by_name["Alt 1"]["withBase"]) == (40.0, 270.0)
    assert (by_name["Alt 2"]["net"], by_name["Alt 2"]["withBase"]) == (-50.0, 180.0)
    # The Allegion part instead of its equal: +120 - 80, not +120 on top of the equal.
    assert (by_name["Allegion as specified"]["net"], by_name["Allegion as specified"]["withBase"]) == (40.0, 270.0)


def test_accepted_in_order_a_line_two_alternates_take_out_counts_once() -> None:
    lines = [
        line("1:01", 100.0),
        line("1:02", 60.0, group="Alt 1", replaced_by=["Alt 2"]),  # deducted by Alt 1, replaced by Alt 2
        line("1:02@sub", 70.0, group="Alt 2"),
    ]
    specs = alternates.specs([{"name": "Alt 1", "kind": "deductive"}, {"name": "Alt 2", "kind": "substitution"}],
                             ["Alt 1", "Alt 2"], form=["Alt 1", "Alt 2"])
    rolled = alternates.rollup(lines, specs)

    assert rolled["baseTotal"] == 160.0
    assert [c["total"] for c in rolled["cumulative"]] == [100.0, 170.0]  # 160 - 60; then + 70, the 60 already out
    assert rolled["overlaps"] == [{"line": "1:02", "alternates": ["Alt 1", "Alt 2"]}]


def test_the_take_off_shows_base_quantity_with_alternate_and_the_difference() -> None:
    lines = [line("1:01", 30.0, qty=6.0, description="HINGE"), line("1:01@Alt 1", 15.0, qty=3.0, group="Alt 1")]
    [alt] = alternates.rollup(lines, alternates.specs([], ["Alt 1"]))["alternates"]
    assert alt["takeoff"] == [{"item": "HINGE", "baseQty": 6.0, "withAlternateQty": 9.0, "netQty": 3.0}]


def test_an_unpriced_alternate_line_leaves_the_alternate_incomplete() -> None:
    [alt] = alternates.rollup([line("1:01@Alt 1", None, group="Alt 1")],
                              alternates.specs([], ["Alt 1"]))["alternates"]
    assert alt["complete"] is False


def test_the_base_counts_a_deductive_alternates_lines() -> None:
    assert alternates.counts_in_base({"alternateGroup": None})
    assert alternates.counts_in_base({"alternateGroup": "Alt 2"}, {"Alt 2"})
    assert not alternates.counts_in_base({"alternateGroup": "Alt 1"}, {"Alt 2"})


def test_a_stated_priority_keeps_its_place_and_the_rest_fill_around_it() -> None:
    specs = alternates.specs([{"name": "Alt 1", "priority": 2}], ["Alt 1", "Alt 2", "Alt 3"],
                             form=["Alt 1", "Alt 2", "Alt 3"])
    assert [(s["name"], s["priority"]) for s in specs] == [("Alt 2", 1), ("Alt 1", 2), ("Alt 3", 3)]
