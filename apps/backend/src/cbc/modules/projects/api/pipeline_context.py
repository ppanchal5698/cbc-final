"""Cross-job pipeline context so agents do not re-derive identical artifacts."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cbc.shared.paths import storage_root
from cbc.shared.pass_files import read_json, write_json

CONTEXT_REL = "extracted/_pipeline_context.json"

_TRACKED = (
    "extracted/door_schedule.json",
    "extracted/scope_metadata.json",
    "extracted/scope_summary.json",
    "extracted/hardware_sets.json",
    "extracted/_sheetmap.json",
    "priced/line_items.json",
    "review/review_flags.json",
)


def _sha(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def context_path(slug: str) -> Path:
    return storage_root() / slug / CONTEXT_REL


def write_context(slug: str) -> dict[str, Any]:
    """Snapshot durable facts after a job sync for the next Claude session."""
    root = storage_root() / slug
    artifacts: dict[str, str] = {}
    for rel in _TRACKED:
        digest = _sha(root / rel)
        if digest:
            artifacts[rel] = digest

    schedule = read_json(root / "extracted" / "door_schedule.json") or {}
    openings = schedule.get("openings") if isinstance(schedule, dict) else []
    if not isinstance(openings, list):
        openings = []

    metadata = read_json(root / "extracted" / "scope_metadata.json") or {}
    if not isinstance(metadata, dict):
        metadata = {}

    hardware = read_json(root / "extracted" / "hardware_sets.json") or {}
    hw_count = 0
    if isinstance(hardware, dict):
        for group in hardware.get("hardware_sets") or []:
            if isinstance(group, dict):
                hw_count += len(group.get("items") or [])

    priced = read_json(root / "priced" / "line_items.json") or {}
    lines = []
    if isinstance(priced, dict):
        lines = priced.get("lines") or priced.get("line_items") or []
    elif isinstance(priced, list):
        lines = priced
    if not isinstance(lines, list):
        lines = []
    with_cost = sum(
        1
        for row in lines
        if isinstance(row, dict)
        and isinstance(row.get("cost"), (int, float))
        and not isinstance(row.get("cost"), bool)
    )

    payload = {
        "updated_at": _now(),
        "door_count": len(openings),
        "brand_from_pdf": metadata.get("brand") or metadata.get("brand_name"),
        "brand_mismatch_warning": metadata.get("brand_mismatch_warning"),
        "hardware_set_count": hw_count,
        "priced_count": with_cost,
        "total_lines": len([r for r in lines if isinstance(r, dict)]),
        "sheetmap_sha": artifacts.get("extracted/_sheetmap.json"),
        "artifacts": artifacts,
        "note": (
            "Prefer this summary over re-reading door_schedule / scope_* unless "
            "you need field-level detail. Artifact SHA digests prove continuity."
        ),
    }
    write_json(context_path(slug), payload)
    return payload


def prompt_block(slug: str) -> str:
    """Inject a short continuity block into the next job's system prompt."""
    path = context_path(slug)
    if not path.is_file():
        return ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    if not isinstance(data, dict):
        return ""
    lines = [
        "",
        "## Pipeline context (do not re-fetch unless stale)",
        f"- Updated: {data.get('updated_at')}",
        f"- Doors: {data.get('door_count')}",
        f"- Brand (from PDF): {data.get('brand_from_pdf')}",
        f"- Brand mismatch: {data.get('brand_mismatch_warning') or 'none'}",
        f"- Hardware items: {data.get('hardware_set_count')}",
        f"- Quote lines with cost: {data.get('priced_count')}/{data.get('total_lines')}",
        "- Artifact digests:",
    ]
    for rel, sha in sorted((data.get("artifacts") or {}).items()):
        lines.append(f"  - `{rel}` → `{sha[:12]}…`")
    lines.append(
        "Read `extracted/_pipeline_context.json` if you need the full block. "
        "Do **not** re-Read door_schedule / scope_summary / scope_metadata solely "
        "to rebuild this summary."
    )
    return "\n".join(lines) + "\n"
