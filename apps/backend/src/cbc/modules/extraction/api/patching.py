"""Typed field patches onto an artifact Python already owns.

A pass used to author `door_schedule.json` whole, through `save_artifact`. One
bad key anywhere in it - `thickness` as a top-level field, `page_size` as an
array, a `flags` entry that was an object - failed the write and took the run
with it. Three consecutive runs on the same bid died three different ways, each
costing everything the earlier phases had done.

The deterministic seed is the base. A pass proposes changes to single fields, and
each one is validated **on its own**:

  - a patch that does not name a real opening and a declared field is rejected
  - a patch whose value the `Opening` contract refuses is rejected
  - a patch that fills a field without citing a page is rejected (NFR-3, and
    `.claude/rules/pdf-verify-before-present.md`, enforced here rather than
    asked for in prose)

A rejected patch costs that field and leaves a review flag. It never costs the
run, and it never silently does nothing: **never silently wrong** applies to the
patch record too.
"""
from __future__ import annotations

from typing import Any

# Fields a patch may set without citing a sheet. Everything else is a value an
# estimator will quote from, so it needs a page (.claude/rules/auditability.md).
EVIDENCE_EXEMPT = frozenset({"flags", "notes", "evidence_note", "confidence"})

# Setting these is how a person records a decision, not how a pass reads a sheet.
NOT_PATCHABLE = frozenset({"confirmed_by", "added_by_hand"})


class PatchResult(dict):
    """One patch's outcome. A dict so it crosses the MCP boundary unchanged."""

    def __init__(self, path: str, applied: bool, reason: str | None = None) -> None:
        super().__init__(path=path, applied=applied, reason=reason)


