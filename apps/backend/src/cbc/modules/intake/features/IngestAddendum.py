"""The ingest_addendum job: a Claude pass reads an addendum against the bid set it changes.

The pass gets a sheet map first; what it found - openings added, removed and
changed - is attached to the version it was reading.
"""
from __future__ import annotations

from typing import Any

from cbc.modules.extraction.api import passes
from cbc.modules.intake.api import versions as intake_versions
from cbc.modules.projects.api import pipeline
from cbc.services import storage  # ponytail: legacy kernel; where a project's tree lives, until storage moves to shared
from cbc.shared.pass_files import read_json


async def run(job: dict[str, Any]) -> None:
    await pipeline.run_pass(job, sync=sync_results, prepare=passes.prepare)


async def sync_results(job: dict[str, Any], project: dict[str, Any] | None) -> str:
    note = await passes.check_output(job, project)
    if note is not None:
        return note
    counts = await import_addendum(project, job)
    return (
        f"{counts['added']} added, {counts['removed']} removed, "
        f"{counts['changed']} changed in addendum diff"
    )


async def import_addendum(project: dict[str, Any], job: dict[str, Any]) -> dict[str, int]:
    """Load review/addendum_diff.json onto the version Claude was reading."""
    slug = project["slug"]
    payload = read_json(storage.project_dir(slug) / "review" / "addendum_diff.json")
    source = storage.project_dir(slug) / "review" / "addendum_diff.json"
    if source.exists() and payload is None:
        raise ValueError("review/addendum_diff.json is missing or invalid JSON")
    if not payload:
        return {"added": 0, "removed": 0, "changed": 0}

    version = (job.get("payload") or {}).get("version")
    if version is None:
        raise ValueError("ingest_addendum job missing payload.version")

    recorded = await intake_versions.record_addendum_diff(project["_id"], int(version), payload)
    if not recorded:
        raise ValueError(f"version {version} not found for addendum diff import")

    return {
        "added": len(payload.get("added") or []),
        "removed": len(payload.get("removed") or []),
        "changed": len(payload.get("changed") or []),
    }
