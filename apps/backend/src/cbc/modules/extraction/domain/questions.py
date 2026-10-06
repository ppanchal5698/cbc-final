"""What extraction may ask a model - only what the parsers cannot read off a sheet.

Each answer lands on its row with a flag for the estimator to confirm, and only
where the take-off has nothing: a model never overwrites a value the schedule
printed, and an unanswered question leaves the row as it was.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from cbc.shared import ai


# ── a sheet with no text layer: where its tables are, then what they say ──────


class TableOnSheet(BaseModel):
    kind: Literal["door_schedule", "hardware_set"]
    box: list[float] = Field(description="[left, top, right, bottom] as fractions from 0 to 1 of the image's width and height.")
    title: str | None = Field(default=None, max_length=120, description="The table's heading as printed.")

    @field_validator("box")
    @classmethod
    def _a_box_on_the_sheet(cls, box: list[float]) -> list[float]:
        if len(box) != 4 or not all(0.0 <= v <= 1.0 for v in box) or box[0] >= box[2] or box[1] >= box[3]:
            raise ValueError("box must be [left, top, right, bottom], each from 0 to 1, left < right, top < bottom")
        return box


class TablesOnSheet(BaseModel):
    tables: list[TableOnSheet]


FIND_SCHEDULE_TABLES = ai.Question(
    name="find_schedule_tables",
    version=1,
    instructions=(
        "You look at one sheet of a construction drawing set for a door-hardware "
        "estimator. Find every door schedule - a table with one row per door opening "
        "(door number, size, type, fire rating, hardware set) - and every hardware set "
        "of a door hardware legend: one heading such as `HW-1`, `H-2` or `GROUP 3` and "
        "the items listed under it. Give each its own box, generous rather than tight. "
        "Window, finish, room and equipment schedules are not door schedules. A sheet "
        "with neither has an empty list - never point at something that is not there."
    ),
    answer=TablesOnSheet,
)


class ScheduleRow(BaseModel):
    door_number: str = Field(min_length=1)
    width: str | None = None
    height: str | None = None
    door_type: str | None = None
    door_material: str | None = None
    frame_type: str | None = None
    frame_material: str | None = None
    fire_rating: str | None = None
    hardware_set: str | None = None
    room_name: str | None = None
    remarks: str | None = None


class ScheduleRows(BaseModel):
    rows: list[ScheduleRow]


READ_DOOR_SCHEDULE = ai.Question(
    name="read_door_schedule",
    version=1,
    instructions=(
        "Transcribe the door schedule in the image for an estimator: one row per door "
        "opening, each value exactly as printed in its column. A blank cell, a dash or "
        "N/A is null. Never carry a value down from the row above, never fill one from "
        "a note, and never add a door the table does not list."
    ),
    answer=ScheduleRows,
)


class SetItem(BaseModel):
    qty: str | None = Field(default=None, description="The count as printed: 3, (6), 1 1/2 PR.")
    description: str
    manufacturer: str | None = None
    part: str | None = Field(default=None, description="The model or catalog number.")
    finish: str | None = None
    supplied_by: str | None = Field(default=None, description="Who furnishes it, as the legend says: GC, OWNER, LL.")


class HardwareSet(BaseModel):
    set_id: str = Field(min_length=1, description="The set's own name: H-1, HW-2, 03, E1.")
    name: str | None = Field(default=None, description="What the heading says the set is for.")
    items: list[SetItem]


READ_HARDWARE_SET = ai.Question(
    name="read_hardware_set",
    version=1,
    instructions=(
        "Transcribe the door hardware set in the image for an estimator: its heading, "
        "then one item per line as printed - the count, what the item is, its "
        "manufacturer, model or catalog number and finish, and who furnishes it when "
        "the legend says. A value the line does not give is null; never fill one from "
        "another line or from what such sets usually hold."
    ),
    answer=HardwareSet,
)


class DoorHanding(BaseModel):
    mark: str = Field(description="The door mark, exactly as given.")
    handing: Literal["LH", "RH", "LHR", "RHR", "UNCLEAR"]
    reason: str = Field(max_length=300, description="What in the drawing shows it: hinge side, swing, which side is outside.")


class Handings(BaseModel):
    doors: list[DoorHanding]


class Printed(BaseModel):
    value: str | None = Field(description="The value, or null when the sheet does not show it.")
    excerpt: str | None = Field(default=None, max_length=200, description="The words exactly as printed.")


class TitleBlock(BaseModel):
    project_name: Printed
    brand: Printed = Field(description="The franchise or retail brand the building is for, if any.")
    address: Printed = Field(description="The street address of the site.")
    city: Printed
    state: Printed = Field(description="Two-letter state or province code.")
    architect: Printed = Field(description="The architect or design firm of record.")
    gc: Printed = Field(description="The general contractor, only if the sheet names one.")
    project_number: Printed = Field(description="The architect's project number.")


READ_TITLE_BLOCK = ai.Question(
    name="read_title_block",
    version=1,
    instructions=(
        "You read the cover sheet or title block of a construction drawing set for an "
        "estimator. Give each field as the sheet prints it, with the words you read it "
        "from. A field the sheet does not show is null - never infer one from another "
        "(a city is not a state, an owner is not a general contractor), and never "
        "reuse a name from the drawing index or a consultant's stamp for the architect."
    ),
    answer=TitleBlock,
)


READ_DOOR_HANDING = ai.Question(
    name="read_door_handing",
    version=1,
    instructions=(
        "You read architectural floor plans for a door-hardware estimator. The image is a "
        "crop of a floor plan. For each door mark you are given, find the door that mark "
        "labels and say its handing as a hardware schedule does. Stand on the door's "
        "outside - the corridor, the exterior, or the side a key is used from - facing the "
        "door. Hinges on your left and the door swinging away from you is LH; hinges on "
        "your right, swinging away, RH; hinges on your left, swinging toward you, LHR; "
        "hinges on your right, swinging toward you, RHR. Answer UNCLEAR when the mark is "
        "not in the image, the opening is a pair or slides, or you cannot tell which side "
        "is outside. Never guess: a wrong handing orders the wrong lock, and an estimator "
        "confirms every answer you give."
    ),
    answer=Handings,
)