def _openings(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in ("openings", "lines", "items"):
            rows = payload.get(key)
            if isinstance(rows, list):
                return [row for row in rows if isinstance(row, dict)]
    return []


def _mark(opening: dict[str, Any]) -> str:
    value = opening.get("door_number") or opening.get("mark")
    return str(value).strip().upper() if value else ""


def _flag(target: dict[str, Any], note: str) -> None:
    flags = target.setdefault("flags", [])
    if isinstance(flags, list) and note not in flags:
        flags.append(note)


def _has_evidence(patch: dict[str, Any]) -> bool:
    evidence = patch.get("evidence")
    if not isinstance(evidence, dict):
        return False
    page = evidence.get("source_page")
    excerpt = str(evidence.get("excerpt") or "").strip()
    return isinstance(page, (int, float)) and bool(excerpt)


def _opening_fields() -> frozenset[str]:
    from cbc.modules.extraction.api.claude_output import Opening

    return frozenset(Opening.model_fields)


def _validates(opening: dict[str, Any]) -> str | None:
    """None when the patched opening still satisfies its contract, else why not."""
    from cbc.modules.extraction.api.claude_output import Opening

    try:
        Opening.model_validate(opening)
    except Exception as exc:  # pydantic ValidationError, kept loose on purpose
        first = str(exc).splitlines()
        return "; ".join(first[1:3]).strip() or str(exc)[:200]
    return None


def apply_patches(
    payload: Any, patches: list[dict[str, Any]]
) -> tuple[Any, list[PatchResult]]:
    """Apply what holds, reject what does not, and say which was which.

    `path` is `openings/<door number>/<field>`. The door number, not an index:
    an index means a patch written against one run lands on a different opening
    in the next, which is a wrong value with a real page number attached to it.

    The payload is not mutated; the caller decides whether to keep the result.
    """
    import copy

    updated = copy.deepcopy(payload)
    rows = _openings(updated)
    by_mark = {_mark(row): row for row in rows if _mark(row)}
    declared = _opening_fields()
    results: list[PatchResult] = []

    for patch in patches:
        raw_path = str((patch or {}).get("path") or "").strip().strip("/")
        parts = raw_path.split("/")
        if len(parts) != 3 or parts[0] not in ("openings", "lines", "items"):
            results.append(PatchResult(
                raw_path, False,
                "path must read openings/<door number>/<field>",
            ))
            continue

        _, mark, field = parts
        target = by_mark.get(mark.strip().upper())
        if target is None:
            results.append(PatchResult(
                raw_path, False,
                f"no opening {mark!r} in this artifact - "
                f"it has {', '.join(sorted(by_mark)[:8]) or 'none'}",
            ))
            continue

        if field in NOT_PATCHABLE:
            results.append(PatchResult(
                raw_path, False, f"{field} records a person's decision, not a reading"
            ))
            _flag(target, f"patch_rejected_{field}")
            continue

        if field not in declared:
            results.append(PatchResult(
                raw_path, False,
                f"{field!r} is not an Opening field - put it in notes",
            ))
            _flag(target, f"patch_rejected_{field}")
            continue

        if field not in EVIDENCE_EXEMPT and not _has_evidence(patch):
            results.append(PatchResult(
                raw_path, False,
                f"{field} needs evidence {{source_page, excerpt}} - a filled value "
                "with no page citation is unauditable (NFR-3)",
            ))
            _flag(target, f"patch_unevidenced_{field}")
            continue

        op = str(patch.get("op") or "set").lower()
        before = target.get(field)
        if op == "append":
            existing = list(before) if isinstance(before, list) else []
            candidate = existing + [patch.get("value")]
        elif op == "set":
            candidate = patch.get("value")
        else:
            results.append(PatchResult(raw_path, False, f"unknown op {op!r} - set or append"))
            continue

        trial = {**target, field: candidate}
        why = _validates(trial)
        if why:
            results.append(PatchResult(raw_path, False, f"rejected by the Opening contract: {why}"))
            _flag(target, f"patch_rejected_{field}")
            continue

        target[field] = candidate
        evidence = patch.get("evidence") if isinstance(patch.get("evidence"), dict) else {}
        if evidence:
            note = (
                f"{field} <- p{evidence.get('source_page')}: "
                f"{str(evidence.get('excerpt') or '')[:120]}"
            )
            target["evidence_note"] = "; ".join(
                part for part in (target.get("evidence_note"), note) if part
            )[:2000]
        results.append(PatchResult(raw_path, True, None))

    return updated, results


def summarise(results: list[PatchResult]) -> dict[str, Any]:
    applied = [r for r in results if r["applied"]]
    rejected = [r for r in results if not r["applied"]]
    return {
        "applied": len(applied),
        "rejected": len(rejected),
        "results": list(results),
        # The whole point: a rejected patch is a flagged field, not a dead run.
        "run_can_continue": True,
    }


def _demo() -> None:
    """Runnable check on the rules that decide whether a patch lands."""
    base = {
        "openings": [
            {"door_number": "05", "size": "3068", "handing": None,
             "source_page": 16, "flags": []},
        ]
    }
    cite = {"source_page": 16, "excerpt": "05 UNISEX WRM RH"}

    out, results = apply_patches(base, [
        {"op": "set", "path": "openings/05/handing", "value": "RH", "evidence": cite},
    ])
    assert results[0]["applied"] is True, results
    assert out["openings"][0]["handing"] == "RH"
    assert "p16" in out["openings"][0]["evidence_note"]
    assert base["openings"][0]["handing"] is None, "the input must not be mutated"

    # No page citation: the value is not taken.
    _, results = apply_patches(base, [
        {"op": "set", "path": "openings/05/fire_rating", "value": "90"},
    ])
    assert results[0]["applied"] is False and "evidence" in results[0]["reason"]

    # An invented key does not become a field.
    out, results = apply_patches(base, [
        {"op": "set", "path": "openings/05/thickness", "value": "1 3/4\"", "evidence": cite},
    ])
    assert results[0]["applied"] is False
    assert "patch_rejected_thickness" in out["openings"][0]["flags"]

    # A value the contract refuses costs that field only.
    out, results = apply_patches(base, [
        {"op": "set", "path": "openings/05/confidence", "value": 7.0},
        {"op": "set", "path": "openings/05/handing", "value": "LH", "evidence": cite},
    ])
    assert results[0]["applied"] is False and results[1]["applied"] is True
    assert out["openings"][0]["handing"] == "LH"

    # An opening that is not there is named, not guessed at.
    _, results = apply_patches(base, [
        {"op": "set", "path": "openings/99/handing", "value": "LH", "evidence": cite},
    ])
    assert results[0]["applied"] is False and "99" in results[0]["reason"]

    # An estimator's own decision is not patchable.
    _, results = apply_patches(base, [
        {"op": "set", "path": "openings/05/confirmed_by", "value": "x@cbc.com"},
    ])
    assert results[0]["applied"] is False

    assert summarise(results)["run_can_continue"] is True
    print("patching demo OK")


if __name__ == "__main__":
    _demo()
