"""A run outside compose reaches the compose Mongo, and finds the data directories.

The replica set advertises `mongo:27017`; from the host every backend client
waited out its timeout. The reference store fell back to seed files after three
seconds a read, and then read them from `reference-library/`, which exists only
inside the image.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from pymongo import MongoClient

from cbc.shared import paths
from cbc.shared.mongo_uri import reachable_uri

SRC = Path(__file__).resolve().parents[2] / "src" / "cbc"
UNCHANGED = [
    "mongodb://cbc:x@mongo:27017/cbc_opshub?authSource=admin&replicaSet=rs0",
    "mongodb://localhost:27017/?directConnection=false",
    "mongodb://localhost:27017,localhost:27018/?replicaSet=rs0",
    "mongodb+srv://u:p@cluster0.example.net/cbc_opshub",
]


@pytest.mark.parametrize(
    "uri, expected",
    [
        ("mongodb://cbc:x@localhost:27017/cbc_opshub?authSource=admin",
         "mongodb://cbc:x@localhost:27017/cbc_opshub?authSource=admin&directConnection=true"),
        ("mongodb://127.0.0.1:27017", "mongodb://127.0.0.1:27017/?directConnection=true"),
        ("mongodb://localhost:27017/cbc_opshub", "mongodb://localhost:27017/cbc_opshub?directConnection=true"),
        *[(uri, uri) for uri in UNCHANGED],
    ],
)
def test_only_a_single_loopback_host_connects_directly(uri: str, expected: str) -> None:
    assert reachable_uri(uri) == expected


def test_pymongo_accepts_every_uri_it_hands_back() -> None:
    for uri in ("mongodb://cbc:x@localhost:27017/db?authSource=admin", "mongodb://127.0.0.1:27017",
                "mongodb://localhost:27017/db?replicaSet=rs0", *UNCHANGED[:3]):
        MongoClient(reachable_uri(uri), connect=False).close()


def test_the_data_directories_default_to_the_checkout(monkeypatch) -> None:
    for name in ("STORAGE_ROOT", "PRICEBOOK_DIR", "REFERENCE_DIR", "CBC_PROJECTS_ROOT"):
        monkeypatch.delenv(name, raising=False)
    root = paths.repo_root()
    assert paths.storage_root() == root / "data" / "projects"
    assert paths.pricebook_dir() == root / "data" / "pricebooks"
    assert paths.reference_dir() == root / "data" / "reference-library"
    assert (paths.reference_dir() / "margins" / "margin_framework.json").is_file()


def test_a_sandboxed_run_reads_its_own_clone(monkeypatch, tmp_path) -> None:
    """sandbox.py hands the Claude subprocess CBC_PROJECTS_ROOT; what runs there reads that copy."""
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "live"))
    monkeypatch.setenv("CBC_PROJECTS_ROOT", str(tmp_path / "clone"))
    assert paths.storage_root() == tmp_path / "clone"
    monkeypatch.delenv("CBC_PROJECTS_ROOT")
    assert paths.storage_root() == tmp_path / "live"


def test_no_code_builds_a_data_directory_off_a_root() -> None:
    """Backend, scripts and skill scripts alike: the directories come from cbc.shared.paths."""
    pattern = re.compile(r'(repo_root\(\)|\bROOT|\bREPO_ROOT)\s*/\s*"(pricebooks|reference-library|projects)"')
    repo = paths.repo_root()
    roots = (SRC, SRC.parents[1] / "scripts", repo / ".claude" / "skills")
    offenders = [
        f"{path.relative_to(repo).as_posix()}:{number}"
        for root in roots
        for path in root.rglob("*.py")
        if "__pycache__" not in path.parts
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if pattern.search(line)
    ]
    assert not offenders, "use cbc.shared.paths (storage_root, pricebook_dir, reference_dir): " + ", ".join(offenders)
