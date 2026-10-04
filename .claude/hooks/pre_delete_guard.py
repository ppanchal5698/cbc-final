#!/usr/bin/env python3
"""PreToolUse guardrail: block destructive commands outside the project worktree.

Exit 2 = block the tool call. Exit 0 = allow.
Rule: the file-safety rule in this project's rules directory.

The rule is about *writes*. Reading reference data is the pipeline's job - a
pricing pass exists to read price books - so nothing here may block a read.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import sys
from pathlib import Path

# The repo-root names are the rule's own wording and the image's symlinks; data/ is
# where the reference data actually lives in a checkout, and behind those symlinks.
PROTECTED_DIRS = ("pricebooks", "reference-library", "data/pricebooks", "data/reference-library", ".claude")

_SEGMENT_SPLIT = re.compile(r"\|\||&&|[|;&\n()]")
GIT_PUSH = re.compile(r"\bgit\s+push\b")
_HEREDOC_START = re.compile(r"<<-?\s*(['\"]?)(\w+)\1")


PROJECT_ROOT = Path(os.environ.get("CLAUDE_PROJECT_DIR", ".")).resolve()


def _in_protected_dir(path: str) -> bool:
    """True when the path lands inside one of *this project's* read-only directories.

    Resolved and compared against the project root, rather than matched by name.
    The first version asked whether any segment of the path was called ".claude",
    which is true of the user's own home-directory config on every machine - so it
    blocked writes to files with nothing to do with this project's guardrails,
    including their own settings and notes. The rule is about this repository, not
    about a word.

    This is the only authority for path-shaped input. A substring fallback was
    added alongside it once and silently overrode it, which reintroduced exactly
    that bug and additionally blocked read-only commands and any file whose text
    merely mentioned a protected directory. Do not add one back.
    """
    try:
        resolved = Path(path).resolve()
    except (OSError, ValueError):
        return False
    for directory in PROTECTED_DIRS:
        target = (PROJECT_ROOT / directory).resolve()
        if resolved == target or target in resolved.parents:
            return True
    return False


# The built-in tools whose whole purpose is to write a named file.
_WRITES_A_FILE = re.compile(r"^(Write|Edit|MultiEdit|NotebookEdit)$")

_P21_FORBIDDEN = ("write", "update", "insert", "create", "delete", "post")

# MCP tools that write. Their arguments name a destination, so a destination
# inside read-only reference data has to be refused - `save_artifact` pointed at
# a vendor sheet is the case this exists for.
#
# Matched on the verb rather than a list of tool names so a server added later is
# covered by default. Read tools are deliberately not checked: a pricing pass
# exists to read price books, and blocking that was the original bug.
_MCP_WRITE_VERBS = (
    "save", "write", "update", "insert", "upsert",
    "delete", "create", "put", "post", "set_", "remove",
)


def _is_mcp_write(tool_name: str) -> bool:
    lowered = tool_name.lower()
    return lowered.startswith("mcp__") and any(v in lowered for v in _MCP_WRITE_VERBS)


def _strings(value: object) -> list[str]:
    """Every string in a tool's arguments, however deeply nested."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for item in value.values() for s in _strings(item)]
    if isinstance(value, list):
        return [s for item in value for s in _strings(item)]
    return []


