"""The cost of one take-off line, by the ladder - decided in code.

  0. Allegion -> the base line is the Hager equal, for the estimator to name; the
     specified Allegion part is an alternate priced by the distributor (Banner /
     SecLock). Never priced off a list.
  1. P21 last PO
  2. Special net (CBC's negotiated sheet)
  3. Catalog row
  4. Price book list x the vendor's multiplier for that section
  5. Division 10 only: the part's direct equal in a brand CBC prices, from the
     cross-reference, with a substitution note for the GC (Matrix 6.4)
  6. Otherwise MANUAL, saying what each rung found.

Each rung takes a row only when the matcher says the row is this item; a rung
that finds several rows at different prices says so and the next rung is not
tried, because a cheaper or dearer list price for an item CBC holds a net for
would be wrong in a way nobody sees. A sheet past its review window is skipped,
and the line says why.

Pure: the line and the bid's rows in, the file rows out. Every number comes from
a row the detail names (NFR-3); the arithmetic is pricing's.
"""
from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from typing import Any

from cbc.modules.quoting.domain import matcher
from cbc.modules.quoting.domain.takeoff import Line

ALLEGION_ALTERNATE = "Allegion as specified"
BY_OTHERS_ALTERNATE = "Supplied by others"
_US_FINISH = re.compile(r"\bUS\d{1,3}[A-Z]?\b", re.I)
_PART_LIKE = re.compile(r"^(?=.*[A-Z])(?=.*\d)[A-Z0-9][A-Z0-9\-/.]*$", re.I)


def vendor_key(name: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(name or "").strip().lower()).strip("_")


@dataclass
class Sources:
    """Everything the ladder reads, fetched once for the whole bid."""

    models: Callable[[str], list[str]]  # the forms of a part to try, most specific first
    finish: matcher.FinishKey
    lapsed: Callable[[Any], bool]  # a dated sheet past the review window
    cost_from_list: Callable[[float, float], float]
    multiplier_category: Callable[[str, Any], str | None]
    special_nets: list[dict[str, Any]] = field(default_factory=list)
    special_net_effective: str | None = None
    catalog: list[dict[str, Any]] = field(default_factory=list)
    book: list[dict[str, Any]] = field(default_factory=list)
    books: dict[str, dict[str, Any]] = field(default_factory=dict)  # priceBookId -> {name, effective}
    tiers: dict[str, dict[str, Any]] = field(default_factory=dict)  # vendor key -> tier record
    last_po: Callable[[str, str | None], dict[str, Any] | None] | None = None
    special_margin: tuple[float, str] | None = None
    priced_at: str = ""
    equals: dict[str, Any] = field(default_factory=dict)  # the Division 10 direct-equal matrix
    equal_rows: list[dict[str, Any]] = field(default_factory=list)  # catalog rows of the brands it names


def _desc_finish(text: Any) -> str | None:
    found = _US_FINISH.search(str(text or ""))
    return found.group(0) if found else None


def guess_part(line: Line) -> str | None:
    """A legend that put the model in its description: the first token that looks
    like a part number and is not a finish code."""
    for token in re.split(r"[\s,;()]+", line.description or ""):
        if _PART_LIKE.match(token) and not _US_FINISH.fullmatch(token) and not matcher.dimensions(token):
            return token
    return None


def _candidates_note(rows: Iterable[dict[str, Any]], show: Callable[[dict[str, Any]], str]) -> str:
    rows = list(rows)
    shown = "; ".join(show(r) for r in rows[:3])
    return shown + (f"; +{len(rows) - 3} more" if len(rows) > 3 else "")


