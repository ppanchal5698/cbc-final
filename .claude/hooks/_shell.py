"""What a Bash command line runs, read the way a shell reads it.

The guards used to search the raw command text. That is blind to quoting and to
everything a shell does before it runs a word: `git commit -m "never git push"`
read as a push, `cd .claude && rm x` as a delete in the current directory, and
`git -C . push`, a `bash <<EOF` body, `bash -c "..."` and `$(...)` were not seen
at all. This tokenises quotes, escapes, operators, heredocs, substitutions,
subshells and the wrappers in front of a command (`sudo`, `env`, `uv run`,
`docker exec`, `xargs`, `find -exec`), and hands each guard the simple commands
that would actually run, each with the directory it runs in.

It is a backstop, not a shell: no globbing, functions, aliases or arithmetic. A
word only the running shell could know - an unset `$VAR`, a `$(...)` result - is
UNKNOWN rather than a guess, and each guard decides what unknown means for it.
"""
from __future__ import annotations

import base64
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

UNKNOWN = "\x00"  # stands in for text only the running shell could supply

_MAX_DEPTH = 8  # nested `bash -c "bash -c ..."` beyond this is not followed


@dataclass
class Command:
    """One simple command: what runs, with the wrappers in front removed."""

    words: list[str]
    cwd: str  # where the command runs; UNKNOWN once a `cd` target was
    shell_cwd: str  # where the shell is - redirections resolve against this
    redirects: list[tuple[str, str]] = field(default_factory=list)
    stdin: str | None = None  # heredoc or here-string body
    stdin_from: "Command | None" = None  # the command piped into this one
    reads_shell: bool = False  # a shell that takes its script on stdin

    @property
    def name(self) -> str:
        return base_name(self.words[0]) if self.words else ""


def base_name(word: str) -> str:
    """`/usr/bin/python3.exe` -> `python3`: the program, not its path."""
    name = re.split(r"[\\/]", word)[-1].lower()
    return name[:-4] if name.endswith(".exe") else name


def is_flag(word: str) -> bool:
    """POSIX (`-rf`, `--force`) and Windows (`/s`, `/q`) switches."""
    if word.startswith("-") and word != "-":
        return True
    return word.startswith("/") and 2 <= len(word) <= 3 and word[1:].isalpha()


# ── paths ───────────────────────────────────────────────────────────────────

_MSYS_DRIVE = re.compile(r"^/(?:cygdrive/|mnt/)?([A-Za-z])(?=/|$)")


def native(path: str) -> str:
    """Git-Bash, Cygwin and WSL spell C:\\x as /c/x, /cygdrive/c/x and /mnt/c/x."""
    if os.name == "nt":
        match = _MSYS_DRIVE.match(path)
        if match:
            path = f"{match.group(1).upper()}:" + (path[match.end():] or "/")
    return path


def resolve(word: str, cwd: str) -> Path | None:
    """The absolute, symlink-resolved path a word names, or None when unknown."""
    if not word or UNKNOWN in word:
        return None
    path = Path(native(word))
    if not path.is_absolute():
        if not cwd or UNKNOWN in cwd:
            return None
        path = Path(native(cwd)) / path
    try:
        return path.resolve()
    except (OSError, RuntimeError, ValueError):
        return None


# ── wrappers: the words in front of the real command ───────────────────────

_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_RESERVED = {"if", "then", "else", "elif", "fi", "do", "done", "while", "until", "!", "{", "}", "time"}
_NOT_A_COMMAND = {"for", "select", "case", "function", "esac", "in"}

