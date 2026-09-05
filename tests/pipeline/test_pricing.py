"""Pricing tests - the money math, the margin bands, and the tax rules.

Every number a customer sees comes out of calc-engine. If these pass, the
arithmetic on a CBC quote is right; if they fail, quotes are wrong.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import render_quote
from tests.shared import ROOT

BANDS = json.loads(
    (ROOT / "reference-library" / "margins" / "margin_framework.json").read_text(encoding="utf-8")
)


def test_sale_ea_is_cost_over_one_minus_margin(calc):
    line = calc.calculate_line(cost=100.0, margin=0.27)
    assert line["sale_ea"] == 136.99
    assert line["divisor"] == 0.73


def test_ext_is_sale_ea_times_quantity(calc):
    line = calc.calculate_line(cost=74.33, margin=0.27, quantity=3)
    assert line["sale_ea"] == 101.82
    # 74.33 / 0.73 = 101.8219..., and three of those is 305.4657 -> 305.47.
    # This asserted 305.46, the result of multiplying the *rounded* unit price:
    # half a cent of error per unit, scaling with quantity, so the printed
    # extensions did not reconcile against a customer's own arithmetic.
    assert line["ext_price"] == 305.47


@pytest.mark.parametrize(
    "product_type,margin,divisor",
    [
        ("commodity", 0.27, 0.73),
        ("restroom_partitions", 0.35, 0.65),
        ("specialty", 0.40, 0.60),
        ("custom_built", 0.25, 0.75),
        ("accessories", 0.56, 0.44),
    ],
)
def test_every_band_applies_its_own_divisor(calc, product_type, margin, divisor):
    result = calc.apply_margin(cost=100.0, product_type=product_type)
    assert result["default_margin"] == pytest.approx(margin)
    assert result["divisor"] == pytest.approx(divisor, abs=1e-9)
    assert result["sale_ea"] == pytest.approx(round(100.0 / divisor, 2), abs=0.01)


def test_accessories_band_is_56_percent_not_35():
    """Corrected in the 14 Jul session. A silent revert would misprice every accessory."""
    assert BANDS["accessories_derived"] == 0.56


def test_hager_worked_example_end_to_end(calc):
    """List 256.31 x locks tier 0.290 = cost 74.33 -> commodity sale 101.82."""
    cost = round(256.31 * 0.29, 2)
    assert cost == 74.33
    assert calc.apply_margin(cost=cost, product_type="commodity")["sale_ea"] == 101.82


def test_subtotals_and_grand_total_roll_up(calc):
    totals = calc.compute_totals(
        [
            {"group": "Door 01", "ext_price": 305.46},
            {"group": "Door 01", "sale_ea": 100.0, "quantity": 2},
            {"group": "Door 02", "ext_price": 40.0},
            {"group": "Accessories", "ext_price": 60.0},
        ]
    )
    groups = {g["group"]: g["subtotal"] for g in totals["groups"]}
    assert groups["Door 01"] == 505.46
    assert groups["Door 02"] == 40.0
    assert groups["Accessories"] == 60.0
    assert totals["subtotal"] == sum(groups.values()) == 605.46


@pytest.mark.parametrize(
    "state,rate", [("OH", 0.08), ("KY", 0.065), ("LA", 0.0), ("TX", 0.0), ("CA", 0.0)]
)
def test_sales_tax_only_for_ohio_and_kentucky(calc, state, rate):
    totals = calc.compute_totals([{"group": "g", "ext_price": 1000.0}], project_state=state)
    assert totals["tax_rate"] == rate
    assert totals["tax"] == round(1000.0 * rate, 2)
    assert totals["grand_total"] == round(1000.0 * (1 + rate), 2)


def test_unknown_state_leaves_tax_unresolved_rather_than_zero(calc):
    totals = calc.compute_totals([{"group": "g", "ext_price": 1000.0}])
    assert totals["project_state"] is None
    assert "UNRESOLVED" in totals["tax_note"]


def test_freight_is_tbd_at_estimate_stage(calc):
    totals = calc.compute_totals([{"group": "g", "ext_price": 100.0}])
    assert totals["freight"] is None
    assert "TBD" in totals["freight_note"]


def test_below_band_margin_is_flagged_not_blocked(calc):
    check = calc.validate_margin("commodity", 0.20)
    assert check["status"] == "fail"
    assert check["flag"] == "below_band"
    assert "deferred" in check["note"]


def test_override_without_a_reason_is_warned(calc):
    result = calc.apply_margin(cost=100.0, product_type="commodity", override_margin=0.15)
    assert result["overridden"] is True
    assert "warning" in result

    with_reason = calc.apply_margin(
        cost=100.0,
        product_type="commodity",
        override_margin=0.15,
        override_reason="bought via SecLock at higher cost",
    )
    assert "warning" not in with_reason


def test_invalid_inputs_are_rejected(calc):
    with pytest.raises(ValueError):
        calc.calculate_line(cost=100.0, margin=1.0)  # divide by zero
    with pytest.raises(ValueError):
        calc.calculate_line(cost=-1.0, margin=0.27)
    with pytest.raises(ValueError):
        calc.apply_margin(cost=100.0, product_type="not_a_band")


def test_quote_blocks_group_and_subtotal():
    blocks = render_quote.build_blocks(
        [
            {"group": "Door 01", "group_type": "door", "ext_price": 100.0},
            {"group": "Door 01", "group_type": "door", "ext_price": 50.5},
            {"group": "Restroom", "group_type": "accessories", "ext_price": 10.0},
            {"group": "Kitchen", "group_type": "frp", "ext_price": None},
        ]
    )
    assert [b["key"] for b in blocks] == ["door", "accessories", "frp"]
    assert blocks[0]["groups"][0]["subtotal"] == 150.5
    assert blocks[2]["groups"][0]["subtotal"] == 0.0, "an unpriced line must not break the roll-up"


def test_unit_weight_is_gone(calc):
    """Legacy truck-loading column, removed in the 14 Jul session."""
    line = calc.calculate_line(cost=100.0, margin=0.27, quantity=2)
    assert "unit_weight" not in line
    assert "total_weight" not in line


def test_an_adder_goes_on_the_list_price_not_the_cost():
    """The price book states the order outright, and the order is the money.

    "These are LIST adders. Multiply by the same category multiplier as the base
    item to get cost." A Hager 3500 storeroom lock lists at 256.31; the
    anti-microbial option adds 57.13 of *list*, which at the 0.29 lock tier is
    16.57 of cost. Adding it to the cost instead charges the full 57.13 and
    inflates the line by 40.56 before margin.
    """
    from cbc.core.calc import cost_from_list

    result = cost_from_list(256.31, 0.29, [{"name": "Anti-microbial", "list_adder": 57.13}])

    assert result["list_with_adders"] == 313.44
    assert result["cost"] == 90.90
    assert result["cost"] != round(256.31 * 0.29 + 57.13, 2)
    # An adder is a recorded act, so the line has to be able to show it.
    assert result["adders"][0]["cost_effect"] == 16.57


def test_a_line_with_no_adders_is_just_list_times_multiplier():
    from cbc.core.calc import cost_from_list

    assert cost_from_list(256.31, 0.29)["cost"] == round(256.31 * 0.29, 2)


def test_an_unpriced_adder_is_reported_not_treated_as_zero():
    """Only Hager's values are harvested; the rest are outstanding (NR-7).

    A missing adder must not read as "no adder" - that silently underprices.
    """
    from cbc.services.reference_library import find_adders

    result = find_adders(["Anti-microbial (26D finish only)", "electrification"])
    assert [m["list_adder"] for m in result["matched"]] == [57.13]
    assert result["unpriced"] == ["electrification"]


def test_both_finish_nomenclatures_read_the_same_finish():
    """A schedule mixes them: US26D, 626 and a bare 26D are one satin (NR-3)."""
    from cbc.services.reference_library import resolve_finish

    for spelling in ("US26D", "626", "26D", "us26d"):
        assert resolve_finish(spelling)["us_code"] == "US26D"


def test_us19_is_never_read_as_us26d():
    """They are different satins. A lockset in the wrong one is a return."""
    from cbc.services.reference_library import resolve_finish

    assert resolve_finish("US19")["us_code"] == "US19"
    assert resolve_finish("US19")["description"] != resolve_finish("US26D")["description"]


def test_a_numeric_two_finishes_share_is_flagged_not_guessed():
    """619 is US19 and US15 in CBC's own crosswalk.

    Picking whichever is listed first is exactly the confusion the crosswalk
    exists to prevent, so it comes back ambiguous with both candidates.
    """
    from cbc.services.reference_library import resolve_finish

    result = resolve_finish("619")
    assert result["ambiguous"] is True
    assert set(result["candidates"]) == {"US19", "US15"}


def test_normalize_finish_stores_canonical_pair():
    """Import stores US + BHMA together so either spelling matches later (NR-3)."""
    from cbc.services.reference_library import normalize_finish_value

    for spelling in ("US26D", "626", "26D"):
        result = normalize_finish_value(spelling)
        assert result["value"] == "US26D (626)"
        assert result["flags"] == []


def test_normalize_finish_keeps_ambiguous_raw_and_flags():
    from cbc.services.reference_library import normalize_finish_value

    result = normalize_finish_value("619")
    assert result["value"] == "619"
    assert "finish_ambiguous" in result["flags"]


def test_normalize_finish_flags_unrecognized():
    from cbc.services.reference_library import normalize_finish_value

    result = normalize_finish_value("NOT-A-FINISH")
    assert result["value"] == "NOT-A-FINISH"
    assert "finish_unrecognized" in result["flags"]


def test_normalize_finish_null_stays_null():
    from cbc.services.reference_library import normalize_finish_value

    assert normalize_finish_value(None) == {"value": None, "flags": []}
    assert normalize_finish_value("  ") == {"value": None, "flags": []}


def _lite_kits():
    import json

    from tests.shared import ROOT

    path = ROOT / "reference-library" / "adders" / "lite_kit_prices.json"
    if not path.exists():
        pytest.skip("run scripts/extract_lite_kits.py to build the lite-kit table")
    return json.load(path.open(encoding="utf-8"))


def test_lite_kit_lookup_matches_known_cell():
    from cbc.core.calc import lookup_lite_kit_list_price

    result = lookup_lite_kit_list_price(12, 12, pdf_page=30)
    assert result["list_price"] == 78
    assert result["width_used"] == 12
    assert result["height_used"] == 12


def test_the_lite_kit_grid_matches_the_printed_page():
    """Cells read by hand off page 30 of the National Guard list (NR-8).

    The grid is read by right edge, because the numbers are right-aligned: a
    two-digit price starts about a digit further right than a three-digit one,
    and matching left edges silently shifts a whole column. NGP really does
    print 95 at 10x10 and 78 at 12x12 while the neighbours run 113-143 - those
    are the catalog's numbers and reproducing them faithfully is the job.
    """
    table = next(t for t in _lite_kits()["tables"] if t["pdf_page"] == 30)
    assert table["widths"] == [6, 8, 10, 12, 14, 16, 18, 20, 22, 24, 26, 28, 30, 32, 34, 36]

    row10 = [table["prices"]["10"].get(str(w)) for w in table["widths"]]
    assert row10 == [113, 113, 95, 143, 149, 149, 157, 173, 177, 181, 183, 193, 193, 193, 197, 197]
    assert table["prices"]["12"]["12"] == 78


def test_no_column_header_was_read_as_a_price():
    """Three pages carry a second width header below the first.

    It reads as a data row whose "prices" are the widths themselves - 8 under
    width 8, 12 under width 12 - and contributed 38 cells that were column
    labels wearing a price before the filter caught them.
    """
    for table in _lite_kits()["tables"]:
        for height, row in table["prices"].items():
            echoes = sum(1 for width, value in row.items() if str(value) == str(width))
            assert echoes < max(3, len(row) // 2), (
                f"page {table['pdf_page']} height {height} looks like a header row"
            )


def test_every_lite_kit_price_is_plausible():
    """A lite kit is not eight dollars. The low outliers were header rows."""
    values = [v for t in _lite_kits()["tables"] for r in t["prices"].values() for v in r.values()]
    assert values, "no prices extracted"
    assert min(values) >= 60, f"implausible low price: {min(values)}"


def test_the_option_rules_survive_their_line_wrapping():
    """The rules are the adders, and the PDF wraps them mid-sentence.

    "Mullion Bars available ... -" continues on the next line with "price of
    Lite Kit plus $236 per Mullion Bar"; the money is on the continuation.
    """
    table = next(t for t in _lite_kits()["tables"] if t["pdf_page"] == 30)
    joined = " | ".join(table["rules"])
    assert "$236 per Mullion Bar" in joined
    assert "$11.00 per perimeter inch" in joined


# A bad number must never reach a customer as a confident one. Each of these
# returned `priced: True` before: a null quantity as $0, a nan cost as nan all
# the way into grandTotal, and an inf cost as an uncaught ArithmeticError that
# took down the whole quote screen because reprice loops every line.
@pytest.mark.parametrize(
    "label,kwargs",
    [
        ("null quantity", {"cost": 100.0, "margin": 0.27, "qty": None}),
        ("infinite cost", {"cost": float("inf"), "margin": 0.27, "qty": 1}),
        ("nan cost", {"cost": float("nan"), "margin": 0.27, "qty": 1}),
        ("nan quantity", {"cost": 100.0, "margin": 0.27, "qty": float("nan")}),
        ("negative quantity", {"cost": 100.0, "margin": 0.27, "qty": -2}),
    ],
)
def test_an_unusable_number_is_reported_unpriced_not_valued(label, kwargs):
    from cbc.services.pricing import price_line

    line = price_line(**kwargs)
    assert line["priced"] is False, f"{label} was priced anyway: {line}"
    assert line["sell"] is None and line["extended"] is None, line
    assert line.get("error"), f"{label} gives the estimator no reason: {line}"


def test_a_good_line_still_prices():
    """The guard above must not have made every line unpriceable."""
    from cbc.services.pricing import price_line

    assert price_line(cost=100.0, margin=0.27, qty=3)["priced"] is True


def test_the_extension_is_rounded_once_not_twice():
    """A line extension must equal the arithmetic, not the rounded unit times qty.

    sale_ea was rounded to cents and *then* multiplied, so every unit carried up
    to half a cent of error and it scaled linearly with quantity. 74.33 at 27%
    over three units extended to 305.46 where 74.33/0.73*3 is 305.47 - and the
    calc-engine self-test asserted the wrong value, pinning it in place.
    """
    from decimal import ROUND_HALF_UP, Decimal

    from cbc.core.calc import calculate_line

    for cost, margin, quantity in [(74.33, 0.27, 3), (12.01, 0.35, 17), (9.99, 0.56, 40)]:
        line = calculate_line(cost=cost, margin=margin, quantity=quantity)
        exact = (Decimal(str(cost)) / Decimal(str(1 - margin))) * Decimal(str(quantity))
        expected = float(exact.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
        assert line["ext_price"] == expected, (cost, margin, quantity, line["ext_price"])

    # The per-unit figure an estimator reads is still whole cents.
    single = calculate_line(cost=74.33, margin=0.27, quantity=1)
    assert single["sale_ea"] == 101.82
    assert single["ext_price"] == 101.82
