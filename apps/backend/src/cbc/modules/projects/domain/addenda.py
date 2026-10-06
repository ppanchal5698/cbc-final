"""The addendum log (FR-14, requirements 6.4): what each addendum to the bid set
changed - its number, the day it was issued, the drawings and specs it changed,
a moved bid date, the bid forms it changed.
"""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class AddendumUpdate(BaseModel):
    issuedOn: date | None = None
    changedDocuments: str | None = Field(default=None, max_length=1000, description="the sheets and sections it changes")
    newBidDue: date | None = Field(default=None, description="the bid date it moves the bid to")
    changedForms: str | None = Field(default=None, max_length=500, description="bid forms it changes")
    notes: str | None = Field(default=None, max_length=1000)


class AddendumCreate(AddendumUpdate):
    number: int | None = Field(default=None, ge=1, le=999, description="the next one when not given")
