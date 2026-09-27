"""The plugin's real business services (contract section 27).

Every service writes through ``context.persistence`` — the platform's
transaction — so a state change and its outbox event share one transaction
(contract section 21). The plugin's public compatibility wrappers supply the
transaction runner; this implementation never commits and never opens a
connection of its own.

Gate J: workforce assignment validates the employee through the core's
``context.people`` before writing a membership row. The core still owns the
*assignment record* (contract section 10); this plugin owns the workplace-side
workforce membership.
"""

from __future__ import annotations

from atlas_sdk import (
    AuthorizationError,
    CapabilityId,
    DomainEvent,
    Employee,
    EventId,
    ExecutionHandle,
    NotFoundError,
    Scope,
    WorkplaceType,
)
from atlas_sdk.context import PluginContext
from atlas_sdk.reporting import DatasetResponse

from .domain import Workplace, WorkplaceContext, WorkplaceMember
from .persistence import (
    WorkforceMembershipORM,
    WorkplaceOperationsRepository,
    WorkplaceORM,
)

__all__ = ["WorkplaceOperationsService"]


def _new_id(prefix: str) -> str:
    import uuid

    return f"{prefix}_{uuid.uuid4().hex[:24]}"


class WorkplaceOperationsService:
    """The business services Workplace Operations provides.

    The service is stateless: it holds only the ids this plugin publishes. A
    fresh instance per call would be equivalent; one instance is simpler.
    """

    def __init__(self, context: PluginContext) -> None:
        self._context = context

    # --- helpers -----------------------------------------------------------

    def _repo(self) -> WorkplaceOperationsRepository:
        return WorkplaceOperationsRepository(self._context.persistence)

    def _require_capability(
        self,
        capability: CapabilityId,
        scope: Scope,
        execution_handle: ExecutionHandle,
    ) -> None:
        decision = self._context.authorization.authorize(execution_handle, capability, scope)
        if not decision.allowed:
            raise AuthorizationError(f"workplace operation denied: {decision.code}")

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

    def _to_workplace(self, row: WorkplaceORM) -> Workplace:
        return Workplace(
            workplace_id=row.workplace_id,
            organization_id=row.organization_id,
            name=row.name,
            code=row.code,
            kind=WorkplaceType(row.kind),
            parent_workplace_id=row.parent_workplace_id,
        )

    # --- registration ------------------------------------------------------

    def create_workplace(
        self,
        organization_id: str,
        name: str,
        code: str,
        kind: WorkplaceType,
        parent_workplace_id: str | None,
        execution_handle: ExecutionHandle,
    ) -> Workplace:
        """Register a workplace under an organization (contract section 27).

        ``kind`` is the workplace's *type* — an office, a site, a warehouse. A
        construction site is ``WorkplaceType.SITE``, a configuration of a
        workplace rather than the platform's identity.
        """
        scope = self._context.scope.resolve(organization_id)
        self._require_capability(
            CapabilityId("workplace.manage"),
            scope,
            execution_handle,
        )

        repo = self._repo()
        if not name.strip() or not code.strip():
            msg = "workplace name and code are required"
            raise ValueError(msg)
        if repo.find_by_code(organization_id, code) is not None:
            msg = f"workplace code {code!r} already exists in organization {organization_id!r}"
            raise NotFoundError(msg, kind="workplace_code", key=code)

        workplace = WorkplaceORM(
            workplace_id=_new_id("wpl"),
            organization_id=organization_id,
            name=name,
            code=code,
            kind=kind.value,
            parent_workplace_id=parent_workplace_id,
        )
        repo.add_workplace(workplace)

        read_model = self._to_workplace(workplace)
        self._audit(
            action="workplace.created",
            scope=scope,
            execution_handle=execution_handle,
            details={"workplace_id": read_model.workplace_id, "code": code, "kind": kind.value},
        )
        self._publish(
            EventId("workplace.created"),
            {
                "workplace_id": read_model.workplace_id,
                "organization_id": organization_id,
                "code": code,
                "kind": kind.value,
                "name": name,
            },
            execution_handle,
        )
        return read_model

    # --- workforce ---------------------------------------------------------

    def add_workforce_member(
        self,
        workplace_id: str,
        employee_id: str,
        execution_handle: ExecutionHandle,
    ) -> WorkplaceMember:
        """Attach an employee to a workplace's workforce.

        Gate J: the employee must exist, verified through the core's people
        service — never through this plugin reading the core's tables. The core
        owns the assignment record; this plugin owns the workplace roster.
        """
        workplace = self._repo().get_workplace(workplace_id)
        if workplace is None:
            msg = f"workplace {workplace_id!r} does not exist"
            raise NotFoundError(msg, kind="workplace", key=workplace_id)

        scope = self._context.scope.resolve(workplace.organization_id)
        self._require_capability(
            CapabilityId("workplace.manage"),
            scope,
            execution_handle,
        )

        # Gate J — consume a real core service through the context.
        employee = self._context.people.get_employee(
            employee_id,
            execution_handle=execution_handle,
        )
        if employee is None:
            msg = f"employee {employee_id!r} does not exist"
            raise NotFoundError(msg, kind="employee", key=employee_id)
        if employee.organization_id != workplace.organization_id:
            msg = (
                f"employee {employee_id!r} belongs to organization "
                f"{employee.organization_id!r}, not {workplace.organization_id!r}"
            )
            raise AuthorizationError(msg)

        repo = self._repo()
        existing = repo.get_membership(workplace_id, employee_id)
        if existing is not None:
            msg = f"employee {employee_id!r} is already a member of workplace {workplace_id!r}"
            raise AuthorizationError(msg)

        membership = WorkforceMembershipORM(
            membership_id=_new_id("wfm"),
            workplace_id=workplace_id,
            employee_id=employee_id,
            organization_id=workplace.organization_id,
        )
        repo.add_membership(membership)

        self._audit(
            action="workplace.workforce.added",
            scope=scope,
            details={
                "workplace_id": workplace_id,
                "employee_id": employee_id,
                "membership_id": membership.membership_id,
            },
            execution_handle=execution_handle,
        )
        self._publish(
            EventId("workplace.workforce.changed"),
            {
                "workplace_id": workplace_id,
                "organization_id": workplace.organization_id,
                "employee_id": employee_id,
                "member_added": True,
                "member_removed": False,
                "membership_id": membership.membership_id,
            },
            execution_handle,
        )
        return WorkplaceMember(
            membership_id=membership.membership_id,
            workplace_id=workplace_id,
            employee_id=employee_id,
            organization_id=workplace.organization_id,
            full_name=employee.full_name,
            employee_number=employee.employee_number,
        )

    def remove_workforce_member(
        self,
        workplace_id: str,
        employee_id: str,
        execution_handle: ExecutionHandle,
    ) -> None:
        """Detach an employee from a workplace's workforce."""
        repo = self._repo()
        workplace = repo.get_workplace(workplace_id)
        if workplace is None:
            msg = f"workplace {workplace_id!r} does not exist"
            raise NotFoundError(msg, kind="workplace", key=workplace_id)

        scope = self._context.scope.resolve(workplace.organization_id)
        self._require_capability(
            CapabilityId("workplace.manage"),
            scope,
            execution_handle,
        )

        membership = repo.get_membership(workplace_id, employee_id)
        if membership is None:
            msg = f"employee {employee_id!r} is not a member of workplace {workplace_id!r}"
            raise NotFoundError(msg, kind="workforce_membership", key=employee_id)

        repo.delete_membership(membership.membership_id)

        self._audit(
            action="workplace.workforce.removed",
            scope=scope,
            details={"workplace_id": workplace_id, "employee_id": employee_id},
            execution_handle=execution_handle,
        )
        delete_payload: dict[str, object] = {
            "workplace_id": workplace_id,
            "organization_id": workplace.organization_id,
            "employee_id": employee_id,
            "member_added": False,
            "member_removed": True,
            "membership_id": membership.membership_id,
            "deleted": True,
        }
        self._publish(EventId("workplace.workforce.changed"), delete_payload, execution_handle)

    # --- queries -----------------------------------------------------------

    def assert_workforce_visible(
        self,
        workplace_id: str,
        execution_handle: ExecutionHandle,
    ) -> None:
        """Deny workforce reads without ``workplace.view`` (Gate M on a query).

        Scope is the organization the workplace belongs to: an actor granted in
        one org cannot read another org's roster (Gate N).
        """
        workplace = self._repo().get_workplace(workplace_id)
        if workplace is None:
            msg = f"workplace {workplace_id!r} does not exist"
            raise NotFoundError(msg, kind="workplace", key=workplace_id)
        scope = self._context.scope.resolve(workplace.organization_id)
        self._require_capability(
            CapabilityId("workplace.view"),
            scope,
            execution_handle,
        )

    def list_workplaces(
        self,
        organization_id: str | None = None,
        kind: WorkplaceType | None = None,
        *,
        execution_handle: ExecutionHandle,
    ) -> list[Workplace]:
        """Workplaces of one organization, optionally filtered by type."""
        scope = self._context.scope.resolve(organization_id)
        self._require_capability(CapabilityId("workplace.view"), scope, execution_handle)
        return [
            self._to_workplace(row) for row in self._repo().list_workplaces(organization_id, kind)
        ]

    def list_workforce(
        self,
        workplace_id: str,
        *,
        execution_handle: ExecutionHandle,
    ) -> list[WorkplaceMember]:
        """The workforce of one workplace (the workforce view of a workplace)."""
        repo = self._repo()
        workplace = repo.get_workplace(workplace_id)
        if workplace is None:
            msg = f"workplace {workplace_id!r} does not exist"
            raise NotFoundError(msg, kind="workplace", key=workplace_id)
        self.assert_workforce_visible(workplace_id, execution_handle)

        return [
            WorkplaceMember(
                membership_id=row.membership_id,
                workplace_id=row.workplace_id,
                employee_id=row.employee_id,
                organization_id=row.organization_id,
                full_name=_employee_label(employee),
                employee_number=_employee_number(employee),
            )
            for row, employee in _with_employee(
                repo.list_memberships(workplace_id),
                self._context,
                execution_handle,
            )
        ]

    def resolve_workplace_context(
        self,
        workplace_id: str,
        *,
        execution_handle: ExecutionHandle,
    ) -> WorkplaceContext:
        """The ``workplace.context`` for a scope: identity plus workforce size.

        Downstream plugins (attendance's module declares it consumes
        ``workplace.context``) call this through the contract, never through
        this plugin's tables.
        """
        repo = self._repo()
        workplace = repo.get_workplace(workplace_id)
        if workplace is None:
            msg = f"workplace {workplace_id!r} does not exist"
            raise NotFoundError(msg, kind="workplace", key=workplace_id)
        scope = self._context.scope.resolve(workplace.organization_id)
        self._require_capability(CapabilityId("workplace.view"), scope, execution_handle)

        return WorkplaceContext(
            workplace_id=workplace.workplace_id,
            organization_id=workplace.organization_id,
            name=workplace.name,
            code=workplace.code,
            kind=WorkplaceType(workplace.kind),
            parent_workplace_id=workplace.parent_workplace_id,
            workforce_size=len(repo.list_memberships(workplace_id)),
        )

    def workforce_dataset(
        self,
        organization_id: str | None,
        *,
        execution_handle: ExecutionHandle,
    ) -> DatasetResponse:
        """The workforce as a labelled dataset for Report Studio (Gate O).

        Report Studio asks the registry for ``reporting.dataset`` providers and
        gets this without naming this plugin (contract section 13). Values are
        strings: the dataset vocabulary is printable columns and rows, and this
        plugin maps its richer types down at its own boundary.
        """
        org_id = organization_id or ""
        scope = self._context.scope.resolve(org_id)
        self._require_capability(CapabilityId("workplace.view"), scope, execution_handle)
        members: list[tuple[WorkplaceORM, WorkplaceMember]] = []
        repo = self._repo()
        workplaces = repo.list_workplaces(org_id) if org_id else repo.list_workplaces()
        for workplace in workplaces:
            for member in self.list_workforce(
                workplace.workplace_id,
                execution_handle=execution_handle,
            ):
                members.append((workplace, member))

        columns = (
            "workplace_code",
            "workplace_name",
            "workplace_kind",
            "employee_number",
            "full_name",
        )
        rows = tuple((w.code, w.name, w.kind, m.employee_number, m.full_name) for w, m in members)
        return DatasetResponse(
            dataset_id="workplace.workforce",
            title="Workplace Workforce",
            columns=columns,
            rows=rows,
        )


def _employee_label(employee: Employee | None) -> str:
    return employee.full_name if employee is not None else ""


def _employee_number(employee: Employee | None) -> str:
    return employee.employee_number if employee is not None else ""


def _with_employee(
    rows: list[WorkforceMembershipORM],
    context: PluginContext,
    execution_handle: ExecutionHandle,
) -> list[tuple[WorkforceMembershipORM, Employee | None]]:
    """Join membership rows to their employees through the core's people port.

    One lookup per member, and the join is a core *service call* (Gate J's
    discipline on read paths too) rather than a read of the core's tables.
    """
    return [
        (
            row,
            context.people.get_employee(
                row.employee_id,
                execution_handle=execution_handle,
            ),
        )
        for row in rows
    ]
