"""The shape of a catalog's page index.

One document per catalog. It says what the catalog is, how it is laid out, and
what is on each page - and deliberately says nothing about what anything costs.

Pre-extracting every product row is what this replaces. Vendor catalogs are too
irregular for that: 37.8% of the codes the old extractor produced contained no
letter at all, 183 dates were indexed as part numbers, and one vendor's sheet
yielded nothing while reporting success. A layout the extractor cannot read
degrades into plausible noise rather than failing.

Storing only *where to look* removes that failure mode. Nothing here can be stale
or wrong about a price, because no price is here. Claude reads the page.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

# What a page is for. Enough to skip the 60% of a price book that is diagrams and
# front matter without opening it.
PageKind = Literal["price_table", "item_numbers", "prose", "diagram", "toc", "unknown"]

BUILDER_VERSION = 1


class CatalogOverview(BaseModel):
    """The 'what is this book' document, written once per catalog.

    Read before any page lookup, so a pass knows how the vendor organises things
    before it starts guessing page numbers.
    """

    summary: str = ""
    product_lines: list[str] = Field(default_factory=list)
    how_prices_are_shown: str = ""
    gotchas: str = ""
    how_to_find_a_part: str = ""


class PageProfile(BaseModel):
    """How to read one vendor's page furniture, learned once and applied to all.

    Every Hager page carries the section title on the 4th line of a running
    header; ASI leads with column names; Rockwood and NGP with boilerplate. A
    fixed heuristic fits one of them. Learning the profile per catalog fits all of
    them, and costs one LLM call instead of one per page.
    """

    # Where the section title comes from: "line_index:3" or "regex:^([A-Z][A-Za-z ]+)$"
    title_source: str | None = None
    # Where the printed page number comes from, same grammar.
    printed_page_source: str | None = None
    # Lines that repeat on every page and carry no information.
    boilerplate: list[str] = Field(default_factory=list)
    # What a part number looks like here, for collecting page code prefixes.
    code_pattern: str | None = None
    notes: str = ""


class PageEntry(BaseModel):
    """One page, described well enough to decide whether to open it."""

    # 1-indexed, and what pdf-tools takes. For a spreadsheet this is the block
    # ordinal - see `sheet` and `rows`.
    pdf_page: int
    # What is actually printed on the page. Hager's PDF page 297 prints as "23",
    # because its numbering restarts per section. An estimator sent to "page 23"
    # of a 744-page book cannot find the line without both (NFR-3).
    printed_page: str | None = None

    title: str = ""
    description: str = ""
    code_prefixes: list[str] = Field(default_factory=list)
    # What is sold on this page, in the catalog's own words. The section name
    # is often not in the header - ASI puts it under a CATEGORY label halfway
    # down - and without it a search for "hand dryer" matches nothing.
    keywords: list[str] = Field(default_factory=list)
    has_prices: bool = False
    # The price-column headings on this page, when it shows more than one. ASI
    # prints "LIST PRICE" beside "**MAP PRICING", and MAP is roughly 55% of list
    # - so a pass that takes the rightmost number gets a figure that is not a
    # price at all, multiplies it, and underquotes the line. MAP is a floor for
    # advertising, never a cost. Recorded here so find_pages can say so at the
    # moment a page is handed over.
    price_columns: list[str] = Field(default_factory=list)
    kind: PageKind = "unknown"
    # How much the profile actually resolved here. A scanned page that fell back
    # to a default scores low rather than being presented as read.
    confidence: float = 0.0

    # Spreadsheets have no pages. The locator becomes a sheet and a row range;
    # everything above still applies.
    sheet: str | None = None
    rows: list[int] | None = None

    def locator(self) -> str:
        """How a citation names this page, for an estimator who has to find it."""
        if self.sheet:
            span = f" rows {self.rows[0]}-{self.rows[1]}" if self.rows else ""
            return f"sheet {self.sheet}{span}"
        if self.printed_page and self.printed_page != str(self.pdf_page):
            return f"PDF p{self.pdf_page} (printed p{self.printed_page})"
        return f"p{self.pdf_page}"


class PageIndexDocument(BaseModel):
    """What one catalog becomes in MongoDB."""

    catalog_id: str
    vendor: str
    file_name: str
    # Rebuild trigger. An unchanged file is not re-read and costs no LLM call.
    file_hash: str
    kind: str = "price_book"
    # list | net | unknown, from cbc.pageindex.basis. Whether the numbers on these
    # pages are list prices to be multiplied, or costs already.
    price_basis: str = "unknown"
    effective_date: str | None = None
    page_count: int = 0

    overview: CatalogOverview = Field(default_factory=CatalogOverview)
    profile: PageProfile = Field(default_factory=PageProfile)
    pages: list[PageEntry] = Field(default_factory=list)

    built_at: str | None = None
    builder_version: int = BUILDER_VERSION
    status: str = "ready"
    error: str | None = None

    def to_mongo(self) -> dict[str, Any]:
        """camelCase for storage, matching the rest of the collections."""
        return {
            "_id": self.catalog_id,
            "catalogId": self.catalog_id,
            "vendor": self.vendor,
            "fileName": self.file_name,
            "fileHash": self.file_hash,
            "kind": self.kind,
            "priceBasis": self.price_basis,
            "effectiveDate": self.effective_date,
            "pageCount": self.page_count,
            "overview": {
                "summary": self.overview.summary,
                "productLines": self.overview.product_lines,
                "howPricesAreShown": self.overview.how_prices_are_shown,
                "gotchas": self.overview.gotchas,
                "howToFindAPart": self.overview.how_to_find_a_part,
            },
            "profile": {
                "titleSource": self.profile.title_source,
                "printedPageSource": self.profile.printed_page_source,
                "boilerplate": self.profile.boilerplate,
                "codePattern": self.profile.code_pattern,
                "notes": self.profile.notes,
            },
            "pages": [
                {
                    "pdfPage": p.pdf_page,
                    "printedPage": p.printed_page,
                    "title": p.title,
                    "description": p.description,
                    "codePrefixes": p.code_prefixes,
                    "keywords": p.keywords,
                    "hasPrices": p.has_prices,
                    "kind": p.kind,
                    **({"priceColumns": p.price_columns} if p.price_columns else {}),
                    "confidence": p.confidence,
                    **({"sheet": p.sheet} if p.sheet else {}),
                    **({"rows": p.rows} if p.rows else {}),
                }
                for p in self.pages
            ],
            "builtAt": self.built_at,
            "builderVersion": self.builder_version,
            "status": self.status,
            "error": self.error,
        }

    @classmethod
    def from_mongo(cls, row: dict[str, Any]) -> PageIndexDocument:
        overview = row.get("overview") or {}
        profile = row.get("profile") or {}
        return cls(
            catalog_id=row["catalogId"],
            vendor=row["vendor"],
            file_name=row["fileName"],
            file_hash=row.get("fileHash", ""),
            kind=row.get("kind", "price_book"),
            price_basis=row.get("priceBasis", "unknown"),
            effective_date=row.get("effectiveDate"),
            page_count=row.get("pageCount", 0),
            overview=CatalogOverview(
                summary=overview.get("summary", ""),
                product_lines=overview.get("productLines", []),
                how_prices_are_shown=overview.get("howPricesAreShown", ""),
                gotchas=overview.get("gotchas", ""),
                how_to_find_a_part=overview.get("howToFindAPart", ""),
            ),
            profile=PageProfile(
                title_source=profile.get("titleSource"),
                printed_page_source=profile.get("printedPageSource"),
                boilerplate=profile.get("boilerplate", []),
                code_pattern=profile.get("codePattern"),
                notes=profile.get("notes", ""),
            ),
            pages=[
                PageEntry(
                    pdf_page=p["pdfPage"],
                    printed_page=p.get("printedPage"),
                    title=p.get("title", ""),
                    description=p.get("description", ""),
                    code_prefixes=p.get("codePrefixes", []),
                    keywords=p.get("keywords", []),
                    price_columns=p.get("priceColumns", []),
                    has_prices=p.get("hasPrices", False),
                    kind=p.get("kind", "unknown"),
                    confidence=p.get("confidence", 0.0),
                    sheet=p.get("sheet"),
                    rows=p.get("rows"),
                )
                for p in row.get("pages", [])
            ],
            built_at=row.get("builtAt"),
            builder_version=row.get("builderVersion", BUILDER_VERSION),
            status=row.get("status", "ready"),
            error=row.get("error"),
        )
