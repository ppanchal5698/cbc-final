"""Rename `extracted/door_schedule.json` to `extracted/line_items.json` on disk.

The artifact stopped being a door schedule when Division 10 counts and FRP areas
became line items in it: a bid set with five openings now writes eighteen rows,
ten of them accessories. A file called `door_schedule.json` holding hand dryers
is the kind of name that makes the next person distrust the contents.

Every reader and writer moved with the rename. The projects already on disk did
not, so they move here. Purely a file rename - the contents are unchanged, and a
project that has already been renamed, or never had the file, is skipped.

`extracted/` is project output under `STORAGE_ROOT`, not reference data, so this
is inside what the file-safety rule allows to be written.
"""
from __future__ import annotations

import logging

from cbc.shared.paths import storage_root

VERSION = 7
DESCRIPTION = "extracted/door_schedule.json -> extracted/line_items.json"

log = logging.getLogger("cbc.migrations")

OLD_NAME = "door_schedule.json"
NEW_NAME = "line_items.json"


async def apply(db) -> None:  # noqa: ANN001 - the runner passes the Motor database
    root = storage_root()
    if not root.is_dir():
        return

    renamed = skipped = 0
    for extracted in sorted(root.glob("*/extracted")):
        old = extracted / OLD_NAME
        new = extracted / NEW_NAME
        if not old.is_file():
            continue
        if new.exists():
            # Already migrated, or the take-off pass rewrote it under the new
            # name. The new file is the live one; leave both rather than
            # overwrite output nobody asked to lose.
            log.warning(
                "line items: %s has both %s and %s - leaving the old file in place",
                extracted.parent.name, OLD_NAME, NEW_NAME,
            )
            skipped += 1
            continue
        old.rename(new)
        renamed += 1

    if renamed or skipped:
        log.info(
            "line items: %s project(s) renamed to %s, %s skipped",
            renamed, NEW_NAME, skipped,
        )
