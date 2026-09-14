"""Strict Pydantic contracts for Claude's on-disk JSON artifacts.

LLM output is non-deterministic. These models are the gate between a file on
disk and a Mongo write: extra keys on openings/priced lines are rejected,
numeric fields are coerced, and a failed parse is quarantined rather than
partially imported.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from cbc.modules.extraction.api.normalize_artifacts import (
    normalize_door_schedule_payload,
    normalize_opening_dict,
    normalize_page_size,
)


def _coerce_number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValueError("boolean is not a number")
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        return float(value.replace(",", "").strip())
    raise ValueError(f"expected a number, got {type(value).__name__}")


class Opening(BaseModel):
    """One row of extracted/door_schedule.json."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    door_number: str | None = None
    mark: str | None = None
    description: str | None = None
    raw_row: str | None = None
    size: str | None = None
    width: str | None = None
    qty: float | None = 1
    hardware_set: str | None = None
    hw_set: str | None = None
    division: str | None = None
    handing: str | None = None
    finish: str | None = None
    fire_rating: str | None = None
    frame_type: str | None = None
    wall_type: str | None = None
    frame_depth: str | None = None
    alternate: str | None = None
    alternate_group: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    flags: list[str] | None = None
    evidence_note: str | None = None
    sheet: str | None = None
    row: int | float | None = None
    source_file: str | None = None
    source_page: int | float | None = None
    bbox: list[float] | None = None
    page_size: dict[str, float] | None = None
    duplicate_reason: str | None = None
    notes: str | None = None
    room_name: str | None = None
    height: str | None = None
    status: str | None = None
    door_type: str | None = None
    material: str | None = None
    hardware: str | None = None
    comments: str | None = None
    type: str | None = None
    location: str | None = None
    manufacturer: str | None = None
    series: str | None = None
    core: str | None = None
    glazing: str | None = None
    undercut: str | None = None
    is_duplicate: bool | None = None
    duplicate_of: str | None = None
    # Written by parse_schedule.py alongside `bbox`: the whole row, and every
    # cell in it. The highlight uses `bbox`; these are what check_bboxes_are_real
    # compares a claim against.
    row_bbox: list[float] | None = None
    cell_boxes: list[list[float]] | None = None
    size_notation: str | None = None
    door_material: str | None = None
    frame_material: str | None = None
    glass: str | None = None
    # export_line_items writes the estimator's own decisions back into the
    # schedule so a rerun can carry them across untouched.
    confirmed_by: str | None = None
    added_by_hand: bool | None = None

    @model_validator(mode="before")
    @classmethod
    def _relocate_stray_schedule_columns(cls, value: Any) -> Any:
        if isinstance(value, dict):
            return normalize_opening_dict(value)
        return value

    @field_validator("qty", mode="before")
    @classmethod
    def _qty(cls, value: Any) -> float | None:
        if value is None or value == "":
            return 1.0
        return _coerce_number(value)

    @field_validator("confidence", mode="before")
    @classmethod
    def _confidence(cls, value: Any) -> float | None:
        if value is None or value == "":
            return None
        return _coerce_number(value)

    @field_validator("page_size", mode="before")
    @classmethod
    def _page_size(cls, value: Any) -> dict[str, float] | None:
        coerced = normalize_page_size(value)
        if coerced is None:
            return None
        if not isinstance(coerced, dict):
            raise ValueError("page_size must be {width, height} or [width, height]")
        if "width" not in coerced or "height" not in coerced:
            raise ValueError("page_size requires numeric width and height")
        width = _coerce_number(coerced.get("width"))
        height = _coerce_number(coerced.get("height"))
        if width is None or height is None:
            raise ValueError("page_size width and height must be numbers")
        return {"width": width, "height": height}


