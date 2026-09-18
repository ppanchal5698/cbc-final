"""Corpus smoke over bid_pdfs/ — skip when the folder is absent."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests.shared import ROOT

BID_PDFS = ROOT / "bid_pdfs"
SCRIPT = ROOT / "apps" / "backend" / "scripts" / "smoke_bid_pdfs.py"
REPORT = ROOT / ".cache" / "bid_pdf_smoke" / "report.json"


@pytest.mark.skipif(not BID_PDFS.is_dir(), reason="bid_pdfs/ not present")
def test_bid_pdf_corpus_smoke() -> None:
    """Every PDF either yields openings or an honest empty reason — never silent miss."""
    assert SCRIPT.is_file(), SCRIPT
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(BID_PDFS), "--max-pages", "12"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    if not REPORT.is_file():
        pytest.fail(f"smoke did not write {REPORT}\nstdout={proc.stdout}\nstderr={proc.stderr}")

    report = json.loads(REPORT.read_text(encoding="utf-8"))
    failed = [r for r in report.get("results") or [] if not r.get("ok")]
    # Soft gate: marker_present_zero_openings is the hard failure class.
    hard = [r for r in failed if r.get("reason") == "marker_present_zero_openings"]
    assert not hard, (
        "Schedule marker present but zero openings:\n"
        + "\n".join(f"- {r['path']}: {r.get('error')}" for r in hard)
        + f"\nSee {REPORT}"
    )
    # parse_error is also a hard fail
    errors = [r for r in failed if r.get("reason") == "parse_error"]
    assert not errors, "\n".join(f"- {r['path']}: {r.get('error')}" for r in errors)