# Options of each wrapper that take a value, so the value is not read as the command.
_WRAPPERS: dict[str, set[str]] = {
    "sudo": {"-u", "-g", "-C", "-D", "-h", "-p", "-r", "-t", "-U", "--user", "--group",
             "--chdir", "--host", "--prompt", "--role", "--type", "--other-user"},
    "doas": {"-u", "-C"},
    "env": {"-u", "--unset", "-C", "--chdir", "-S", "--split-string"},
    "nice": {"-n", "--adjustment"},
    "ionice": {"-c", "-n", "-p", "--class", "--classdata", "--pid"},
    "stdbuf": {"-i", "-o", "-e", "--input", "--output", "--error"},
    "timeout": {"-s", "-k", "--signal", "--kill-after"},
    "nohup": set(),
    "command": set(),
    "builtin": set(),
    "exec": {"-a"},
    "chronic": set(),
    "watch": {"-n", "--interval", "-d"},
}
# `<tool> run ...` style launchers, and their options that take a value.
_RUNNERS: dict[tuple[str, ...], set[str]] = {
    ("uv", "run"): {"--with", "--python", "-p", "--project", "--directory", "--package",
                    "--extra", "--env-file", "--group", "--index", "--with-requirements"},
    ("uvx",): {"--with", "--python", "-p", "--from", "--index"},
    ("pipx", "run"): {"--spec", "--python"},
    ("poetry", "run"): {"-C", "--directory", "-P", "--project"},
    ("pipenv", "run"): set(),
    ("pdm", "run"): {"-p", "--project"},
    ("hatch", "run"): set(),
    ("rye", "run"): set(),
    ("conda", "run"): {"-n", "--name", "-p", "--prefix"},
    ("npx",): {"-p", "--package"},
    ("bunx",): set(),
    ("pnpm", "exec"): set(),
    ("pnpm", "dlx"): set(),
}
_CONTAINER_EXEC_OPTS = {"-e", "--env", "-u", "--user", "-w", "--workdir", "--env-file",
                        "--detach-keys", "--index"}


def _skip_options(words: list[str], start: int, with_value: set[str]) -> int:
    index = start
    while index < len(words):
        word = words[index]
        if word == "--":
            return index + 1
        if not word.startswith("-") or word == "-":
            return index
        index += 2 if word in with_value else 1
    return index


def unwrap(words: list[str], cwd: str) -> tuple[list[str], str]:
    """Strip assignments, reserved words and wrappers; return the real command."""
    while words:
        head = base_name(words[0])
        if _ASSIGNMENT.match(words[0]):
            words = words[1:]
        elif head in _NOT_A_COMMAND:
            return [], cwd
        elif head in _RESERVED:
            words = words[1:]
        elif head in _WRAPPERS:
            index = 1
            while index < len(words):
                word = words[index]
                if head == "env" and _ASSIGNMENT.match(word):
                    index += 1
                    continue
                if head == "env" and word in ("-C", "--chdir") and index + 1 < len(words):
                    target = resolve(words[index + 1], cwd)
                    cwd = str(target) if target else UNKNOWN
                if head == "timeout" and not word.startswith("-"):
                    index += 1  # the duration
                    break
                if word == "--":
                    index += 1
                    break
                if not word.startswith("-"):
                    break
                index += 2 if word in _WRAPPERS[head] else 1
            words = words[index:]
        else:
            for prefix, with_value in _RUNNERS.items():
                if [base_name(w) for w in words[: len(prefix)]] == list(prefix):
                    words = words[_skip_options(words, len(prefix), with_value):]
                    break
            else:
                if head in ("docker", "podman") and words[1:2] == ["exec"]:
                    index = _skip_options(words, 2, _CONTAINER_EXEC_OPTS)
                    words, cwd = words[index + 1:], UNKNOWN  # past the container name
                elif (head in ("docker", "podman") and words[1:3] == ["compose", "exec"]) or (
                    head == "docker-compose" and words[1:2] == ["exec"]
                ):
                    start = 3 if head != "docker-compose" else 2
                    index = _skip_options(words, start, _CONTAINER_EXEC_OPTS)
                    words, cwd = words[index + 1:], UNKNOWN
                elif head == "kubectl" and "exec" in words and "--" in words:
                    words, cwd = words[words.index("--") + 1:], UNKNOWN
                else:
                    break
    return words, cwd


# ── the reader ──────────────────────────────────────────────────────────────

_REDIRECT = re.compile(r"(?:\d+|&)?(?:<<<|<<-|<<|<>|<&|>>|>&|>\||<|>)")
_BREAK = set(" \t\n;&|()<>")