class DoorSchedule(BaseModel):
    """extracted/door_schedule.json — object wrapper or a bare openings array."""

    model_config = ConfigDict(extra="ignore")

    openings: list[Opening] = Field(default_factory=list)
    lines: list[Opening] | None = None
    no_scope_reason: str | None = None
    sheet: str | None = None
    source_file: str | None = None
    door_schedule_found: bool | None = None

    @classmethod
    def parse_payload(cls, raw: Any) -> DoorSchedule:
        raw = normalize_door_schedule_payload(raw)
        if isinstance(raw, list):
            return cls(openings=[Opening.model_validate(item) for item in raw])
        if not isinstance(raw, dict):
            raise ValueError("door_schedule.json must be an object or an array")
        data = dict(raw)
        if "openings" not in data and isinstance(data.get("lines"), list):
            data["openings"] = data["lines"]
        return cls.model_validate(data)


class ScopeMetadata(BaseModel):
    model_config = ConfigDict(extra="ignore")

    brand: str | None = None
    state: str | None = None
    location: str | None = None
    address: str | None = None
    city: str | None = None
    architect: str | None = None
    gc: str | None = None
    initiator: str | None = None
    project_number: str | None = None
    project_name: str | None = None
    bid_due_date: str | None = None
    bid_alternates: list[str] | None = None
    mode: str | None = None
    flags: list[str] | None = None
    source_files: list[str] | None = None
    field_sources: dict[str, Any] | None = None
    source_page: int | float | None = None


class ScopeSummary(BaseModel):
    model_config = ConfigDict(extra="ignore")

    frp_in_scope: bool
    divisions: list[Any] | None = None
    out_of_scope_items: list[Any] | None = None
    flags: list[str] | None = None
    door_schedule_found: bool | None = None
    schedule_found: bool | None = None
    has_division_08_scope: bool | None = None
    door_schedule_pages: list[Any] | None = None


class HardwareSetEntry(BaseModel):
    model_config = ConfigDict(extra="ignore")

    hardware_set: str | None = None
    set_id: str | None = None
    specified: str | None = None
    openings: list[Any] | None = None
    items: list[Any] | None = None


class HardwareSets(BaseModel):
    model_config = ConfigDict(extra="ignore")

    sets: list[HardwareSetEntry] | None = None
    hardware_sets: list[HardwareSetEntry] | None = None


class FrpTakeoff(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: str | None = None
    panels: list[Any] | None = None
    quantity: float | None = None
    flags: list[str] | None = None


class PricedLine(BaseModel):
    """One row of priced/line_items.json."""

    model_config = ConfigDict(extra="forbid")

    line_id: str | None = None
    group: str | None = None
    group_type: str | None = None
    quantity: float | None = 1
    cost_source: str | None = None
    part_number: str | None = None
    part: str | None = None
    description: str | None = None
    division: str | None = None
    cost: float | None = None
    margin: float | None = None
    sale_ea: float | None = None
    ext_price: float | None = None
    basis: str | None = None
    cost_source_detail: str | None = None
    multiplier: float | None = None
    multiplier_tier: str | None = None
    multiplier_effective_date: str | None = None
    price_book_version: str | None = None
    source_page: int | float | None = None
    price_status: str | None = None
    added_by_hand: bool | None = None
    flags: list[str] | None = None
    substitution_note: str | None = None
    margin_overridden: bool | None = None
    margin_override_reason: str | None = None
    notes: str | None = None
    vendor: str | None = None
    unit: str | None = None
    uom: str | None = None
    opening: str | None = None
    mark: str | None = None
    hw_set: str | None = None
    hardware_set: str | None = None
    catalog_page: int | float | str | None = None

    @field_validator("line_id", mode="before")
    @classmethod
    def _line_id(cls, value: Any) -> str | None:
        if value is None or value == "":
            return None
        return str(value)

    @field_validator("quantity", "cost", "margin", "sale_ea", "ext_price", "multiplier", mode="before")
    @classmethod
    def _num(cls, value: Any) -> float | None:
        if value is None or value == "":
            return None
        return _coerce_number(value)


class PricedQuote(BaseModel):
    model_config = ConfigDict(extra="ignore")

    lines: list[PricedLine] = Field(default_factory=list)

    @classmethod
    def parse_payload(cls, raw: Any) -> PricedQuote:
        if isinstance(raw, list):
            return cls(lines=[PricedLine.model_validate(item) for item in raw])
        if not isinstance(raw, dict):
            raise ValueError("priced/line_items.json must be an object or an array")
        return cls.model_validate(raw)
