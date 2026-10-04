"""W4: deterministic priced/line_items.json seed - the cost ladder, no LLM."""
from __future__ import annotations

import json

import cbc.shared.storage as storage_mod
from cbc.modules.pricing.api import preprice


def _seed_bid(tmp_path, monkeypatch, items, *, set_id="HW-1"):
    slug = "demo_bid"
    root = tmp_path / "projects" / slug
    (root / "extracted").mkdir(parents=True)
    (root / "priced").mkdir(parents=True)
    (root / "extracted" / "hardware_sets.json").write_text(
        json.dumps({"hardware_sets": [{"set_id": set_id, "source_page": 4, "items": items}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(storage_mod, "project_dir", lambda s: tmp_path / "projects" / s)
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "projects"))
    monkeypatch.delenv("P21_BASE_URL", raising=False)
    return slug, root


def _lines(root):
    return json.loads((root / "priced" / "line_items.json").read_text(encoding="utf-8"))["lines"]


def test_seed_writes_one_line_per_item_with_unique_ids(tmp_path, monkeypatch) -> None:
    slug, root = _seed_bid(
        tmp_path,
        monkeypatch,
        [
            {"part_number": "010108", "manufacturer": "Hager", "quantity": 2},
            {"part_number": "011234", "manufacturer": "Hager", "quantity": 1},
        ],
    )
    result = preprice.seed_line_items(slug)
    assert result["written"]
    lines = _lines(root)
    assert len(lines) == 2
    ids = [line["line_id"] for line in lines]
    assert ids == ["HW-1-00", "HW-1-01"]
    assert len(set(ids)) == len(ids), "line_id must be unique - a dupe lands a price on the wrong row"


def test_the_envelope_carries_the_source_stamp(tmp_path, monkeypatch) -> None:
    slug, root = _seed_bid(tmp_path, monkeypatch, [{"part_number": "010108", "manufacturer": "Hager"}])
    preprice.seed_line_items(slug)
    payload = json.loads((root / "priced" / "line_items.json").read_text(encoding="utf-8"))
    assert payload["source"] == preprice.SOURCE


def test_allegion_is_manual_with_null_cost(tmp_path, monkeypatch) -> None:
    slug, root = _seed_bid(tmp_path, monkeypatch, [{"part_number": "98", "manufacturer": "Von Duprin"}])
    preprice.seed_line_items(slug)
    line = _lines(root)[0]
    assert line["cost"] is None
    assert line["cost_source"] == "DISTRIBUTOR_MANUAL"
    assert any("allegion" in str(f) for f in line["flags"])


def test_a_line_with_no_cost_is_manual_needs_judgment(tmp_path, monkeypatch) -> None:
    slug, root = _seed_bid(tmp_path, monkeypatch, [{"description": "unmatched item", "quantity": 1}])
    preprice.seed_line_items(slug)
    line = _lines(root)[0]
    assert line["cost"] is None
    assert line["price_status"] == "NEEDS_JUDGMENT"
    assert line["cost_source"] == "MANUAL"


def test_the_seeded_file_passes_check_pricing_with_no_llm(tmp_path, monkeypatch) -> None:
    """The W4 gate: check_pricing returns zero problems against the seeded file."""
    from cbc.modules.extraction.api.validation.artifacts import check_pricing

    slug, root = _seed_bid(
        tmp_path,
        monkeypatch,
        [
            {"part_number": "010108", "manufacturer": "Hager", "quantity": 2},
            {"part_number": "98", "manufacturer": "Von Duprin", "quantity": 1},
            {"description": "unmatched", "quantity": 1},
        ],
    )
    preprice.seed_line_items(slug)
    problems, _warnings = check_pricing(slug)
    assert not problems, problems


def test_a_re_seed_lands_on_the_same_rows(tmp_path, monkeypatch) -> None:
    slug, root = _seed_bid(tmp_path, monkeypatch, [{"part_number": "010108", "manufacturer": "Hager"}])
    preprice.seed_line_items(slug)
    first = _lines(root)[0]["line_id"]
    preprice.seed_line_items(slug)
    second = _lines(root)[0]["line_id"]
    assert first == second == "HW-1-00"


def test_a_real_pass_is_not_reseeded(tmp_path, monkeypatch) -> None:
    slug, root = _seed_bid(tmp_path, monkeypatch, [{"part_number": "010108", "manufacturer": "Hager"}])
    # A file not stamped with our SOURCE is a real pass's output - leave it alone.
    (root / "priced" / "line_items.json").write_text(
        json.dumps({"source": "the pricing pass", "lines": []}), encoding="utf-8"
    )
    result = preprice.seed_line_items(slug)
    assert not result["written"]


def test_an_empty_seed_is_never_written(tmp_path, monkeypatch) -> None:
    """The stamp makes the file patch-only, and an empty one has nothing to patch:
    the pass could neither add a line nor save the file, and the job died on
    "must contain a non-empty lines array". A stale empty seed is removed too."""
    slug = "demo_bid"
    priced = tmp_path / "projects" / slug / "priced"
    priced.mkdir(parents=True)
    (priced / "line_items.json").write_text(
        json.dumps({"source": preprice.SOURCE, "lines": []}), encoding="utf-8"
    )
    monkeypatch.setattr(storage_mod, "project_dir", lambda s: tmp_path / "projects" / s)
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "projects"))
    result = preprice.seed_line_items(slug)  # no hardware_sets.json, no take-off
    assert result["written"] is False
    assert not (priced / "line_items.json").exists()