class _Reader:
    def __init__(self, text: str, cwd: str, variables: dict[str, str], depth: int) -> None:
        self.text = text
        self.pos = 0
        self.cwd = cwd
        self.vars = variables
        self.depth = depth
        self.out: list[Command] = []
        self._heredocs: list[tuple[Command, str, bool]] = []
        self._pipe_from: Command | None = None

    # -- top level ---------------------------------------------------------

    def run(self, stop: str | None = None) -> None:
        """Read commands until the end, or until `stop` closes a group."""
        while self.pos < len(self.text):
            ended = self._command(stop)
            if ended == stop and stop is not None:
                return

    def _command(self, stop: str | None) -> str:
        words: list[str] = []
        command = Command(words=[], cwd=self.cwd, shell_cwd=self.cwd)
        command.stdin_from, self._pipe_from = self._pipe_from, None
        while self.pos < len(self.text):
            self._skip_blanks()
            if self.pos >= len(self.text):
                break
            char = self.text[self.pos]
            if stop is not None and char == stop:
                self.pos += 1
                self._finish(command, words)
                return stop
            if char == "#" and not words:
                while self.pos < len(self.text) and self.text[self.pos] != "\n":
                    self.pos += 1
                continue
            operator = self._operator()
            if operator:
                self._finish(command, words)
                if operator in ("|", "|&"):
                    self._pipe_from = command
                if operator == "\n":
                    self._read_heredocs()
                return operator
            if char == "(" and not words:
                self.pos += 1
                saved = self.cwd
                self.run(stop=")")
                self.cwd = saved
                continue
            if self.text.startswith(("<(", ">("), self.pos):
                words.append(self._word())  # process substitution, not a redirection
                continue
            match = _REDIRECT.match(self.text, self.pos)
            if match:
                op = match.group(0).lstrip("0123456789")
                self.pos = match.end()
                self._skip_blanks()
                target = self._word()
                if op in ("<<", "<<-"):
                    self._heredocs.append((command, target, op == "<<-"))
                elif op == "<<<":
                    command.stdin = target
                else:
                    command.redirects.append((op, target))
                continue
            before = self.pos
            word = self._word()
            if self.pos == before:
                self.pos += 1  # a stray `(` or `)`: not a word, and not ours to parse
                continue
            words.append(word)
        self._finish(command, words)
        if self._heredocs:
            self._read_heredocs()
        return ""

    def _operator(self) -> str:
        text, pos = self.text, self.pos
        for op in ("&&", "||", ";;", "|&"):
            if text.startswith(op, pos):
                self.pos += 2
                return op
        char = text[pos]
        if char == "&" and text.startswith("&>", pos):
            return ""  # a redirection, not "run in the background"
        if char in ";|&\n":
            self.pos += 1
            return char
        return ""

    def _skip_blanks(self) -> None:
        while self.pos < len(self.text):
            if self.text[self.pos] in " \t":
                self.pos += 1
            elif self.text.startswith("\\\n", self.pos):
                self.pos += 2
            else:
                return

    def _read_heredocs(self) -> None:
        """Bodies start on the line after their `<<WORD`, in order."""
        pending, self._heredocs = self._heredocs, []
        for command, delimiter, strip_tabs in pending:
            lines: list[str] = []
            while self.pos < len(self.text):
                end = self.text.find("\n", self.pos)
                line = self.text[self.pos:] if end < 0 else self.text[self.pos:end]
                self.pos = len(self.text) if end < 0 else end + 1
                if (line.lstrip("\t") if strip_tabs else line) == delimiter:
                    break
                lines.append(line.lstrip("\t") if strip_tabs else line)
            command.stdin = "\n".join(lines)
            if command.reads_shell:
                self._nested(command.stdin, command.cwd)

    # -- words -------------------------------------------------------------

    def _word(self) -> str:
        """One word with quotes removed and what can be expanded, expanded."""
        out: list[str] = []
        text = self.text
        start = self.pos
        while self.pos < len(text):
            char = text[self.pos]
            if char in _BREAK:
                if char in "<>" and self.pos + 1 < len(text) and text[self.pos + 1] == "(":
                    self.pos += 2  # process substitution <( ) >( )
                    self._substitution(")")
                    out.append(UNKNOWN)
                    continue
                break
            if char == "\\":
                if text.startswith("\\\n", self.pos):
                    self.pos += 2
                else:
                    out.append(text[self.pos + 1:self.pos + 2])
                    self.pos += 2
            elif char == "'":
                end = text.find("'", self.pos + 1)
                end = len(text) if end < 0 else end
                out.append(text[self.pos + 1:end])
                self.pos = end + 1
            elif char == '"':
                self.pos += 1
                out.append(self._double_quoted())
            elif char == "$" and text.startswith("$'", self.pos):
                out.append(self._ansi_c())
            elif char == "$":
                out.append(self._dollar())
            elif char == "`":
                out.append(self._backtick())
            elif char == "~" and self.pos == start:
                rest = text[self.pos + 1:self.pos + 2]
                if rest in ("", "/") or rest in _BREAK:
                    out.append(os.path.expanduser("~").replace("\\", "/"))
                else:
                    out.append(char)
                self.pos += 1
            else:
                out.append(char)
                self.pos += 1
        return "".join(out)

    def _double_quoted(self) -> str:
        out: list[str] = []
        text = self.text
        while self.pos < len(text):
            char = text[self.pos]
            if char == '"':
                self.pos += 1
                return "".join(out)
            if char == "\\" and text[self.pos + 1:self.pos + 2] in ('"', "\\", "$", "`", "\n"):
                nxt = text[self.pos + 1]
                out.append("" if nxt == "\n" else nxt)
                self.pos += 2
            elif char == "$":
                out.append(self._dollar())
            elif char == "`":
                out.append(self._backtick())
            else:
                out.append(char)
                self.pos += 1
        return "".join(out)

    def _ansi_c(self) -> str:
        text = self.text
        self.pos += 2
        out: list[str] = []
        escapes = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\", "'": "'", '"': '"', "0": ""}
        while self.pos < len(text) and text[self.pos] != "'":
            if text[self.pos] == "\\" and self.pos + 1 < len(text):
                out.append(escapes.get(text[self.pos + 1], text[self.pos + 1]))
                self.pos += 2
            else:
                out.append(text[self.pos])
                self.pos += 1
        self.pos += 1
        return "".join(out)

    def _dollar(self) -> str:
        text = self.text
        if text.startswith("$((", self.pos):
            depth, self.pos = 0, self.pos + 1
            while self.pos < len(text):
                if text[self.pos] == "(":
                    depth += 1
                elif text[self.pos] == ")":
                    depth -= 1
                    if depth == 0:
                        self.pos += 1
                        break
                self.pos += 1
            return UNKNOWN
        if text.startswith("$(", self.pos):
            self.pos += 2
            self._substitution(")")
            return UNKNOWN
        if text.startswith("${", self.pos):
            end = text.find("}", self.pos)
            end = len(text) if end < 0 else end
            name = text[self.pos + 2:end]
            self.pos = end + 1
            return self._variable(name) if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) else UNKNOWN
        match = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*)").match(text, self.pos)
        if match:
            self.pos = match.end()
            return self._variable(match.group(1))
        if re.compile(r"\$[0-9#?$!@*-]").match(text, self.pos):
            self.pos += 2
            return UNKNOWN
        self.pos += 1
        return "$"

    def _variable(self, name: str) -> str:
        if name in self.vars:
            return self.vars[name]
        if name == "PWD":
            return self.cwd
        if name in ("HOME", "USERPROFILE", "CLAUDE_PROJECT_DIR", "TMPDIR", "TEMP", "TMP"):
            value = os.environ.get(name)
            if value:
                return value
        return UNKNOWN

    def _backtick(self) -> str:
        text = self.text
        end = self.pos + 1
        while end < len(text) and text[end] != "`":
            end += 2 if text[end] == "\\" else 1
        self._nested(text[self.pos + 1:end].replace("\\`", "`"), self.cwd)
        self.pos = end + 1
        return UNKNOWN

    def _substitution(self, stop: str) -> None:
        """A `$( )` body is commands in their own subshell."""
        saved_cwd, saved_pipe = self.cwd, self._pipe_from
        self._pipe_from = None
        self.run(stop=stop)
        self.cwd, self._pipe_from = saved_cwd, saved_pipe

    def _nested(self, script: str, cwd: str) -> None:
        if self.depth >= _MAX_DEPTH or not script:
            return
        self.out.extend(parse(script, cwd, dict(self.vars), self.depth + 1))

    # -- one finished command ------------------------------------------------

    def _finish(self, command: Command, words: list[str]) -> None:
        if not words:
            return
        if all(_ASSIGNMENT.match(w) for w in words):
            for word in words:  # `D=.claude; echo x > $D`
                name, _, value = word.partition("=")
                self.vars[name] = value
            return
        effective, cwd = unwrap(list(words), self.cwd)
        if not effective:
            return
        command.words, command.cwd = effective, cwd
        self.out.append(command)
        name = command.name
        if name in ("export", "declare", "local", "readonly", "typeset"):
            for word in effective[1:]:
                if _ASSIGNMENT.match(word):
                    key, _, value = word.partition("=")
                    self.vars[key] = value
        elif name in ("cd", "chdir", "pushd", "set-location", "sl", "push-location"):
            self._change_directory(effective[1:])
        elif name in ("popd", "pop-location"):
            self.cwd = UNKNOWN
        self._expand_nested(command)

    def _change_directory(self, args: list[str]) -> None:
        targets = [a for a in args if a == "-" or not a.startswith("-")]
        if not targets:
            self.cwd = os.path.expanduser("~")
            return
        if targets[0] == "-":
            self.cwd = UNKNOWN
            return
        resolved = resolve(targets[0], self.cwd)
        self.cwd = str(resolved) if resolved else UNKNOWN

    def _expand_nested(self, command: Command) -> None:
        """Commands that run other commands: shells, eval, PowerShell, xargs, find."""
        words, name, cwd = command.words, command.name, command.cwd
        if name in ("bash", "sh", "zsh", "dash", "ksh", "ash", "mksh"):
            script = _dash_c(words)
            if script is not None:
                self._nested(script, cwd)
            elif not [w for w in words[1:] if not w.startswith("-")]:
                command.reads_shell = True  # `bash <<EOF`, `echo cmd | sh`
                if command.stdin is not None:
                    self._nested(command.stdin, cwd)
                elif command.stdin_from and command.stdin_from.name in ("echo", "printf"):
                    self._nested(" ".join(command.stdin_from.words[1:]), cwd)
        elif name == "eval":
            self._nested(" ".join(words[1:]), cwd)
        elif name in ("powershell", "pwsh"):
            self._nested(_powershell_script(words) or "", cwd)
        elif name == "cmd":
            switch = next((i for i, w in enumerate(words) if w.lower() in ("/c", "/k")), None)
            if switch is not None:
                self._nested(" ".join(words[switch + 1:]), cwd)
        elif name == "xargs":
            index, replace = 1, False
            while index < len(words) and words[index].startswith("-"):
                flag = words[index]
                replace |= flag.startswith(("-I", "-i", "--replace"))
                takes = flag in ("-I", "-n", "-P", "-d", "-L", "-s", "-E", "-a", "--delimiter",
                                 "--max-args", "--max-procs", "--arg-file")
                index += 2 if takes else 1
            inner = words[index:]
            if inner:
                inner = inner if replace else [*inner, UNKNOWN]  # args arrive on stdin
                self._emit(inner, cwd)
        elif name == "find":
            self._expand_find(words, cwd)

    def _expand_find(self, words: list[str], cwd: str) -> None:
        index = 1
        starts: list[str] = []
        while index < len(words) and not (words[index].startswith(("-", "(", "!"))):
            starts.append(words[index])
            index += 1
        starts = starts or ["."]
        while index < len(words):
            word = words[index]
            if word in ("-exec", "-execdir", "-ok", "-okdir"):
                end = index + 1
                while end < len(words) and words[end] not in (";", "+"):
                    end += 1
                inner = [UNKNOWN if "{}" in w else w for w in words[index + 1:end]]
                if inner:
                    self._emit(inner, cwd)
                index = end + 1
                continue
            if word == "-delete":
                self._emit(["rm", *starts], cwd)  # removes what it finds under them
            index += 1

    def _emit(self, words: list[str], cwd: str) -> None:
        effective, cwd = unwrap(words, cwd)
        if effective:
            command = Command(words=effective, cwd=cwd, shell_cwd=cwd)
            self.out.append(command)
            self._expand_nested(command)


