"""The plugin-facing SDK context.

Every public operation carries an opaque :class:`ExecutionHandle`.  The SDK
never gives a plugin a mutable authority container or a Core session.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Protocol, TypeVar

from .capability import CapabilityId, CapabilityKind
from .contract import ContractId
from .event import DomainEvent, EventId
from .execution import ExecutionHandle
from .registry import CapabilityRegistryPort, ContractRegistryPort, EventRegistryPort
from .types import (
    Assignment,
    AuditEntry,
    AuthorizationDecision,
    Employee,
    Job,
    Notification,
    Organization,
    ScheduledJob,
    Scope,
    WorkflowCase,
    Workplace,
    WorkplaceType,
)

T = TypeVar("T")


class PluginPersistencePort(Protocol):
    """Owner-scoped persistence for one plugin's declared tables."""

    def add(self, entity: object) -> None: ...
    def delete(self, entity: object) -> None: ...
    def get(self, entity_type: type[Any], entity_id: object) -> Any | None: ...
    def find(self, entity_type: type[Any], **filters: object) -> Any | None: ...
    def all(self, entity_type: type[Any], **filters: object) -> list[Any]: ...
    def create_tables(self, *entity_types: type[Any]) -> None: ...


class TransactionRunnerPort(Protocol):
    """Run one plugin operation inside the platform-owned transaction."""

    def run(self, operation: Callable[[], T]) -> T: ...


class PeoplePort(Protocol):
    def create_employee(
        self,
        full_name: str,
        employee_number: str,
        organization_id: str,
        *,
        execution_handle: ExecutionHandle,
    ) -> Employee: ...

    def get_employee(
        self,
        employee_id: str,
        *,
        execution_handle: ExecutionHandle,
    ) -> Employee | None: ...
    def list_employees(
        self,
        organization_id: str | None = None,
        *,
        execution_handle: ExecutionHandle,
    ) -> list[Employee]: ...


class OrganizationPort(Protocol):
    def create_organization(
        self,
        name: str,
        code: str,
        *,
        execution_handle: ExecutionHandle,
    ) -> Organization: ...
    def get_organization(
        self,
        organization_id: str,
        *,
        execution_handle: ExecutionHandle,
    ) -> Organization | None: ...
    def add_workplace(
        self,
        organization_id: str,
        name: str,
        kind: WorkplaceType = WorkplaceType.OFFICE,
        *,
        execution_handle: ExecutionHandle,
    ) -> Workplace: ...
    def list_workplaces(
        self,
        organization_id: str,
        *,
        execution_handle: ExecutionHandle,
    ) -> list[Workplace]: ...


class JobsPort(Protocol):
    def create_job(
        self,
        organization_id: str,
        title: str,
        workplace_id: str | None = None,
        *,
        execution_handle: ExecutionHandle,
    ) -> Job: ...
    def get_job(
        self,
        job_id: str,
        *,
        execution_handle: ExecutionHandle,
    ) -> Job | None: ...
    def list_jobs(
        self,
        organization_id: str,
        *,
        execution_handle: ExecutionHandle,
    ) -> list[Job]: ...


class AssignmentPort(Protocol):
    def assign(
        self,
        employee_id: str,
        job_id: str,
        workplace_id: str | None = None,
        start_date: date | None = None,
        *,
        execution_handle: ExecutionHandle,
    ) -> Assignment: ...
    def get_assignment(
        self,
        assignment_id: str,
        *,
        execution_handle: ExecutionHandle,
    ) -> Assignment | None: ...
    def assignments_for(
        self,
        employee_id: str,
        *,
        execution_handle: ExecutionHandle,
    ) -> list[Assignment]: ...


class AuthorizationPort(Protocol):
    def authorize(
        self,
        handle: ExecutionHandle,
        capability: CapabilityId,
        requested_scope: Scope,
        *,
        confirmation_id: str | None = None,
        requested_action: str | None = None,
        requested_resource_id: str | None = None,
    ) -> AuthorizationDecision:
        """Resolve Core facts and return a typed, audited decision."""
        ...

    def register_capability(
        self,
        capability: CapabilityId,
        kind: CapabilityKind = CapabilityKind.VIEW,
        name: str = "",
        metadata: Mapping[str, object] | None = None,
    ) -> None:
        """Declare capability metadata; this never grants it to a principal."""
        ...

    def resolve_identity(self, identity_id: str) -> str | None:
        """Resolve a linked trusted identity without granting permission."""
        ...

    def resolve_principal(self, handle: ExecutionHandle) -> str | None:
        """The principal Core resolved for a valid handle, or ``None``.

        A handle is opaque, so a self-scoped read cannot know whose rows it may
        return. Core answers exactly that one question and nothing else: no
        scope, channel, action, capability set, or policy context. Anything the
        plugin is about to be *allowed* to do still goes through
        :meth:`authorize`.
        """
        ...

    def register_role(
        self,
        role_id: str,
        name: str,
        capabilities: frozenset[CapabilityId],
    ) -> None:
        """Declare a Core-validated role bundle; assignment remains Core-only."""
        ...


