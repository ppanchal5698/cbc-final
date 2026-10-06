#!/usr/bin/env python3
"""PreToolUse guardrail: block destructive commands outside the project worktree.

Exit 2 = block the tool call. Exit 0 = allow.
Rule: the file-safety rule in this project's rules directory.

The rule is about *writes*. Reading reference data is the pipeline's job - a
pricing pass exists to read price books - so nothing here may block a read.

Bash commands are read through `_shell`, which tokenises them the way a shell
does - quotes, heredocs, chains, `cd`, `git -C`, subshells, `bash -c`, `xargs`,
`find -exec` - so a quoted "git push" in a commit message is not a push, and a
`cd .claude && rm x` is a delete inside `.claude`.

This is a backstop, not the guarantee. `.claude` and `reference-library` are
mounted read-only (`:ro`) into every container, so there the kernel refuses a
write however it is spelled. `data/pricebooks` is not: platform writes it
(uploads, deletes), the worker writes the page index, and worker and parser
download missing books from Blob storage into it - so for price books this hook
is the only guard inside a container. A path assembled at run time
(`'.cla' + 'ude'`) is beyond any text check; see the patches README for the
controls that do not depend on reading a command.
"""
from __future__ import annotations

import json
import os
import posixpath
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _shell  # noqa: E402  (a sibling module; the hook runs as a script)

# The repo-root names are the rule's own wording and the image's symlinks; data/ is
# where the reference data actually lives in a checkout, and behind those symlinks.
PROTECTED_DIRS = ("pricebooks", "reference-library", "data/pricebooks", "data/reference-library", ".claude")

PROJECT_ROOT = Path(os.environ.get("CLAUDE_PROJECT_DIR", ".")).resolve()


def _protected_roots() -> list[Path]:
    return [(PROJECT_ROOT / directory).resolve() for directory in PROTECTED_DIRS]


def _is_protected(path: Path | None) -> bool:
    """True when a resolved path lands inside one of *this project's* read-only dirs.

    Resolved and compared against the project root, rather than matched by name.
    The first version asked whether any segment of the path was called ".claude",
    which is true of the user's own home-directory config on every machine - so it
    blocked writes to files with nothing to do with this project's guardrails. The
    rule is about this repository, not about a word. Do not add a substring
    fallback back: one once silently overrode this and reintroduced exactly that.
    """
    if path is None:
        return False
    return any(path == root or root in path.parents for root in _protected_roots())


def _covers_protected(path: Path | None) -> bool:
    """Protected, or a directory that contains one - `.` and the repo root included."""
    if path is None:
        return False
    return _is_protected(path) or any(path in root.parents for root in _protected_roots())


def _in_protected_dir(path: str, cwd: str | None = None) -> bool:
    return _is_protected(_shell.resolve(path, cwd or os.getcwd()))


# The built-in tools whose whole purpose is to write a named file.
_WRITES_A_FILE = re.compile(r"^(Write|Edit|MultiEdit|NotebookEdit)$")

_P21_FORBIDDEN = ("write", "update", "insert", "create", "delete", "post")

# MCP tools that write. Their arguments name a destination, so a destination
# inside read-only reference data has to be refused - `save_artifact` pointed at
# a vendor sheet is the case this exists for.
#
# Matched on the verb rather than a list of tool names so a server added later is
# covered by default. Read tools are deliberately not checked: a pricing pass
# exists to read price books, and blocking that was the original bug. Verbs are
# matched per word of the tool name - a substring test found `put` in
# `compute_totals`.
_MCP_WRITE_VERBS = ("save", "write", "update", "insert", "upsert", "delete", "create",
                    "remove", "patch", "append", "upload", "rename", "move")
_MCP_WRITE_WORDS = {"put", "post", "set"}


def _is_mcp_write(tool_name: str) -> bool:
    lowered = tool_name.lower()
    if not lowered.startswith("mcp__"):
        return False
    words = re.split(r"[_\-]+", lowered.rsplit("__", 1)[-1])
    return any(w in _MCP_WRITE_WORDS or w.startswith(_MCP_WRITE_VERBS) for w in words)