def _dash_c(words: list[str]) -> str | None:
    """The script of `bash -c '...'` / `sh -lc '...'`, or None."""
    index = 1
    while index < len(words):
        word = words[index]
        if word in ("-o", "+o", "-O", "+O", "--rcfile", "--init-file"):
            index += 2  # takes a value
            continue
        if word.startswith("-") and not word.startswith("--") and "c" in word[1:]:
            return words[index + 1] if index + 1 < len(words) else ""
        if not word.startswith(("-", "+")):
            return None
        index += 1
    return None


def _powershell_script(words: list[str]) -> str | None:
    for index, word in enumerate(words[1:], start=1):
        lowered = word.lower()
        if lowered.startswith(("-e", "/e")) and "encodedcommand".startswith(lowered.lstrip("-/")) \
                and lowered.lstrip("-/") != "":
            try:
                return base64.b64decode(words[index + 1]).decode("utf-16-le")
            except (IndexError, ValueError):
                return UNKNOWN
        if lowered.startswith(("-c", "/c")) and "command".startswith(lowered.lstrip("-/")):
            return " ".join(words[index + 1:])
        if lowered.startswith(("-f", "/f")) and "file".startswith(lowered.lstrip("-/")):
            return None
    return None


def parse(text: str, cwd: str | None = None, variables: dict[str, str] | None = None,
          depth: int = 0) -> list[Command]:
    """Every simple command the text would run, nested ones included, in order."""
    reader = _Reader(text or "", cwd or os.getcwd(), variables if variables is not None else {}, depth)
    reader.run()
    return reader.out


