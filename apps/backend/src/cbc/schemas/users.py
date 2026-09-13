from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from cbc.schemas.common import CallKind


class UserPublic(BaseModel):
    id: str
    email: EmailStr
    name: str
    initials: str
    role: str = "estimator"


class CallCreate(BaseModel):
    kind: CallKind = "call"
    text: str = Field(min_length=1, max_length=4000)
    org: str | None = Field(default=None, description="Who it was with - GC, architect, vendor")
    ref: str | None = Field(default=None, description="The stage or line it was logged against")


class Call(CallCreate):
    id: str
    projectId: str
    who: str
    createdAt: datetime