def _row(line: Line, src: Sources) -> dict[str, Any]:
    out: dict[str, Any] = {
        "line_id": line.key,
        "group": line.group,
        "group_type": "accessories" if line.division.startswith("10") else "frp" if line.division.startswith(("06", "09")) else "door",
        "division": line.division,
        "part_number": line.part,
        "description": line.description or line.part,
        "manufacturer": line.manufacturer,
        "finish": line.finish,
        "quantity": line.qty,
        "unit": line.unit,
        "qty_per_opening": line.qty_per_opening,
        "openings": list(line.openings),
        "source_file": line.source_file,
        "source_page": line.source_page,
        "cost": None,
        "cost_source": "MANUAL",
        "price_status": "NEEDS_JUDGMENT",
        "priced_at": src.priced_at,
        "flags": list(line.flags),
    }
    if line.alternate:
        out["alternate_group"] = BY_OTHERS_ALTERNATE
        out["notes"] = line.alternate
    if src.special_margin:
        out["margin"], out["margin_override_reason"] = src.special_margin
    return out


def _priced(row: dict[str, Any], cost: float, source: str, detail: str, **provenance: Any) -> dict[str, Any]:
    row.update(cost=round(float(cost), 2), cost_source=source, cost_source_detail=detail,
               price_status="PRICED", **{k: v for k, v in provenance.items() if v is not None})
    return row


def _rung_special_net(spec: matcher.Spec, models: list[str], src: Sources) -> matcher.Choice:
    return matcher.choose(
        spec, src.special_nets, models=models,
        model_of=lambda r: r.get("part_number"), finish_of=lambda r: _desc_finish(r.get("description")),
        size_of=lambda r: r.get("description"), price_of=lambda r: r.get("net_price"),
        describe=lambda r: r.get("description"), finish=src.finish,
    )


def _rung_catalog(spec: matcher.Spec, models: list[str], vendor: str, src: Sources) -> matcher.Choice:
    rows = [r for r in src.catalog if not vendor or r.get("vendorKey") == vendor]
    return matcher.choose(
        spec, rows, models=models,
        model_of=lambda r: r.get("part"), finish_of=lambda r: _desc_finish(r.get("description")),
        size_of=lambda r: f"{r.get('part') or ''} {r.get('description') or ''}", price_of=lambda r: r.get("cost"),
        describe=lambda r: r.get("description"), finish=src.finish,
    )


def _rung_book(spec: matcher.Spec, models: list[str], vendor: str, src: Sources) -> matcher.Choice:
    rows = [r for r in src.book if not vendor or r.get("vendor") == vendor]
    return matcher.choose(
        spec, rows, models=models,
        model_of=lambda r: r.get("model"), finish_of=lambda r: r.get("finish"),
        size_of=lambda r: r.get("size"), price_of=lambda r: r.get("listPrice"),
        describe=lambda r: f"{r.get('description') or ''} {r.get('table') or ''}", finish=src.finish,
    )


def _show_net(r: dict[str, Any]) -> str:
    return f"{r.get('item_code')} {r.get('description')} ${r.get('net_price')}"


def _show_catalog(r: dict[str, Any]) -> str:
    return f"{r.get('manufacturer')} {r.get('part')} ${r.get('cost')}"


def _show_book(r: dict[str, Any]) -> str:
    return f"{r.get('model')} {r.get('size') or ''} {r.get('finish') or ''} ${r.get('listPrice')} p.{r.get('page')}".replace("  ", " ")


MAX_CANDIDATES = 8  # rows offered to whoever chooses; more than this, the legend says too little
# Where an undecided row keeps its candidates until they are chosen among. Not a
# field of the priced file: the job takes it off before it writes.
UNDECIDED = "_undecided"


def _undecided(row: dict[str, Any], label: str, choice: matcher.Choice, show) -> list[dict[str, Any]]:
    """This item, at several prices: someone picks, and no cheaper or dearer rung is
    tried in the meantime. `UNDECIDED` keeps the rows for whoever does."""
    row["cost_source_detail"] = (f"{label}: {choice.reason}: {_candidates_note(choice.candidates, show)}"
                                 " - an estimator picks which")
    row["flags"].append("ambiguous_match")
    row[UNDECIDED] = {"rung": label, "candidates": choice.candidates[:MAX_CANDIDATES],
                      "shown": [show(r) for r in choice.candidates[:MAX_CANDIDATES]]}
    return [row]



