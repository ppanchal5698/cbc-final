"""Rendering the two HTML artifacts, deterministically.

`build_proposal` told `quote-builder` to run `validate_and_render_quote.py` and
`quality-reviewer` to run `render_review_summary.py`. Telling is not enforcing:
an agent that hand-writes the HTML instead produces a quotation that looks right
and was never checked against the pricing rules, and one that skips the step
produces nothing at all. `quality-reviewer` could not have run its script even
if it tried - `Bash` was not in its tool list.

So the worker runs both scripts itself after the pass, and whatever the agent
wrote is overwritten by the validated render. The agent still does the work only
it can do - the judgment, the flags, the RFI prose - and the arithmetic and the
markup come from code that does the same thing every time.

A failure here is reported, not raised: the pass may have produced a perfectly
good review with a quote that does not yet validate, and losing the whole job
over the render would throw away the part that worked.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from cbc.core.paths import repo_root

REPO_ROOT = repo_root()

QUOTE_SCRIPT = REPO_ROOT / "scripts" / "validate_and_render_quote.py"
REVIEW_SCRIPT = REPO_ROOT / "scripts" / "render_review_summary.py"
QUOTE_TEMPLATE = REPO_ROOT / "templates" / "quotation.html"
REVIEW_TEMPLATE = REPO_ROOT / "templates" / "review_summary.html"
# Bump when check_pricing, render_quote.py, or the review script change.
RENDERER_VERSION = "1"

# Long enough for a large quote, short enough that a hung render does not hold a
# worker slot until the job times out.
TIMEOUT_SECONDS = 180


@dataclass(frozen=True)
class RenderResult:
    ok: bool
    detail: str

    def __bool__(self) -> bool:
        return self.ok


def _sha256_file(path: Path) -> str:
    if not path.is_file():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fingerprint(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _project_root(slug: str) -> Path:
    return REPO_ROOT / "projects" / slug


def _stamp_path(html: Path) -> Path:
    return Path(str(html) + ".render.json")


def _stamp_matches(html: Path, key: str) -> bool:
    if not html.is_file():
        return False
    stamp = _stamp_path(html)
    if not stamp.is_file():
        return False
    try:
        data = json.loads(stamp.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    return (
        data.get("key") == key and data.get("rendererVersion") == RENDERER_VERSION
    )


def _write_stamp(html: Path, key: str) -> None:
    stamp = _stamp_path(html)
    stamp.parent.mkdir(parents=True, exist_ok=True)
    stamp.write_text(
        json.dumps({"key": key, "rendererVersion": RENDERER_VERSION}, indent=2),
        encoding="utf-8",
    )


def _quotation_key(slug: str) -> str:
    root = _project_root(slug)
    return _fingerprint(
        _sha256_file(root / "priced" / "line_items.json"),
        _sha256_file(QUOTE_TEMPLATE),
        RENDERER_VERSION,
    )


def _review_key(slug: str) -> str:
    root = _project_root(slug)
    return _fingerprint(
        _sha256_file(root / "priced" / "line_items.json"),
        _sha256_file(QUOTE_TEMPLATE),
        RENDERER_VERSION,
        _sha256_file(root / "review" / "review_flags.json"),
        _sha256_file(REVIEW_TEMPLATE),
    )


def _run(script, slug: str, label: str) -> RenderResult:
    if not script.exists():
        return RenderResult(False, f"{label}: script missing at {script}")
    try:
        done = subprocess.run(
            [sys.executable, str(script), slug],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return RenderResult(False, f"{label}: timed out after {TIMEOUT_SECONDS}s")
    if done.returncode == 0:
        return RenderResult(True, f"{label}: rendered")
    # The scripts print their reasons to stderr, one per line, and those reasons
    # are the point - "line 14 has a cost with no sale_ea" is what the estimator
    # needs, not "exit 1".
    reason = (done.stderr or done.stdout or "").strip().splitlines()
    return RenderResult(False, f"{label}: {'; '.join(reason[-3:]) or 'failed'}")


def render_quotation(slug: str) -> RenderResult:
    """Validate the priced lines and render projects/{slug}/quotation.html."""
    html = _project_root(slug) / "quotation.html"
    key = _quotation_key(slug)
    if _stamp_matches(html, key):
        return RenderResult(True, "quotation: unchanged")
    result = _run(QUOTE_SCRIPT, slug, "quotation")
    if result.ok:
        _write_stamp(html, key)
    return result


def render_review_summary(slug: str) -> RenderResult:
    """Render projects/{slug}/review/review_summary.html from flags and lines."""
    html = _project_root(slug) / "review" / "review_summary.html"
    key = _review_key(slug)
    if _stamp_matches(html, key):
        return RenderResult(True, "review summary: unchanged")
    result = _run(REVIEW_SCRIPT, slug, "review summary")
    if result.ok:
        _write_stamp(html, key)
    return result