# Shell commands that write, and where in their arguments the destination sits.
# "last" is cp/mv-shaped: the final argument is the target, so `cp books/x /tmp/y`
# reads and is fine while `cp /tmp/y books/x` writes and is not. "any" is for
# commands where every path argument is a target.
_WRITE_LAST = ("cp", "mv", "install", "rsync")
# Deletion is a write. Listing it here means it is checked by resolving the target
# like everything else, rather than by substring-matching the command text - which
# fired on any command that merely contained the word and a path, a heredoc
# writing documentation about the rule included.
_WRITE_ANY = (
    "rm", "rmdir", "unlink", "del",
    "remove-item", "ri", "rd", "erase-item",
    "tee", "touch", "mkdir", "truncate", "chmod", "chown", "unzip", "tar",
)
_RECURSIVE_FORCE_CMDS = {
    "rm", "remove-item", "ri", "rd", "erase-item", "del",
}
_INPLACE = ("sed", "perl")
_PYTHON = {"python", "python3", "py"}
_PDF_IMPORT = re.compile(r"(?:^|\s)(?:import|from)\s+(fitz|pymupdf|pypdf)\b")
_PYTHON_WRITE = re.compile(
    r"\bwrite_text\b|\bwrite_bytes\b|\bjson\.dump\b|"
    r"""open\s*\([^)]*['\"](?:w|wb|a|at|wt|ab)['\"]"""
)
_STRING_LIT = re.compile(r"""['\"]([^'\"]+)['\"]""")


def _python_tokens(command: str) -> list[str]:
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        tokens = command.split()
    while tokens and (
        "=" in tokens[0].split("/")[0]
        or Path(tokens[0].strip("([{ ")).name in _WRAPPERS
    ):
        tokens = tokens[1:]
    if not tokens:
        return []
    return [tokens[0].strip("([{ ")] + tokens[1:]


def _is_inline_python_prefix(prefix: str) -> bool:
    """True when this is `python`/`python3` with no .py script argument.

    Only the last command in the prefix counts. In `cd repo && python - <<'PY'`
    the heredoc belongs to `python`, not to `cd` - but this read the whole prefix
    as one command, saw `cd`, and returned False. Every chained invocation
    therefore skipped the inline-python checks completely, which is how a write
    into `.claude/` got through: not because the path sat in a variable, but
    because the body was never examined at all. A bare `python - <<'PY'` was
    blocked the whole time, so the hole only opened once someone wrote the `cd`
    that nearly everyone writes.
    """
    prefix = _SEGMENT_SPLIT.split(prefix)[-1]
    tokens = _python_tokens(prefix)
    if not tokens or Path(tokens[0]).name not in _PYTHON:
        return False
    for token in tokens[1:]:
        if token.startswith("-"):
            continue
        return not token.endswith(".py")
    return True


def _python_dash_c_bodies(command: str) -> list[str]:
    """Every `python -c` program in the command. Quoted `;` / `()` stay inside the body."""
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        tokens = command.split()
    bodies: list[str] = []
    index = 0
    while index < len(tokens):
        name = Path(tokens[index].strip("([{ ")).name
        if name not in _PYTHON:
            index += 1
            continue
        index += 1
        while index < len(tokens):
            token = tokens[index]
            if token == "-c" and index + 1 < len(tokens):
                bodies.append(tokens[index + 1])
                break
            if token.startswith("-c") and len(token) > 2:
                bodies.append(token[2:])
                break
            if not token.startswith("-"):
                break
            index += 1
        index += 1
    return bodies


def _python_heredoc_bodies(command: str) -> list[str]:
    """Bodies of `python <<EOF` / `python3 << 'PY'` — the program, not stdin docs."""
    lines = command.split("\n")
    bodies: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        match = _HEREDOC_START.search(line)
        if not match:
            index += 1
            continue
        prefix = line[: match.start()].rstrip()
        index += 1
        chunk: list[str] = []
        delimiter = match.group(2)
        strip_tabs = match.group(0).startswith("<<-")
        while index < len(lines):
            body = lines[index]
            closed = body.strip() == delimiter or (
                strip_tabs and body.strip().lstrip("\t") == delimiter
            )
            index += 1
            if closed:
                break
            chunk.append(body)
        if _is_inline_python_prefix(prefix):
            bodies.append("\n".join(chunk))
    return bodies


def _inline_python_bodies(command: str) -> list[str]:
    """Program text of `python -c` and `python <<EOF`. Script-file invocations are omitted."""
    return _python_heredoc_bodies(command) + _python_dash_c_bodies(
        _strip_heredoc_bodies(command)
    )