def test_an_expired_special_net_is_skipped_with_a_note(tmp_path, monkeypatch) -> None:
    """A special net off a sheet past the review window is not seeded: the rung is
    skipped, the reason is on the line, and the ladder carries on to MANUAL."""
    from cbc.modules.pricing.api import catalog_baseline_backfill, reference_library

    slug, root = _seed_bid(tmp_path, monkeypatch, [{"part_number": "3553", "manufacturer": "Hager"}])
    monkeypatch.setattr(
        reference_library,
        "get_special_net",
        lambda vendor, part: {"net_price": 64.58, "item_code": "000091", "effective_date": "2015-01-01"},
    )
    monkeypatch.setattr(catalog_baseline_backfill, "_lookup_catalog_item", lambda part, vendor: None)
    preprice.seed_line_items(slug)
    line = _lines(root)[0]
    assert line["cost"] is None
    assert line["cost_source"] == "MANUAL"
    assert "skipped" in line["cost_source_detail"] and "2015-01-01" in line["cost_source_detail"]


def test_list_x_dates_the_line_from_the_tier_record(tmp_path, monkeypatch) -> None:
    """The list× rung stamps the tier's effective date and book version, so the
    proposal's lapsed gate can fire on a seeded line."""
    from cbc.modules.pricing.api import catalog_baseline_backfill, hager_list_price, reference_library

    slug, root = _seed_bid(
        tmp_path,
        monkeypatch,
        [{"part_number": "PEMKO-275A-42", "item_type": "threshold", "quantity": 1}],
    )
    monkeypatch.setattr(catalog_baseline_backfill, "_lookup_catalog_item", lambda part, vendor: None)
    monkeypatch.setattr(
        hager_list_price,
        "lookup_ngp_list_price",
        lambda code, width_in=None: {"list_price": 100.0, "source_page": 531},
    )
    monkeypatch.setattr(
        reference_library,
        "get_vendor_tier",
        lambda vendor, category=None: {
            "vendor": "Hager",
            "multiplier": 0.4,
            "effective_date": "2026-03-02",
            "price_book": "Price Book #18, effective 2026-02-02",
        },
    )
    preprice.seed_line_items(slug)
    line = _lines(root)[0]
    assert line["cost_source"] == "LIST_X_MULTIPLIER"
    assert line["multiplier_effective_date"] == "2026-03-02"
    assert line["price_book_version"] == "Hager Price Book #18, effective 2026-02-02"
    assert line["multiplier_tier"] == "thresholds_weatherstrip"


