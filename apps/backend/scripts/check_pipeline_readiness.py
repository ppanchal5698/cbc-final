#!/usr/bin/env python3
"""One-shot readiness checks for upload → quotation draft pipeline.

Run on the host (reachable Mongo) or inside the worker container:

    python apps/backend/scripts/check_pipeline_readiness.py
    docker exec cbc-final-worker python /app/scripts/check_pipeline_readiness.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def _ok(label: str, detail: str = "") -> None:
    print(f"PASS  {label}" + (f" — {detail}" if detail else ""))


def _fail(label: str, detail: str) -> None:
    print(f"FAIL  {label} — {detail}")


def main() -> int:
    failed = 0

    # 1. visual_pages module in the running image / install
    try:
        from cbc.modules.extraction.api import visual_pages  # noqa: F401

        _ok("visual_pages.py", str(Path(visual_pages.__file__)))
    except Exception as exc:
        _fail("visual_pages.py", str(exc))
        failed += 1

    # 2. PARSER_URL
    parser_url = (os.environ.get("PARSER_URL") or "").strip()
    if parser_url:
        _ok("PARSER_URL", parser_url)
    else:
        # Also accept parsing_config resolution
        try:
            from cbc.modules.ops.api.parsing_config import enabled, resolve

            resolved, _ = resolve(None)
            if enabled(resolved):
                _ok("PARSER_URL", str(resolved.get("url")))
            else:
                _fail("PARSER_URL", "empty / parsing disabled")
                failed += 1
        except Exception as exc:
            _fail("PARSER_URL", str(exc))
            failed += 1

    # 3. readonly_uri
    try:
        from cbc.shared.mongo import readonly_uri

        uri = readonly_uri()
        if uri:
            _ok("readonly_uri()", uri.split("@")[-1][:60])
        else:
            _fail("readonly_uri()", "None")
            failed += 1
    except Exception as exc:
        _fail("readonly_uri()", str(exc))
        failed += 1

    # 4–6. Mongo inventory
    try:
        from pymongo import MongoClient

        from cbc.shared.config import settings
        from cbc.shared.mongo_uri import reachable_uri

        client = MongoClient(
            reachable_uri(settings.mongodb_uri), serverSelectionTimeoutMS=5000
        )
        db = client[settings.mongodb_db]

        pdf_books = list(
            db["priceBooks"].find(
                {"filename": {"$regex": r"\.pdf$", "$options": "i"}},
                {"filename": 1, "path": 1, "vendor": 1, "kind": 1},
            )
        )
        hager_pdfs = [
            b
            for b in pdf_books
            if str(b.get("vendor", "")).lower() == "hager"
            or "hager" in str(b.get("filename", "")).lower()
        ]
        if hager_pdfs:
            names = ", ".join(b.get("filename") or "?" for b in hager_pdfs)
            _ok("priceBooks Hager PDFs", names)
        else:
            _fail("priceBooks Hager PDFs", "none registered — run register_pricebook_pdfs.py")
            failed += 1

        page_n = db["pageIndex"].count_documents({})
        if page_n > 0:
            _ok("pageIndex count", str(page_n))
        else:
            _fail("pageIndex count", "0 — index_catalog not finished")
            failed += 1

        items_n = db["catalogItems"].count_documents({})
        if items_n >= 100:
            _ok("catalogItems", str(items_n))
        else:
            _fail("catalogItems", f"{items_n} (expected ~164 seed)")
            failed += 1

        # 7. special net
        from cbc.modules.pricing.api import reference_library as reflib

        net = reflib.get_special_net("hager", "010108")
        if net and net.get("net_price") is not None:
            _ok("get_special_net(hager, 010108)", f"net={net.get('net_price')}")
        else:
            # try a known model from seed if 010108 missing
            alt = reflib.get_special_net("hager", "3510")
            if alt and alt.get("net_price") is not None:
                _ok("get_special_net", f"3510 net={alt.get('net_price')}")
            else:
                _fail("get_special_net", "no net for 010108 or 3510")
                failed += 1

        client.close()
    except Exception as exc:
        _fail("mongo inventory", str(exc))
        failed += 1

    # 8. OCR / tesseract (worker image)
    try:
        import shutil

        tess = shutil.which("tesseract")
        if tess:
            _ok("tesseract", tess)
        else:
            _fail("tesseract", "not on PATH (rebuild worker with OCR)")
            failed += 1
    except Exception as exc:
        _fail("tesseract", str(exc))
        failed += 1

    # 9. Claude CLI presence (auth may still fail at runtime)
    try:
        import shutil

        claude = shutil.which("claude")
        if claude:
            _ok("claude CLI", claude)
        else:
            _fail("claude CLI", "not on PATH")
            failed += 1
    except Exception as exc:
        _fail("claude CLI", str(exc))
        failed += 1

    # 10. Hager PDF path resolution (sandbox cwd safety)
    try:
        from cbc.shared.pdfpages import resolve_pdf_path

        path = resolve_pdf_path("data/pricebooks/hager_price_book_18.pdf")
        _ok("hager PDF resolve", str(path))
    except Exception as exc:
        _fail("hager PDF resolve", str(exc))
        failed += 1

    # 11. LIST_X backfill importable
    try:
        from cbc.modules.pricing.api.list_x_backfill import backfill_priced_lines  # noqa: F401
        from cbc.modules.pricing.api.hager_list_price import lookup_ngp_list_price

        hit = lookup_ngp_list_price("785S")
        if hit and hit.get("list_price"):
            _ok("NGP 785S list lookup", f"${hit['list_price']} p.{hit.get('source_page')}")
        else:
            _fail("NGP 785S list lookup", "no price (PDF missing or unreadable)")
            failed += 1
    except Exception as exc:
        _fail("list_x / hager_list_price", str(exc))
        failed += 1

    # 12. Catalog parse wait + P21 connectivity knobs
    wait = (os.environ.get("CATALOG_PARSE_WAIT") or "").strip().lower()
    if wait in {"1", "true", "yes", "on"}:
        _ok("CATALOG_PARSE_WAIT", wait)
    else:
        _fail("CATALOG_PARSE_WAIT", f"{wait!r} — set to 1 so pricing waits for MinerU index")
        failed += 1

    p21 = (os.environ.get("P21_BASE_URL") or "").strip()
    if p21:
        _ok("P21_BASE_URL", p21.split("://")[-1][:40])
    else:
        _ok("P21_BASE_URL", "unset (NR-10 — Path 1 deferred; MANUAL / LIST_X OK)")

    # 13. Promote empty-pricing guard present
    try:
        from cbc.worker_kit.sandbox import EmptyPricingPromoteError  # noqa: F401

        _ok("sandbox EmptyPricingPromoteError", "present")
    except Exception as exc:
        _fail("sandbox EmptyPricingPromoteError", str(exc))
        failed += 1

    print()
    if failed:
        print(f"{failed} check(s) failed")
        return 1
    print("All readiness checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