def _strings(value: object) -> list[str]:
    """Every string in a tool's arguments, however deeply nested."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for item in value.values() for s in _strings(item)]
    if isinstance(value, list):
        return [s for item in value for s in _strings(item)]
    return []


# ── what a shell command writes ─────────────────────────────────────────────

# "last" is cp/mv-shaped: the final argument is the target, so `cp books/x /tmp/y`
# reads and is fine while `cp /tmp/y books/x` writes and is not. "any" is for
# commands where every path argument is a target. Deletion is a write too:
# resolving its targets like everything else, rather than substring-matching the
# command text, is what stops a heredoc documenting the rule from tripping it.
_WRITE_LAST = {"cp", "mv", "install", "rsync", "ln", "copy-item", "cpi", "copy",
               "move-item", "mi", "move", "rename-item", "rni", "ren"}
_WRITE_ANY = {"rm", "rmdir", "unlink", "del", "remove-item", "ri", "rd", "erase-item",
              "erase", "tee", "tee-object", "touch", "mkdir", "md", "truncate", "chmod",
              "chown", "chgrp", "shred", "set-content", "sc", "add-content", "ac",
              "out-file", "new-item", "ni", "clear-content", "clc"}
_RECURSIVE_FORCE_CMDS = {"rm", "remove-item", "ri", "rd", "erase-item", "del"}
_INPLACE = {"sed", "perl"}
_FILE_REDIRECTS = {">", ">>", ">|", "&>", "&>>", "<>"}
# PowerShell parameters that name the file a cmdlet writes.
_PS_PATH_PARAMS = {"-path", "-literalpath", "-filepath", "-destination", "-dest"}


def _arguments(words: list[str]) -> list[str]:
    """Path-shaped arguments: flags and redirection fragments are not destinations."""
    return [w for w in words[1:] if not _shell.is_flag(w) and ">" not in w and "<" not in w]


def _tar_targets(words: list[str]) -> list[str]:
    """`tar` writes its archive when creating, and its directory when extracting.

    Every argument used to count as a target, so `tar -czf /tmp/b.tgz .claude` -
    a read of `.claude` - was blocked as a write into it.
    """
    args = words[1:]
    if not args:
        return []
    letters = "".join(a.lstrip("-") for a in args if a.startswith("-") and not a.startswith("--"))
    if not args[0].startswith("-"):
        letters += args[0]  # old style: `tar czf out.tgz dir`
    longs = {a.split("=", 1)[0] for a in args if a.startswith("--")}
    archive = directory = None
    for index, arg in enumerate(args):
        if arg.startswith("--file="):
            archive = arg.split("=", 1)[1]
        elif arg == "--file" or (not arg.startswith("--") and arg.lstrip("-").endswith("f")
                                 and (arg.startswith("-") or index == 0)):
            archive = args[index + 1] if index + 1 < len(args) else None
        if arg in ("-C", "--directory") and index + 1 < len(args):
            directory = args[index + 1]
        elif arg.startswith("--directory="):
            directory = arg.split("=", 1)[1]
    targets = []
    if (set(letters) & set("cru")) or longs & {"--create", "--append", "--update"}:
        if archive:
            targets.append(archive)
    if "x" in letters or longs & {"--extract", "--get"}:
        targets.append(directory or ".")
    return targets


def _in_place(words: list[str]) -> bool:
    """`sed -i`, `-i.bak`, `--in-place`, `perl -pi`; never `--quiet`, which only has an i."""
    for word in words[1:]:
        if word == "--in-place" or word.startswith("--in-place="):
            return True
        if word.startswith("-") and not word.startswith("--") and "i" in word[1:]:
            return True
    return False


def _powershell_targets(words: list[str]) -> list[str]:
    named = [words[i + 1] for i, w in enumerate(words[:-1]) if w.lower() in _PS_PATH_PARAMS]
    if named:
        return named
    positional = [w for w in words[1:] if not w.startswith("-")]
    return positional[-1:] if base_name_is(words, _WRITE_LAST) else positional[:1]


def base_name_is(words: list[str], names: set[str]) -> bool:
    return bool(words) and _shell.base_name(words[0]) in names


def _command_targets(command: _shell.Command) -> list[tuple[str, str]]:
    """(word, directory it resolves against) for every path this command writes."""
    words, name = command.words, command.name
    targets: list[tuple[str, str]] = []
    for op, target in command.redirects:
        if op in _FILE_REDIRECTS or (op == ">&" and not target.isdigit() and target != "-"):
            targets.append((target, command.shell_cwd))
    paths: list[str] = []
    if "-" in name and (name in _WRITE_ANY or name in _WRITE_LAST):
        paths = _powershell_targets(words)
    elif name in _WRITE_LAST:
        destination = next((words[i + 1] for i, w in enumerate(words[:-1])
                            if w in ("-t", "--target-directory")), None)
        destination = destination or next(
            (w.split("=", 1)[1] for w in words if w.startswith("--target-directory=")), None)
        arguments = _arguments(words)
        paths = [destination] if destination else arguments[-1:]
    elif name in _WRITE_ANY:
        paths = _arguments(words)
    elif name == "tar":
        paths = _tar_targets(words)
    elif name == "unzip":
        paths = [next((words[i + 1] for i, w in enumerate(words[:-1]) if w == "-d"), ".")]
    elif name == "dd":
        paths = [w[3:] for w in words[1:] if w.startswith("of=")]
    elif name in _INPLACE and _in_place(words):
        paths = _arguments(words)
    targets.extend((path, command.cwd) for path in paths)
    return targets


# ── git: push, and writes into protected paths ──────────────────────────────

_GIT_GLOBAL_WITH_VALUE = {"-C", "-c", "--git-dir", "--work-tree", "--namespace",
                          "--exec-path", "--super-prefix", "--config-env"}
_GIT_PUSHES = {"push", "send-pack", "http-push"}
_GIT_APPLY_READ_ONLY = {"--check", "--stat", "--numstat", "--summary"}
_PATCH_PATH = re.compile(r"^(?:\+\+\+|---) (?:[ab]/)?(\S.*?)\s*$|^diff --git a/(\S+) b/(\S+)|"
                         r"^(?:rename|copy) (?:from|to) (\S.*)$", re.M)


def _git(words: list[str]) -> tuple[str | None, list[str], str | None]:
    """(subcommand, its arguments, the -C directory) of a `git ...` command."""
    index, directory = 1, None
    while index < len(words):
        word = words[index]
        if word in _GIT_GLOBAL_WITH_VALUE and index + 1 < len(words):
            if word == "-C":
                directory = words[index + 1]
            index += 2
            continue
        if word.startswith("-"):
            index += 1
            continue
        return word, words[index + 1:], directory
    return None, [], directory


def _patch_paths(text: str) -> list[str]:
    paths = []
    for match in _PATCH_PATH.finditer(text):
        for group in match.groups():
            if group and group != "/dev/null":
                paths.append(group)
    return paths


def _pathspecs(args: list[str], with_value: set[str]) -> list[str]:
    specs, index = [], 0
    while index < len(args):
        arg = args[index]
        if arg == "--":
            specs.extend(args[index + 1:])
            break
        if arg in with_value:
            index += 2
            continue
        if not arg.startswith("-"):
            specs.append(arg)
        index += 1
    return specs


def _check_git(command: _shell.Command) -> int:
    words = command.words
    if command.name != "git":
        return 0
    sub, args, directory = _git(words)
    # An alias made to push - `git -c alias.p=push p`, `git config alias.p push` -
    # is caught where it is made, since its later use names no push at all.
    if any(w.startswith("alias.") or "=" in w and w.split("=")[0].startswith("alias.")
           for w in words) and any("push" in w for w in words):
        return block("a git alias that pushes is not permitted from the pipeline",
                     rule="git-push", matched=" ".join(words)[:80])
    if sub in _GIT_PUSHES:
        return block("git push is not permitted from the pipeline", rule="git-push",
                     matched=f"git {sub}")
    if sub is None:
        return 0
    cwd = command.cwd
    if directory:
        resolved = _shell.resolve(directory, cwd)
        cwd = str(resolved) if resolved else _shell.UNKNOWN

    def refuse(target: str) -> int:
        return block(f"git {sub} would write {target}, which is read-only during a run",
                     rule="git-protected-write", matched=target)

    if sub in ("apply", "am"):
        if sub == "apply" and set(args) & _GIT_APPLY_READ_ONLY and "--apply" not in args:
            return 0
        files = [a for a in args if not a.startswith("-")]
        texts = []
        for name in files:
            path = _shell.resolve(name, cwd)
            try:
                texts.append(path.read_text(encoding="utf-8", errors="replace") if path else None)
            except OSError:
                texts.append(None)
        if not files or "-" in files:
            texts.append(command.stdin)
        if any(text is None for text in texts):
            return block(f"git {sub}: cannot tell which files this patch writes; apply it "
                         "outside the agent session", rule="git-protected-write",
                         matched=" ".join(files) or "stdin")
        for text in texts:
            for target in _patch_paths(text or ""):
                if _is_protected(_shell.resolve(target, cwd)):
                    return refuse(target)
        return 0
    if sub in ("restore", "checkout", "update-index"):
        positional = [a for a in args if not a.startswith("-")]
        if sub == "checkout" and "--" not in args and len(positional) < 2:
            # One word is a branch to switch to - unless it names a path on disk,
            # as `git checkout .` does: that restores everything under it.
            path = _shell.resolve(positional[0], cwd) if positional else None
            if path is not None and path.exists() and _covers_protected(path):
                return refuse(positional[0])
            return 0
        if sub == "update-index" and ({"--stdin", "--index-info"} & set(args)):
            return refuse("paths read from stdin")
        if any(a.startswith("--pathspec-from-file") for a in args):
            return refuse("paths read from a file")
        with_value = {"-s", "--source", "--conflict", "--cacheinfo", "--chmod", "-b", "-B"}
        specs = _pathspecs(args, with_value)
        if sub == "checkout" and "--" not in args:
            specs = specs[1:]  # `git checkout <tree-ish> <path>...`
        for spec in specs:
            plain = spec[2:] or "." if spec.startswith(":/") else spec  # `:/` is the repo top
            if _covers_protected(_shell.resolve(plain, cwd)):
                return refuse(spec)
    return 0


# ── inline code ─────────────────────────────────────────────────────────────

_PDF_IMPORT = re.compile(
    r"(?:^|[\s;])(?:import|from)\s+(fitz|pymupdf|pypdf)\b"
    r"|(?:__import__|import_module)\(\s*['\"](fitz|pymupdf|pypdf)\b"
)
# Calls that write a file, in the languages a command can run inline. Paired with a
# string literal that resolves into a protected dir, which is the actual signal.
_CODE_WRITE = re.compile(
    r"\bwrite_text\b|\bwrite_bytes\b|\bjson\.dump\b|"
    r"""\bopen\s*\([^)]*['\"](?:[wax]b?\+?|r\+b?|[wa]t)['\"]|"""
    r"\bos\.(?:replace|rename|remove|unlink|rmdir|makedirs|mkdir|symlink|link)\b|"
    r"\bshutil\.\w+|\.(?:unlink|rename|replace|mkdir|touch|rmdir|symlink_to)\s*\(|"
    r"\b(?:writeFile|writeFileSync|appendFile|appendFileSync|copyFile|copyFileSync|"
    r"renameSync|rmSync|unlinkSync|mkdirSync|createWriteStream|cpSync|symlinkSync)\b|"
    r"\bFile(?:Utils)?\.\w+|\bIO\.write\b|\bopen\s*\(?\s*\w+\s*,\s*['\"]\+?[>]|"
    r"\b(?:rename|unlink|copy|move)\s*\("
)
_STRING_LIT = re.compile(r"""['"]([^'"\n]+)['"]""")


