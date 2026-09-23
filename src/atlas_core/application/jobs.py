"""Jobs application service (contract section 2: Jobs / Positions)."""

from __future__ import annotations

from atlas_sdk import Job as SdkJob
from atlas_sdk.context import JobsPort

from ..domain.identifiers import JobId, OrganizationId, WorkplaceId
from ..domain.job import Job, JobStatus
from .unit_of_work import UnitOfWorkPort


def _to_read_model(job: Job) -> SdkJob:
    return SdkJob(
        job_id=job.job_id,
        organization_id=job.organization_id,
        title=job.title,
        workplace_id=job.workplace_id,
        status=job.status.value,
    )


class JobsService(JobsPort):
    def __init__(self, uow: UnitOfWorkPort) -> None:
        self._uow = uow

    def create_job(
        self,
        organization_id: str,
        title: str,
        workplace_id: str | None = None,
    ) -> SdkJob:
        if not title.strip():
            msg = "job title is required"
            raise ValueError(msg)

        job = Job(
            organization_id=OrganizationId(organization_id),
            title=title,
            workplace_id=None if workplace_id is None else WorkplaceId(workplace_id),
            status=JobStatus.OPEN,
        )
        self._uow.jobs.add(job)
        return _to_read_model(job)

    def get_job(self, job_id: str) -> SdkJob | None:
        found = self._uow.jobs.get(JobId(job_id))
        return _to_read_model(found) if found else None

    def list_jobs(self, organization_id: str) -> list[SdkJob]:
        return [_to_read_model(j) for j in self._uow.jobs.all(OrganizationId(organization_id))]


__all__ = ["JobsService"]
