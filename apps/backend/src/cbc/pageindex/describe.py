"""Turn one page of a catalog into an index entry, using a learned profile.

This is the part that runs 1,216 times, so it does not call an LLM. The profile
says where this vendor puts its section title and page number; applying it is
string work. One LLM call per catalog decides the profile, and the pages are
described from it for free.

A page the profile cannot resolve is not guessed at - it comes back with a low
confidence and `kind: "unknown"`, and the builder sends those few to the model.
"""
from __future__ import annotations

import re
from typing import Any

from cbc.pageindex.models import PageEntry, PageKind, PageProfile

# A money-shaped token. Deciding "does this page carry prices" is the difference
# between a page worth opening and one that is a diagram.
_PRICE = re.compile(r"(?<![\w.])\$?\d{1,3}(?:,\d{3})*\.\d{2}(?![\w])")

# A part-number-shaped token, when the profile does not supply a better pattern.
#
# Two families, because vendors split about evenly between them: letter-led
# (BB1279, ECBB1100, B-2888) and digit-led (Hager's 3400 series, LCN 4040XP).
# The digit-led branch demands four digits so it does not collect page numbers
# and the cents half of a price, which is how the old extractor ended up with
# 183 dates recorded as part numbers.
_CODE_FALLBACK = re.compile(
    r"\b(?:[A-Z]{1,4}-?\d{2,5}[A-Z0-9/-]*|\d{4,5}[A-Z][A-Z0-9/-]*|\d{4,5})\b"
)

# A bare page number, for the common case where the printed number is the only
# short numeric line in the header.
_BARE_NUMBER = re.compile(r"^\s*(\d{1,4})\s*$")

_SOURCE = re.compile(r"^(line_index|regex):(.*)$", re.DOTALL)

# US finish codes are code-shaped and appear on nearly every price page, so they
# crowd the real part families out of the routing list. They are a finish
# nomenclature, not a product (business rule 7.5), and the crosswalk in
# reference-library already owns them.
_FINISH = re.compile(r"^US\d{1,2}[A-Z]?$")


# A bare four-digit number in this range is a year, not a part family. Real
# families across the indexed catalogs (3400, 9566, 2630, 1828) fall outside it.
# A vendor who genuinely numbers a part 2026 loses one routing hint; the
# alternative is every effective date on every page becoming a product, which is
# exactly what the extractor this replaces did 183 times.
_YEAR = re.compile(r"^(?:19|20)\d{2}$")


# Column labels that head a table rather than name a section. Without a learned
# profile these win the first-heading fallback and title every ASI page "MODEL
# NUMBER", which tells a reader nothing about what is on it.
_GENERIC_HEADING = frozenset(
    {
        "MODEL NUMBER",
        "CATEGORY",
        "DESCRIPTION",
        "PRICE EACH",
        "ITEM",
        "ITEM NUMBER",
        "PRODUCT",
        "PRODUCT NAME",
        "SHIPPING",
        "PART NUMBER",
        "LIST PRICE",
        "NET PRICE",
        "PAGE",
        "QTY",
        "QUANTITY",
    }
)

# Page furniture that is never a section heading, for the no-profile fallback.
_NOT_A_HEADING = re.compile(
    r"^(?:\d{1,4}|[\d/.\-]{6,}|(?:https?://)?www\..*|.*@.*|page \d+.*)$", re.IGNORECASE
)


# Lines that read like a product category rather than a table cell or furniture.
# ASI puts "TOILET TISSUE DISPENSERS" a dozen lines down under a CATEGORY label,
# so a description built only from the page header knows nothing about what is
# actually being sold on the page - and a search for "hand dryer" finds nothing.
_CATEGORY_NOISE = frozenset(
    """model number category price each shipping continued description item
    product name page total list net cu.ft wt-lbs finish size qty""".split()
)


