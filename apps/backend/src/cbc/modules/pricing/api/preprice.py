"""Seed priced/line_items.json in code before the pricing pass runs.

The pricing loop used to be the model iterating every line, calling p21 / catalog /
calc for each. This prices in Python everything the ladder can answer, so the pass
is left with judgment - substitutions, RFQs, the lines that genuinely need a human -
not arithmetic. It is the deterministic-pricing lever the token overhaul turns on.

Mirrors ``extraction/infrastructure/pretakeoff.py``: a SOURCE stamp, ``_seeded_by_us``
ownership so a reseed never clobbers a real pass, never-raises, and a ``_demo()``.

Placement is ``api/``, not ``infrastructure/`` (docs/backend/modules.md boundary
rule 1): a module is reached only through ``api/`` and the caller, quoting's
``MatchAndPrice``, is outside pricing. The two backfills and ``hager_list_price``
already sit in ``api/`` for the same reason.

The ladder is load-bearing. ``_priced_off_a_page_the_catalog_already_answers``
(validation) rejects a quote that priced off a book page the catalog already
answers, so catalog must precede list×:

  0. Allegion gate  -> DISTRIBUTOR_MANUAL, cost null, reason names Banner/SecLock. No rung tried.
  1. P21 last PO    -> ``p21.P21Client`` (read-only)
  2. Special net    -> ``reference_library.get_special_net`` (pure Python)
  3. Catalog baseline and
  4. list × multiplier -> the two existing backfills, in order, after the write.
  5. everything else -> MANUAL, ``price_status`` NEEDS_JUDGMENT, flag naming the rung.

The lines are every one the take-off supports: each item of a hardware group an
opening cites, one MANUAL line for a cited group nobody itemised, and the
Division 10 / FRP rows of ``extracted/line_items.json``. The pass can only patch
lines that exist, so a line not seeded here never reaches the quote.
"""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from typing import Any

from cbc.modules.pricing.api import catalog_baseline_backfill, p21, pricing, reference_library
from cbc.shared import storage
from cbc.shared.hardware_sets import SET_KEYS
from cbc.shared.pass_files import read_json, write_json

log = logging.getLogger("cbc.worker")

SOURCE = "preprice.py (deterministic pre-pricing)"

_ENV = "PREPRICE_SEED"


