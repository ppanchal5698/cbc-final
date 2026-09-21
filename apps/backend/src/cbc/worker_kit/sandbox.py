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
from cbc.shared import storage

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

# Written inside the clone by the audit hook (NFR-3) and artifact-storage, and only
# ever appended to. They used to be discarded with the stray files, so a run's audit
# trail and its artifact history never reached the bid.
APPEND_ONLY = frozenset({"audit_trail.jsonl", ".versions/versions.jsonl"})
# artifact-storage's content-addressed copies: the name is the content's SHA-256.
VERSION_COPY = re.compile(r"^\.versions/[0-9a-f]{64}$")


def _append_new_lines(source: Path, target: Path) -> bool:
    """Append the lines `source` has and `target` lacks. Returns whether any were.

    The clone began as a copy of the live bid, so normally the new lines are the
    clone's tail. If the live file moved on during the run, its lines are kept and
    only the clone's unseen lines are added - history is appended, never rewritten.
    """
    new = source.read_bytes()
    old = target.read_bytes() if target.exists() else b""
    if new.startswith(old):
        extra = new[len(old):]
    else:
        seen = set(old.splitlines())
        extra = b"".join(line + b"\n" for line in new.splitlines() if line and line not in seen)
    if not extra:
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("ab") as handle:
        if old and not old.endswith(b"\n") and not new.startswith(old):
            handle.write(b"\n")
        handle.write(extra)
    return True


def mode() -> str:
    raw = os.environ.get("CLAUDE_SANDBOX", "process").strip().lower()
    return "docker" if raw == "docker" else "process"


def allowed_relpath(relative: str) -> bool:
    """True when `relative` is a known Claude output path (posix, no `..`)."""
    posix = relative.replace("\\", "/").lstrip("/")
    if ".." in posix.split("/"):
        return False
    return bool(SAVE_ALLOW.match(posix))


def scratch_root(slug: str) -> Path:
    """Where a bid's clone lives while a job works on it.

    Keyed by project, not by job. Claude Code's prompt cache is a prefix match
    and the working directory is part of that prefix, so a path that changes
    every job makes every run pay to write the same ~32k prefix again. Measured
    on this CLI with a four-run probe: two runs from one directory, then the
    same prompt and byte-identical files from a second directory - the second
    directory cost $0.0404 against $0.0056, 7.2x, and wrote exactly as many
    cache tokens as the very first cold run.

    The clone is still wiped and re-made in `prepare`, so a job sees what it has
    always seen: a fresh copy of the live bid. Only the *name* is stable, which
    is the whole of what the cache keys on.
    """
    return settings.storage_root / "_scratch" / str(slug)


def workspace_dir(slug: str) -> Path:
    return scratch_root(slug) / "workspace"


def quarantine_dir(slug: str, job_id: str) -> Path:
    """Where a workspace is set aside when its promote failed.

    Under per-job keying a failed clone survived because the next job had its
    own directory. Now it would be the next job's `rmtree`, so move it out of
    the way instead of losing the only copy of work that never reached the bid.
    """
    return scratch_root(slug) / f"failed-{job_id}"


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


def prepare(slug: str) -> Path:
    """Clone the bid into an isolated workspace. Returns cwd for Claude."""
    from cbc.shared.storage_backends import hydrate_project

    hydrate_project(slug)
    workspace = workspace_dir(slug)
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
    # Catalog tools return repo-relative price-book paths (data/pricebooks/...).
    # Claude's cwd is this workspace, not /app, so pdf-tools cannot open books
    # unless we link them here.
    pb_source = REPO_ROOT / "data" / "pricebooks"
    if not pb_source.is_dir():
        try:
            from cbc.shared.paths import pricebook_dir

            pb_source = pricebook_dir()
        except Exception:
            pb_source = None
    if pb_source is not None and pb_source.is_dir():
        pb_link = workspace / "data" / "pricebooks"
        if not pb_link.exists():
            try:
                pb_link.parent.mkdir(parents=True, exist_ok=True)
                os.symlink(pb_source, pb_link, target_is_directory=True)
            except OSError as exc:
                log.warning("sandbox: could not link pricebooks into workspace: %s", exc)
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