def _check_inline_code(command: _shell.Command) -> int:
    """T-11 / U-9: inline fitz/pypdf, and inline code writing into protected dirs."""
    program = _shell.python_program(command)
    if program is not None and (match := _PDF_IMPORT.search(program)):
        return block(
            "inline import of fitz/pymupdf/pypdf is blocked; use pdf-tools or parse_schedule.py",
            rule="inline-pdf-lib",
            matched=match.group(0).strip(),
        )
    code = _shell.inline_code(command)
    if code and _CODE_WRITE.search(code):
        for match in _STRING_LIT.finditer(code):
            value = match.group(1)
            if _is_protected(_shell.resolve(value, command.cwd)):
                rule = "protected-python-write" if program is not None else "protected-code-write"
                return block(f"{value} is read-only during a run", rule=rule, matched=value)
    return 0


# ── deletes ─────────────────────────────────────────────────────────────────

def _is_recursive_force_rm(words: list[str]) -> tuple[bool, str]:
    """True when this is a recursive+force delete.

    Covers POSIX `rm -rf` / `rm -r -f` / `rm --recursive --force`, Windows
    `del /s /q`, and PowerShell `Remove-Item -Recurse -Force` (and aliases).
    """
    if not words or _shell.base_name(words[0]) not in _RECURSIVE_FORCE_CMDS:
        return False, ""
    recursive = force = False
    flags: list[str] = []
    for token in words[1:]:
        if not _shell.is_flag(token):
            continue
        flags.append(token)
        lowered = token.lower()
        if lowered in ("--recursive", "-recurse", "/s"):
            recursive = True
        elif lowered in ("--force", "-force", "/q", "/f"):
            force = True
        elif token.startswith("--"):
            continue
        elif token.startswith("/"):
            recursive |= "s" in lowered
            force |= "q" in lowered or "f" in lowered
        else:
            recursive |= "r" in lowered
            force |= "f" in lowered
    return recursive and force, (_shell.base_name(words[0]) + " " + " ".join(flags)).strip()


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


