"""Jobs / positions: a role an organisation hires for."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from .identifiers import JobId, OrganizationId, WorkplaceId, new_id


class JobStatus(StrEnum):
    OPEN = "open"
    FILLED = "filled"
    CLOSED = "closed"


@dataclass(frozen=True)
class Job:
    job_id: JobId = field(default_factory=lambda: JobId(new_id("job")))
    organization_id: OrganizationId = field(default_factory=lambda: OrganizationId(""))
    title: str = ""
    workplace_id: WorkplaceId | None = None
    status: JobStatus = JobStatus.OPEN


__all__ = ["Job", "JobStatus"]