def test_list_x_prices_at_the_tier_records_multiplier(tmp_path, monkeypatch) -> None:
    """A typed-in 0.4 stood in for the threshold tier, so a changed tier sheet
    priced at the old rate under the new sheet's date."""
    from cbc.modules.pricing.api import catalog_baseline_backfill, hager_list_price, reference_library

    slug, root = _seed_bid(
        tmp_path, monkeypatch,
        [{"part_number": "PEMKO-275A-42", "item_type": "threshold", "quantity": 1}],
    )
    monkeypatch.setattr(catalog_baseline_backfill, "_lookup_catalog_item", lambda part, vendor: None)
    monkeypatch.setattr(
        hager_list_price, "lookup_ngp_list_price",
        lambda code, width_in=None: {"list_price": 100.0, "source_page": 531},
    )
    monkeypatch.setattr(
        reference_library, "get_vendor_tier",
        lambda vendor, category=None: {"vendor": "Hager", "multiplier": 0.42, "effective_date": "2026-03-02"},
    )
    preprice.seed_line_items(slug)
    line = _lines(root)[0]
    assert line["multiplier"] == 0.42 and line["cost"] == 42.0


# ── what the take-off cites, not only what the legend parsed ────────────────
#
# CBC-260001: the legend would not parse, so there was no hardware_sets.json; the
# seed wrote an empty, stamped file; the pass could only patch lines that did not
# exist; and the job died on "must contain a non-empty lines array" - with four
# openings citing hardware groups and eight Division 10 items in the take-off.

def _take_off(root, rows):
    (root / "extracted" / "line_items.json").write_text(
        json.dumps({"source": "estimator-confirmed via Ops-Hub", "openings": rows}), encoding="utf-8"
    )


def _door(mark, group, page=15):
    return {"door_number": mark, "mark": mark, "hardware_set": group, "source_page": page}


def _accessory(model, notes, qty=1):
    return {
        "door_number": model, "mark": model, "division": "10 28", "qty": qty,
        "manufacturer": "Bobrick", "description": f"accessory — Bobrick — {model}",
        "source_page": 12, "notes": notes,
        "specialty": {"kind": "div10", "specifiedModel": model, "unit": "ea", "room": "Restroom"},
    }


def _no_catalog(monkeypatch, priced=None):
    from cbc.modules.pricing.api import catalog_baseline_backfill

    rows = priced or {}
    monkeypatch.setattr(
        catalog_baseline_backfill, "_lookup_catalog_item",
        lambda part, vendor: rows.get(part),
    )


def test_the_bid_that_died_now_seeds_a_quote_that_validates(tmp_path, monkeypatch) -> None:
    from cbc.modules.extraction.api.validation.artifacts import check_pricing

    slug, root = _seed_bid(tmp_path, monkeypatch, [])
    (root / "extracted" / "hardware_sets.json").unlink()  # the legend never parsed
    _take_off(root, [
        _door("01", "GROUP 1"), _door("02", "GROUP 2"), _door("06", "GROUP 6"),
        _accessory("B-5806", "PA-51 GRAB BAR. Schedule: 'PROVIDED & INSTALLED BY GC'", qty=3),
        _accessory("B-254", "PA-64 DISPOSAL. Schedule: 'PROVIDED BY DBC PARTS'. Spec p6: (OFCI)."),
    ])
    _no_catalog(monkeypatch)

    assert preprice.seed_line_items(slug)["written"]
    lines = {line["line_id"]: line for line in _lines(root)}
    assert {"GROUP 1-SET", "GROUP 2-SET", "GROUP 6-SET", "10-B-5806", "10-B-254"} == set(lines)
    problems, _ = check_pricing(slug)
    assert not problems, problems


