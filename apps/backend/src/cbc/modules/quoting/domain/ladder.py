"""The cost of one take-off line, by the ladder - decided in code.

  0. Allegion -> the base line is the Hager equal, for the estimator to name; the
     specified Allegion part is an alternate priced by the distributor (Banner /
     SecLock). Never priced off a list.
  1. P21 last PO
  2. Special net (CBC's negotiated sheet)
  3. Catalog row
  4. Price book list x the vendor's multiplier for that section
  5. Otherwise MANUAL, saying what each rung found.

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
from dataclasses import dataclass, field
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


def _undecided(row: dict[str, Any], label: str, choice: matcher.Choice, show) -> list[dict[str, Any]]:
    """This item, at several prices: the estimator picks, and no cheaper or dearer
    rung is tried in the meantime."""
    row["cost_source_detail"] = (f"{label}: {choice.reason}: {_candidates_note(choice.candidates, show)}"
                                 " - an estimator picks which")
    row["flags"].append("ambiguous_match")
    return [row]


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
        net = choice.row
        if choice.candidates and net is None:
            tried.append(f"special net: {choice.reason}")
        if net is not None:
            if src.lapsed(src.special_net_effective):
                tried.append(f"special net {net.get('item_code')} skipped - the sheet dated "
                             f"{src.special_net_effective} is past review")
            else:
                return [_priced(
                    row, net["net_price"], "SPECIAL_NET",
                    f"special-net sheet ({net.get('section') or 'Hager special nets'}) item {net.get('item_code')} "
                    f"- {net.get('description')}",
                    part_number=net.get("part_number") or part, manufacturer="Hager",
                    multiplier_effective_date=src.special_net_effective,
                    price_book_version=f"Hager special-net sheet, effective {src.special_net_effective}",
                )]

    # 3. Catalog row.
    choice = _rung_catalog(spec, models, vendor, src)
    if choice.ambiguous:
        return _undecided(row, "catalog", choice, _show_catalog)
    catalog_row = choice.row
    if choice.candidates and catalog_row is None:
        tried.append(f"catalog: {choice.reason}")
    if catalog_row is not None:
        book = src.books.get(str(catalog_row.get("priceBookId"))) or {}
        effective = book.get("effective")
        if src.lapsed(effective):
            tried.append(f"catalog row {catalog_row.get('part')} skipped - {book.get('name') or 'its price book'} "
                         f"dated {effective} is past review")
        else:
            basis = (f"; list ${catalog_row['listPrice']} x {catalog_row['multiplier']}"
                     if catalog_row.get("listPrice") and catalog_row.get("multiplier") else "")
            return [_priced(
                row, catalog_row["cost"], "CATALOG_BASELINE",
                f"product catalog ({catalog_row.get('seedSource') or 'catalog'}) {catalog_row.get('manufacturer')} "
                f"part {catalog_row.get('part')}{basis}",
                part_number=catalog_row.get("part"), manufacturer=catalog_row.get("manufacturer") or line.manufacturer,
                list_price=catalog_row.get("listPrice"), multiplier=catalog_row.get("multiplier") or None,
                multiplier_effective_date=effective,
                price_book_version=f"{book.get('name')}, effective {effective}" if book.get("name") else None,
            )]

    # 4. Price book list x the multiplier for its section.
    choice = _rung_book(spec, models, vendor, src)
    if choice.ambiguous:
        return _undecided(row, "price book", choice, _show_book)
    entry = choice.row
    if choice.candidates and entry is None:
        tried.append(f"price book: {choice.reason}")
    if entry is not None:
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
        elif src.lapsed(tier.get("effective_date")) or src.lapsed(effective):
            tried.append(f"price book {where} skipped - the sheet or its multiplier is past review")
        else:
            cost = src.cost_from_list(float(entry["listPrice"]), float(multiplier))
            book = src.books.get(str(entry.get("priceBookId"))) or {}
            return [_priced(
                row, cost, "LIST_X_MULTIPLIER",
                f"{where} list ${entry['listPrice']:.2f} x {category or 'account'} {multiplier:g} -> ${cost:.2f}",
                part_number=entry.get("model"), manufacturer=row.get("manufacturer") or entry_vendor.title(),
                list_price=entry.get("listPrice"), multiplier=float(multiplier), multiplier_tier=category or "all",
                multiplier_effective_date=tier.get("effective_date") or effective,
                price_book_version=f"{book.get('name') or entry.get('file')}, effective {effective}",
                catalog_page=entry.get("page"),
            )]

    # 5. Nothing the ladder can stand behind.
    tried.append(f"no special net, catalog row or price-book row for {part}"
                 + (f" ({line.manufacturer})" if line.manufacturer else ""))
    row["cost_source_detail"] = "; ".join(tried) + " - needs a distributor or vendor quote"
    return [row]
