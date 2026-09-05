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

import re

import pytest

from cbc.services import render
from tests.shared import ROOT

# The job branches moved to the shared worker kit with the services/ layout;
# apps/worker/main.py is gone.
WORKER = (ROOT / "packages" / "cbc" / "worker_kit" / "runtime.py").read_text(encoding="utf-8")


def _branch(job_type: str) -> str:
    """The body of one `if job["type"] == ...` branch in sync_results."""
    start = WORKER.index(f'if job["type"] == "{job_type}":')
    rest = WORKER[start:]
    nxt = re.search(r'\n    if job\["type"\]', rest[10:])
    return rest[: nxt.start() + 10] if nxt else rest


def test_the_render_helper_calls_both_scripts() -> None:
    """Rendering is centralized so job branches cannot skip either artifact."""
    start = WORKER.index("def _sync_blocking_render(")
    end = WORKER.index("\n\nasync def sync_results", start)
    body = WORKER[start:end]
    assert "render.render_quotation" in body
    assert "render.render_review_summary" in body


@pytest.mark.parametrize("job_type", ["build_proposal", "run_full_pipeline"])
def test_the_worker_renders_both_artifacts_itself(job_type: str) -> None:
    body = _branch(job_type)
    assert "_sync_blocking_render" in body, f"{job_type} trusts the pass for rendering"


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
