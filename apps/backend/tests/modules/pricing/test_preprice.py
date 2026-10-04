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


def test_the_seed_never_raises_on_a_missing_hardware_file(tmp_path, monkeypatch) -> None:
    slug = "demo_bid"
    (tmp_path / "projects" / slug / "priced").mkdir(parents=True)
    monkeypatch.setattr(storage_mod, "project_dir", lambda s: tmp_path / "projects" / s)
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "projects"))
    result = preprice.seed_line_items(slug)  # no hardware_sets.json
    assert result["written"] is True
    assert _lines(tmp_path / "projects" / slug) == []