def _under_projects(path: str | Path | None, cwd: str | None = None) -> bool:
    """True when the path resolves inside a projects tree this run owns."""
    if path is None:
        return False
    resolved = path if isinstance(path, Path) else _shell.resolve(path, cwd or os.getcwd())
    if resolved is None:
        return False
    return any(resolved == root or root in resolved.parents for root in _projects_roots())


# ── checkpoint artifacts ────────────────────────────────────────────────────

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

# The preprice seed's `source` stamp. Owner: cbc.modules.pricing.api.preprice.SOURCE
# - duplicated because this hook must not import `cbc` (see _seeded_file_exists),
# and tests/system/test_integrity.py asserts the two still match.
_PREPRICE_SOURCE = "preprice.py (deterministic pre-pricing)"

# Artifacts Python seeds and `propose_patch` edits in place (openings by door
# number, priced lines by line_id), each with the `source` stamp that makes a
# file on disk a seed, or None when any file there is one. Only preprice's own
# priced file counts: with PREPRICE_SEED=0 the pricing pass writes that file
# whole with save_artifact, and withdrawing that would leave it no way to write
# the file at all - a worse failure than a whole-file write.
_PATCHABLE_ARTIFACTS = {
    "extracted/line_items.json": None,
    "priced/line_items.json": _PREPRICE_SOURCE,
}


