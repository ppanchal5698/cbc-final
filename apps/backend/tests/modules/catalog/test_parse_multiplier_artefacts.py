"""parse_multiplier artefacts must not write under read-only reference-library."""
from __future__ import annotations

from pathlib import Path

from cbc.modules.catalog.features import ParseMultiplier
from cbc.shared.config import settings
from cbc.shared.paths import reference_dir


def test_multiplier_artefact_dir_is_under_writable_pricebooks(tmp_path, monkeypatch) -> None:
    pb = tmp_path / "pricebooks"
    pb.mkdir()
    monkeypatch.setattr(settings, "pricebook_dir", pb)

    out = ParseMultiplier.artefact_dir("sheet-abc")

    assert out == pb / "processed" / "mineru" / "multipliers" / "sheet-abc"
    assert out.is_relative_to(pb.resolve())
    # reference-library stays read-only in compose — never park MinerU JSON there.
    assert not str(out).startswith(str(reference_dir()))