def _python_write_target(body: str) -> str | None:
    if not _PYTHON_WRITE.search(body):
        return None
    for match in _STRING_LIT.finditer(body):
        value = match.group(1)
        if _in_protected_dir(value):
            return value
    return None


def _check_inline_python(command: str) -> int:
    """T-11 / U-9: block inline fitz/pypdf and Python writes into protected dirs."""
    for body in _inline_python_bodies(command):
        if match := _PDF_IMPORT.search(body):
            return block(
                "inline import of fitz/pypdf is blocked; use pdf-tools or parse_schedule.py",
                rule="inline-pdf-lib",
                matched=match.group(0).strip(),
            )
        target = _python_write_target(body)
        if target:
            return block(
                f"{target} is read-only during a run",
                rule="protected-python-write",
                matched=target,
            )
    return 0


def _write_targets(command: str) -> list[str]:
    """Paths this command would write to. Empty for a command that only reads.

    ponytail: recognises write-shaped shell, not all of it. `bash -c`, backticks,
    a variable holding the path, `find -exec` and `xargs` all still get through,
    and no amount of regex closes that. Inline `python -c` / `python <<EOF` is
    checked separately in `_check_inline_python`. This catches accidents and the
    obvious cases, which is what a PreToolUse hook can honestly offer.

    The enforceable boundary is the filesystem: docker-compose mounts all three
    protected directories into the worker read-only (`:ro`), so in the container
    the kernel refuses the write regardless of how it is spelled. Treat this
    function as the local-development and defence-in-depth layer, not the guarantee.
    """
    command = _strip_heredoc_bodies(command)
    # Each stage of a pipeline or chain is its own command: in `echo x | tee sheet`
    # the writer is `tee`, and looking only at the first word would miss it.
    return [
        target
        for segment in re.split(r"\|\||&&|[|;&\n()]", command)
        for target in _segment_write_targets(segment)
    ]


# Words that precede the real command without being it.
_WRAPPERS = ("sudo", "env", "nohup", "time", "command", "exec", "nice", "then", "do")


def _is_flag_token(token: str) -> bool:
    """True for POSIX (`-rf`, `--force`) and Windows (`/s`, `/q`) switches."""
    if token.startswith("-") and token != "-":
        return True
    if token.startswith("/") and 2 <= len(token) <= 3 and token[1:].isalpha():
        return True
    return False


def _segment_write_targets(command: str) -> list[str]:
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        tokens = command.split()
    if not tokens:
        return []

    targets: list[str] = []

    # Find the actual command word. `(cp a b` tokenises with the paren attached,
    # and `cp` != `(cp`, so the write went undetected - that is not a hypothetical:
    # it overwrote a vendor sheet during this work. Leading environment
    # assignments and wrapper words hide the command the same way.
    while tokens and (
        "=" in tokens[0].split("/")[0]
        or Path(tokens[0].strip("([{ ")).name in _WRAPPERS
    ):
        tokens = tokens[1:]
    if not tokens:
        return []
    tokens = [tokens[0].strip("([{ ")] + tokens[1:]

    # Redirection: the token after > or >>, or a >path written without a space.
    for index, token in enumerate(tokens):
        if token in (">", ">>") and index + 1 < len(tokens):
            targets.append(tokens[index + 1])
        elif token.startswith(">") and len(token.lstrip(">")) > 0:
            targets.append(token.lstrip(">"))

    name = Path(tokens[0]).name.lower()
    # Flags and redirection are not path arguments. `2>&1` trailing a command made
    # itself the "last argument" of a cp and hid the real destination behind it.
    # Windows cmd switches (`/s`, `/q`) are flags too, not destinations.
    arguments = [
        t for t in tokens[1:]
        if not _is_flag_token(t) and ">" not in t and "<" not in t
    ]

    if name in _WRITE_LAST and arguments:
        targets.append(arguments[-1])
    elif name in _WRITE_ANY:
        targets.extend(arguments)
    elif name in _INPLACE and any(t.startswith("-") and "i" in t for t in tokens[1:]):
        targets.extend(arguments)

    return targets


