from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel

from cbc.schemas.common import JobStatus, JobType


class JobCreate(BaseModel):
    type: JobType
    projectId: str | None = None
    payload: dict[str, Any] = {}


class Job(BaseModel):
    id: str
    type: JobType
    projectId: str | None = None
    payload: dict[str, Any] = {}
    status: JobStatus = "queued"
    attempts: int = 0
    error: str | None = None
    errorCode: str | None = None
    log: str | None = None
    createdBy: str | None = None
    createdAt: datetime
    startedAt: datetime | None = None
    finishedAt: datetime | None = None
    phaseState: dict[str, Any] | None = None