def _keywords(body: list[str], limit: int = 6) -> list[str]:
    """What is being sold on this page, in the catalog's own words.

    Heading-shaped lines from anywhere on the page, not just the top: the section
    name is as likely to sit halfway down under a column label as in the running
    header, and it is the only thing that answers "which page has hand dryers".
    """
    seen: dict[str, int] = {}
    for line in body:
        text = re.sub(r"\(continued\)", "", line, flags=re.IGNORECASE).strip(" -:|")
        if not (4 <= len(text) <= 60) or not any(c.isalpha() for c in text):
            continue
        words = [w for w in re.split(r"[^A-Za-z]+", text) if len(w) > 2]
        if len(words) < 2 or len(words) > 7:
            continue
        # Headings are set apart by case; a sentence of prose is not a category.
        if not (text.isupper() or text.istitle()):
            continue
        if all(w.lower() in _CATEGORY_NOISE for w in words):
            continue
        key = " ".join(words).upper()
        seen[key] = seen.get(key, 0) + 1
    ranked = sorted(seen.items(), key=lambda kv: (-kv[1], kv[0]))
    return [k for k, _ in ranked[:limit]]


def _first_heading(lines: list[str], limit: int = 8) -> str | None:
    """The first line that reads like a section name rather than furniture.

    Without a learned profile the obvious fallback is line one, but on most price
    books that is the printed page number - which would title every page in the
    book with a digit and route nothing.
    """
    for line in lines[:limit]:
        if len(line) < 3 or len(line) > 90:
            continue
        if _NOT_A_HEADING.match(line):
            continue
        if not any(ch.isalpha() for ch in line):
            continue
        return line[:80]
    return None


def _stem(token: str) -> str:
    """The family a code belongs to, for routing.

    Splitting on every separator turns Bobrick's `B-2888` into `B` and loses it.
    The leading segment is only the family when it is substantial on its own -
    `3400-ANSI` is a 3400, `B-2888` is a B-2888.
    """
    head = token.strip().upper().split("/")[0]
    first = head.partition("-")[0]
    return first if len(first) >= 3 else head


def page_lines(text: str) -> list[str]:
    """Non-empty, stripped lines. The unit every profile rule addresses."""
    return [line.strip() for line in text.splitlines() if line.strip()]


def _apply_source(source: str | None, lines: list[str]) -> str | None:
    """Resolve a profile rule against one page's lines.

    Two grammars, both deliberately dull: `line_index:3` takes the fourth line,
    `regex:...` takes the first capture that matches anywhere on the page. A rule
    that does not resolve returns None rather than an approximation.
    """
    if not source:
        return None
    match = _SOURCE.match(source)
    if not match:
        return None
    kind, argument = match.group(1), match.group(2)

    if kind == "line_index":
        try:
            index = int(argument)
        except ValueError:
            return None
        return lines[index] if 0 <= index < len(lines) else None

    try:
        pattern = re.compile(argument, re.MULTILINE)
    except re.error:
        return None
    for line in lines:
        found = pattern.search(line)
        if found:
            return (found.group(1) if found.groups() else found.group(0)).strip()
    return None


def _strip_boilerplate(lines: list[str], boilerplate: list[str]) -> list[str]:
    """Drop the running header and footer this vendor repeats on every page."""
    if not boilerplate:
        return lines
    needles = [b.strip().lower() for b in boilerplate if b.strip()]
    return [
        line
        for line in lines
        if not any(needle in line.lower() for needle in needles)
    ]


def _classify(body: list[str], has_prices: bool, code_count: int) -> tuple[PageKind, float]:
    """What this page is for, and how sure the evidence makes us."""
    joined = " ".join(body[:40]).lower()
    if not body:
        # No text layer at all - a scan or a full-page image. Say so; do not
        # describe a page nobody has read.
        return "diagram", 0.2
    if "table of contents" in joined or "index" == joined.strip():
        return "toc", 0.7
    if has_prices and code_count >= 3:
        return "price_table", 0.9
    if code_count >= 5 and not has_prices:
        # Hager's item-number tables: product name -> item number, no money.
        return "item_numbers", 0.8
    if has_prices:
        return "price_table", 0.6
    if len(body) > 12:
        return "prose", 0.5
    return "unknown", 0.3


