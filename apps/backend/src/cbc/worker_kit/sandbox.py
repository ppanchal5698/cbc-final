"""Per-job scratch directory, output allowlist, optional docker sandbox."""
from __future__ import annotations

import logging
import os
import re
import shutil
from pathlib import Path
from typing import Iterable

from cbc.shared.config import settings
from cbc.shared.paths import repo_root
from cbc.services import storage

log = logging.getLogger("cbc.sandbox")

REPO_ROOT = repo_root()

# Claude may only promote files matching these relative paths back to the bid.
_ROOT_FILES = frozenset({"quotation.html"})
_DIR_SUFFIXES = {
    "extracted": (".json",),
    "priced": (".json",),
    "review": (".json", ".html", ".md"),
}

SAVE_ALLOW = re.compile(
    r"^(extracted|priced|review)/[A-Za-z0-9._-]+\.(json|html|md)$|^quotation\.html$"
)


def mode() -> str:
    raw = os.environ.get("CLAUDE_SANDBOX", "process").strip().lower()
    return "docker" if raw == "docker" else "process"


def allowed_relpath(relative: str) -> bool:
    """True when `relative` is a known Claude output path (posix, no `..`)."""
    posix = relative.replace("\\", "/").lstrip("/")
    if ".." in posix.split("/"):
        return False
    return bool(SAVE_ALLOW.match(posix))


def scratch_root(job_id: str) -> Path:
    return settings.storage_root / "_scratch" / str(job_id)


def workspace_dir(job_id: str) -> Path:
    return scratch_root(job_id) / "workspace"


def ensure_workspace_trusted(workspace: Path, *, home: Path | None = None) -> bool:
    """Mark `workspace` trusted in ~/.claude.json so permissions.allow applies.

    Claude Code ignores project permissions.allow until the trust dialog is
    accepted. Unattended jobs have nobody to click it. The container entrypoint
    trusts /app, but each job runs with cwd under _scratch/.../workspace — a
    different project key — so trust must be set per scratch cwd or the allow
    list is ignored and MCP / Write looks like an empty take-off.
    """
    import json

    root = Path(home) if home is not None else Path.home()
    config = root / ".claude.json"
    key = str(Path(workspace).resolve())
    try:
        data = json.loads(config.read_text(encoding="utf-8")) if config.exists() else {}
    except (json.JSONDecodeError, OSError):
        data = {}
    project = data.setdefault("projects", {}).setdefault(key, {})
    if project.get("hasTrustDialogAccepted"):
        return False
    project["hasTrustDialogAccepted"] = True
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(json.dumps(data, indent=2), encoding="utf-8")
    log.info("sandbox: marked %s as a trusted Claude workspace", key)
    return True


def prepare(job_id: str, slug: str) -> Path:
    """Clone the bid into an isolated workspace. Returns cwd for Claude."""
    from cbc.services.storage_backends import hydrate_project

    hydrate_project(slug)
    workspace = workspace_dir(job_id)
    if workspace.exists():
        shutil.rmtree(workspace, ignore_errors=True)
    dest_project = workspace / "projects" / slug
    dest_project.parent.mkdir(parents=True, exist_ok=True)
    source = storage.project_dir(slug)
    if source.is_dir():
        shutil.copytree(source, dest_project, dirs_exist_ok=True)
    else:
        dest_project.mkdir(parents=True, exist_ok=True)
        storage.scaffold(slug)
        if storage.project_dir(slug).is_dir():
            shutil.copytree(storage.project_dir(slug), dest_project, dirs_exist_ok=True)

    # `.claude` is the only agent runtime. It used to be copied twice, under
    # two names, from two trees kept identical by nothing.
    for name in (".claude", "CLAUDE.md"):
        origin = REPO_ROOT / name
        target = workspace / name
        if not origin.exists() or target.exists():
            continue
        try:
            if origin.is_dir():
                shutil.copytree(origin, target)
            else:
                shutil.copy2(origin, target)
        except OSError as exc:
            log.warning("sandbox: could not copy %s: %s", name, exc)
    try:
        ensure_workspace_trusted(workspace)
    except OSError as exc:
        log.warning("sandbox: could not mark workspace trusted: %s", exc)
    return workspace


def iter_outputs(project_clone: Path) -> Iterable[tuple[Path, str]]:
    """Yield (absolute path, posix relative path) under a project clone."""
    if not project_clone.is_dir():
        return
    for path in project_clone.rglob("*"):
        if not path.is_file():
            continue
        try:
            rel = path.relative_to(project_clone).as_posix()
        except ValueError:
            continue
        yield path, rel


def promote(job_id: str, slug: str) -> list[str]:
    """Copy allowlisted files from the scratch clone back to the live bid.

    Returns the relative paths that were promoted. Anything else is discarded.
    """
    clone = workspace_dir(job_id) / "projects" / slug
    dest = storage.project_dir(slug)
    dest.mkdir(parents=True, exist_ok=True)
    promoted: list[str] = []
    discarded: list[str] = []
    for path, rel in iter_outputs(clone):
        if not allowed_relpath(rel):
            discarded.append(rel)
            continue
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        promoted.append(rel)
    if discarded:
        log.warning(
            "sandbox: discarded %s non-allowlisted file(s) for %s: %s",
            len(discarded),
            slug,
            ", ".join(discarded[:8]),
        )
    if promoted:
        try:
            from cbc.services.storage_backends import push_paths

            push_paths([dest / rel for rel in promoted])
        except Exception:
            log.exception("sandbox: durable push after promote failed for %s", slug)
    return promoted


def cleanup(job_id: str) -> None:
    root = scratch_root(job_id)
    shutil.rmtree(root, ignore_errors=True)