def _strip_heredoc_bodies(command: str) -> str:
    """Remove heredoc bodies before scanning command text.

    Heredoc content is stdin for the preceding command, not shell to execute.
    Without this, documentation that merely names a forbidden operation — a table
    row reading ``git push``, a setup note mentioning ``chown … pricebooks`` —
    is indistinguishable from the operation itself.
    """
    lines = command.split("\n")
    kept: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        match = _HEREDOC_START.search(line)
        if not match:
            kept.append(line)
            index += 1
            continue

        # Everything after the marker on the start line is still shell, not body -
        # and it is where the redirection lives. Dropping it meant
        # `cat <<EOF > pricebooks/vendor.csv` was scanned as bare `cat`, so
        # _write_targets saw no target at all and a run could overwrite a vendor
        # sheet: the exact case this guard exists for.
        prefix = line[: match.start()].rstrip()
        suffix = line[match.end():].strip()
        head = " ".join(part for part in (prefix, suffix) if part)
        if head:
            kept.append(head)

        delimiter = match.group(2)
        strip_tabs = match.group(0).startswith("<<-")
        index += 1
        while index < len(lines):
            body = lines[index]
            closed = body.strip() == delimiter or (
                strip_tabs and body.strip().lstrip("\t") == delimiter
            )
            index += 1
            if closed:
                break
    return "\n".join(kept)


def _is_recursive_force_rm(segment: str) -> tuple[bool, str]:
    """True when this segment is a recursive+force delete.

    Covers POSIX `rm -rf` / `rm -r -f` / `rm --recursive --force`, Windows
    `del /s /q`, and PowerShell `Remove-Item -Recurse -Force` (and aliases).
    """
    try:
        tokens = shlex.split(segment, posix=True)
    except ValueError:
        tokens = segment.split()
    while tokens and (
        "=" in tokens[0].split("/")[0] or Path(tokens[0].strip("([{ ")).name in _WRAPPERS
    ):
        tokens = tokens[1:]
    if not tokens:
        return False, ""
    name = Path(tokens[0].strip("([{ ")).name.lower()
    if name not in _RECURSIVE_FORCE_CMDS:
        return False, ""

    recursive = force = False
    flags: list[str] = []
    for token in tokens[1:]:
        if not _is_flag_token(token):
            continue
        flags.append(token)
        lowered = token.lower()
        if lowered in ("--recursive", "-recurse", "/s"):
            recursive = True
        elif lowered in ("--force", "-force", "/q", "/f"):
            force = True
        elif token.startswith("--"):
            recursive |= lowered == "--recursive"
            force |= lowered == "--force"
        elif token.startswith("/"):
            recursive |= "s" in lowered
            force |= "q" in lowered or "f" in lowered
        else:
            recursive |= "r" in lowered
            force |= "f" in lowered
    return recursive and force, (name + " " + " ".join(flags)).strip()


def _projects_roots() -> tuple[Path, ...]:
    """Where a bid's working files may live, same precedence as storage_root().

    This asked only about `<repo>/projects`, which has not existed since projects
    moved under `data/`. So `rm -rf data/projects/<bid>/uploads/processed` - a
    delete the file-safety rule explicitly permits - came back as "outside
    project scope", and the only way to tidy a project directory was to turn the
    guard off.

    `<repo>/projects` stays in the list: a sandboxed run is handed its own clone
    through CBC_PROJECTS_ROOT and may still use that name.
    """
    roots = []
    for var in ("CBC_PROJECTS_ROOT", "STORAGE_ROOT"):
        value = os.environ.get(var)
        if value:
            roots.append(Path(value))
    roots.append(PROJECT_ROOT / "data" / "projects")
    roots.append(PROJECT_ROOT / "projects")
    resolved = []
    for root in roots:
        try:
            resolved.append(root.resolve())
        except (OSError, ValueError):
            continue
    return tuple(resolved)


