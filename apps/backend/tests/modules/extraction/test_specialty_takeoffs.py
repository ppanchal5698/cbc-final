"""Specialty takeoff import and list API scope flags."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
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
    inserted: list[dict] = []

    async def insert_one(doc):
        inserted.append(doc)

    coll = SimpleNamespace(
        delete_many=AsyncMock(),
        insert_one=AsyncMock(side_effect=insert_one),
    )
    monkeypatch.setattr(specialty_takeoffs, "takeoffs", lambda: coll)

    project = {"slug": slug, "_id": "bid-1"}
    counts = await specialty_takeoffs.import_specialty_takeoffs(project)

    assert counts["frp"] == 1
    assert counts["div10"] == 1
    types = {row["takeoffType"] for row in inserted}
    assert "frpArea" in types
    assert "accessoryCount" in types
    div10_row = next(r for r in inserted if r["takeoffType"] == "accessoryCount")
    assert div10_row["status"] == "NOT_EXTRACTED"


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