def _from_net(row: dict[str, Any], net: dict[str, Any], src: Sources, tried: list[str]) -> dict[str, Any] | None:
    """The line priced at a special net - or None, said in `tried`, when the sheet is past review."""
    if src.lapsed(src.special_net_effective):
        tried.append(f"special net {net.get('item_code')} skipped - the sheet dated "
                     f"{src.special_net_effective} is past review")
        return None
    return _priced(
        row, net["net_price"], "SPECIAL_NET",
        f"special-net sheet ({net.get('section') or 'Hager special nets'}) item {net.get('item_code')} "
        f"- {net.get('description')}",
        part_number=net.get("part_number") or row.get("part_number"), manufacturer="Hager",
        multiplier_effective_date=src.special_net_effective,
        price_book_version=f"Hager special-net sheet, effective {src.special_net_effective}",
    )


def _from_book(row: dict[str, Any], entry: dict[str, Any], src: Sources, vendor: str,
               tried: list[str]) -> dict[str, Any] | None:
    """The line priced at a price-book row times its section's multiplier - or None,
    said in `tried`, when no multiplier covers the section or a sheet is past review."""
    entry_vendor = entry.get("vendor") or vendor
    category = src.multiplier_category(entry_vendor, entry.get("section"))
    tier = src.tiers.get(entry_vendor) or {}
    multiplier = (tier.get("categories") or {}).get(category) if category else tier.get("multiplier")
    effective = entry.get("effective")
    where = (f"{entry.get('file')} p.{entry.get('page')} (printed {entry.get('printedPage')}) "
             f"{entry.get('model')} {entry.get('size') or ''} {entry.get('finish') or ''}").replace("  ", " ")
    if multiplier is None:
        tried.append(f"price book {where} list ${entry.get('listPrice')}, but no {entry_vendor} multiplier "
                     f"covers its section {entry.get('section')!r}")
        return None
    if src.lapsed(tier.get("effective_date")) or src.lapsed(effective):
        tried.append(f"price book {where} skipped - the sheet or its multiplier is past review")
        return None
    cost = src.cost_from_list(float(entry["listPrice"]), float(multiplier))
    book = src.books.get(str(entry.get("priceBookId"))) or {}
    return _priced(
        row, cost, "LIST_X_MULTIPLIER",
        f"{where} list ${entry['listPrice']:.2f} x {category or 'account'} {multiplier:g} -> ${cost:.2f}",
        part_number=entry.get("model"), manufacturer=row.get("manufacturer") or entry_vendor.title(),
        list_price=entry.get("listPrice"), multiplier=float(multiplier), multiplier_tier=category or "all",
        multiplier_effective_date=tier.get("effective_date") or effective,
        price_book_version=f"{book.get('name') or entry.get('file')}, effective {effective}",
        catalog_page=entry.get("page"),
    )


def price_choice(row: dict[str, Any], index: int, reason: str, src: Sources) -> dict[str, Any] | None:
    """An undecided row priced at the candidate someone chose - through the same
    rung, with the same checks - and saying who chose it and why. None when the
    choice is not one of the rows, or its sheet cannot be priced from."""
    pending = row.get(UNDECIDED) or {}
    candidates = pending.get("candidates") or []
    if not 0 <= index < len(candidates):
        return None
    chosen, tried = candidates[index], []
    rung = pending.get("rung")
    if rung == "special net":
        priced = _from_net(row, chosen, src, tried)
    elif rung == "catalog":
        priced = _from_catalog(row, chosen, src, row.get("manufacturer"), tried)
    else:
        priced = _from_book(row, chosen, src, vendor_key(row.get("manufacturer")), tried)
    if priced is None:
        return None
    priced["flags"] = [f for f in priced["flags"] if f != "ambiguous_match"] + ["model_chose_match"]
    priced["cost_source_detail"] += (f"; chosen among {len(candidates)} by the model ({reason.strip()})"
                                     " - an estimator confirms it")
    return priced


