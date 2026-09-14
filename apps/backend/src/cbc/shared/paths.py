"""Where the repository root is, asked once instead of counted in every module.

Eleven modules each derived the root by counting directory levels back from
their own file - `Path(__file__).resolve().parents[1]`, or `[2]` where the module
sat one deeper. The count is correct only for the depth the file happens to live
at, and it is what tells the API where `projects/` and `templates/` are, and the
worker where a run may write. Move a module one level and the arithmetic still
produces a path: the wrong one, silently, with no import error and no crash - the
service simply reads an empty directory or writes outside the tree.

Anchoring on a marker that only the root has removes the whole class. Depth stops
mattering, so a file can move without taking a hidden dependency on where it was.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

# Files that exist at the repository root and nowhere below it. `.mcp.json` is
# the tool registration the runtime already treats as root-level; the others are
# fallbacks for a checkout or image missing it.
MARKERS = (".mcp.json", "pytest.ini", "requirements.txt")


@lru_cache(maxsize=1)
def repo_root() -> Path:
    """The repository root, found by walking up from this file to a marker."""
    here = Path(__file__).resolve()
    for candidate in here.parents:
        if any((candidate / marker).exists() for marker in MARKERS):
            return candidate
    # No marker anywhere above us. Better to say so than to hand back a plausible
    # directory that later gets written into.
    raise RuntimeError(
        f"cannot locate the repository root above {here}: none of {MARKERS} found. "
        "If this is a partial checkout or a slimmed image, restore one of them."
    )


def data_dir(env_var: str, default: str) -> Path:
    """A data directory named by `env_var`; a relative value resolves against the root.

    Read at call time and free of `cbc.shared.config`: the MCP servers import these
    in a subprocess that is deliberately not handed the root settings. The defaults
    are the checkout's layout - the image sets every one of these variables.
    """
    path = Path(os.environ.get(env_var) or default)
    return path if path.is_absolute() else (repo_root() / path).resolve()


def storage_root() -> Path:
    return data_dir("STORAGE_ROOT", "data/projects")


def pricebook_dir() -> Path:
    return data_dir("PRICEBOOK_DIR", "data/pricebooks")


def reference_dir() -> Path:
    """The seed JSON. It was `reference-library/`, which exists only inside the image."""
    return data_dir("REFERENCE_DIR", "data/reference-library")


def _demo() -> None:
    root = repo_root()
    assert root.is_dir(), root
    assert any((root / m).exists() for m in MARKERS), f"no marker in {root}"
    # The directories every caller of this actually goes looking for.
    assert (root / "apps" / "backend" / "src" / "cbc").is_dir(), (
        "apps/backend/src/cbc should sit under the root"
    )
    assert (root / "apps" / "web").is_dir(), "apps/web should sit under the root"
    assert repo_root() is root, "result should be cached"
    print(f"cbc.shared.paths OK - {root}")


if __name__ == "__main__":
    _demo()
