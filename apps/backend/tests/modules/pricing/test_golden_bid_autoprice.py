"""Golden bid: LIST_X backfill + promote guard for Endeavor-style hardware."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from cbc.modules.pricing.api import list_x_backfill
from cbc.worker_kit import sandbox

from cbc.shared.paths import repo_root

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "golden"
EXPECTATIONS = json.loads(
    (FIXTURES / "endeavor_2_0_expectations.json").read_text(encoding="utf-8")
)
_HAGER_PDF = repo_root() / "data" / "pricebooks" / "hager_price_book_18.pdf"


def _seed_endeavor_priced(root: Path) -> None:
    """Minimal hardware_sets + empty-cost priced lines for Pemko/Zero SKUs."""
    (root / "extracted").mkdir(parents=True)
    (root / "priced").mkdir(parents=True)
    hw = {
        "hardware_sets": [
            {
                "name": "GROUP 1",
                "items": [
                    {
                        "item_type": "threshold",
                        "cost_source": "LIST_X_MULTIPLIER",
                        "multiplier": 0.4,
                        "matched": {"part_number": "275A", "series": '42"'},
                    },
                    {
                        "item_type": "door_shoe",
                        "cost_source": "LIST_X_MULTIPLIER",
                        "multiplier": 0.4,
                        "matched": {"part_number": "39A", "series": '42"'},
                    },
                    {
                        "item_type": "door_seal",
                        "cost_source": "LIST_X_MULTIPLIER",
                        "multiplier": 0.4,
                        "matched": {"part_number": "188S BK"},
                    },
                    {
                        "item_type": "hinge",
                        "cost_source": "DISTRIBUTOR_MANUAL",
                        "matched": {"part_number": "IVES 700", "manufacturer": "Ives"},
                    },
                ],
            },
            {
                "name": "GROUP 2",
                "items": [
                    {
                        "item_type": "threshold",
                        "cost_source": "LIST_X_MULTIPLIER",
                        "multiplier": 0.4,
                        "matched": {"part_number": "275A", "series": '36"'},
                    },
                    {
                        "item_type": "door_shoe",
                        "cost_source": "LIST_X_MULTIPLIER",
                        "multiplier": 0.4,
                        "matched": {"part_number": "39A", "series": '36"'},
                    },
                    {
                        "item_type": "door_seal",
                        "cost_source": "LIST_X_MULTIPLIER",
                        "multiplier": 0.4,
                        "matched": {"part_number": "188S BK"},
                    },
                ],
            },
        ]
    }
    lines = [
        {
            "line_id": "G1-06",
            "part_number": "PEMKO 275A",
            "quantity": 1,
            "cost": None,
            "cost_source": "MANUAL",
            "multiplier": 0.4,
            "price_book_version": "Hager Price Book #18",
        },
        {
            "line_id": "G1-07",
            "part_number": "ZERO 39A SWEEP",
            "quantity": 1,
            "cost": None,
            "cost_source": "MANUAL",
            "multiplier": 0.4,
            "price_book_version": "Hager Price Book #18",
        },
        {
            "line_id": "G1-08",
            "part_number": "ZERO 188S BK",
            "quantity": 1,
            "cost": None,
            "cost_source": "MANUAL",
            "multiplier": 0.4,
            "price_book_version": "Hager Price Book #18",
        },
        {
            "line_id": "G1-01",
            "part_number": "IVES 700",
            "quantity": 1,
            "cost": None,
            "cost_source": "MANUAL",
        },
        {
            "line_id": "G2-06",
            "part_number": "PEMKO 275A",
            "quantity": 1,
            "cost": None,
            "cost_source": "MANUAL",
            "multiplier": 0.4,
            "price_book_version": "Hager Price Book #18",
        },
        {
            "line_id": "G2-07",
            "part_number": "ZERO 39A SWEEP",
            "quantity": 1,
            "cost": None,
            "cost_source": "MANUAL",
            "multiplier": 0.4,
            "price_book_version": "Hager Price Book #18",
        },
        {
            "line_id": "G2-08",
            "part_number": "ZERO 188S BK",
            "quantity": 1,
            "cost": None,
            "cost_source": "MANUAL",
            "multiplier": 0.4,
            "price_book_version": "Hager Price Book #18",
        },
    ]
    (root / "extracted" / "hardware_sets.json").write_text(json.dumps(hw), encoding="utf-8")
    (root / "priced" / "line_items.json").write_text(
        json.dumps({"lines": lines}), encoding="utf-8"
    )


@pytest.mark.skipif(
    not _HAGER_PDF.is_file(),
    reason="Hager price book PDF not present",
)
def test_golden_endeavor_list_x_backfill(tmp_path, monkeypatch) -> None:
    slug = "endeavor_golden"
    root = tmp_path / "projects" / slug
    root.mkdir(parents=True)
    _seed_endeavor_priced(root)

    import cbc.shared.storage as storage_mod

    monkeypatch.setattr(storage_mod, "project_dir", lambda s: tmp_path / "projects" / s)

    stats = list_x_backfill.backfill_priced_lines(slug)
    assert stats["filled"] >= EXPECTATIONS["expected_list_x_min_priced"]

    payload = json.loads((root / "priced" / "line_items.json").read_text(encoding="utf-8"))
    lines = payload["lines"]
    assert lines, "priced lines must not be empty after backfill"
    with_cost = sum(1 for row in lines if row.get("cost") is not None)
    assert with_cost >= EXPECTATIONS["expected_list_x_min_priced"]
    allegion_manual = sum(
        1
        for row in lines
        if row.get("cost") is None and "IVES" in str(row.get("part_number") or "").upper()
    )
    assert allegion_manual >= 1
    metrics = list_x_backfill.priced_line_metrics(slug)
    assert metrics["lines_with_cost"] == with_cost


def test_promote_never_erases_golden_priced_lines(tmp_path) -> None:
    from cbc.shared.config import settings
    from cbc.worker_kit.sandbox import EmptyPricingPromoteError

    previous = settings.storage_root
    settings.storage_root = tmp_path
    try:
        slug = "endeavor_golden"
        live = tmp_path / slug
        _seed_endeavor_priced(live)
        # Simulate a successful backfill already on live.
        live_payload = json.loads((live / "priced" / "line_items.json").read_text())
        for row in live_payload["lines"]:
            if "275A" in str(row.get("part_number")):
                row["cost"] = 12.41
        (live / "priced" / "line_items.json").write_text(
            json.dumps(live_payload), encoding="utf-8"
        )

        workspace = sandbox.prepare("job-golden", slug)
        clone = workspace / "projects" / slug
        (clone / "priced").mkdir(parents=True, exist_ok=True)
        (clone / "priced" / "line_items.json").write_text(
            json.dumps({"lines": []}), encoding="utf-8"
        )
        with pytest.raises(EmptyPricingPromoteError):
            sandbox.promote("job-golden", slug)
        kept = json.loads((live / "priced" / "line_items.json").read_text())
        assert any(row.get("cost") == 12.41 for row in kept["lines"])
    finally:
        sandbox.cleanup("job-golden")
        settings.storage_root = previous
