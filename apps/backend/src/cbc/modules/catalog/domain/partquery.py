"""How a spec string becomes a catalog query, in one place.

A door schedule cites `PEMKO-275A-42`. The catalog stores `275A` under
manufacturer `Pemko`. The old lookup tried the raw string exact, then `^raw` as a
prefix, and missed - so a pricing pass fell through to opening a PDF price book,
read a *different* part off it (NGP 431S), and quoted $12.41 for a part the
catalog already held at $7.16. That is the defect this module exists to close:
normalise the spec, then ask Mongo.

The sync MCP reader (pymongo) and the Ops-Hub API (motor) cannot share a
connection, so they share the *filter* instead. Everything here is pure - no
client, no I/O - which is also what makes it testable without a database.

`spec_key` is the same normaliser the match-learning loop keys on, so a learned
match and a catalog lookup agree on what a spec string is.
"""
from __future__ import annotations

import re
from typing import Any

# Rows safe to quote without re-reading a PDF page. Price-book ingest extracts
# are OCR guesses; the accuracy rule keeps them out of pricing.
INGEST_SEED = "price book ingest"

_SPLIT = re.compile(r"[\s\-_/,]+")
_HAS_LETTER = re.compile(r"[A-Za-z]")
_HAS_DIGIT = re.compile(r"\d")


def tokens(text: str) -> list[str]:
    """Split a spec string the way a part number is actually written."""
    return [t for t in _SPLIT.split(str(text or "").strip()) if t]


def _vendor_tokens(vendors: object) -> set[str]:
    """Vendor names as lowercase tokens, plus whole names, so `VON DUPRIN` matches."""
    out: set[str] = set()
    for vendor in vendors or ():
        parts = tokens(str(vendor))
        if not parts:
            continue
        out.update(t.lower() for t in parts)
        out.add(" ".join(t.lower() for t in parts))
    return out


def normalize(part: str, vendors: object = ()) -> list[str]:
    """Candidate part strings for `part`, most specific first.

    The raw string is always candidate #0. ASI writes real part numbers like
    `10-645210A-00`; stripping its leading numeric token would shred a part that
    matches exactly, so nothing is stripped until the raw string has had its
    chance.
    """
    raw = str(part or "").strip()
    if not raw:
        return []

    candidates = [raw]

    def add(value: str) -> None:
        if value and value not in candidates:
            candidates.append(value)

    parts = tokens(raw)
    known = _vendor_tokens(vendors)

    # Strip a leading vendor name, two tokens before one, so VON DUPRIN goes
    # before VON.
    body = parts
    for width in (2, 1):
        if len(body) > width and " ".join(t.lower() for t in body[:width]) in known:
            body = body[width:]
            add("-".join(body))
            break

    # Drop one trailing token at a time. A schedule writes the part first and
    # qualifies it afterwards - `4501-48-26D` is part 4501, 48 inches, finish
    # 26D - so every shorter prefix is a more general form of the same request.
    #
    # This replaces picking "the longest token with a letter and a digit", which
    # chose the qualifier over the part: `4501-48-26D` offered the finish `26D`,
    # `190S-20X40-32D` offered the size `20X40`, and `5100-HDHOS-ALUM` offered
    # nothing at all. All three then missed a catalog row that was there.
    for width in range(len(body) - 1, 0, -1):
        add("-".join(body[:width]))

    return [c for c in candidates if _specific_enough(c)]


def _specific_enough(candidate: str) -> bool:
    """Whether a candidate identifies anything at all.

    A part number carries a digit. A bare manufacturer letter (`B` from `B-212`)
    does not, and offering one matched every Bobrick part.
    """
    text = str(candidate).strip()
    return len(text) >= 2 and bool(_HAS_DIGIT.search(text))


