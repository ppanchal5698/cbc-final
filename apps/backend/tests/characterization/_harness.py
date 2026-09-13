"""Pin what the API does today, so the rewrite can be checked against it.

Each recipe calls an endpoint and pins its status code and the *shape* of its
response - keys and JSON types, with ids and timestamps reduced to markers - in
`snapshots/<test module>.json`. A snapshot is written only under
UPDATE_SNAPSHOTS=1; a missing or different one fails, so a new test cannot
record itself green in CI.

Shape, not values: two runs create different ids and dates, but the contract a
client depends on is which keys come back and what kind of thing each is.
Values that matter to behaviour are asserted in the recipe itself.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi.routing import APIRoute

from cbc.shared.auth import require_admin

SNAPSHOTS = Path(__file__).parent / "snapshots"
UPDATE = os.environ.get("UPDATE_SNAPSHOTS", "").strip() == "1"

_OBJECT_ID = re.compile(r"^[0-9a-f]{24}$")
_ISO_TIME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}")


def shape(value: Any) -> Any:
    """Keys and JSON types; ids and timestamps become markers."""
    if isinstance(value, dict):
        return {("<id>" if _OBJECT_ID.match(str(k)) else k): shape(v) for k, v in sorted(value.items())}
    if isinstance(value, list):
        # ponytail: first element stands for the list; a mixed list is under-described.
        return [shape(value[0])] if value else []
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, (int, float)):
        return "number"
    if value is None:
        return "null"
    if isinstance(value, str):
        if _OBJECT_ID.match(value):
            return "id"
        if _ISO_TIME.match(value):
            return "datetime"
        return "str"
    return type(value).__name__


def describe(response) -> dict[str, Any]:
    content_type = response.headers.get("content-type", "").split(";")[0].strip()
    if response.status_code == 204 or not response.content:
        body: Any = None
    elif content_type == "application/json":
        body = shape(response.json())
    else:
        body = {"content-type": content_type}
    return {"status": response.status_code, "body": body}


class Snapshots:
    def __init__(self, name: str) -> None:
        self.path = SNAPSHOTS / f"{name}.json"
        self.expected = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}
        self.recorded: dict[str, Any] = {}

    def pin_value(self, key: str, actual: Any) -> Any:
        self.recorded[key] = actual
        if UPDATE:
            return actual
        assert key in self.expected, (
            f"no snapshot for {key!r} in {self.path.name}; record it with UPDATE_SNAPSHOTS=1"
        )
        assert actual == self.expected[key], (
            f"{key}: contract changed\nexpected {self.expected[key]}\nactual   {actual}"
        )
        return actual

    def pin(self, op: str, response, variant: str = ""):
        """`op` is the route template, e.g. "POST /api/projects/{code}/line-items"."""
        key = f"{op} #{variant}" if variant else op
        self.pin_value(key, describe(response))
        return response

    def save(self) -> None:
        if UPDATE and self.recorded:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.recorded, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def route_table(app) -> list[dict[str, Any]]:
    """Every operation the app serves: method, path, declared status, admin-only.

    Walks FastAPI's included-router wrappers explicitly. Since 0.141 `app.routes`
    holds opaque `_IncludedRouter` entries, so a naive walk finds only /api/health.
    """
    def walk(routes, prefix=""):
        for route in routes:
            if isinstance(route, APIRoute):
                yield prefix, route
            elif type(route).__name__ == "_IncludedRouter":
                inner = prefix + (route.include_context.prefix or "")
                yield from walk(route.original_router.routes, inner)

    def calls(dependant):
        for dep in dependant.dependencies:
            yield dep.call
            yield from calls(dep)

    rows = {}
    for prefix, route in walk(app.router.routes):
        admin = require_admin in set(calls(route.dependant))
        for method in route.methods - {"HEAD", "OPTIONS"}:
            key = f"{method} {prefix + route.path}"
            rows.setdefault(key, {"op": key, "status": route.status_code or 200, "admin": admin})
    return [rows[k] for k in sorted(rows)]


# Values that satisfy each path parameter's type, for calls that must be rejected
# before any handler looks the resource up.
PLACEHOLDERS = {
    "code": "CBC-000000",
    "prior_code": "CBC-000001",
    "version": "1",
    "page_number": "1",
    "vendor": "hager",
    "family": "margins",
    "key": "x",
    "email": "nobody@example.com",
}


def fill(path: str) -> str:
    def value(match: re.Match) -> str:
        name = match.group(1)
        return PLACEHOLDERS.get(name, "0" * 24)

    return re.sub(r"\{([^}]+)\}", value, path)


def finish_pipeline_jobs(db_name: str, code: str) -> None:
    """Mark a bid's queued and running jobs done.

    Phase-boundary routes refuse (409) while another pipeline job is active, and
    no worker claims jobs in a test database, so a recipe clears them itself.
    """
    from cbc.persistence import names
    from tests.shared import mongo_client

    raw = mongo_client()
    try:
        database = raw[db_name]
        project = database[names.BID_REQUESTS].find_one({"code": code}, {"_id": 1})
        database.jobs.update_many(
            {"projectId": project["_id"], "status": {"$in": ["queued", "running"]}},
            {"$set": {"status": "done", "finishedAt": datetime.now(timezone.utc)}},
        )
    finally:
        raw.close()


def pdf_bytes(pages: int = 2, label: str = "DOOR SCHEDULE") -> bytes:
    """A small real PDF: the upload routes check the magic bytes and count pages."""
    try:
        import pymupdf as fitz
    except ImportError:  # older PyMuPDF
        import fitz

    document = fitz.open()
    for number in range(pages):
        document.new_page().insert_text((72, 72), f"{label} sheet {number + 1}")
    return document.tobytes()
