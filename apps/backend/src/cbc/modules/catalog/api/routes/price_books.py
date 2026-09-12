"""Price books and multiplier programs.

Uploading a book enqueues an ingest job, so the next bid Claude prices is using
the sheet purchasing just loaded. Staleness is surfaced rather than suppressed -
NFR-10 has no named owner yet, and pretending otherwise would hide the risk.
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse

from cbc.config import settings
from cbc.db import db, oid, serialise
from cbc.http.deps import Actor, AdminActor
from cbc.schemas import PriceBookCreate, PriceBookUpdate
from cbc.services import audit, freshness as freshness_settings, jobs, storage
from cbc.pageindex import basis, store as catalog_store
from cbc.services.reference_library import sync_vendor_categories

router = APIRouter(prefix="/api/price-books", tags=["price-books"])

PDF_MAGIC = b"%PDF-"



def _now() -> datetime:
    return datetime.now(timezone.utc)


def _age_days(effective: str | None) -> int | None:
    if not effective:
        return None
    try:
        return (date.today() - date.fromisoformat(effective)).days
    except ValueError:
        return None


async def _decorate(book: dict[str, Any]) -> dict[str, Any]:
    bands = await freshness_settings.load()
    age = _age_days(book.get("effective"))
    return {
        **serialise(book),
        "ageDays": age,
        "stale": age is not None and age > bands.catalog_stale_days,
        "undated": book.get("effective") is None,
    }


@router.get("")
async def list_price_books() -> dict[str, Any]:
    books = await db.price_books.find().sort([("vendor", 1), ("program", 1)]).to_list(200)
    decorated = [await _decorate(b) for b in books]
    return {
        "priceBooks": decorated,
        "counts": {
            "total": len(decorated),
            "stale": sum(1 for b in decorated if b["stale"]),
            "undated": sum(1 for b in decorated if b["undated"]),
        },
        "stewardship": {
            "owner": None,
            "cadence": None,
            "note": "NFR-10 is open - no owner or refresh cadence has been assigned.",
        },
    }


@router.get("/{book_id}")
async def get_price_book(book_id: str) -> dict[str, Any]:
    book = await db.price_books.find_one({"_id": oid(book_id)})
    if not book:
        raise HTTPException(404, "price book not found")

    parts = await db.products.find({"priceBookId": book["_id"]}).sort("part", 1).to_list(500)
    part_count = await db.products.count_documents({"priceBookId": book["_id"]})
    return {"priceBook": await _decorate(book), "parts": serialise(parts), "partCount": part_count}


@router.post("", status_code=201)
async def create_price_book(body: PriceBookCreate, actor: Actor) -> dict:
    document = {**body.model_dump(exclude_none=True), "partCount": 0, "updatedAt": _now()}
    result = await db.price_books.insert_one(document)
    document["_id"] = result.inserted_id
    await audit.record(
        "price_book.create", actor, {"priceBookId": result.inserted_id}, after=body.vendor
    )
    return await _decorate(document)


@router.post("/{book_id}/file", status_code=201)
async def upload_price_book_file(
    book_id: str,
    actor: Actor,
    file: UploadFile = File(...),
) -> dict:
    """Attach the sheet and ask Claude to read it into the catalog."""
    book = await db.price_books.find_one({"_id": oid(book_id)})
    if not book:
        raise HTTPException(404, "price book not found")

    settings.pricebook_dir.mkdir(parents=True, exist_ok=True)
    target = storage.unique_filename(settings.pricebook_dir, file.filename or "pricebook.pdf")
    try:
        size = await storage.receive_upload(
            file, target, settings.max_upload_bytes, magic=PDF_MAGIC
        )
    except ValueError as exc:
        detail = str(exc)
        if "exceeds" in detail:
            status = 413
        elif "malware" in detail.lower() or "scanner" in detail.lower():
            status = 422
        else:
            status = 415
        raise HTTPException(status, detail) from exc

    await db.price_books.update_one(
        {"_id": book["_id"]},
        {
            "$set": {
                "filename": target.name,
                "path": storage.relative(target),
                "bytes": size,
                "uploadedAt": _now(),
                "updatedAt": _now(),
            }
        },
    )

    # Deterministic extraction into the search index. `ingest_pricebook` - the
    # Claude pass - remains available as the adapter of last resort for a layout
    # the generic extractor cannot read, but it is no longer the default: it costs
    # minutes and tokens per book to do what parsing does in seconds.
    job = await jobs.enqueue(
        "index_catalog",
        payload={
            "priceBookId": str(book["_id"]),
            "filename": target.name,
            "fileSha": catalog_store.file_hash(target),
        },
        actor=actor,
    )

    await audit.record("price_book.upload", actor, {"priceBookId": book["_id"]}, after=target.name)
    response: dict[str, Any] = {
        "priceBook": await _decorate(await db.price_books.find_one({"_id": book["_id"]})),
        "job": serialise(job),
    }
    return response


@router.get("/{book_id}/file")
async def download_price_book(book_id: str) -> FileResponse:
    book = await db.price_books.find_one({"_id": oid(book_id)})
    if not book or not book.get("path"):
        raise HTTPException(404, "no file attached to this price book")

    path = storage.absolute(book["path"])
    if not path.exists():
        raise HTTPException(410, f"file missing on disk: {book['path']}")
    return FileResponse(path, filename=book.get("filename") or path.name)


@router.patch("/{book_id}")
async def update_price_book(book_id: str, body: PriceBookUpdate, actor: AdminActor) -> dict:
    book = await db.price_books.find_one({"_id": oid(book_id)})
    if not book:
        raise HTTPException(404, "price book not found")

    changes = body.model_dump(exclude_unset=True)
    if not changes:
        return await _decorate(book)

    await db.price_books.update_one({"_id": book["_id"]}, {"$set": {**changes, "updatedAt": _now()}})

    if "categories" in changes and changes["categories"] is not None:
        await asyncio.to_thread(
            sync_vendor_categories, book.get("vendor", ""), changes["categories"]
        )

    # A changed multiplier reprices every part on this program - but only where
    # there is a list price to multiply. A vendor bought on a flat net program
    # publishes costs, and multiplying one of those discounts it a second time:
    # a Bobrick line at its 2017 net would be quoted at a fraction of what CBC
    # pays. Ingest keeps nets out of `listPrice` for exactly this reason; these
    # two filters are the belt to that braces, and they also cover rows written
    # before the basis was recorded.
    #
    # An *unknown* basis is deliberately still repriced. It means no multiplier
    # has been transcribed for the vendor, not that the sheet quotes nets - and a
    # hand-built book is somebody stating outright that they entered a list price.
    repriced: int | None = None
    if "multiplier" in changes and changes["multiplier"]:
        if basis.price_basis(book.get("filename"), book.get("vendor")) == basis.NET:
            repriced = 0
        else:
            result = await db.products.update_many(
                {
                    "priceBookId": book["_id"],
                    "listPrice": {"$ne": None},
                    "priceBasis": {"$ne": basis.NET},
                },
                [
                    {
                        "$set": {
                            "multiplier": changes["multiplier"],
                            "cost": {
                                "$round": [
                                    {"$multiply": ["$listPrice", changes["multiplier"]]}, 2
                                ]
                            },
                            "updatedAt": _now(),
                            "updatedBy": actor,
                        }
                    }
                ],
            )
            repriced = result.modified_count

    await audit.record(
        "price_book.update",
        actor,
        {"priceBookId": book["_id"]},
        before={k: book.get(k) for k in changes},
        after={**changes, **({"repricedParts": repriced} if repriced is not None else {})},
    )
    return await _decorate(await db.price_books.find_one({"_id": book["_id"]}))


@router.post("/{book_id}/mark-reviewed")
async def mark_reviewed(book_id: str, actor: Actor) -> dict:
    book = await db.price_books.find_one({"_id": oid(book_id)})
    if not book:
        raise HTTPException(404, "price book not found")

    today = date.today().isoformat()
    await db.price_books.update_one(
        {"_id": book["_id"]}, {"$set": {"lastReviewed": today, "updatedAt": _now()}}
    )
    await audit.record("price_book.reviewed", actor, {"priceBookId": book["_id"]}, after=today)
    return await _decorate(await db.price_books.find_one({"_id": book["_id"]}))


@router.delete("/{book_id}", status_code=204, response_class=Response)
async def delete_price_book(book_id: str, actor: AdminActor) -> Response:
    """Remove the program. Products priced under it are kept but marked orphaned.

    Deleting a book must not silently vaporise catalog rows a live quote points at.
    """
    book = await db.price_books.find_one({"_id": oid(book_id)})
    if not book:
        raise HTTPException(404, "price book not found")

    await db.products.update_many(
        {"priceBookId": book["_id"]},
        {"$set": {"priceBookId": None, "orphanedFrom": book.get("vendor"), "updatedAt": _now()}},
    )

    # Remove what was indexed from this book's PDF, so a deleted catalog stops
    # appearing in search. Queued rather than done inline: the worker is the only
    # writer to the index, and deletion has to be verified, not assumed.
    if book.get("catalogId") or book.get("filename"):
        payload: dict[str, Any] = {
            "filename": book.get("filename"),
            "priceBookId": str(book["_id"]),
        }
        if book.get("catalogId"):
            payload["catalogId"] = book["catalogId"]
        await jobs.enqueue("delete_catalog", payload=payload, actor=actor)
    await db.price_books.delete_one({"_id": book["_id"]})
    await audit.record(
        "price_book.delete",
        actor,
        {"priceBookId": book["_id"]},
        before=book.get("vendor"),
        note="products retained, marked orphaned",
    )
    return Response(status_code=204)
