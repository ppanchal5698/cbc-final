#!/usr/bin/env python3
"""Compare the code engine's priced take-off with the estimators' own quote, bid by bid.

    python scripts/eval_bids.py --all
    python scripts/eval_bids.py --bid "Dutch Bros Toledo" --project CBC-260143

Each folder in ground_truth/<bid name>/ holds what an estimator sent for that
bid: the quote as sent, and the line detail it was priced from - their
spreadsheet or a P21 quote export, as is (.xlsx or .csv). Columns are found by
their headers; a sheet that names them some other way gets a columns.json in its
folder saying which is which: {"part": "Catalog #", "qty": "Q"}. The folder
names its bid by a project.txt holding the bid's code, or by being named like it.

The bid must already be in the app, read, with its hardware sets. It is priced
the way the v2 job prices it, without asking the model - so a run repeats - and
nothing is written to it. Base-bid lines are compared by part number, all of a
part's lines together, since one sheet lists a part per door and another per set:

  agree      the same part, the same quantity, the cost within 2%
  qty        the same part at another quantity
  cost       the same part and quantity at a cost more than 2% away
  unpriced   a part the estimator priced that the code left for a person
  missing    a part the estimator quoted that the code did not
  extra      a part the code quoted that the estimator did not

"model" beside a part means the two agree on the model and differ on an option
(5100 against 5100-HDHOS): worth a look, not counted against the match.

The plan's gate for switching pricing to the code engine: across the corpus,
nothing in qty, cost, missing or extra that the estimators would not also price
by hand, and no job failure.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import re
import sys
from pathlib import Path
from typing import Any

from cbc.modules.catalog.domain import partquery

ROOT = Path(__file__).resolve().parents[3]
GROUND_TRUTH = ROOT / "ground_truth"
COST_TOLERANCE = 0.02

# Header words for each field, most specific first. A header is matched whole,
# after upper-casing and dropping punctuation; columns.json covers the rest.
COLUMNS: dict[str, tuple[str, ...]] = {
    "part": ("PART NUMBER", "PART NO", "PART", "CATALOG NUMBER", "CATALOG NO", "CATALOG", "MODEL NUMBER",
             "MODEL NO", "MODEL", "ITEM ID", "ITEM NUMBER", "ITEM NO", "ITEM"),
    "description": ("DESCRIPTION", "ITEM DESCRIPTION", "DESC"),
    "manufacturer": ("MANUFACTURER", "MFR", "MFG", "MFGR", "BRAND", "VENDOR", "SUPPLIER"),
    "finish": ("FINISH", "FIN"),
    "qty": ("QUANTITY", "QTY", "QTY EA"),
    "cost": ("UNIT COST", "OUR COST", "COST EA", "COST EACH", "COST", "NET COST", "NET"),
    "sell": ("SALE EA", "SELL EA", "UNIT SELL", "UNIT PRICE", "PRICE EA", "SELL", "PRICE"),
    "extended": ("EXTENDED", "EXT PRICE", "EXTENDED PRICE", "EXT", "TOTAL"),
    "mark": ("DOOR", "DOOR NO", "MARK", "OPENING", "HW SET", "HDW SET", "HARDWARE SET", "SET", "GROUP"),
    "section": ("SECTION", "DIVISION", "DIV"),
    "alternate": ("ALTERNATE", "ALT"),
    "source": ("COST SOURCE", "SOURCE", "BASIS"),
}
_PUNCT = re.compile(r"[^A-Z0-9 ]+")
_SPACE = re.compile(r"\s+")
_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


def _header(cell: Any) -> str:
    return _SPACE.sub(" ", _PUNCT.sub(" ", str(cell or "").upper())).strip()


def _number(cell: Any) -> float | None:
    """`$1,234.50` is 1234.5, `27%` is 27, a blank or a word is None."""
    if isinstance(cell, (int, float)) and not isinstance(cell, bool):
        return float(cell)
    found = _NUMBER.search(str(cell or "").replace(",", "").replace("$", ""))
    return float(found.group(0)) if found else None


def read_sheet(path: Path) -> list[list[Any]]:
    """The rows of a .csv, or of every worksheet of an .xlsx, one after another."""
    if path.suffix.lower() == ".csv":
        with path.open(newline="", encoding="utf-8-sig") as handle:
            return [row for row in csv.reader(handle)]
    try:
        import openpyxl
    except ImportError as exc:  # the API's image does not carry it; an estimator's machine may
        raise SystemExit("reading .xlsx needs openpyxl (pip install openpyxl), or save the sheet as .csv") from exc
    try:
        book = openpyxl.load_workbook(path, read_only=True, data_only=True)
    except Exception as exc:  # an encrypted workbook is not a zip at all
        raise ValueError(f"{path.name} cannot be opened ({type(exc).__name__}) - if it is "
                         "password-protected, save a copy without the password, or export it as .csv") from exc
    return [list(row) for sheet in book.worksheets for row in sheet.iter_rows(values_only=True)]


def find_columns(rows: list[list[Any]], named: dict[str, str] | None = None) -> tuple[int, dict[str, int]] | None:
    """The header row and the column of each field it has - None when no row in the
    first 25 names a part (or description) and a quantity."""
    wanted = {field: (_header(named[field]),) if named and field in named else words
              for field, words in COLUMNS.items()}
    for index, row in enumerate(rows[:25]):
        headers = [_header(cell) for cell in row]
        columns: dict[str, int] = {}
        for field, words in wanted.items():
            for word in words:
                if word in headers and headers.index(word) not in columns.values():
                    columns[field] = headers.index(word)
                    break
        if "qty" in columns and ("part" in columns or "description" in columns):
            return index, columns
    return None


def estimator_lines(rows: list[list[Any]], header: int, columns: dict[str, int]) -> list[dict[str, Any]]:
    """The priced lines under the header: a row with a quantity and something to name it by."""
    def cell(row: list[Any], field: str) -> Any:
        at = columns.get(field)
        return row[at] if at is not None and at < len(row) else None

    out = []
    for row in rows[header + 1:]:
        qty = _number(cell(row, "qty"))
        part = str(cell(row, "part") or "").strip()
        description = str(cell(row, "description") or "").strip()
        if not qty or not (part or description):
            continue
        cost = _number(cell(row, "cost"))
        extended = _number(cell(row, "extended"))
        out.append({
            "part": part or None, "description": description, "qty": qty, "cost": cost,
            "manufacturer": str(cell(row, "manufacturer") or "").strip() or None,
            "mark": str(cell(row, "mark") or "").strip() or None,
            "alternate": str(cell(row, "alternate") or "").strip() or None,
            "section": str(cell(row, "section") or "").strip() or None,
            "extended": extended,
        })
    return out


def _key(part: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(part or "").upper())


def _forms(part: Any) -> set[str]:
    """The part and its shorter forms - never one as short as ASI's leading `10`,
    which every ASI part shares."""
    return {_key(form) for form in partquery.normalize(str(part or "")) if partquery.prefix_safe(form)} - {""}


def _totals(lines: list[dict[str, Any]], part: str, qty: str, cost: str) -> dict[str, dict[str, Any]]:
    """All of a part's lines as one: its quantity, and its cost each weighted by quantity
    (None while any of its lines has no cost)."""
    out: dict[str, dict[str, Any]] = {}
    for line in lines:
        key = _key(line.get(part))
        if not key:
            continue
        entry = out.setdefault(key, {"part": line.get(part), "qty": 0.0, "spend": 0.0, "priced": True})
        amount = float(line.get(qty) or 0)
        entry["qty"] += amount
        if line.get(cost) is None:
            entry["priced"] = False
        else:
            entry["spend"] += amount * float(line[cost])
    for entry in out.values():
        entry["cost"] = round(entry["spend"] / entry["qty"], 2) if entry["priced"] and entry["qty"] else None
    return out


def compare(expected: list[dict[str, Any]], ours: list[dict[str, Any]],
            tolerance: float = COST_TOLERANCE) -> dict[str, Any]:
    """The base bid's parts side by side: the estimator's lines against the priced file's rows."""
    theirs = _totals([line for line in expected if not line.get("alternate")], "part", "qty", "cost")
    mine = _totals([row for row in ours if not row.get("alternate_group")], "part_number", "quantity", "cost")
    result: dict[str, list[dict[str, Any]]] = {k: [] for k in ("agree", "qty", "cost", "unpriced", "missing", "extra")}
    used: set[str] = set()
    for key, want in theirs.items():
        found, relation = (key, "exact") if key in mine else (None, None)
        if found is None:  # the same model under another option or size
            shared = {other: max((len(f) for f in _forms(want["part"]) & _forms(got["part"])), default=0)
                      for other, got in mine.items() if other not in used and other not in theirs}
            best = max(shared, key=shared.get, default=None)
            if best is not None and shared[best]:
                found, relation = best, "model"
        if found is None:
            result["missing"].append({"part": want["part"], "qty": want["qty"], "cost": want["cost"]})
            continue
        used.add(found)
        got = mine[found]
        row = {"part": want["part"], "ours": got["part"], "match": relation,
               "qty": [want["qty"], got["qty"]], "cost": [want["cost"], got["cost"]]}
        if abs(want["qty"] - got["qty"]) > 1e-6:
            result["qty"].append(row)
        elif got["cost"] is None:
            result["unpriced"].append(row)
        elif want["cost"] is not None and abs(got["cost"] - want["cost"]) > tolerance * want["cost"]:
            result["cost"].append(row)
        else:
            result["agree"].append(row)
    result["extra"] = [{"part": got["part"], "qty": got["qty"], "cost": got["cost"]}
                       for key, got in mine.items() if key not in used]
    unkeyed = [row for row in ours if not row.get("alternate_group") and not _key(row.get("part_number"))]
    return {**result, "counts": {k: len(v) for k, v in result.items()},
            "unnumbered": {"estimator": sum(1 for line in expected if not _key(line.get("part"))),
                           "ours": len(unkeyed)}}