def prefix_safe(candidate: str) -> bool:
    """Whether a candidate may be matched as a *prefix*.

    An exact match on a short candidate is harmless - it either is the part or it
    is not. A prefix match is not: `10`, the leading token of ASI's
    `10-645210A-00`, prefixes hundreds of its parts. Three characters is the
    shortest real part number the catalog holds (`33E`, `30S`).
    """
    return _specific_enough(candidate) and len(str(candidate).strip()) >= 3


def spec_key(spec: object) -> str:
    """A stable key for a spec string, for recalling what was matched to it.

    Case and separators carry no meaning here - `IVES 700 83", 630` and
    `ives-700-83-630` are the same request - so both collapse to one key.
    """
    if isinstance(spec, dict):
        spec = " ".join(str(v) for v in spec.values() if v not in (None, ""))
    # Inch and foot marks are punctuation here, not meaning: 83" and 83 are the
    # same request, and a key that tells them apart recalls nothing.
    words = (re.sub(r"[^0-9a-z]+", "", t.lower()) for t in tokens(str(spec or "")))
    return " ".join(w for w in words if w)


# `42in`, `36inch`, `7ft`, `1200mm` - a measurement someone wrote without a space.
# It has a letter and a digit like a part number does, and it is not one; counting
# it as one made `42in` and `42 inches` two different specifications.
_MEASUREMENT = re.compile(r"^\d+(?:in|ins|inch|inches|ft|feet|mm|cm|m)$", re.IGNORECASE)


def part_tokens(key: str) -> set[str]:
    """The tokens in a spec key that look like part numbers - letter *and* digit.

    `275a`, `99eo`, `b318`. These are what an estimator actually reads a spec by;
    the prose around them is how one person happened to write it down.
    """
    return {
        token
        for token in str(key or "").split()
        if _HAS_LETTER.search(token)
        and _HAS_DIGIT.search(token)
        and not _MEASUREMENT.match(token)
    }


def similarity(left: str, right: str) -> float:
    """How alike two spec keys are, 0.0-1.0.

    Not `difflib` alone: that compares character sequences in order, and the same
    opening gets written `Threshold, PEMKO 275A, 42 inches` on one bid and
    `pemko 275a threshold 42in` on the next. Those are the same request and score
    ~0.6 as sequences, so an order-sensitive measure recalls nothing that was not
    typed identically - which is the exact-match case we already have.

    So: when both sides name the same part numbers, that is the match, because a
    part number is the one token in a spec that means only itself. Otherwise fall
    back to overlap of tokens, which at least ignores word order.
    """
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0

    left_parts, right_parts = part_tokens(left), part_tokens(right)
    if left_parts and left_parts == right_parts:
        return 0.95
    if left_parts and right_parts and left_parts.isdisjoint(right_parts):
        # Both name part numbers and they share none: different parts, whatever
        # the prose around them says.
        return 0.0

    left_tokens, right_tokens = set(left.split()), set(right.split())
    if not left_tokens or not right_tokens:
        return 0.0
    overlap = len(left_tokens & right_tokens)
    return overlap / len(left_tokens | right_tokens)


def trust_clause(*, include_ingest: bool = False) -> dict[str, Any]:
    """Rows safe to quote. Markdown seed and hand-added parts; never OCR extracts."""
    if include_ingest:
        return {}
    return {
        "$and": [
            {"seedSource": {"$ne": INGEST_SEED}},
            {
                "$or": [
                    {"seedSource": {"$regex": r"catalog\.md", "$options": "i"}},
                    {"seedSource": {"$exists": False}},
                    {"seedSource": None},
                    {"seedSource": ""},
                ]
            },
        ]
    }


def vendor_clause(vendor: str | None) -> dict[str, Any] | None:
    """Match a vendor by key or manufacturer name.

    `vendorKey` uses underscores (`national_guard`), so a caller passing
    "National Guard" has to reach the manufacturer field to match at all.
    """
    if not vendor or not str(vendor).strip():
        return None
    key = str(vendor).strip().lower()
    return {
        "$or": [
            {"vendorKey": key},
            {"vendorKey": key.replace(" ", "_")},
            {"manufacturer": {"$regex": re.escape(key), "$options": "i"}},
        ]
    }


