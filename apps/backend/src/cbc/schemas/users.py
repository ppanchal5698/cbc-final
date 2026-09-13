from __future__ import annotations

from pydantic import BaseModel, EmailStr


class UserPublic(BaseModel):
    id: str
    email: EmailStr
    name: str
    initials: str
    role: str = "estimator"