# ── code a command runs inline ──────────────────────────────────────────────

_PYTHON = re.compile(r"^(?:python(?:\d+(?:\.\d+)*)?w?|py)$")


def python_program(command: Command) -> str | None:
    """The program text of `python -c ...` or `python` reading stdin; None for a script."""
    words = command.words
    if not words or not _PYTHON.match(command.name):
        return None
    index = 1
    while index < len(words):
        word = words[index]
        if word == "-":
            return _stdin_text(command)
        if word.startswith("--"):
            index += 2 if word == "--check-hash-based-pycs" else 1
            continue
        if word.startswith("-") and len(word) > 1:
            # Bundled short options, as getopt reads them: `-Bc code`, `-W ignore`.
            for position in range(1, len(word)):
                flag = word[position]
                if flag == "c":
                    rest = word[position + 1:]
                    return rest or (words[index + 1] if index + 1 < len(words) else "")
                if flag == "m":
                    return None
                if flag in "WX":
                    if position + 1 == len(word):
                        index += 1  # the value is the next word
                    break
                if flag.isdigit():
                    break  # `py -3.12`
            index += 1
            continue
        return None  # a script path
    return _stdin_text(command)


def script_path(command: Command) -> Path | None:
    """The `.py` file a `python script.py` invocation runs."""
    words = command.words
    if not words or not _PYTHON.match(command.name) or python_program(command) is not None:
        return None
    for word in words[1:]:
        if not word.startswith("-"):
            return resolve(word, command.cwd)
    return None