def _seeded_file_exists(project: str, rel: str, stamp: str | None = None) -> bool:
    """True only when the seeded artifact is positively there and, given a
    stamp, carries it.

    Unknown counts as absent, so the write is allowed. A bid whose schedule will
    not parse has no seed, and `propose_patch` edits rather than creates - a
    guard that fails closed here would strand that run with no way to produce the
    artifact. The schema gate still runs on whichever path the write takes.

    Only the root this run owns is consulted, in storage_root()'s order. Falling
    through from a sandbox's clone to the live data/projects let a seed the run
    does not own block it.
    """
    if not project:
        return False
    # Resolved without importing `cbc`. The hook runs in a bare interpreter where
    # that import fails - the first version of this check relied on it, caught the
    # ImportError, and so answered "absent" every single time, which made the whole
    # rule dead code that looked live.
    explicit = [v for v in (os.environ.get("CBC_PROJECTS_ROOT"), os.environ.get("STORAGE_ROOT")) if v]
    roots = explicit[:1] or [str(PROJECT_ROOT / "data" / "projects"), str(PROJECT_ROOT / "projects")]
    for root in roots:
        try:
            path = Path(root) / project / rel
            if not path.is_file():
                continue
            if stamp is None:
                return True
            # An unreadable file is unknown, and unknown is absent (above).
            return json.loads(path.read_text(encoding="utf-8")).get("source") == stamp
        except (OSError, ValueError, AttributeError):
            continue
    return False