def _with(clauses: list[dict[str, Any] | None], extra: dict[str, Any]) -> dict[str, Any]:
    kept = [c for c in [*clauses, extra] if c]
    if not kept:
        return {}
    return {"$and": kept} if len(kept) > 1 else kept[0]


def identity_filter(
    candidate: str,
    vendor: str | None = None,
    *,
    prefix: bool = False,
    include_ingest: bool = False,
) -> dict[str, Any]:
    """Exact (or prefix) match on part or model, within trust and vendor."""
    escaped = re.escape(str(candidate).strip())
    pattern = f"^{escaped}" if prefix else f"^{escaped}$"
    match = {
        "$or": [
            {"part": {"$regex": pattern, "$options": "i"}},
            {"model": {"$regex": pattern, "$options": "i"}},
        ]
    }
    base = [trust_clause(include_ingest=include_ingest), vendor_clause(vendor)]
    return _with(base, match)


def text_filter(
    query: str,
    vendor: str | None = None,
    *,
    include_ingest: bool = False,
) -> dict[str, Any]:
    """`$text` against the `product_search` index.

    The index has always existed and was never used: the old filter `$or`-ed four
    regexes, one of them an unanchored literal substring of the *whole* query, so
    "paper towel dispenser recessed" matched nothing while scanning all 6,579
    rows. `$text` answers the same question from 6 index keys.
    """
    base = [trust_clause(include_ingest=include_ingest), vendor_clause(vendor)]
    return _with(base, {"$text": {"$search": str(query).strip()}})


def regex_filter(
    query: str,
    vendor: str | None = None,
    *,
    include_ingest: bool = False,
) -> dict[str, Any]:
    """The pre-`$text` shape, kept as the fallback for partial tokens.

    `$text` tokenises on word boundaries, so a fragment like `2752` inside
    `2752WSP` is invisible to it. This still scans, so it runs only when `$text`
    came back empty.
    """
    escaped = re.escape(str(query).strip())
    match = {
        "$or": [
            {"part": {"$regex": f"^{escaped}", "$options": "i"}},
            {"model": {"$regex": f"^{escaped}", "$options": "i"}},
            {"description": {"$regex": escaped, "$options": "i"}},
            {"manufacturer": {"$regex": escaped, "$options": "i"}},
        ]
    }
    base = [trust_clause(include_ingest=include_ingest), vendor_clause(vendor)]
    return _with(base, match)


def _demo() -> None:
    """Runnable check - the real cases that were silently missing."""
    vendors = ["pemko", "asi", "national_guard", "Von Duprin", "ives", "zero"]

    # The $12.41 defect: the raw string missed, the normalised one hits.
    assert normalize("PEMKO-275A-42", vendors)[0] == "PEMKO-275A-42"
    assert "275A" in normalize("PEMKO-275A-42", vendors)

    # ASI part numbers survive whole - the raw string is always tried first.
    assert normalize("10-645210A-00", vendors)[0] == "10-645210A-00"

    # Two-token vendor names are stripped before the one-token pass sees VON.
    assert "99EO" in normalize("VON-DUPRIN-99EO-42-626", vendors)

    # Empty in, empty out - never a query for everything.
    assert normalize("", vendors) == []

    # spec_key collapses case and separators onto one key.
    assert spec_key('IVES 700 83", 630') == spec_key("ives-700-83-630")

    # Trust: ingest rows are excluded by default, included on request.
    assert trust_clause()["$and"][0] == {"seedSource": {"$ne": INGEST_SEED}}
    assert trust_clause(include_ingest=True) == {}

    # vendorKey uses underscores; a caller saying "National Guard" still matches.
    assert {"vendorKey": "national_guard"} in vendor_clause("National Guard")["$or"]

    assert "$text" in str(text_filter("paper towel dispenser"))
    print("partquery demo OK")


if __name__ == "__main__":
    _demo()