def test_a_cited_group_with_no_items_is_one_manual_line(tmp_path, monkeypatch) -> None:
    slug, root = _seed_bid(tmp_path, monkeypatch, [], set_id="GROUP 1")
    _take_off(root, [_door("01", "GROUP 1"), _door("04", "GROUP 1")])
    preprice.seed_line_items(slug)
    [line] = _lines(root)
    assert (line["line_id"], line["cost"], line["cost_source"]) == ("GROUP 1-SET", None, "MANUAL")
    assert line["quantity"] == 2, "one set per opening that cites it"
    assert line["source_page"] == 4 and "hardware_group_not_itemised" in line["flags"]


def test_a_group_built_from_the_schedule_takes_its_page_from_the_openings(tmp_path, monkeypatch) -> None:
    """The matcher's thin set: page on each opening, none on the set. Without it
    every placeholder failed the pricing check for having no source_page."""
    from cbc.modules.extraction.api.validation.artifacts import check_pricing

    slug, root = _seed_bid(tmp_path, monkeypatch, [])
    (root / "extracted" / "hardware_sets.json").write_text(json.dumps({"sets": [
        {"set_id": "GROUP 1", "openings": [{"door_number": "01", "source_page": 15}], "items": []},
    ]}), encoding="utf-8")
    _take_off(root, [_door("01", "GROUP 1")])
    preprice.seed_line_items(slug)
    assert _lines(root)[0]["source_page"] == 15
    problems, _ = check_pricing(slug)
    assert not problems, problems


def test_a_legend_group_no_opening_cites_is_not_priced(tmp_path, monkeypatch) -> None:
    """The struck-through office door: its group is still drawn in the legend."""
    slug, root = _seed_bid(tmp_path, monkeypatch, [{"part_number": "FS43", "manufacturer": "IVES"}], set_id="4")
    _take_off(root, [_door("01", "GROUP 1")])
    preprice.seed_line_items(slug)
    payload = json.loads((root / "priced" / "line_items.json").read_text(encoding="utf-8"))
    assert [line["line_id"] for line in payload["lines"]] == ["GROUP 1-SET"]
    assert any(flag.startswith("legend_group_unused") for flag in payload["flags"])

    # And the pricing check says so. It read only a bare list of sets, and every
    # writer wraps them in an object, so this warning had never fired.
    from cbc.modules.extraction.api.validation.artifacts import check_pricing

    _, warnings = check_pricing(slug)
    assert any("hardware 4 was extracted but has no line" in w for w in warnings), warnings


def test_legend_and_schedule_name_a_group_differently(tmp_path, monkeypatch) -> None:
    """The legend says `1`, the schedule `GROUP 1`: one group, priced once."""
    slug, root = _seed_bid(tmp_path, monkeypatch, [{"part_number": "FS43", "manufacturer": "IVES"}], set_id="1")
    _take_off(root, [_door("01", "GROUP 1")])
    preprice.seed_line_items(slug)
    assert [line["line_id"] for line in _lines(root)] == ["1-00"]


def test_division_10_is_seeded_and_an_owner_furnished_item_is_not_priced(tmp_path, monkeypatch) -> None:
    slug, root = _seed_bid(tmp_path, monkeypatch, [])
    _take_off(root, [
        _accessory("B-165-1836", "PA-52 MIRROR. Schedule: 'PROVIDED & INSTALLED BY GC'"),
        _accessory("B-212", "PA-66 COAT HOOK. Spec p6: HOOKS (OFCI)."),
    ])
    catalog = {"cost": 40.0, "part": "x", "seedSource": "catalog.md"}
    _no_catalog(monkeypatch, {"B-165-1836": catalog, "B-212": catalog})
    preprice.seed_line_items(slug)
    lines = {line["line_id"]: line for line in _lines(root)}

    mirror, hook = lines["10-B-165-1836"], lines["10-B-212"]
    assert mirror["group_type"] == "accessories" and mirror["cost_source"] == "CATALOG_BASELINE"
    assert hook["cost"] is None and hook["cost_source"] == "MANUAL"
    assert "supplied_by_others_noted" in hook["flags"]
    assert "OFCI" in hook["cost_source_detail"]