_INLINE_FLAGS = {
    "node": ("-e", "--eval", "-p", "--print"),
    "deno": ("eval",),
    "bun": ("-e", "--eval", "eval"),
    "ruby": ("-e",),
    "perl": ("-e", "-E"),
    "php": ("-r",),
    "osascript": ("-e",),
}


def inline_code(command: Command) -> str | None:
    """Program text a command runs inline: python, node, ruby, perl, php."""
    program = python_program(command)
    if program is not None:
        return program
    flags = _INLINE_FLAGS.get(command.name)
    if not flags:
        return None
    words = command.words
    for index, word in enumerate(words[1:], start=1):
        for flag in flags:
            if word == flag:
                return words[index + 1] if index + 1 < len(words) else ""
            if flag.startswith("-") and len(flag) == 2 and word.startswith(flag) and len(word) > 2:
                return word[2:]
            if flag.startswith("--") and word.startswith(flag + "="):
                return word[len(flag) + 1:]
    if command.name in ("node", "deno", "bun", "ruby", "perl", "php") and (
        len(words) == 1 or words[1] == "-"
    ):
        return _stdin_text(command)
    return None


def _stdin_text(command: Command) -> str | None:
    if command.stdin is not None:
        return command.stdin
    source = command.stdin_from
    if source and source.name in ("echo", "printf"):
        return " ".join(source.words[1:])
    return None