def _under_projects(path: str) -> bool:
    """True when the path resolves inside a projects tree this run owns."""
    try:
        resolved = Path(path).resolve()
    except (OSError, ValueError):
        return False
    return any(
        resolved == workspaces or workspaces in resolved.parents
        for workspaces in _projects_roots()
    )


# Checkpoint artifacts must go through save_artifact (schema + versioning).
# Bare Write/Edit bypasses MCP validation and caused invalid line_items.json
# to land on disk (thickness / page_size array) while the agent reported success.
_CHECKPOINT_ARTIFACTS = frozenset(
    {
        "extracted/scope_metadata.json",
        "extracted/scope_summary.json",
        "extracted/line_items.json",
        "extracted/frp_takeoff.json",
        "extracted/div10_takeoff.json",
        "extracted/hardware_sets.json",
        "priced/line_items.json",
    }
)

# Artifacts `propose_patch` can actually edit. It addresses openings by door
# number, so it understands the door schedule and nothing else yet. Withdrawing
# whole-file authority for an artifact it cannot edit would leave no way to write
# that artifact at all, which is a worse failure than a whole-file write.
_PATCHABLE_ARTIFACTS = frozenset({"extracted/line_items.json"})


def _seeded_file_exists(project: str, rel: str) -> bool:
    """True only when the seeded artifact is positively there.

    Unknown counts as absent, so the write is allowed. A bid whose schedule will
    not parse has no seed, and `propose_patch` edits rather than creates - a
    guard that fails closed here would strand that run with no way to produce the
    artifact. The schema gate still runs on whichever path the write takes.
    """
    if not project:
        return False
    # Resolved without importing `cbc`. The hook runs in a bare interpreter where
    # that import fails - the first version of this check relied on it, caught the
    # ImportError, and so answered "absent" every single time, which made the whole
    # rule dead code that looked live.
    roots = [
        os.environ.get("CBC_PROJECTS_ROOT"),
        os.environ.get("STORAGE_ROOT"),
        str(PROJECT_ROOT / "data" / "projects"),
        str(PROJECT_ROOT / "projects"),
    ]
    for root in roots:
        if not root:
            continue
        try:
            if (Path(root) / project / rel).is_file():
                return True
        except (OSError, ValueError):
            continue
    return False


def _checkpoint_relpath(path: str) -> str | None:
    """Return the checkpoint-relative path if this Write targets one."""
    try:
        from _artifact_path import project_path_from_tool, slashes
    except ImportError:
        normalized = path.replace("\\", "/")
        for rel in _CHECKPOINT_ARTIFACTS:
            if normalized.endswith("/" + rel) or normalized.endswith(rel):
                return rel
        return None
    resolved = project_path_from_tool("Write", {"file_path": path})
    if not resolved:
        normalized = slashes(path)
        for rel in _CHECKPOINT_ARTIFACTS:
            if normalized.endswith("/" + rel) or normalized == rel:
                return rel
        return None
    _project, rel = resolved
    rel = rel.replace("\\", "/")
    return rel if rel in _CHECKPOINT_ARTIFACTS else None


def block(reason: str, *, rule: str | None = None, matched: str | None = None) -> int:
    detail = reason
    if rule or matched:
        tags = [part for part in (f"rule={rule}" if rule else None,
                                  f"matched={matched!r}" if matched else None)
                if part]
        detail = f"{reason} ({', '.join(tags)})"
    print(f"BLOCKED: {detail} (file-safety rule).", file=sys.stderr)
    return 2


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0
    return check(payload)


