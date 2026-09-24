"""Typed field patches onto an artifact Python already owns.

A pass used to author `line_items.json` whole, through `save_artifact`. One
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


# For a `lines` patch, the evidence a field needs depends on the field's axis: a
# cost-derived value is provenanced by cost_source + cost_source_detail, a
# drawing-derived one by the source_page + excerpt every opening uses. Demanding a
# drawing page for a cost forces the agent to invent one.
_LINE_PRICING_FIELDS = frozenset({"cost", "margin", "sale_ea", "ext_price", "multiplier"})

_ROOTS = ("openings", "lines", "items")


def _root_model(root: str):
    """(model, note field) for a path root. The note column is load-bearing:
    PricedLine / Div10Item are extra='forbid' and PricedLine has no evidence_note,
    so a lines/items note goes in `notes`; an opening's stays in `evidence_note`.
    This also fixes a live bug - div10 rows were gated against Opening."""
    from cbc.modules.extraction.api.claude_output import Div10Item, Opening, PricedLine

    return {
        "openings": (Opening, "evidence_note"),
        "lines": (PricedLine, "notes"),
        "items": (Div10Item, "notes"),
    }[root]


def _rows(payload: Any, root: str) -> list[dict[str, Any]]:
    """The rows for this path's root - not 'whichever key exists'. A `lines`
    payload patched via openings/... would otherwise be validated as openings."""
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        rows = payload.get(root)
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
    return []


def _key(row: dict[str, Any], root: str) -> str:
    """A row's business key: line_id for a priced/div10 row (mandatory, and the
    Mongo lineKey), the door mark for an opening. Never a list index - an index
    means a patch written against one run lands on a different row in the next."""
    if root in ("lines", "items"):
        value = row.get("line_id")
        if value not in (None, ""):
            return str(value).strip()
    value = row.get("door_number") or row.get("mark")
    return str(value).strip() if value else ""


def _resolve(mark: str, rows: list[dict[str, Any]], root: str) -> dict[str, Any] | None:
    """Exact key match first; the uppercased key only when exactly one candidate
    matches, so a case fold never silently lands on the wrong row."""
    exact: dict[str, dict[str, Any]] = {}
    folded: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        key = _key(row, root)
        if not key:
            continue
        exact.setdefault(key, row)
        folded.setdefault(key.upper(), []).append(row)
    if mark in exact:
        return exact[mark]
    candidates = folded.get(mark.strip().upper(), [])
    return candidates[0] if len(candidates) == 1 else None


def _flag(target: dict[str, Any], note: str) -> None:
    flags = target.setdefault("flags", [])
    if isinstance(flags, list) and note not in flags:
        flags.append(note)


def _has_evidence(patch: dict[str, Any]) -> bool:
    """Drawing-form evidence: a page and the excerpt read off it."""
    evidence = patch.get("evidence")
    if not isinstance(evidence, dict):
        return False
    page = evidence.get("source_page")
    excerpt = str(evidence.get("excerpt") or "").strip()
    return isinstance(page, (int, float)) and bool(excerpt)


def _has_pricing_evidence(patch: dict[str, Any]) -> bool:
    """Pricing-form evidence: the cost source and its citation - a different axis
    from the drawing page. A cost has no page; demanding one invents it."""
    evidence = patch.get("evidence")
    if not isinstance(evidence, dict):
        return False
    return bool(str(evidence.get("cost_source") or "").strip()) and bool(
        str(evidence.get("cost_source_detail") or "").strip()
    )


def _evidence_ok(patch: dict[str, Any], root: str, field: str) -> bool:
    if field in EVIDENCE_EXEMPT:
        return True
    if root == "lines" and field in _LINE_PRICING_FIELDS:
        return _has_pricing_evidence(patch)
    return _has_evidence(patch)


def _evidence_message(root: str, field: str) -> str:
    if root == "lines" and field in _LINE_PRICING_FIELDS:
        return (
            f"{field} is a cost - it needs evidence {{cost_source, cost_source_detail}}, "
            "not a drawing page (a cost has no page; demanding one invents it) (NFR-3)"
        )
    return (
        f"{field} needs evidence {{source_page, excerpt}} - a filled value with no "
        "page citation is unauditable (NFR-3)"
    )


def _validates(row: dict[str, Any], model) -> str | None:
    """None when the patched row still satisfies its contract, else why not. The
    row is closed to the model's fields first, so a stray key an older pass left
    (e.g. a normalized-away `manufacturer`) does not fail an otherwise-valid patch."""
    closed = {key: value for key, value in row.items() if key in model.model_fields}
    try:
        model.model_validate(closed)
    except Exception as exc:  # pydantic ValidationError, kept loose on purpose
        first = str(exc).splitlines()
        return "; ".join(first[1:3]).strip() or str(exc)[:200]
    return None


# Top-level paths a patch may set, as opposed to openings/<door>/<field>.
#
# Deliberately tiny, and only for records of what the agent *did* - never for a
# value read off a row, which belongs on its opening with its own evidence.
TOP_LEVEL_PATCHABLE = frozenset({"visual_pages_checked"})


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
    results: list[PatchResult] = []

    for patch in patches:
        raw_path = str((patch or {}).get("path") or "").strip().strip("/")

        # A patch that records what the agent opened, rather than what it read
        # off a row. `check_extraction` *requires* `visual_pages_checked` on
        # line_items.json, and with only openings/<door>/<field> patchable
        # there was no way to write it: the artifact is seeded and the prompts
        # steer to propose_patch, so the agent did the visual reads, tried to
        # record them, was told "top-level fields aren't patchable", treated
        # that as expected and saved nothing. Three runs died on the coverage
        # check that its own reads had satisfied.
        if raw_path in TOP_LEVEL_PATCHABLE:
            value = (patch or {}).get("value")
            if not isinstance(value, list):
                results.append(PatchResult(
                    raw_path, False,
                    f"{raw_path} takes a list of "
                    "{path, source_page, image_path, finding} rows",
                ))
                continue
            op = str((patch or {}).get("op") or "set").lower()
            if op == "append":
                existing = updated.get(raw_path)
                value = (list(existing) if isinstance(existing, list) else []) + value
            elif op != "set":
                results.append(PatchResult(raw_path, False, f"unknown op {op!r} - set or append"))
                continue
            if isinstance(updated, dict):
                updated[raw_path] = value
                results.append(PatchResult(raw_path, True, None))
            else:
                results.append(PatchResult(
                    raw_path, False, "this artifact has no top level to patch"
                ))
            continue

        parts = raw_path.split("/")
        if len(parts) != 3 or parts[0] not in _ROOTS:
            results.append(PatchResult(
                raw_path, False,
                "path must read openings/<door number>/<field> (or "
                "lines/<line_id>/<field>, items/<line_id>/<field>), or be one of "
                + ", ".join(sorted(TOP_LEVEL_PATCHABLE)),
            ))
            continue

        root, mark, field = parts
        model, note_field = _root_model(root)
        rows = _rows(updated, root)
        target = _resolve(mark, rows, root)
        if target is None:
            # Rejects, does not panic: name the missing key and the keys it has.
            keys = sorted({_key(row, root) for row in rows if _key(row, root)})
            results.append(PatchResult(
                raw_path, False,
                f"no {root[:-1]} {mark!r} in this artifact - "
                f"it has {', '.join(keys[:8]) or 'none'}",
            ))
            continue

        if field in NOT_PATCHABLE:
            results.append(PatchResult(
                raw_path, False, f"{field} records a person's decision, not a reading"
            ))
            _flag(target, f"patch_rejected_{field}")
            continue

        if field not in model.model_fields:
            results.append(PatchResult(
                raw_path, False,
                f"{field!r} is not a {model.__name__} field - put it in notes",
            ))
            _flag(target, f"patch_rejected_{field}")
            continue

        if not _evidence_ok(patch, root, field):
            results.append(PatchResult(raw_path, False, _evidence_message(root, field)))
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
        why = _validates(trial, model)
        if why:
            results.append(PatchResult(
                raw_path, False, f"rejected by the {model.__name__} contract: {why}"
            ))
            _flag(target, f"patch_rejected_{field}")
            continue

        target[field] = candidate
        evidence = patch.get("evidence") if isinstance(patch.get("evidence"), dict) else {}
        if evidence:
            if root == "lines" and field in _LINE_PRICING_FIELDS:
                note = (
                    f"{field} <- {evidence.get('cost_source')}: "
                    f"{str(evidence.get('cost_source_detail') or '')[:120]}"
                )
            else:
                note = (
                    f"{field} <- p{evidence.get('source_page')}: "
                    f"{str(evidence.get('excerpt') or '')[:120]}"
                )
            target[note_field] = "; ".join(
                part for part in (target.get(note_field), note) if part
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
