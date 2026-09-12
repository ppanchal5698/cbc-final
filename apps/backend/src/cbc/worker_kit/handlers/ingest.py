"""Job-type handlers invoked after a Claude pass completes."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from pymongo import UpdateOne

from bson import ObjectId

from cbc.pageindex import basis
from cbc.db import db
from cbc.core.paths import repo_root

REPO_ROOT = repo_root()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _prices_for(sheet_basis: str, product: dict) -> tuple[float | None, float | None, float | None]:
    """(listPrice, cost, multiplier) for one ingested row.

    The ingest agent is told to record "the list figure on the sheet", and it has no
    way to say the sheet quotes nets - so on a net program it labels a cost as a
    list price. Downstream, changing the program multiplier recomputes
    `cost = listPrice x multiplier`, which would discount an already-net figure a
    second time.

    Rather than ask the agent to judge it, the basis is taken from the sheet, which
    is where the fact actually lives. On a net sheet the figure is stored as the
    cost it is and `listPrice` is left empty, so it cannot be multiplied by anything
    later even if a guard is missed - the repricing query only ever selects rows
    that have a list price.
    """
    list_price = product.get("list_price")
    cost = product.get("cost")
    multiplier = product.get("multiplier")

    if sheet_basis == basis.NET:
        # Whatever it was called, it is the cost. Prefer an explicit cost if the
        # pass recorded one; a net sheet has no multiplier to carry.
        return None, cost if cost is not None else list_price, None

    # LIST, or UNKNOWN - an untranscribed tier is not evidence of a net program,
    # and a hand-built book is a person saying outright that this is a list price.
    return list_price, cost, multiplier


async def ingest_pricebook(job: dict) -> str:
    """Load the parts Claude read off a price book into the catalog."""
    payload = job.get("payload") or {}
    output_path = (REPO_ROOT / payload.get("outputPath", ".cache/pricebook-ingest.json")).resolve()
    # This function reads and then deletes whatever it is pointed at, so it does
    # not take the path on trust even though the worker now sets it.
    if not output_path.is_relative_to(REPO_ROOT / ".cache"):
        raise ValueError(f"ingest output must stay under .cache/: {output_path}")
    if not output_path.exists():
        return "no ingest file produced"

    data = json.loads(output_path.read_text(encoding="utf-8"))
    book_id = ObjectId(payload["priceBookId"])
    book = await db.price_books.find_one({"_id": book_id}) or {}
    sheet_basis = basis.price_basis(
        payload.get("filename") or book.get("filename"), book.get("vendor")
    )
    written = 0
    bulk: list[UpdateOne] = []
    for product in data.get("products", []):
        if not product.get("part"):
            continue
        # Keyed on the vendor as well as the part: a part number is only unique
        # within its manufacturer, and keying on `part` alone made Rockwood's
        # sheet overwrite Hager's costs for every number they happen to share.
        manufacturer = product.get("manufacturer")
        list_price, cost, multiplier = _prices_for(sheet_basis, product)
        bulk.append(
            UpdateOne(
                {"part": product["part"], "manufacturer": manufacturer},
                {
                    "$set": {
                        "description": product.get("description", ""),
                        "division": product.get("division"),
                        "listPrice": list_price,
                        "multiplier": multiplier,
                        "cost": cost,
                        "priceBasis": sheet_basis,
                        "priceBookId": book_id,
                        "sourcePage": product.get("source_page"),
                        "seedSource": "price book ingest",
                        "updatedAt": _now(),
                        "updatedBy": "claude",
                    },
                    "$setOnInsert": {
                        "part": product["part"],
                        "manufacturer": manufacturer,
                        "createdAt": _now(),
                    },
                },
                upsert=True,
            )
        )
        written += 1

    for start in range(0, len(bulk), 500):
        await db.products.bulk_write(bulk[start : start + 500], ordered=False)

    # An effective date is only written when the ingest actually read one. Setting
    # it unconditionally wrote null over a date purchasing had entered by hand,
    # and an undated book reports `stale: false` - so a lapsed sheet quietly
    # stopped being flagged, which is the whole point of the price-books screen.
    changes: dict = {"partCount": written, "lastIngestedAt": _now(), "priceBasis": sheet_basis}
    if data.get("effective_date"):
        changes["effective"] = data["effective_date"]
    await db.price_books.update_one({"_id": book_id}, {"$set": changes})
    output_path.unlink(missing_ok=True)
    return f"{written} parts written to the catalog ({sheet_basis} prices)"
