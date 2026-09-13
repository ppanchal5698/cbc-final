"""The composition root's ordering rule, checked rather than documented.

`cbc.shared.config` builds settings from `os.environ` once, at import, so `.env`
has to be applied before anything imports it - otherwise the process silently
ignores its own configuration. That rule lived only in a docstring.

This imports the real root in a fresh interpreter with a spy on
`apply_to_environ`, and records whether config was already loaded when it ran.
It checks the property, not the textual order of two lines, so an import that
pulls config in transitively fails it too.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from tests.shared import PKG

SPY = """
import json, sys
import cbc.shared.envfile as envfile

seen = {}
original = envfile.apply_to_environ

def spy(*args, **kwargs):
    seen["config_loaded"] = "cbc.shared.config" in sys.modules
    return original(*args, **kwargs)

envfile.apply_to_environ = spy
import ROOT
print(json.dumps(seen))
"""


@pytest.mark.parametrize("root", ["cbc.app.main", "cbc.worker.main"])
def test_env_file_is_applied_before_settings_are_built(tmp_path, root) -> None:
    env = {
        **os.environ,
        "PYTHONPATH": str(PKG.parent),
        "CBC_ENV_FILE": str(tmp_path / ".env"),
        "APP_ENV": "development",
    }
    result = subprocess.run([sys.executable, "-c", SPY.replace("ROOT", root)], capture_output=True, text=True, env=env, timeout=120)
    assert result.returncode == 0, result.stderr[-2000:]
    seen = json.loads(result.stdout.strip().splitlines()[-1])
    assert seen == {"config_loaded": False}, (
        "cbc.shared.config was imported before .env was applied, or apply_to_environ never ran"
    )
