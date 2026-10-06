"""A bid's special margin is applied in code: customer, then brand, then the band.

It was a reference tool the pricing agent was told to call and did not have, so
whether a Wendys line got its margin depended on a model remembering to look.
"""
from __future__ import annotations

import json

import pytest

import cbc.shared.storage as storage_mod
from cbc.modules.pricing.api import preprice, pricing, reference_calc, reference_library

TABLE = {
    "customers": [
        {"name": "Wendys", "margin": 0.20},
        {"name": "Acme Builders", "margin": 0.18},
        {"name": "Cava", "margin": None},
    ]
}


@pytest.fixture(autouse=True)
def special_margins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(reference_library, "load_special_margins", lambda: TABLE)


def test_the_customer_margin_beats_the_brand_margin() -> None:
    assert pricing.special_margin("Acme Builders", "Wendys") == (0.18, "special customer margin: Acme Builders")


def test_the_brand_margin_applies_when_the_customer_has_none() -> None:
    assert pricing.special_margin("Nobody Inc", "wendys") == (0.20, "special brand margin: Wendys")


def test_the_account_is_found_however_the_bid_spells_it() -> None:
    assert pricing.special_margin(None, "Wendy's") == (0.20, "special brand margin: Wendys")
    assert pricing.special_margin("ACME BUILDERS", None) == (0.18, "special customer margin: Acme Builders")
    assert pricing.special_margin("", "") is None


def test_a_margin_cbc_has_not_given_is_never_invented() -> None:
    assert pricing.special_margin(None, "Cava") is None
    assert pricing.special_margin(None, None) is None


def test_preprice_prices_a_brand_bid_at_its_special_margin(tmp_path, monkeypatch) -> None:
    root = tmp_path / "projects" / "wendys_bid"
    (root / "extracted").mkdir(parents=True)
    (root / "extracted" / "hardware_sets.json").write_text(
        json.dumps({"hardware_sets": [{"set_id": "HW-1", "source_page": 4, "items": [{"part_number": "BB1191", "manufacturer": "Hager", "quantity": 1}]}]}),
        encoding="utf-8",
    )
    (root / "extracted" / "scope_metadata.json").write_text(json.dumps({"brand": "Wendys", "gc": "Other GC"}), encoding="utf-8")
    monkeypatch.setattr(storage_mod, "project_dir", lambda s: tmp_path / "projects" / s)
    monkeypatch.delenv("P21_BASE_URL", raising=False)
    # A P21 hit is enough to price the line; the margin is what is under test.
    monkeypatch.setattr(
        preprice, "_apply_ladder", lambda line, item, client: preprice._set_cost(line, 80.0, "P21_LAST_PO", "PO 2026-09-01")
    )

    preprice.seed_line_items("wendys_bid")
    line = json.loads((root / "priced" / "line_items.json").read_text(encoding="utf-8"))["lines"][0]
    assert line["margin"] == 0.20
    assert line["sale_ea"] == 100.0  # 80 / (1 - 0.20)
    assert line["margin_override_reason"] == "special brand margin: Wendys"


def test_the_calc_engine_applies_it_without_being_told_the_number() -> None:
    result = reference_calc.apply_margin(80.0, "commodity", brand="Wendys")
    assert result["margin"] == 0.20
    assert result["override_reason"] == "special brand margin: Wendys"
    assert reference_calc.apply_margin(80.0, "commodity", override_margin=0.30, brand="Wendys")["margin"] == 0.30