class ScopePort(Protocol):
    def resolve(
        self,
        organization_id: str | None,
        workplace_id: str | None = None,
        principal_id: str | None = None,
    ) -> Scope: ...
    def narrow(self, requested: Scope, subject: Scope) -> Scope: ...


class PolicyPort(Protocol):
    def evaluate(
        self,
        handle: ExecutionHandle,
        capability: CapabilityId,
        requested_scope: Scope,
    ) -> bool:
        """Read-only policy evaluation; registration is Core-only."""
        ...


class AuditPort(Protocol):
    def record(
        self,
        action: str,
        details: Mapping[str, object] | None = None,
        *,
        execution_handle: ExecutionHandle,
    ) -> str: ...
    def list_records(
        self,
        organization_id: str | None = None,
        limit: int = 100,
        *,
        execution_handle: ExecutionHandle,
    ) -> list[AuditEntry]: ...


class WorkflowPort(Protocol):
    def define(
        self,
        workflow_id: str,
        initial_state: str,
        transitions: Mapping[str, Sequence[str]],
        *,
        execution_handle: ExecutionHandle,
    ) -> None: ...
    def start(
        self,
        workflow_id: str,
        entity_id: str,
        case_input: Mapping[str, object] | None = None,
        *,
        execution_handle: ExecutionHandle,
    ) -> str: ...
    def transition(
        self,
        case_id: str,
        to_state: str,
        *,
        execution_handle: ExecutionHandle,
    ) -> None: ...
    def get_case(
        self,
        case_id: str,
        *,
        execution_handle: ExecutionHandle,
    ) -> WorkflowCase | None: ...


class NotificationPort(Protocol):
    def send(
        self,
        channel: str,
        recipient: str,
        subject: str,
        body: str,
        *,
        execution_handle: ExecutionHandle,
    ) -> str: ...
    def list_sent(
        self,
        recipient: str | None = None,
        *,
        execution_handle: ExecutionHandle,
    ) -> list[Notification]: ...


class SchedulingPort(Protocol):
    def schedule(
        self,
        key: str,
        run_at: datetime,
        payload: Mapping[str, object] | None = None,
        *,
        execution_handle: ExecutionHandle,
    ) -> str: ...
    def due(
        self,
        now: datetime | None = None,
        *,
        execution_handle: ExecutionHandle,
    ) -> list[ScheduledJob]: ...


class EventPublisherPort(Protocol):
    def publish(self, event: DomainEvent, *, execution_handle: ExecutionHandle) -> None: ...


class EventDispatcherPort(Protocol):
    def subscribe(
        self,
        event_id: EventId,
        subscriber: Callable[[DomainEvent], None],
        *,
        execution_handle: ExecutionHandle,
    ) -> None: ...
    def unsubscribe(
        self,
        event_id: EventId,
        subscriber: Callable[[DomainEvent], None],
        *,
        execution_handle: ExecutionHandle,
    ) -> None: ...


class ContractInvokerPort(Protocol):
    def invoke(
        self,
        contract_id: ContractId,
        request: object,
        *,
        execution_handle: ExecutionHandle,
    ) -> object: ...
    def invoke_all(
        self,
        contract_id: ContractId,
        request: object,
        *,
        execution_handle: ExecutionHandle,
    ) -> list[object]: ...


@dataclass(frozen=True)
class PluginContext:
    """Everything a plugin may reach; all authority enters through a handle."""

    plugin_id: str
    people: PeoplePort
    organization: OrganizationPort
    jobs: JobsPort
    assignments: AssignmentPort
    authorization: AuthorizationPort
    scope: ScopePort
    policy: PolicyPort
    audit: AuditPort
    workflow: WorkflowPort
    notification: NotificationPort
    scheduling: SchedulingPort
    events: EventPublisherPort
    dispatcher: EventDispatcherPort
    invoker: ContractInvokerPort
    capabilities: CapabilityRegistryPort
    contracts: ContractRegistryPort
    events_registry: EventRegistryPort
    persistence: PluginPersistencePort
    transactions: TransactionRunnerPort


__all__ = [
    "AssignmentPort",
    "AuditPort",
    "AuthorizationPort",
    "ContractInvokerPort",
    "EventDispatcherPort",
    "EventPublisherPort",
    "JobsPort",
    "NotificationPort",
    "OrganizationPort",
    "PeoplePort",
    "PluginContext",
    "PluginPersistencePort",
    "PolicyPort",
    "SchedulingPort",
    "ScopePort",
    "TransactionRunnerPort",
    "WorkflowPort",
]
