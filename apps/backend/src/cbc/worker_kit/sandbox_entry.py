"""Entry point for the one-shot Claude sandbox container.

The worker writes `_prompt.txt` and `_sandbox_request.json` into the scratch
workspace, then `docker run`s this module. Mongo is not on this network and
MONGODB_URI is not passed in.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from cbc.modules.ops.api.claude_cli import run_claude
from cbc.worker_kit.sandbox import ensure_workspace_trusted


def main() -> int:
    os.environ.pop("MONGODB_URI", None)
    workspace = Path("/workspace")
    # Docker sandbox mounts an empty tmpfs over ~/.claude, so the worker
    # entrypoint's trust for /app does not apply. Accept trust for this cwd
    # before Claude starts or permissions.allow is ignored.
    ensure_workspace_trusted(workspace)
    ensure_workspace_trusted(Path("/app"))
    prompt = (workspace / "_prompt.txt").read_text(encoding="utf-8")
    request: dict = {}
    req_path = workspace / "_sandbox_request.json"
    if req_path.is_file():
        request = json.loads(req_path.read_text(encoding="utf-8"))
    recording = None
    rec = request.get("recording")
    if rec:
        recording = Path(rec)
    result = run_claude(
        prompt,
        timeout=int(request.get("timeout") or 1800),
        env=dict(os.environ),
        recording=recording,
        job_type=request.get("job_type"),
        max_turns=request.get("max_turns"),
        settings=request.get("settings"),
        cwd=workspace,
        on_heartbeat=None,
    )
    (workspace / "_sandbox_result.json").write_text(
        json.dumps(
            {
                "ok": result.ok,
                "output": result.output,
                "error": result.error,
                "returncode": result.returncode,
                "permanent": result.permanent,
                "error_code": result.error_code,
            }
        ),
        encoding="utf-8",
    )
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
