"""The proposal HTML comes from the scripts, whatever the pass decided to write.

`build_proposal` instructed `quote-builder` to run validate_and_render_quote.py
and `quality-reviewer` to run render_review_summary.py. Instructions are not
enforcement: an agent that hand-wrote the HTML produced a quotation that had
never been checked against the pricing rules, and `quality-reviewer` could not
have run its script in any case - Bash was not in its tool list.

The worker now runs both after the pass, so the markup and the arithmetic are the
same every time.
"""
from __future__ import annotations

import importlib
import inspect

import pytest

from cbc.modules.quoting.infrastructure import render


def test_the_render_helper_calls_both_scripts() -> None:
    """Rendering is centralized so job slices cannot skip either artifact."""
    from cbc.modules.quoting.api import proposal_artifacts

    body = inspect.getsource(proposal_artifacts.render_artifacts)
    assert "render.render_quotation" in body
    assert "render.render_review_summary" in body


@pytest.mark.parametrize(
    "job_slice",
    ["quoting.features.BuildProposal", "intake.features.RunFullPipeline"],
    ids=["build_proposal", "run_full_pipeline"],
)
def test_the_worker_renders_both_artifacts_itself(job_slice: str) -> None:
    body = inspect.getsource(importlib.import_module(f"cbc.modules.{job_slice}").sync_results)
    assert "render_artifacts" in body, f"{job_slice} trusts the pass for rendering"


def test_a_render_failure_is_reported_rather_than_raised() -> None:
    """A good review with a quote that does not validate is still worth keeping."""
    result = render.render_quotation("no_such_project_anywhere")
    assert not result.ok
    assert "line_items" in result.detail or "not written" in result.detail
    assert not result  # RenderResult is falsy when it failed


def test_the_scripts_it_calls_actually_exist() -> None:
    """A path typo here fails only at the end of a run that already cost minutes."""
    assert render.QUOTE_SCRIPT.exists(), render.QUOTE_SCRIPT
    assert render.REVIEW_SCRIPT.exists(), render.REVIEW_SCRIPT


def test_a_missing_script_is_a_clean_failure(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(render, "QUOTE_SCRIPT", tmp_path / "gone.py")
    result = render.render_quotation("anything")
    assert not result.ok
    assert "missing" in result.detail


def _quote_project(tmp_path, monkeypatch, slug: str = "demo"):
    monkeypatch.setattr(render, "REPO_ROOT", tmp_path)
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "projects"))
    templates = tmp_path / "templates"
    templates.mkdir()
    (templates / "quotation.html").write_text("quote-tmpl", encoding="utf-8")
    (templates / "review_summary.html").write_text("review-tmpl", encoding="utf-8")
    monkeypatch.setattr(render, "QUOTE_TEMPLATE", templates / "quotation.html")
    monkeypatch.setattr(render, "REVIEW_TEMPLATE", templates / "review_summary.html")
    root = tmp_path / "projects" / slug
    (root / "priced").mkdir(parents=True)
    (root / "review").mkdir(parents=True)
    (root / "priced" / "line_items.json").write_text('{"lines":[]}', encoding="utf-8")
    (root / "quotation.html").write_text("<html>quote</html>", encoding="utf-8")
    (root / "review" / "review_summary.html").write_text("<html>review</html>", encoding="utf-8")
    return root


def test_unchanged_quotation_skips_the_subprocess(tmp_path, monkeypatch) -> None:
    root = _quote_project(tmp_path, monkeypatch)
    calls = {"n": 0}

    def fake_run(script, slug, label):
        calls["n"] += 1
        return render.RenderResult(True, f"{label}: rendered")

    monkeypatch.setattr(render, "_run", fake_run)
    first = render.render_quotation("demo")
    assert first.ok and calls["n"] == 1
    second = render.render_quotation("demo")
    assert second.detail == "quotation: unchanged"
    assert calls["n"] == 1
    (root / "priced" / "line_items.json").write_text('{"lines":[1]}', encoding="utf-8")
    third = render.render_quotation("demo")
    assert calls["n"] == 2
    assert "unchanged" not in third.detail


def test_unchanged_review_skips_until_flags_change(tmp_path, monkeypatch) -> None:
    root = _quote_project(tmp_path, monkeypatch)
    (root / "review" / "review_flags.json").write_text("[]", encoding="utf-8")
    calls = {"n": 0}

    def fake_run(script, slug, label):
        calls["n"] += 1
        return render.RenderResult(True, f"{label}: rendered")

    monkeypatch.setattr(render, "_run", fake_run)
    render.render_review_summary("demo")
    again = render.render_review_summary("demo")
    assert again.detail == "review summary: unchanged"
    assert calls["n"] == 1
    (root / "review" / "review_flags.json").write_text('[{"severity":"high"}]', encoding="utf-8")
    render.render_review_summary("demo")
    assert calls["n"] == 2


def _stub_render_artifacts(monkeypatch, tmp_path, *, q_unchanged: bool, r_unchanged: bool, pdf_exists: bool):
    """Wire render_artifacts to controllable HTML render results and a spy on the PDF step."""
    from cbc.modules.quoting.api import proposal_artifacts as pa

    root = tmp_path / "projects" / "demo"
    root.mkdir(parents=True)
    if pdf_exists:
        (root / "quotation.pdf").write_bytes(b"%PDF-1.4 existing")
    monkeypatch.setattr(pa, "storage_root", lambda: tmp_path / "projects")
    monkeypatch.setattr(pa.review_flags, "write_flags", lambda slug: 0)
    monkeypatch.setattr(
        pa.render,
        "render_quotation",
        lambda slug: render.RenderResult(True, "quotation", unchanged=q_unchanged),
    )
    monkeypatch.setattr(
        pa.render,
        "render_review_summary",
        lambda slug: render.RenderResult(True, "review", unchanged=r_unchanged),
    )
    spy = {"n": 0}
    monkeypatch.setattr(pa, "_render_delivery", lambda slug: spy.__setitem__("n", spy["n"] + 1))
    return pa, spy


def test_pdf_is_not_re_rendered_when_nothing_changed(tmp_path, monkeypatch) -> None:
    pa, spy = _stub_render_artifacts(
        monkeypatch, tmp_path, q_unchanged=True, r_unchanged=True, pdf_exists=True
    )
    assert pa.render_artifacts("build_proposal", "demo") == []
    assert spy["n"] == 0, "WeasyPrint ran though both renders were unchanged"


def test_pdf_is_rendered_when_a_render_changed(tmp_path, monkeypatch) -> None:
    pa, spy = _stub_render_artifacts(
        monkeypatch, tmp_path, q_unchanged=False, r_unchanged=True, pdf_exists=True
    )
    pa.render_artifacts("build_proposal", "demo")
    assert spy["n"] == 1, "a changed quotation must re-produce the PDF"


def test_pdf_is_rendered_when_missing_even_if_unchanged(tmp_path, monkeypatch) -> None:
    pa, spy = _stub_render_artifacts(
        monkeypatch, tmp_path, q_unchanged=True, r_unchanged=True, pdf_exists=False
    )
    pa.render_artifacts("build_proposal", "demo")
    assert spy["n"] == 1, "a missing quotation.pdf must be rendered"