def _from_catalog(row: dict[str, Any], catalog_row: dict[str, Any], src: Sources, manufacturer: str | None,
                  tried: list[str]) -> dict[str, Any] | None:
    """The line priced at a catalog row - or None, said in `tried`, when its book is past review."""
    book = src.books.get(str(catalog_row.get("priceBookId"))) or {}
    effective = book.get("effective")
    if src.lapsed(effective):
        tried.append(f"catalog row {catalog_row.get('part')} skipped - {book.get('name') or 'its price book'} "
                     f"dated {effective} is past review")
        return None
    basis = (f"; list ${catalog_row['listPrice']} x {catalog_row['multiplier']}"
             if catalog_row.get("listPrice") and catalog_row.get("multiplier") else "")
    return _priced(
        row, catalog_row["cost"], "CATALOG_BASELINE",
        f"product catalog ({catalog_row.get('seedSource') or 'catalog'}) {catalog_row.get('manufacturer')} "
        f"part {catalog_row.get('part')}{basis}",
        part_number=catalog_row.get("part"), manufacturer=catalog_row.get("manufacturer") or manufacturer,
        list_price=catalog_row.get("listPrice"), multiplier=catalog_row.get("multiplier") or None,
        multiplier_effective_date=effective,
        price_book_version=f"{book.get('name')}, effective {effective}" if book.get("name") else None,
    )


_EQUAL_BRANDS = {"Bobrick": "bobrick", "ASI": "asi", "Bradley": "bradley", "Gamco": "gamco"}


def _norm(text: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(text or "").upper())


def _matrix_row(part: str, equals: dict[str, Any]) -> dict[str, Any] | None:
    """The cross-reference row naming this part, in whichever column and however
    its brand's catalog writes it (`B-212`, `10-0714`, `G-2116`)."""
    prefixes = [p for p in (equals.get("catalog_prefixes") or {}).values() if p]
    wanted = _norm(part)
    for entry in equals.get("rows") or []:
        for value in entry.values():
            if value and wanted in {_norm(value), *(_norm(prefix + value) for prefix in prefixes)}:
                return entry
    return None


def _direct_equal(row: dict[str, Any], line: Line, spec: matcher.Spec, src: Sources,
                  tried: list[str]) -> dict[str, Any] | None:
    """A Division 10 part CBC cannot price, offered as the first preferred brand's
    equal that it can - the GC approves a direct equal before it is ordered."""
    entry = _matrix_row(spec.part or "", src.equals)
    if entry is None:
        return None
    prefixes = src.equals.get("catalog_prefixes") or {}
    specified = vendor_key(line.manufacturer)
    for brand in src.equals.get("preferred_brands") or []:
        value, key = entry.get(brand), _EQUAL_BRANDS.get(brand, vendor_key(brand))
        if not value or key == specified:
            continue
        form = (prefixes.get(brand) or "") + value
        choice = _rung_catalog(matcher.Spec(part=form, manufacturer=brand, finish=spec.finish, text=spec.text),
                               [form, value], key, replace(src, catalog=src.equal_rows))
        if choice.row is None:
            continue
        priced = _from_catalog(row, choice.row, src, brand, tried)
        if priced is not None:
            specified_as = " ".join(v for v in (line.manufacturer, line.part) if v)
            priced["substitution_note"] = (
                f"{specified_as} is specified and CBC has no price for it; {choice.row.get('manufacturer')} "
                f"{choice.row.get('part')} is its direct equal (CBC cross-reference). The GC approves a "
                "direct equal before it is ordered.")
            priced["flags"].append("direct_equal")
            return priced
    tried.append(f"the cross-reference lists equals for {spec.part}, but none the catalog prices")
    return None


def _allegion_rows(line: Line, src: Sources) -> list[dict[str, Any]]:
    """The Hager equal as the base line, and the Allegion part as specified beside it."""
    specified = " ".join(v for v in (line.manufacturer, line.part, line.description) if v)
    base = _row(line, src)
    base.update(
        part_number=None, manufacturer="Hager",
        description=f"Hager equal to {specified}",
        cost_source_detail=(f"Allegion specified ({specified}): price the Hager equal - no equal is on "
                            "file for this part yet, so an estimator names it"),
    )
    base["flags"].append("allegion_equal_needed")
    alternate = _row(line, src)
    alternate.update(
        line_id=f"{line.key}:allegion", cost_source="DISTRIBUTOR_MANUAL", alternate_group=ALLEGION_ALTERNATE,
        cost_source_detail="Allegion - distributor quote (Banner Solutions / SecLock); never priced off a list",
    )
    alternate["flags"].append("allegion_distributor_manual")
    return [base, alternate]