def _copy_replace(source: Path, target: Path) -> None:
    """Copy `source` onto `target`, replacing host/root-owned files when needed.

    Bind mounts and host-side writes can leave live bid files owned by root (or
    otherwise unwritable by the worker uid). A bare shutil.copy2 then aborts the
    whole promote and discards every sibling artifact still in scratch.
    """
    try:
        shutil.copy2(source, target)
        return
    except PermissionError:
        log.warning("sandbox: replace unwritable %s before promote", target)
    try:
        target.chmod(0o644)
    except OSError:
        pass
    try:
        target.unlink(missing_ok=True)
    except TypeError:
        # Python < 3.8 style; keep a narrow fallback for older runtimes.
        if target.exists():
            target.unlink()
    except OSError as exc:
        raise PermissionError(f"cannot replace unwritable promote target {target}") from exc
    shutil.copy2(source, target)


def _priced_line_count(path: Path) -> int | None:
    """Number of quote lines in a priced artifact, or None when unreadable."""
    import json

    if not path.is_file():
        return 0
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if isinstance(payload, list):
        return len(payload)
    if isinstance(payload, dict):
        rows = payload.get("lines")
        if not isinstance(rows, list):
            rows = payload.get("line_items")
        return len(rows) if isinstance(rows, list) else 0
    return 0


class EmptyPricingPromoteError(ValueError):
    """Scratch priced/line_items.json would erase a non-empty live quote."""

    error_code = "sandbox_promote_empty_pricing"


def promote(slug: str) -> list[str]:
    """Copy allowlisted files from the scratch clone back to the live bid.

    The audit trail and the versions index are appended to, never replaced; the
    content-addressed version copies are copied. Returns the relative paths that
    were promoted. Anything else is discarded.

    Rejects promoting an empty ``priced/line_items.json`` over a live file that
    already has lines — that was the session-to-session data-loss failure mode.
    """
    clone = workspace_dir(slug) / "projects" / slug
    dest = storage.project_dir(slug)
    dest.mkdir(parents=True, exist_ok=True)

    scratch_priced = clone / "priced" / "line_items.json"
    live_priced = dest / "priced" / "line_items.json"
    if scratch_priced.is_file():
        scratch_n = _priced_line_count(scratch_priced)
        live_n = _priced_line_count(live_priced) or 0
        if scratch_n is None:
            raise EmptyPricingPromoteError(
                f"priced/line_items.json in scratch is invalid JSON; refusing to "
                f"overwrite live quote for {slug}"
            )
        if scratch_n == 0 and live_n > 0:
            raise EmptyPricingPromoteError(
                f"scratch priced/line_items.json has 0 lines but live has {live_n}; "
                f"refusing to erase quote for {slug}"
            )

    promoted: list[str] = []
    discarded: list[str] = []
    for path, rel in iter_outputs(clone):
        target = dest / rel
        if rel in APPEND_ONLY:
            if _append_new_lines(path, target):
                promoted.append(rel)
            continue
        if not (allowed_relpath(rel) or VERSION_COPY.match(rel)):
            discarded.append(rel)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        _copy_replace(path, target)
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
            from cbc.shared.storage_backends import push_paths

            push_paths([dest / rel for rel in promoted])
        except Exception:
            log.exception("sandbox: durable push after promote failed for %s", slug)
    return promoted


def cleanup(slug: str) -> None:
    """Drop the clone, keeping anything quarantined beside it.

    This used to remove the whole scratch root, which was safe when the root was
    per-job. Per-project it would take a `failed-*` copy from an earlier job
    with it.
    """
    shutil.rmtree(workspace_dir(slug), ignore_errors=True)


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
    # The worker image compose builds; no separate extraction image is built.
    return os.environ.get("CBC_SANDBOX_IMAGE", "cbc-final-worker:latest").strip()


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
    from cbc.modules.ops.api.claude_cli import HeartbeatWatchdog, RunResult

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