def env_for(workspace: Path, base: dict[str, str] | None) -> dict[str, str]:
    """Environment for a Claude subprocess confined to `workspace`."""
    env = dict(base or os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(workspace)
    env["CBC_PROJECTS_ROOT"] = str(workspace / "projects")
    env.pop("MONGODB_URI", None)
    return env


# Keys the sandbox container may inherit. Everything else, including the
# writable Mongo URI, stays on the worker.
_SANDBOX_ENV_KEEP = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_MODEL",
    "CLAUDE_BIN",
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC",
    "HOME",
    "PATH",
    "PYTHONPATH",
    "STORAGE_ROOT",
    "CBC_PROJECTS_ROOT",
    "CLAUDE_PROJECT_DIR",
    "MONGODB_READONLY_URI",
    "MONGODB_DB",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "AWS_REGION",
    "AWS_DEFAULT_REGION",
    "OPENROUTER_API_KEY",
    "NVIDIA_NIM_API_KEY",
)


def docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    sock = Path("/var/run/docker.sock")
    return sock.exists() or bool(os.environ.get("DOCKER_HOST", "").strip())


def sandbox_image() -> str:
    return os.environ.get("CBC_SANDBOX_IMAGE", "cbc-final-extraction:latest").strip()


def sandbox_network() -> str:
    return os.environ.get("CBC_SANDBOX_NETWORK", "cbc-final-llm").strip()


def run_claude_docker(
    prompt: str,
    timeout: int = 1800,
    env: dict[str, str] | None = None,
    redact_values: list[str] | None = None,
    recording: Path | None = None,
    job_type: str | None = None,
    max_turns: int | None = None,
    cancel_check=None,
    settings: dict | None = None,
    on_heartbeat=None,
    heartbeat_seconds: float = 30,
    cwd: Path | None = None,
    **_ignored,
):
    """Run Claude in a one-shot read-only container bound only to the scratch dir.

    Skipped-at-runtime: pytest and Windows-without-socket use CLAUDE_SANDBOX=process.
    """
    from cbc.core.claude_cli import HeartbeatWatchdog, RunResult

    if cwd is None:
        return RunResult(
            ok=False,
            output="",
            error="docker sandbox requires a scratch workspace",
            returncode=2,
            permanent=True,
            error_code="sandbox_unavailable",
        )
    if not docker_available():
        return RunResult(
            ok=False,
            output="",
            error="CLAUDE_SANDBOX=docker but the docker socket/CLI is not available",
            returncode=127,
            permanent=True,
            error_code="sandbox_unavailable",
        )

    import json
    import subprocess

    workspace = Path(cwd)
    prompt_path = workspace / "_prompt.txt"
    request_path = workspace / "_sandbox_request.json"
    result_path = workspace / "_sandbox_result.json"
    rec_inside = workspace / "_recording.log"
    prompt_path.write_text(prompt, encoding="utf-8")
    request_path.write_text(
        json.dumps(
            {
                "timeout": timeout,
                "job_type": job_type,
                "max_turns": max_turns,
                "settings": settings,
                "recording": str(rec_inside),
            }
        ),
        encoding="utf-8",
    )

    inner_env = {key: value for key, value in (env or {}).items() if key in _SANDBOX_ENV_KEEP}
    inner_env["CLAUDE_PROJECT_DIR"] = "/workspace"
    inner_env["CBC_PROJECTS_ROOT"] = "/app/data/projects"
    inner_env["STORAGE_ROOT"] = "/app/data/projects"
    inner_env["HOME"] = "/home/cbc"
    inner_env["PYTHONPATH"] = "/app:/app/packages"
    inner_env.pop("MONGODB_URI", None)

    argv = [
        "docker",
        "run",
        "--rm",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges=true",
        "--network",
        sandbox_network(),
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,size=256m",
        "--tmpfs",
        "/home/cbc/.claude:rw,size=64m",
        "-v",
        f"{workspace}:/workspace",
        "-v",
        f"{workspace / 'projects'}:/app/data/projects",
        "-w",
        "/workspace",
        "--user",
        "1000:1000",
    ]
    for key, value in inner_env.items():
        argv.extend(["-e", f"{key}={value}"])
    argv.extend([sandbox_image(), "python", "-m", "cbc.worker_kit.sandbox_entry"])

    watchdog = HeartbeatWatchdog(on_heartbeat, heartbeat_seconds)
    watchdog.start()
    try:
        completed = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout + 60,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired:
        return RunResult(
            ok=False,
            output="",
            error=f"sandbox docker timed out after {timeout}s",
            returncode=124,
        )
    except FileNotFoundError:
        return RunResult(
            ok=False,
            output="",
            error="docker CLI not found",
            returncode=127,
            permanent=True,
            error_code="sandbox_unavailable",
        )
    finally:
        watchdog.stop()

    if cancel_check and cancel_check():
        return RunResult(
            ok=False,
            output="",
            error="cancelled by estimator",
            returncode=130,
        )

    payload: dict = {}
    if result_path.is_file():
        try:
            payload = json.loads(result_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = {}
    if recording is not None and rec_inside.is_file():
        recording.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(rec_inside, recording)

    if payload:
        return RunResult(
            ok=bool(payload.get("ok")),
            output=str(payload.get("output") or ""),
            error=payload.get("error"),
            returncode=int(payload.get("returncode") or completed.returncode),
            permanent=bool(payload.get("permanent")),
            error_code=payload.get("error_code"),
        )
    err = (completed.stderr or completed.stdout or "sandbox container produced no result")[-4000:]
    return RunResult(
        ok=False,
        output=completed.stdout or "",
        error=err,
        returncode=completed.returncode,
        permanent=completed.returncode in (125, 126, 127),
        error_code="sandbox_unavailable" if completed.returncode in (125, 126, 127) else None,
    )

