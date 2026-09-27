"""The plugin's real business services (contract section 27, cluster section 8).

Three rules this service obeys:

1. **Contracts are the only cross-plugin channel.** Membership in a workplace's
   workforce is proven by consuming ``workplace.workforce`` (Gate K), and a
   workplace's organization by consuming ``workplace.context`` — never by
   importing another plugin or reading its tables (contract sections 9 and 22).
2. **The platform owns the transaction.** Every write goes through the
   restricted ``context.persistence`` adapter; the public compatibility wrapper
   supplies the platform-owned ``context.transactions`` boundary, while a bound
   contract handler remains under the registry's outer transaction (contract
   section 21).
3. **Recording is idempotent.** The same (workplace, employee, date) updates the
   status instead of adding a second row, so a retry can never double-count a
   person on a day.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from typing import Protocol, cast

from atlas_sdk import (
    AttendanceStatus,
    AuthorizationError,
    CapabilityId,
    DomainEvent,
    Employee,
    EventId,
    ExecutionHandle,
    NotFoundError,
    Scope,
)
from atlas_sdk.context import PluginContext
from atlas_sdk.contract import ContractId
from atlas_sdk.reporting import DatasetResponse

from .domain import AttendanceRecord, DailySummary, DailySummaryEntry
from .persistence import AttendanceOperationsRepository, AttendanceORM

__all__ = ["AttendanceOperationsService"]

#: Gate K — the contracts this plugin consumes are spelled as *literal ids*,
#: never imported from a provider's package (contract section 9). Whatever
#: plugin happens to be installed and enabled to provide them answers the call.
WORKPLACE_WORKFORCE_CONTRACT = ContractId("workplace.workforce")
WORKPLACE_CONTEXT_CONTRACT = ContractId("workplace.context")


@dataclass(frozen=True)
class _WorkforceRequest:
    """The request shape of ``workplace.workforce``, spelled locally.

    The contract id is the agreement; the request object is built by the caller
    and the provider accepts it structurally — the pattern the demo consumer
    established — which keeps this plugin from importing the provider's classes.
    """

    workplace_id: str


@dataclass(frozen=True)
class _WorkplaceContextRequest:
    """The request shape of ``workplace.context``, spelled locally."""

    workplace_id: str


class _WorkforceMember(Protocol):
    """The slice of a ``workplace.workforce`` response this plugin reads.

    Structural on purpose: the contract is the channel, so the dependency is on
    the response's *shape*, never on the provider's classes.
    """

    employee_id: str
    employee_number: str
    full_name: str
    organization_id: str


class _WorkplaceContext(Protocol):
    """The slice of a ``workplace.context`` response this plugin reads."""

    organization_id: str


class AttendanceOperationsService:
    """The business services Attendance Operations provides.

    The service is stateless: it holds only the context the platform handed the
    plugin. A fresh instance per call would be equivalent; one instance is
    simpler.
    """

    def __init__(self, context: PluginContext) -> None:
        self._context = context

    # --- helpers -----------------------------------------------------------

    def _repo(self) -> AttendanceOperationsRepository:
        return AttendanceOperationsRepository(self._context.persistence)

    def _require_capability(
        self,
        capability: CapabilityId,
        scope: Scope,
        execution_handle: ExecutionHandle,
    ) -> None:
        decision = self._context.authorization.authorize(execution_handle, capability, scope)
        if not decision.allowed:
            raise AuthorizationError(f"attendance operation denied: {decision.code}")

    def _publish(
        self,
        event: EventId,
        payload: dict[str, object],
        execution_handle: ExecutionHandle,
    ) -> None:
        self._context.events.publish(
            DomainEvent(event_id=event, payload=payload),
            execution_handle=execution_handle,
        )

    def _audit(
        self,
        action: str,
        scope: Scope,
        details: dict[str, object],
        execution_handle: ExecutionHandle,
    ) -> str:
        return self._context.audit.record(
            action=action,
            details=details,
            execution_handle=execution_handle,
        )

    # --- cross-plugin reads (Gate K) --------------------------------------

    def _workforce(
        self,
        workplace_id: str,
        execution_handle: ExecutionHandle,
    ) -> list[_WorkforceMember]:
        """A workplace's workforce, through the contract — never a table read.

        The provider authorizes the caller itself (``workplace.view`` in the
        workplace's scope), so an attendance recorder must also hold that view:
        recording who was at a workplace inherently means reading its roster.
        """
        response = self._context.invoker.invoke(
            WORKPLACE_WORKFORCE_CONTRACT,
            _WorkforceRequest(workplace_id=workplace_id),
            execution_handle=execution_handle,
        )
        if not isinstance(response, list):
            return []
        return [cast("_WorkforceMember", member) for member in response]

    def _workplace_organization(
        self,
        workplace_id: str,
        execution_handle: ExecutionHandle,
    ) -> str:
        """Resolve a workplace's organization through the ``workplace.context``.

        That contract answers without a capability of its own, which makes it the
        right way to scope a *query*: attendance's own ``attendance.view`` is
        checked against the organization it returns.
        """
        response = self._context.invoker.invoke(
            WORKPLACE_CONTEXT_CONTRACT,
            _WorkplaceContextRequest(workplace_id=workplace_id),
            execution_handle=execution_handle,
        )
        return cast("_WorkplaceContext", response).organization_id

    # --- recording ---------------------------------------------------------

    def record_attendance(
        self,
        employee_id: str,
        workplace_id: str,
        date: date,
        status: AttendanceStatus,
        execution_handle: ExecutionHandle,
    ) -> AttendanceRecord:
        """Record one employee's status at one workplace on one date.

        Gate J: the employee must exist, verified through the core's people
        service. Gate K: the employee must be a member of that workplace's
        workforce, verified through the ``workplace.workforce`` contract. Gates
        L/M/N: the write is audited, requires ``attendance.manage``, and is
        scoped to the employee's organization.
        """
        # Gate J — consume a real core service through the context, and read the
        # organization the scope is built from off the same answer.
        employee = self._context.people.get_employee(
            employee_id,
            execution_handle=execution_handle,
        )
        if employee is None:
            msg = f"employee {employee_id!r} does not exist"
            raise NotFoundError(msg, kind="employee", key=employee_id)

        # Gates M/N — fail fast and cheap, before any cross-plugin call.
        scope = self._context.scope.resolve(employee.organization_id)
        self._require_capability(
            CapabilityId("attendance.manage"),
            scope,
            execution_handle,
        )

        # Gate K — membership is proven by the workforce contract, not by this
        # plugin reading another plugin's roster table.
        members = self._workforce(workplace_id, execution_handle)
        if not any(member.employee_id == employee_id for member in members):
            msg = (
                f"employee {employee_id!r} is not a member of the workforce of "
                f"workplace {workplace_id!r}"
            )
            raise NotFoundError(msg, kind="workforce_membership", key=employee_id)

        repo = self._repo()
        existing = repo.find(workplace_id, employee_id, date)
        created = existing is None
        if created:
            row = AttendanceORM(
                attendance_id=_new_id("att"),
                organization_id=employee.organization_id,
                workplace_id=workplace_id,
                employee_id=employee_id,
                record_date=date,
                status=status.value,
            )
            repo.add(row)
        else:
            existing.status = status.value
            row = existing

        record = _to_record(row, employee)
        self._audit(
            action="attendance.recorded" if created else "attendance.updated",
            scope=scope,
            details={
                "attendance_id": row.attendance_id,
                "workplace_id": workplace_id,
                "employee_id": employee_id,
                "date": date.isoformat(),
                "status": status.value,
                "updated": not created,
            },
            execution_handle=execution_handle,
        )
        self._publish(
            EventId("attendance.recorded"),
            {
                "attendance_id": row.attendance_id,
                "organization_id": employee.organization_id,
                "workplace_id": workplace_id,
                "employee_id": employee_id,
                "date": date.isoformat(),
                "status": status.value,
                "updated": not created,
            },
            execution_handle,
        )
        return record

    # --- queries -----------------------------------------------------------

    def assert_summary_visible(
        self,
        workplace_id: str,
        execution_handle: ExecutionHandle,
    ) -> None:
        """Deny a summary read without ``attendance.view`` (Gate M on a query).

        Scope is the organization the workplace belongs to, resolved through the
        ``workplace.context`` contract: an actor granted in one org cannot read
        another org's summary (Gate N).
        """
        organization_id = self._workplace_organization(workplace_id, execution_handle)
        scope = self._context.scope.resolve(organization_id)
        self._require_capability(
            CapabilityId("attendance.view"),
            scope,
            execution_handle,
        )

    def daily_summary(
        self,
        workplace_id: str,
        date: date,
        *,
        execution_handle: ExecutionHandle,
    ) -> DailySummary:
        """The statuses recorded for one workplace on one date.

        Employee labels come from the core's people port (Gate J's discipline on
        read paths too); the roster itself is not this plugin's to read.
        """
        self.assert_summary_visible(workplace_id, execution_handle)
        rows = self._repo().list_for_workplace_and_date(workplace_id, date)
        return DailySummary(
            workplace_id=workplace_id,
            date=date,
            entries=tuple(
                _to_entry(
                    row,
                    self._context.people.get_employee(
                        row.employee_id,
                        execution_handle=execution_handle,
                    ),
                )
                for row in rows
            ),
        )

    def daily_summary_dataset(
        self,
        organization_id: str | None,
        *,
        execution_handle: ExecutionHandle,
    ) -> DatasetResponse:
        """The recorded attendance as a labelled dataset for Report Studio (Gate O).

        Report Studio asks the registry for ``reporting.dataset`` providers and
        gets this without naming this plugin (contract section 13). Values are
        strings: the dataset vocabulary is printable columns and rows, and this
        plugin maps its richer types down at its own boundary.
        """
        scope = self._context.scope.resolve(organization_id)
        decision = self._context.authorization.authorize(
            execution_handle,
            CapabilityId("attendance.view"),
            scope,
        )
        if not decision.allowed:
            raise AuthorizationError(f"attendance dataset read denied: {decision.code}")
        rows = self._repo().list_for_organization(organization_id)
        return DatasetResponse(
            dataset_id="attendance.daily_summary",
            title="Attendance Daily Summary",
            columns=("employee_number", "full_name", "attendance_date", "attendance_status"),
            rows=tuple(
                _dataset_row(
                    row,
                    self._context.people.get_employee(
                        row.employee_id,
                        execution_handle=execution_handle,
                    ),
                )
                for row in rows
            ),
        )


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:24]}"


def _to_record(row: AttendanceORM, employee: Employee | None) -> AttendanceRecord:
    return AttendanceRecord(
        attendance_id=row.attendance_id,
        organization_id=row.organization_id,
        workplace_id=row.workplace_id,
        employee_id=row.employee_id,
        date=row.record_date,
        status=AttendanceStatus(row.status),
        full_name=employee.full_name if employee is not None else "",
        employee_number=employee.employee_number if employee is not None else "",
    )


def _to_entry(row: AttendanceORM, employee: Employee | None) -> DailySummaryEntry:
    return DailySummaryEntry(
        employee_id=row.employee_id,
        employee_number=employee.employee_number if employee is not None else "",
        full_name=employee.full_name if employee is not None else "",
        status=AttendanceStatus(row.status),
    )


def _dataset_row(row: AttendanceORM, employee: Employee | None) -> tuple[str, ...]:
    return (
        employee.employee_number if employee is not None else "",
        employee.full_name if employee is not None else "",
        row.record_date.isoformat(),
        row.status,
    )