def check(payload: dict) -> int:
    tool_input = payload.get("tool_input") or {}
    tool_name = str(payload.get("tool_name") or "")

    # Write / Edit / NotebookEdit name their target instead of carrying a command.
    #
    # Only for tools that WRITE. This matcher also covers every mcp__ tool, and
    # `file_path` is the ordinary name for a read tool's input too - so applying
    # it to all of them blocked `pdf-tools` from opening a price book. That is the
    # one read the pricing pass exists to make: a run found the right page, was
    # refused the file, and wrote all 27 lines MANUAL rather than priced.
    if _WRITES_A_FILE.match(tool_name) or _is_mcp_write(tool_name):
        target = str(tool_input.get("file_path") or tool_input.get("notebook_path") or "")
        if target and _in_protected_dir(target):
            return block(
                f"{target} is read-only during a run",
                rule="protected-write-tool",
                matched=target,
            )
        # Bare Write/Edit of extraction checkpoints skips save_artifact schema
        # validation. Force the MCP path instead.
        if _WRITES_A_FILE.match(tool_name) and target:
            checkpoint = _checkpoint_relpath(target)
            if checkpoint:
                return block(
                    f"{checkpoint} must be written via mcp__artifact-storage__save_artifact "
                    "(not Write/Edit) so schema validation and versioning run",
                    rule="checkpoint-save-artifact",
                    matched=target,
                )

    # Whole-file authorship of a checkpoint Python already seeded. A pass that
    # rewrites the document puts one bad key between the run and everything the
    # earlier phases produced - three runs on one bid died that way, on
    # `thickness`, on `page_size`, on `flags`. `propose_patch` validates each
    # field on its own, so a bad one costs that field and leaves a review flag.
    if tool_name == "mcp__artifact-storage__save_artifact":
        rel = str(tool_input.get("path") or "").replace("\\", "/").lstrip("/")
        project = str(tool_input.get("project") or "")
        if rel in _PATCHABLE_ARTIFACTS and _seeded_file_exists(project, rel):
            return block(
                f"{rel} is already seeded - change named fields with "
                "mcp__artifact-storage__propose_patch instead of replacing the file. "
                "Each patch is validated on its own, so a rejected one costs that "
                "field rather than the run.",
                rule="checkpoint-propose-patch",
                matched=rel,
            )

    if tool_name.startswith("mcp__p21-connector__"):
        lower = tool_name.lower()
        if any(word in lower for word in _P21_FORBIDDEN):
            return block("P21 write tools are forbidden (NFR-5)", rule="nfr-5", matched=tool_name)

    # A writing MCP tool aimed at read-only reference data. Resolved against the
    # project root like every other path here, never substring-matched - the
    # substring version of this check is what blocked reads, unrelated homedirs,
    # and any file whose text merely mentioned a protected directory.
    if _is_mcp_write(tool_name):
        for value in _strings(tool_input):
            if _in_protected_dir(value):
                return block(
                    f"{value} is read-only during a run",
                    rule="protected-mcp-write",
                    matched=value,
                )

    command = str(tool_input.get("command") or "")
    if not command:
        return 0

    blocked = _check_inline_python(command)
    if blocked:
        return blocked

    scan = _strip_heredoc_bodies(command)

    if match := GIT_PUSH.search(scan):
        return block(
            "git push is not permitted from the pipeline",
            rule="git-push",
            matched=match.group(0),
        )

    # Scope is decided by where the delete targets resolve, never by whether the
    # command text happens to contain the word. The substring test this replaces
    # was switched off by `projects/` appearing anywhere at all - a trailing
    # comment was enough to permit a recursive delete of any path on the machine.
    for segment in _SEGMENT_SPLIT.split(scan):
        is_rm_rf, flags = _is_recursive_force_rm(segment)
        if not is_rm_rf:
            continue
        targets = _segment_write_targets(segment)
        outside = [target for target in targets if not _under_projects(target)]
        if outside or not targets:
            return block(
                "File deletion outside project scope is prohibited",
                rule="rm-rf-outside-projects",
                matched=outside[0] if outside else flags,
            )

    # Writing into reference data by any other means. The rule says a run never
    # writes to these directories, but the check only ever ran inside an `rm`, so
    # `echo x > <a vendor sheet>` went straight through. Resolved per target, so a
    # command that merely reads from those directories is untouched.
    for target in _write_targets(command):
        if _in_protected_dir(target):
            return block(
                f"{target} is read-only during a run",
                rule="protected-bash-write",
                matched=target,
            )

    return 0


if __name__ == "__main__":
    sys.exit(main())