def _artifact_rel(path: str, project: str) -> str:
    """`./priced/x`, `projects/<bid>/priced/x` and `priced\\x` are one artifact."""
    rel = posixpath.normpath(path.replace("\\", "/")).lstrip("/")
    prefix = f"projects/{project}/"
    return rel[len(prefix):] if project and rel.startswith(prefix) else rel


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
    cwd = str(payload.get("cwd") or os.getcwd())

    # Write / Edit / NotebookEdit name their target instead of carrying a command.
    #
    # Only for tools that WRITE. This matcher also covers every mcp__ tool, and
    # `file_path` is the ordinary name for a read tool's input too - so applying
    # it to all of them blocked `pdf-tools` from opening a price book. That is the
    # one read the pricing pass exists to make: a run found the right page, was
    # refused the file, and wrote all 27 lines MANUAL rather than priced.
    if _WRITES_A_FILE.match(tool_name) or _is_mcp_write(tool_name):
        target = str(tool_input.get("file_path") or tool_input.get("notebook_path") or "")
        if target and _in_protected_dir(target, cwd):
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
        project = str(tool_input.get("project") or "")
        rel = _artifact_rel(str(tool_input.get("path") or ""), project)
        if rel in _PATCHABLE_ARTIFACTS and _seeded_file_exists(
            project, rel, _PATCHABLE_ARTIFACTS[rel]
        ):
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
            if _in_protected_dir(value, cwd):
                return block(
                    f"{value} is read-only during a run",
                    rule="protected-mcp-write",
                    matched=value,
                )

    command = str(tool_input.get("command") or "")
    if not command:
        return 0
    return check_command(command, cwd)


def check_command(command: str, cwd: str) -> int:
    """Every simple command the text runs, nested ones included."""
    for simple in _shell.parse(command, cwd):
        for check_one in (_check_git, _check_inline_code):
            verdict = check_one(simple)
            if verdict:
                return verdict

        # Scope is decided by where the delete targets resolve, never by whether
        # the command text happens to contain a word. The substring test this
        # replaced was switched off by `projects/` appearing in a trailing comment.
        is_rm_rf, flags = _is_recursive_force_rm(simple.words)
        if is_rm_rf:
            targets = [w for w in simple.words[1:] if not _shell.is_flag(w)]
            outside = [t for t in targets if not _under_projects(_shell.resolve(t, simple.cwd))]
            if outside or not targets:
                shown = outside[0].replace(_shell.UNKNOWN, "?") if outside else flags
                return block("File deletion outside project scope is prohibited",
                             rule="rm-rf-outside-projects", matched=shown)

        # Writing into reference data by any means. Resolved per target, so a
        # command that only reads from those directories is untouched.
        for target, base in _command_targets(simple):
            if _is_protected(_shell.resolve(target, base)):
                return block(f"{target} is read-only during a run",
                             rule="protected-bash-write", matched=target)
    return 0


if __name__ == "__main__":
    sys.exit(main())