async def _project(folder: Path, code: str | None) -> dict[str, Any] | None:
    from cbc.modules.projects.api.lookup import ProjectNotFound, load
    from cbc.modules.projects.infrastructure.collections import bid_requests
    from cbc.shared import storage

    named = (folder / "project.txt").read_text(encoding="utf-8").strip() if (folder / "project.txt").exists() else None
    for candidate in filter(None, (code, named, storage.slugify(folder.name))):
        try:
            return await load(candidate)
        except ProjectNotFound:
            continue
    return await bid_requests().find_one({"name": {"$regex": f"^{re.escape(folder.name)}$", "$options": "i"}})


async def evaluate(folder: Path, code: str | None = None) -> dict[str, Any]:
    from cbc.modules.quoting.features import MatchAndPrice

    sheets = [p for p in sorted(folder.iterdir()) if p.suffix.lower() in (".xlsx", ".xlsm", ".csv")]
    if not sheets:
        return {"error": "no line detail in the folder - add the estimator's .xlsx or .csv"}
    named = json.loads((folder / "columns.json").read_text(encoding="utf-8")) if (folder / "columns.json").exists() else None
    expected: list[dict[str, Any]] = []
    for sheet in sheets:
        try:
            rows = read_sheet(sheet)
        except ValueError as exc:
            return {"error": str(exc)}
        found = find_columns(rows, named)
        if found is None:
            return {"error": f"{sheet.name}: no header row names a part and a quantity - "
                             "say which columns they are in columns.json"}
        expected += estimator_lines(rows, *found)
    project = await _project(folder, code)
    if project is None:
        return {"error": "no bid in the app by this folder's name - put its code in project.txt"}
    try:
        priced = await MatchAndPrice.price_bid(project, choose=False)
    except Exception as exc:  # the gate counts these: a job failure is a fail
        return {"error": f"pricing failed: {type(exc).__name__}: {exc}", "job_failure": True}
    return {"bid": project.get("code"), **compare(expected, priced["lines"])}


