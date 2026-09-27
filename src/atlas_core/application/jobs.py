"""Jobs application service with mandatory handle-bound authorization."""

from __future__ import annotations

from typing import TYPE_CHECKING

from atlas_sdk import AuthorizationError, ExecutionHandle, Scope
from atlas_sdk import Job as SdkJob
from atlas_sdk.context import JobsPort

from ..domain.execution import ExecutionFacts
from ..domain.identifiers import JobId, OrganizationId, WorkplaceId
from ..domain.job import Job, JobStatus
from ..domain.role import JOBS_MANAGE
from .execution_guard import authorization_for_uow, require_execution_handle
from .unit_of_work import UnitOfWorkPort

if TYPE_CHECKING:
    from .authorization import AuthorizationService
    from .execution import ExecutionHandleResolver


def _to_read_model(job: Job) -> SdkJob:
    return SdkJob(
        job_id=job.job_id,
        organization_id=job.organization_id,
        title=job.title,
        workplace_id=job.workplace_id,
        status=job.status.value,
    )


class JobsService(JobsPort):
    def __init__(
        self,
        uow: UnitOfWorkPort,
        *,
        resolver: ExecutionHandleResolver | None = None,
        authorization: AuthorizationService | None = None,
    ) -> None:
        self._uow = uow
        if resolver is None or authorization is None:
            bound = authorization_for_uow(uow)
            resolver = resolver or bound._handle_resolver  # type: ignore[attr-defined]
            authorization = authorization or bound
        self._resolver = resolver
        self._authorization = authorization

    def _check(
        self,
        handle: ExecutionHandle,
        scope: Scope,
    ) -> ExecutionFacts | None:
        facts = require_execution_handle(
            handle,
            scope,
            resolver=self._resolver.resolve if self._resolver is not None else None,
        )
        if not isinstance(facts, ExecutionFacts):
            return None
        if self._authorization is not None:
            decision = self._authorization.authorize(handle, JOBS_MANAGE, scope)
            if not decision.allowed:
                raise AuthorizationError(f"jobs operation denied: {decision.code}")
        return facts

    def create_job(
        self,
        organization_id: str,
        title: str,
        workplace_id: str | None = None,
        *,
        execution_handle: ExecutionHandle,
    ) -> SdkJob:
        self._check(execution_handle, Scope(organization_id=organization_id))
        if not title.strip():
            raise ValueError("job title is required")
        job = Job(
            organization_id=OrganizationId(organization_id),
            title=title,
            workplace_id=None if workplace_id is None else WorkplaceId(workplace_id),
            status=JobStatus.OPEN,
        )
        self._uow.jobs.add(job)
        return _to_read_model(job)

    def get_job(
        self,
        job_id: str,
        *,
        execution_handle: ExecutionHandle,
    ) -> SdkJob | None:
        found = self._uow.jobs.get(JobId(job_id))
        self._check(
            execution_handle,
            Scope(organization_id=found.organization_id) if found is not None else Scope(),
        )
        return _to_read_model(found) if found else None

    def list_jobs(
        self,
        organization_id: str,
        *,
        execution_handle: ExecutionHandle,
    ) -> list[SdkJob]:
        self._check(execution_handle, Scope(organization_id=organization_id))
        return [_to_read_model(j) for j in self._uow.jobs.all(OrganizationId(organization_id))]


__all__ = ["JobsService"]