def preprice_seed_enabled() -> bool:
    """The ``PREPRICE_SEED`` kill switch (default on). Read here and by the prompt
    builder through this one helper - two readers of the same env var must not
    disagree, and this flag decides which cost ladder the prompt carries."""
    return os.environ.get(_ENV, "1").strip().lower() not in {"0", "false", "no"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _line_items_path(slug: str):
    return storage.project_dir(slug) / "priced" / "line_items.json"


def _seeded_by_us(path) -> bool:
    """True when the file is this seed's own output and safe to replace - never a
    real pass's. Same contract as ``pretakeoff._seeded_by_us``."""
    if not path.is_file():
        return True
    try:
        import json

        return json.loads(path.read_text(encoding="utf-8")).get("source") == SOURCE
    except (OSError, ValueError):
        return False


def _line_count(path) -> int:
    payload = read_json(path) if path.is_file() else None
    rows = payload.get("lines") if isinstance(payload, dict) else payload
    return len(rows) if isinstance(rows, list) else 0


def _sets(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    for key in SET_KEYS:
        rows = payload.get(key)
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
    return []


def _qty(item: dict[str, Any]) -> float:
    raw = item.get("quantity") if item.get("quantity") is not None else item.get("qty")
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 1.0


def _manufacturer(item: dict[str, Any]) -> str | None:
    matched = item.get("matched") if isinstance(item.get("matched"), dict) else {}
    specified = item.get("specified") if isinstance(item.get("specified"), dict) else {}
    for candidate in (
        item.get("manufacturer"),
        item.get("vendor"),
        matched.get("manufacturer"),
        specified.get("manufacturer"),
    ):
        text = str(candidate or "").strip()
        if text:
            return text
    return None


def _seed_line(set_id: str, index: int, item: dict[str, Any], source_page: Any) -> dict[str, Any]:
    part = catalog_baseline_backfill._item_part(item)
    return {
        # A re-seed lands on the same rows: the door number never a list index.
        "line_id": f"{set_id}-{index:02d}",
        "group": set_id,
        "group_type": "door",
        "hw_set": set_id,
        "part_number": part or None,
        "description": item.get("description") or None,
        "quantity": _qty(item),
        "manufacturer": _manufacturer(item),
        "source_page": source_page,
        "cost": None,
        "cost_source": "MANUAL",
        "price_status": "NEEDS_JUDGMENT",
        "flags": [],
    }


def _group_key(text: Any) -> str | None:
    """`GROUP 1`, `SET 01` and `1` are one group; None when the callout has no number."""
    match = re.search(r"([0-9]{1,3})([A-Z]?)\s*$", str(text or "").strip().upper())
    return f"{int(match.group(1))}{match.group(2)}" if match else None


def _take_off_rows(slug: str) -> list[dict[str, Any]]:
    """The estimator-confirmed take-off: openings and specialty rows alike."""
    payload = read_json(storage.project_dir(slug) / "extracted" / "line_items.json")
    rows = payload.get("openings") if isinstance(payload, dict) else payload
    return [
        row for row in (rows if isinstance(rows, list) else [])
        if isinstance(row, dict) and row.get("in_scope") is not False
    ]


def _cited_groups(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """The hardware groups the openings cite, by group number."""
    cited: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = _group_key(row.get("hardware_set"))
        if key is None:
            continue
        group = cited.setdefault(key, {
            "name": str(row["hardware_set"]).strip(),
            "doors": [],
            "source_page": row.get("source_page"),
        })
        group["doors"].append(str(row.get("door_number") or row.get("mark") or "?"))
    return cited


def _group_line(set_id: str, source_page: Any, openings: list[str], why: str) -> dict[str, Any]:
    """One MANUAL line standing for a hardware group nobody itemised.

    Without it a bid whose legend would not parse seeded no lines at all. An empty
    seed is patch-only with nothing to patch, so the pass could neither add the
    hardware nor write the file, and the job died on validation.
    """
    return {
        "line_id": f"{set_id}-SET",
        "group": set_id,
        "group_type": "door",
        "hw_set": set_id,
        "part_number": None,
        "description": f"Hardware {set_id} (opening {', '.join(openings) or '-'}) - {why}",
        "quantity": float(len(openings) or 1),
        "unit": "set",
        "source_page": source_page,
        "cost": None,
        "cost_source": "MANUAL",
        "cost_source_detail": f"{why}; price it from the sheet, or confirm who supplies it",
        "price_status": "NEEDS_JUDGMENT",
        "flags": ["hardware_group_not_itemised"],
    }


# Schedule wording for an item another party supplies. The Dutch Bros accessory
# schedule marks most of its items "(OFCI)" - owner furnished, contractor installed.
_BY_OTHERS = re.compile(
    r"\b(?:OFCI|O\.F\.C\.I|N\.I\.C|NIC|BY\s+OTHERS"
    r"|OWNER[\s-]+(?:FURNISHED|SUPPLIED|PROVIDED)"
    r"|(?:PROVIDED|FURNISHED|SUPPLIED)\s+BY\s+(?:THE\s+)?(?:OWNER|TENANT|LANDLORD))\b",
    re.I,
)


def _specialty_lines(rows: list[dict[str, Any]]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Division 10 and FRP rows as quote lines, each with the row it came from.

    specialty_takeoffs imports them as line items so pricing reads one file, and
    then nothing seeded a line for them: the quote dropped Division 10 entirely.
    A row with no quantity (an FRP run nobody has measured) has nothing to price.
    """
    out: list[tuple[dict[str, Any], dict[str, Any]]] = []
    used: set[str] = set()
    for row in rows:
        division = str(row.get("division") or "").strip()
        qty = row.get("qty")
        if not division.startswith(("10", "06")):
            continue
        if isinstance(qty, bool) or not isinstance(qty, (int, float)) or qty <= 0:
            continue
        spec = row.get("specialty") if isinstance(row.get("specialty"), dict) else {}
        part = str(spec.get("specifiedModel") or "").strip() or None
        base = f"{division[:2]}-{row.get('mark') or row.get('door_number') or part or len(out) + 1}"
        line_id, n = base, 2
        while line_id in used:
            line_id, n = f"{base}-{n}", n + 1
        used.add(line_id)
        accessory = division.startswith("10")
        line = {
            "line_id": line_id,
            "group": spec.get("room") or ("Division 10" if accessory else "FRP"),
            "group_type": "accessories" if accessory else "frp",
            "division": division,
            "part_number": part,
            "description": row.get("description") or part,
            "quantity": float(qty),
            "unit": spec.get("unit"),
            "manufacturer": row.get("manufacturer"),
            "source_page": row.get("source_page"),
            "cost": None,
            "cost_source": "MANUAL",
            "price_status": "NEEDS_JUDGMENT",
            "flags": [],
        }
        by_others = _BY_OTHERS.search(str(row.get("notes") or ""))
        if by_others:
            line["cost_source_detail"] = (
                f"the schedule says {by_others.group(0)!r} - another party may supply "
                "this; confirm it is CBC's scope before pricing it"
            )
            _flag(line, catalog_baseline_backfill.SUPPLIED_BY_OTHERS)
        out.append((line, row))
    return out


def _flag(line: dict[str, Any], flag: str) -> None:
    flags = line.setdefault("flags", [])
    if flag not in flags:
        flags.append(flag)


def _set_cost(line: dict[str, Any], cost: float, source: str, detail: str | None) -> bool:
    """Arithmetic through ``pricing.price_line`` -> ``domain/calc``, never the MCP
    tool. Returns True when the line was priced."""
    priced = pricing.price_line(cost, line.get("margin"), line.get("quantity"), line.get("division"))
    if not priced.get("priced"):
        return False
    line["cost"] = round(float(cost), 2)
    line["margin"] = priced["margin"]
    line["sale_ea"] = priced["sell"]
    line["ext_price"] = priced["extended"]
    line["cost_source"] = source
    if detail:
        line["cost_source_detail"] = detail
    line["price_status"] = "PRICED"
    return True


def _apply_ladder(line: dict[str, Any], item: dict[str, Any], client: p21.P21Client) -> None:
    # Rung 0: Allegion is distributor-only (Banner/SecLock), never a run's to price.
    if catalog_baseline_backfill._is_allegion(line, item):
        line["cost_source"] = "DISTRIBUTOR_MANUAL"
        line["cost_source_detail"] = (
            "Allegion (Von Duprin / LCN / Schlage / Ives) — distributor quote "
            "(Banner Solutions / SecLock); never priced off a list"
        )
        _flag(line, "allegion_distributor_manual")
        return

    part = line.get("part_number")
    if not part:
        _flag(line, "no_part_number")
        return

    vendor = line.get("manufacturer")
    # Rung 1: P21 last PO.
    try:
        po = client.last_po(part, vendor)
    except Exception:
        po = None
    if po is not None:
        if po.get("cost") is not None and _set_cost(line, po["cost"], "P21_LAST_PO", po.get("detail")):
            return
        if po.get("context"):
            # Unreliable PO: no cost, but the number is context for the estimator.
            line["cost_source_detail"] = po["context"]

    # Rung 2: special net (pure Python, Hager only today).
    try:
        net = reference_library.get_special_net(vendor or "", part)
    except Exception:
        net = None
    if net and net.get("net_price") is not None:
        effective = net.get("effective_date")
        if reference_library.sheet_lapsed(effective):
            # A lapsed sheet is a price the proposal gate would hold: skip the
            # rung, say why, and let catalog / list× try a current one.
            note = f"special net for {net.get('item_code') or part} skipped — sheet effective {effective} is past review"
            line["cost_source_detail"] = "; ".join(filter(None, [line.get("cost_source_detail"), note]))
        else:
            detail = (
                f"special-net sheet ({net.get('section') or 'Hager special nets'}) "
                f"item {net.get('item_code') or part}"
            )
            if _set_cost(line, net["net_price"], "SPECIAL_NET", detail):
                # The sheet's date is what quoting's is_lapsed reads off the line.
                if effective:
                    line["multiplier_effective_date"] = effective
                    line["price_book_version"] = f"Hager special-net sheet, effective {effective}"
                return

    # Rungs 3-4 (catalog baseline, list×) run after the write, as the two
    # backfills. Rung 5 (MANUAL / NEEDS_JUDGMENT) is the skeleton's default.


def _build_lines(slug: str, client: p21.P21Client) -> tuple[list[dict[str, Any]], list[str]]:
    """Every line the take-off supports, and envelope notes on what was left out."""
    payload = read_json(storage.project_dir(slug) / "extracted" / "hardware_sets.json")
    # Stamped on every line before any rung prices it. Each rung - P21, special
    # net, catalog, list x, and a patched MANUAL line - prices with the line's own
    # margin when it has one, so this one place covers them all.
    meta = read_json(storage.project_dir(slug) / "extracted" / "scope_metadata.json")
    meta = meta if isinstance(meta, dict) else {}
    special = pricing.special_margin(meta.get("gc"), meta.get("brand"))
    rows = _take_off_rows(slug)
    cited = _cited_groups(rows)
    lines: list[dict[str, Any]] = []
    notes: list[str] = []

    def price(line: dict[str, Any], item: dict[str, Any]) -> None:
        if special:
            # A recorded reason, so a special margin below its band is the
            # estimator's known call rather than a blocking review flag.
            line["margin"], line["margin_override_reason"] = special
            line["margin_overridden"] = True
        _apply_ladder(line, item, client)
        lines.append(line)

    seen: set[str | None] = set()
    for hw_set in _sets(payload):
        set_id = str(
            hw_set.get("set_id") or hw_set.get("hardware_set") or hw_set.get("name") or "SET"
        ).strip() or "SET"
        key = _group_key(set_id)
        if cited and key not in cited:
            # A legend group no opening cites. On the sheet that prompted this,
            # an omitted office door's group was still drawn, struck through.
            notes.append(
                f"legend_group_unused — {set_id} is in the hardware legend but no "
                "opening cites it; not priced"
            )
            continue
        seen.add(key)
        # A set built from the schedule's callouts carries its page on each
        # opening, not on itself; the page that cites the group is the drawing
        # page an estimator opens to find it.
        doors = [door for door in hw_set.get("openings") or [] if isinstance(door, dict)]
        source_page = next(
            (page for page in (
                hw_set.get("source_page"),
                *(door.get("source_page") for door in doors),
                (cited.get(key) or {}).get("source_page"),
            ) if page is not None),
            None,
        )
        items = [item for item in hw_set.get("items") or [] if isinstance(item, dict)]
        if not items:
            openings = (cited.get(key) or {}).get("doors") or []
            lines.append(_group_line(set_id, source_page, openings, "its items were not read from the legend"))
        for index, item in enumerate(items):
            price(_seed_line(set_id, index, item, source_page), item)

    for key, group in cited.items():
        if key not in seen:
            lines.append(_group_line(
                group["name"], group["source_page"], group["doors"],
                "it is not in the hardware legend that was read",
            ))

    for line, row in _specialty_lines(rows):
        if catalog_baseline_backfill.SUPPLIED_BY_OTHERS in line["flags"]:
            lines.append(line)
        else:
            price(line, row)
    return lines, notes


def _summary(lines: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(lines)
    with_cost = sum(1 for line in lines if isinstance(line.get("cost"), (int, float)))
    return {
        "total_lines": total,
        "lines_with_cost": with_cost,
        "manual_cutoff_applied": with_cost < total,
    }


def _envelope_flags(lines: list[dict[str, Any]]) -> list[str]:
    """Blanket gaps go on the envelope, not 300 identical per-line flags - the
    per-line noise is exactly what this change exists to stop paying for."""
    flags: list[str] = []
    if not p21._base_url():
        flags.append("p21_not_reached — P21 is not connected (NR-10)")
    flags.append("vendor_books_not_read — list prices come from the catalog/list× backfills")
    return flags


def _finalize_manual(slug: str) -> None:
    """Rung 5: after the backfills, any line still without a cost is MANUAL and
    NEEDS_JUDGMENT with a reason naming the rung it is owed - a blank MANUAL line
    tells an estimator nothing (NFR-2, check_pricing enforces the reason)."""
    path = _line_items_path(slug)
    payload = read_json(path)
    if not isinstance(payload, dict):
        return
    lines = payload.get("lines") or []
    changed = False
    for line in lines:
        if not isinstance(line, dict):
            continue
        if line.get("cost") is not None:
            continue
        allegion = str(line.get("cost_source") or "").upper() == "DISTRIBUTOR_MANUAL"
        if not allegion:
            line["cost_source"] = "MANUAL"
        line["price_status"] = "NEEDS_JUDGMENT"
        if not str(line.get("cost_source_detail") or "").strip():
            if not (line.get("part_number") or "").strip():
                line["cost_source_detail"] = (
                    "no part number read — carry the specified item across, then a "
                    "distributor / RFQ quote"
                )
            else:
                line["cost_source_detail"] = (
                    "no automatic cost path matched (P21 / special-net / catalog / "
                    "list×) — needs a distributor or RFQ quote"
                )
            changed = True
    if changed:
        payload["summary"] = _summary([ln for ln in lines if isinstance(ln, dict)])
        write_json(path, payload)


def seed_line_items(slug: str, *, client: p21.P21Client | None = None) -> dict[str, Any]:
    """Write a complete priced/line_items.json from extracted/hardware_sets.json.

    One line per hardware item, each priced-with-provenance or MANUAL-with-a-reason.
    Never raises: a bid that will not seed is a job for the pricing pass, not a
    reason to fail the job.
    """
    path = _line_items_path(slug)
    if not _seeded_by_us(path):
        return {"written": False, "note": "already present and not ours to replace"}

    try:
        # One P21Client per seed: its cache and breaker are per-bid, so a lookup
        # never leaks across customers and priced_at stays honest.
        pass_client = client or p21.P21Client()
        lines, notes = _build_lines(slug, pass_client)
    except Exception:
        log.exception("preprice: building lines failed for %s", slug)
        return {"written": False, "note": "seed raised"}

    # A seed that read no sets must not replace lines that exist. A patched
    # MANUAL line keeps this seed's stamp, so a re-price whose hardware file
    # this reader could not see used to write an empty file over the agent's work.
    if not lines and _line_count(path):
        log.warning("preprice: no hardware sets read for %s; kept the existing priced lines", slug)
        return {"written": False, "note": "no hardware sets read; existing lines kept"}

    # Nor may it write an empty file. The stamp makes the file patch-only, and an
    # empty one has nothing to patch: the pass could neither add a line nor
    # save the file, and the job died on "must contain a non-empty lines array".
    if not lines:
        try:
            path.unlink(missing_ok=True)  # only ever our own seed - checked above
        except OSError:
            log.exception("preprice: could not remove the empty seed for %s", slug)
        return {"written": False, "note": "nothing in the take-off to seed"}

    payload = {
        "source": SOURCE,
        "seeded_at": _now(),
        "lines": lines,
        "flags": _envelope_flags(lines) + notes,
        "summary": _summary(lines),
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        write_json(path, payload)
    except OSError:
        log.exception("preprice: writing line_items.json failed for %s", slug)
        return {"written": False, "note": "write failed"}

    # Rungs 3-4: the two existing backfills, catalog before list× (ladder order).
    # Both are idempotent and skip a line whose cost is already set, so they only
    # fill the MANUAL skeleton rows. They also stay in the post-pass net unchanged.
    for backfill in (
        catalog_baseline_backfill.backfill_priced_lines,
        _list_x_backfill,
    ):
        try:
            backfill(slug)
        except Exception:
            log.exception("preprice: %s failed for %s", getattr(backfill, "__name__", "backfill"), slug)

    # Rung 5: everything still null is MANUAL / NEEDS_JUDGMENT with a named reason.
    try:
        _finalize_manual(slug)
    except Exception:
        log.exception("preprice: finalize failed for %s", slug)

    return {"written": True, "lines": len(lines)}


def _list_x_backfill(slug: str) -> Any:
    from cbc.modules.pricing.api.list_x_backfill import backfill_priced_lines

    return backfill_priced_lines(slug)


def prompt_block(slug: str) -> str:
    """The seed worklist for the pricing prompt: what the ladder priced and what it
    left for judgment, so the pass is told where to look rather than to re-derive."""
    payload = read_json(_line_items_path(slug))
    if not isinstance(payload, dict):
        return ""
    lines = [ln for ln in (payload.get("lines") or []) if isinstance(ln, dict)]
    if not lines:
        return ""
    priced = sum(1 for ln in lines if ln.get("cost") is not None)
    needs = [ln for ln in lines if ln.get("cost") is None]
    parts = [
        f"**Deterministic pricing seeded {priced}/{len(lines)} lines.** "
        "Each priced line carries its cost_source and a citation; do not re-price it.",
    ]
    if needs:
        by_reason: dict[str, int] = {}
        for ln in needs:
            flags = [str(f) for f in (ln.get("flags") or [])]
            if any(f.startswith("allegion") for f in flags):
                reason = "allegion"
            elif "hardware_group_not_itemised" in flags:
                reason = "hardware group with no items read - leave it MANUAL"
            elif catalog_baseline_backfill.SUPPLIED_BY_OTHERS in flags:
                reason = "supplied by others per the schedule - do not price"
            else:
                reason = "needs distributor / RFQ / judgment"
            by_reason[reason] = by_reason.get(reason, 0) + 1
        owed = ", ".join(f"{count} {reason}" for reason, count in sorted(by_reason.items()))
        parts.append(
            f"{len(needs)} line(s) are MANUAL and need judgment ({owed}). A blank "
            "MANUAL line tells an estimator nothing - name why, and the distributor "
            "or RFQ that would settle it."
        )
    return "\n\n".join(parts)


def _demo() -> None:
    """`python -m cbc.modules.pricing.api.preprice` - seed a fixture bid in a temp
    tree and print the ladder outcome per line."""
    import json
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "projects" / "demo"
        (root / "extracted").mkdir(parents=True)
        (root / "priced").mkdir(parents=True)
        (root / "extracted" / "hardware_sets.json").write_text(
            json.dumps(
                {
                    "hardware_sets": [
                        {
                            "set_id": "HW-1",
                            "source_page": 4,
                            "items": [
                                {"part_number": "010108", "manufacturer": "Hager", "quantity": 2},
                                {"part_number": "98", "manufacturer": "Von Duprin", "quantity": 1},
                                {"description": "no part", "quantity": 1},
                            ],
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        os.environ.setdefault("STORAGE_ROOT", str(Path(tmp) / "projects"))
        storage_root_override = Path(tmp) / "projects"
        original = storage.project_dir
        storage.project_dir = lambda s: storage_root_override / s  # type: ignore[assignment]
        try:
            result = seed_line_items("demo")
            payload = json.loads((root / "priced" / "line_items.json").read_text(encoding="utf-8"))
        finally:
            storage.project_dir = original  # type: ignore[assignment]
    print(json.dumps({"result": result, "payload": payload}, indent=2))


if __name__ == "__main__":
    _demo()