def _report(name: str, result: dict[str, Any]) -> bool:
    print(f"\n{name}")
    if "error" in result:
        print(f"  {result['error']}")
        return bool(result.get("job_failure"))
    counts = result["counts"]
    print("  " + "  ".join(f"{k} {v}" for k, v in counts.items())
          + f"   (lines without a part number: estimator {result['unnumbered']['estimator']}, "
            f"ours {result['unnumbered']['ours']})")
    for kind in ("qty", "cost", "missing", "extra", "unpriced"):
        for row in result[kind][:8]:
            print(f"    {kind:8} {json.dumps(row)}")
    return any(counts[k] for k in ("qty", "cost", "missing", "extra"))


async def _run(folders: list[Path], code: str | None, write: bool) -> int:
    failed = False
    for folder in folders:
        result = await evaluate(folder, code)
        failed |= _report(folder.name, result)
        if write:
            (folder / "eval.json").write_text(json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8")
    print()
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--bid", help="one folder under ground_truth/")
    parser.add_argument("--project", help="the bid's code, when its folder is not named like it")
    parser.add_argument("--all", action="store_true", help="every folder under ground_truth/")
    parser.add_argument("--write", action="store_true", help="also write eval.json into each folder")
    args = parser.parse_args()
    if args.bid:
        folders = [GROUND_TRUTH / args.bid]
    elif args.all:
        folders = sorted(p for p in GROUND_TRUTH.iterdir() if p.is_dir()) if GROUND_TRUTH.is_dir() else []
    else:
        parser.error("give --bid or --all")
    if not folders or not all(folder.is_dir() for folder in folders):
        parser.error(f"nothing to compare: put each bid's files in {GROUND_TRUTH}/<bid name>/")
    return asyncio.run(_run(folders, args.project, args.write))


if __name__ == "__main__":
    sys.exit(main())