def _code_prefixes(body: list[str], pattern: str | None, limit: int = 8) -> list[str]:
    """The families of part number this page carries, most frequent first.

    Prefixes rather than whole codes: the point is routing - "this page is where
    the 3400 series lives" - not reproducing the catalog.
    """
    try:
        compiled = re.compile(pattern) if pattern else _CODE_FALLBACK
    except re.error:
        compiled = _CODE_FALLBACK

    counts: dict[str, int] = {}
    for line in body:
        for token in compiled.findall(line):
            token = token if isinstance(token, str) else token[0]
            stem = _stem(token)
            if len(stem) >= 3 and not _FINISH.match(stem) and not _YEAR.match(stem):
                counts[stem] = counts.get(stem, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [stem for stem, _ in ranked[:limit]]


def _summarise(
    title: str, body: list[str], kind: PageKind, has_prices: bool,
    keywords: list[str] | None = None,
) -> str:
    """Two lines: what is on the page, and what you get if you open it.

    Built from the page's own words. A generated sentence would read better and
    would be one more thing that can be wrong about a page nobody checked.
    """
    subject = title or (body[0][:60] if body else "")
    detail = ""
    for line in body[1:8]:
        if line.lower() != subject.lower() and 3 < len(line) < 90:
            detail = line
            break

    what = {
        "price_table": "Price table",
        "item_numbers": "Item-number listing",
        "toc": "Contents",
        "prose": "Reference text",
        "diagram": "No text layer - diagram or scan",
        "unknown": "Page",
    }[kind]

    parts = [f"{what}{f' - {subject}' if subject else ''}."]
    if detail:
        parts.append(f"Begins: {detail}.")
    if keywords:
        parts.append("Covers: " + ", ".join(k.title() for k in keywords[:4]) + ".")
    if has_prices:
        parts.append("Carries prices.")
    return " ".join(parts)[:400]


# Headings that name a money column. A page showing more than one of these is
# showing more than one kind of number, and only one of them is a cost basis.
_PRICE_COLUMN_HEADINGS = (
    ("MINIMUM ADVERTISED", "MAP"),
    ("MAP", "MAP"),
    ("LIST PRICE", "LIST"),
    ("NET PRICE", "NET"),
    ("DEALER", "DEALER"),
)


def _price_columns(body: list[str]) -> list[str]:
    """Which money columns this page prints, when it prints more than one.

    ASI heads its price tables "LIST PRICE | **MAP PRICING", and MAP runs about
    55% of list - 145.70 against 80.10 on page 35. A pass that takes the
    rightmost number on the row gets MAP, applies the vendor multiplier to it and
    quotes roughly half what the part costs, which is the error that wins a bid
    and loses money on it. MAP is an advertising floor, never a cost basis, and
    the only place that fact arrives in time is the page itself.
    """
    found: dict[str, int] = {}
    for line in body:
        upper = line.upper()
        for needle, label in _PRICE_COLUMN_HEADINGS:
            at = upper.find(needle)
            if at >= 0 and label not in found:
                found[label] = at
    # Left to right, as the page prints them, so the reader can see that LIST
    # comes before MAP rather than having to know it.
    ordered = sorted(found, key=lambda label: found[label])
    # One money column is an ordinary price list; two is the trap.
    return ordered if len(ordered) > 1 else []


def describe_page(
    text: str,
    pdf_page: int,
    profile: PageProfile,
    *,
    sheet: str | None = None,
    rows: list[int] | None = None,
) -> PageEntry:
    """One page's index entry. No LLM, no network, no I/O."""
    lines = page_lines(text)
    title = _apply_source(profile.title_source, lines) or ""
    printed = _apply_source(profile.printed_page_source, lines)

    if printed is None:
        # The overwhelmingly common case: the printed number is a short numeric
        # line somewhere in the first few lines of the header.
        for line in lines[:4]:
            bare = _BARE_NUMBER.match(line)
            if bare:
                printed = bare.group(1)
                break

    body = _strip_boilerplate(lines, profile.boilerplate)
    if title and body and body[0].strip().lower() == title.strip().lower():
        body = body[1:]

    has_prices = bool(_PRICE.search("\n".join(body)))
    price_columns = _price_columns(body) if has_prices else []
    prefixes = _code_prefixes(body, profile.code_pattern)
    keywords = _keywords(body)
    kind, confidence = _classify(body, has_prices, len(prefixes))

    # A title the profile found is real evidence; inferring one from the page is
    # weaker, and the score says so. Take the first line that is actually a
    # heading: the literal first line is usually the printed page number, which
    # names every page in the book "114" and routes nothing.
    if not title:
        title = _first_heading(body) or _first_heading(lines) or ""
        # A column label is not a section name. What the page sells is a better
        # title than the header of the table it sells it in.
        if title.strip().upper() in _GENERIC_HEADING and keywords:
            title = keywords[0].title()
        if title:
            confidence = min(confidence, 0.5)

    return PageEntry(
        pdf_page=pdf_page,
        printed_page=printed,
        title=title,
        description=_summarise(title, body, kind, has_prices, keywords),
        code_prefixes=prefixes,
        keywords=keywords,
        has_prices=has_prices,
        price_columns=price_columns,
        kind=kind,
        confidence=round(confidence, 2),
        sheet=sheet,
        rows=rows,
    )


def needs_a_second_look(entry: PageEntry) -> bool:
    """Pages worth spending an LLM call on, in batches, after the cheap pass."""
    return entry.confidence < 0.5 or (not entry.title and entry.kind == "unknown")


def _demo() -> None:
    """The real Hager header shape, and a page the profile cannot read."""
    hager = PageProfile(
        title_source="line_index:3",
        printed_page_source="line_index:0",
        boilerplate=["www.hagerco.com", "03/01/2026"],
    )
    text = (
        "23\n03/01/2026\nwww.hagerco.com\nLocks - 3400 Series\n"
        "Strikes\nDescription\n3400 ANSI strike 1-1/4 x 4-7/8  $12.50\n"
        "3402 T-strike  $14.75\n3400L lip strike  $16.00\n"
    )
    entry = describe_page(text, pdf_page=297, profile=hager)
    assert entry.title == "Locks - 3400 Series", entry.title
    # The pair NFR-3 needs: the page pdf-tools takes, and the one printed on it.
    assert entry.printed_page == "23" and entry.pdf_page == 297
    assert entry.has_prices and entry.kind == "price_table", entry
    assert "3400" in entry.code_prefixes, entry.code_prefixes
    # Finish codes are a nomenclature, not a part family (rule 7.5).
    finishes = describe_page(
        "3400 lock US26D 626 US10B  $12.50", 1, PageProfile()
    ).code_prefixes
    assert "3400" in finishes and not [c for c in finishes if c.startswith("US")], finishes
    assert "printed p23" in entry.locator(), entry.locator()

    blank = describe_page("", pdf_page=5, profile=hager)
    assert blank.kind == "diagram" and blank.confidence <= 0.2
    assert needs_a_second_look(blank)
    assert not needs_a_second_look(entry)

    # A spreadsheet block cites a sheet and rows, not a page.
    sheet = describe_page(
        "Program Net\nB-2888 Soap dispenser  $41.00", 1, PageProfile(),
        sheet="Program Net", rows=[12, 260],
    )
    assert "sheet Program Net rows 12-260" == sheet.locator(), sheet.locator()
    print("cbc.pageindex.describe OK")


if __name__ == "__main__":
    _demo()
