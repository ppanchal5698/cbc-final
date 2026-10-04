"""Specialty takeoff import and list API scope flags."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from cbc.modules.extraction.api import specialty_takeoffs
from cbc.modules.extraction.features import ListTakeoffs
from cbc.shared import storage as storage_mod


@pytest.fixture()
def project_root(tmp_path, monkeypatch):
    monkeypatch.setattr(
        storage_mod, "project_dir", lambda slug: tmp_path / "projects" / slug
    )
    return tmp_path


def _write_extracted(root: Path, slug: str, **files: object) -> Path:
    extracted = root / "projects" / slug / "extracted"
    extracted.mkdir(parents=True, exist_ok=True)
    for name, payload in files.items():
        (extracted / name).write_text(json.dumps(payload), encoding="utf-8")
    return extracted


@pytest.mark.asyncio
async def test_div10_empty_status_imports_placeholder(project_root, monkeypatch) -> None:
    slug = "div10_seed"
    _write_extracted(
        project_root,
        slug,
        **{
            "div10_takeoff.json": {
                "div10_in_scope": True,
                "status": "NOT_EXTRACTED",
                "items": [],
                "flags": ["div10_not_extracted"],
            },
            "frp_takeoff.json": {
                "frp_in_scope": True,
                "status": "NOT_MEASURED",
                "areas": [],
            },
        },
    )
    bulk: list = []

    async def apply_bulk(requests):
        bulk.extend(requests)

    monkeypatch.setattr(
        specialty_takeoffs.extraction_openings, "list_for_project", AsyncMock(return_value=[])
    )
    monkeypatch.setattr(
        specialty_takeoffs.extraction_openings, "apply_bulk", AsyncMock(side_effect=apply_bulk)
    )

    project = {"slug": slug, "_id": "bid-1"}
    counts = await specialty_takeoffs.import_specialty_takeoffs(project)

    assert counts["frp"] == 1
    assert counts["div10"] == 1

    # In scope with nothing found is a result. It reaches the estimator as a
    # flagged line in the openings table rather than as an empty panel.
    docs = [request._doc for request in bulk]
    divisions = {doc["division"] for doc in docs}
    assert divisions == {
        specialty_takeoffs.DIVISION_ACCESSORIES,
        specialty_takeoffs.DIVISION_FRP,
    }
    div10_row = next(
        doc for doc in docs if doc["division"] == specialty_takeoffs.DIVISION_ACCESSORIES
    )
    assert div10_row["status"] == "needs_look"
    assert "div10_not_extracted" in div10_row["flags"]
    assert div10_row["specialty"]["status"] == "NOT_EXTRACTED"


def test_scope_flags_from_summary(project_root) -> None:
    slug = "scope_flags"
    _write_extracted(
        project_root,
        slug,
        **{
            "scope_summary.json": {
                "frp_in_scope": True,
                "div10_in_scope": False,
            }
        },
    )
    flags = ListTakeoffs._scope_flags(slug)
    assert flags == {"frpInScope": True, "div10InScope": False}
