"""quote-builder's documented command runs from a plain shell, and stays quiet about the halt."""
from __future__ import annotations

import os
import subprocess
import sys

from tests.shared import ROOT

SCRIPT = ROOT / ".claude" / "skills" / "generate-quotation" / "scripts" / "render_quote.py"


def test_render_quote_runs_without_anything_on_the_path() -> None:
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--demo"], capture_output=True, text=True, env=env, cwd=str(ROOT)
    )
    assert result.returncode == 0, result.stderr
    # "Draft ready for estimator review" is delivery-agent's halt line, and only its.
    assert "Draft ready for estimator review" not in result.stdout
