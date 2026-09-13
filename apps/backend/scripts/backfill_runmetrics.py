#!/usr/bin/env python3
"""Populate `runMetrics` from existing `projects/*/.runs/*.log` recordings.

    python scripts/backfill_runmetrics.py
    python scripts/backfill_runmetrics.py --dry-run

Safe to re-run: each document is keyed `{jobId}:{attempt}` and upserted.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

from cbc.shared.envfile import apply_to_environ  # noqa: E402

apply_to_environ()

from bson import ObjectId  # noqa: E402
from bson.errors import InvalidId  # noqa: E402

from cbc.db import db, ensure_indexes  # noqa: E402
from cbc.modules.ops.api import runmetrics  # noqa: E402


def _recordings() -> list[Path]:
    return sorted((ROOT / "projects").glob("*/.runs/*.log"))


async def backfill(*, dry_run: bool = False) -> int:
    await ensure_indexes()
    written = 0
    for path in _recordings():
        job_id, attempt = runmetrics.parse_recording_name(path.name)
        slug = path.parent.parent.name
        job: dict = {"_id": job_id, "attempts": attempt, "type": "unknown"}
        try:
            found = await db.jobs.find_one({"_id": ObjectId(job_id)})
        except (InvalidId, TypeError):
            found = await db.jobs.find_one({"_id": job_id})
        if found:
            job = found
            job["attempts"] = attempt
        else:
            job["projectSlug"] = slug
        project = None
        if job.get("projectId"):
            project = await db.projects.find_one({"_id": job["projectId"]})
        if project is None and slug not in ("_system",):
            project = await db.projects.find_one({"slug": slug}) or {"slug": slug}
        parsed = runmetrics.parse_recording(path)
        document = runmetrics.document_for(
            job,
            parsed,
            project=project,
            provider=job.get("provider"),
            outcome_status=job.get("status") or "unknown",
            error_code=job.get("errorCode"),
        )
        print(
            f"{document['_id']}  {document['jobType']}  "
            f"cost={document.get('totalCostUsd')}  {path}"
        )
        if not dry_run:
            await db.run_metrics.replace_one(
                {"_id": document["_id"]}, document, upsert=True
            )
        written += 1
    print(f"{'would write' if dry_run else 'wrote'} {written} runMetrics document(s)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    return asyncio.run(backfill(dry_run=args.dry_run))


if __name__ == "__main__":
    sys.exit(main())