def price(line: Line, src: Sources) -> list[dict[str, Any]]:
    """The file rows for one take-off line: one, or two for an Allegion part."""
    if matcher.is_allegion(line.part, line.description, manufacturer=line.manufacturer):
        if line.alternate:  # another party supplies it: there is no equal for CBC to find
            row = _row(line, src)
            row.update(cost_source="DISTRIBUTOR_MANUAL",
                       cost_source_detail="Allegion, supplied by others per the schedule - not CBC's to price")
            return [row]
        return _allegion_rows(line, src)

    row = _row(line, src)
    if line.unit == "SET" and not line.part:
        # A whole set to price by hand: the take-off already says why.
        row["cost_source_detail"] = f"{line.description}; price the set from the sheet"
        return [row]
    # Only a door hardware legend writes the model into its description; a
    # specialty row's description is a location (`6/A2.2`), not a part.
    part = line.part or (guess_part(line) if line.division.startswith("08") else None)
    if not part:
        row["cost_source_detail"] = "no part number on the legend - name the part, then price it"
        row["flags"].append("no_part_number")
        return [row]
    if line.qty is None:
        row["flags"].append("quantity_unread")

    vendor = vendor_key(line.manufacturer)
    models = src.models(part)
    spec = matcher.Spec(part=part, manufacturer=line.manufacturer, finish=line.finish, text=line.text)
    tried: list[str] = []

    # 1. P21 last PO.
    if src.last_po is not None:
        po = src.last_po(part, line.manufacturer)
        if po and po.get("cost") is not None:
            return [_priced(row, po["cost"], "P21_LAST_PO", po.get("detail") or "P21 last PO")]
        if po and po.get("context"):
            tried.append(po["context"])

    # 2. Special net - CBC's sheet is Hager's.
    if vendor in ("", "hager"):
        choice = _rung_special_net(spec, models, src)
        if choice.ambiguous:
            return _undecided(row, "special net", choice, _show_net)
        if choice.candidates and choice.row is None:
            tried.append(f"special net: {choice.reason}")
        if choice.row is not None:
            priced = _from_net(row, choice.row, src, tried)
            if priced is not None:
                return [priced]

    # 3. Catalog row.
    choice = _rung_catalog(spec, models, vendor, src)
    if choice.ambiguous:
        return _undecided(row, "catalog", choice, _show_catalog)
    catalog_row = choice.row
    if choice.candidates and catalog_row is None:
        tried.append(f"catalog: {choice.reason}")
    if catalog_row is not None:
        priced = _from_catalog(row, catalog_row, src, line.manufacturer, tried)
        if priced is not None:
            return [priced]

    # 4. Price book list x the multiplier for its section.
    choice = _rung_book(spec, models, vendor, src)
    if choice.ambiguous:
        return _undecided(row, "price book", choice, _show_book)
    if choice.candidates and choice.row is None:
        tried.append(f"price book: {choice.reason}")
    if choice.row is not None:
        priced = _from_book(row, choice.row, src, vendor, tried)
        if priced is not None:
            return [priced]

    # 5. Division 10: the direct equal CBC can price.
    if line.division.startswith("10") and src.equals:
        offered = _direct_equal(row, line, spec, src, tried)
        if offered is not None:
            return [offered]

    # 6. Nothing the ladder can stand behind.
    tried.append(f"no special net, catalog row or price-book row for {part}"
                 + (f" ({line.manufacturer})" if line.manufacturer else ""))
    row["cost_source_detail"] = "; ".join(tried) + " - needs a distributor or vendor quote"
    return [row]
