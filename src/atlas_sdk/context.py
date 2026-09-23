"""The plugin context: the single handle a plugin receives (contract section 2).

``PluginContext`` bundles the core application services a plugin may call, plus
the scope it runs in and the event publisher it writes through. Plugins never
import core internals — they hold a context.

Every service below is a Protocol owned by the SDK; ``atlas_core`` provides the
implementations. That inversion is the whole point of the hexagonal boundary:
core depends on the SDK's published language, never the reverse.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

from .capability import CapabilityId
from .contract import ContractId
from .event import DomainEvent, EventId
from .registry import (
    CapabilityRegistryPort,
    ContractRegistryPort,
    EventRegistryPort,
)
from .types import (
    Assignment,
    AuditEntry,
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


class PeoplePort(Protocol):
    def create_employee(
        self,
        full_name: str,
        employee_number: str,
        organization_id: str,
    ) -> Employee: ...

    def get_employee(self, employee_id: str) -> Employee | None: ...
    def list_employees(self, organization_id: str | None = None) -> list[Employee]: ...


class OrganizationPort(Protocol):
    def create_organization(self, name: str, code: str) -> Organization: ...
    def get_organization(self, organization_id: str) -> Organization | None: ...
    def add_workplace(
        self,
        organization_id: str,
        name: str,
        kind: WorkplaceType = WorkplaceType.OFFICE,
    ) -> Workplace: ...
    def list_workplaces(self, organization_id: str) -> list[Workplace]: ...


class JobsPort(Protocol):
    def create_job(
        self,
        organization_id: str,
        title: str,
        workplace_id: str | None = None,
    ) -> Job: ...

    def get_job(self, job_id: str) -> Job | None: ...
    def list_jobs(self, organization_id: str) -> list[Job]: ...


class AssignmentPort(Protocol):
    def assign(
        self,
        employee_id: str,
        job_id: str,
        workplace_id: str | None = None,
        start_date: date | None = None,
    ) -> Assignment: ...

    def get_assignment(self, assignment_id: str) -> Assignment | None: ...
    def assignments_for(self, employee_id: str) -> list[Assignment]: ...


class AuthorizationPort(Protocol):
    def check(self, capability: CapabilityId, scope: Scope, subject_id: str) -> bool:
        """True if ``subject_id`` may exercise ``capability`` within ``scope``."""
        ...

    def grant(self, subject_id: str, role: str, scope: Scope) -> None:
        """Assign ``role`` to ``subject_id`` within ``scope``."""
        ...

    def register_role(
        self,
        role_id: str,
        name: str,
        capabilities: frozenset[CapabilityId],
    ) -> None:
        """Publish a role through which a plugin's own capabilities can be granted.

        A plugin declares a capability in its manifest, but before an
        administrator can grant that capability to anybody a role carrying it has
        to exist. Plugins call this at initialize time; the platform's own roles
        are seeded by the core. Calling twice with the same id is a refresh.
        """
        ...


class ScopePort(Protocol):
    def resolve(
        self,
        organization_id: str | None,
        workplace_id: str | None = None,
    ) -> Scope:
        """Build a scope value from raw ids."""
        ...

    def narrow(self, requested: Scope, subject: Scope) -> Scope:
        """Intersect the scope an operation wants with the scope an actor may see.

        The result never grants more than ``subject``. Disjoint scopes yield an
        empty scope (``organization_id is None``), which queries treat as
        "nothing visible".
        """
        ...


class PolicyPort(Protocol):
    def register(
        self,
        policy_id: str,
        effective_from: date,
        effective_to: date | None = None,
        enabled: bool = True,
        condition: Mapping[str, str] | None = None,
    ) -> None:
        """Register an effective-dated policy."""
        ...

    def evaluate(self, policy_id: str, on: date, facts: Mapping[str, object]) -> bool:
        """True if the policy is in effect on ``on`` and ``facts`` satisfy it."""
        ...


class AuditPort(Protocol):
    def record(
        self,
        action: str,
        actor: str,
        scope: Scope | None = None,
        details: Mapping[str, object] | None = None,
    ) -> str:
        """Append one audit record and return its id."""
        ...

    def list_records(
        self,
        organization_id: str | None = None,
        limit: int = 100,
    ) -> list[AuditEntry]: ...


class WorkflowPort(Protocol):
    def define(
        self,
        workflow_id: str,
        initial_state: str,
        transitions: Mapping[str, Sequence[str]],
    ) -> None:
        """Register a state machine: allowed transitions keyed by source state."""

    def start(
        self,
        workflow_id: str,
        entity_id: str,
        case_input: Mapping[str, object] | None = None,
    ) -> str:
        """Start a workflow case for ``entity_id``; returns the case id."""
        ...

    def transition(self, case_id: str, to_state: str) -> None: ...
    def get_case(self, case_id: str) -> WorkflowCase | None: ...


class NotificationPort(Protocol):
    def send(
        self,
        channel: str,
        recipient: str,
        subject: str,
        body: str,
    ) -> str: ...

    def list_sent(self, recipient: str | None = None) -> list[Notification]: ...


class SchedulingPort(Protocol):
    def schedule(
        self,
        key: str,
        run_at: datetime,
        payload: Mapping[str, object] | None = None,
    ) -> str: ...

    def due(self, now: datetime | None = None) -> list[ScheduledJob]: ...


class EventPublisherPort(Protocol):
    def publish(self, event: DomainEvent) -> None:
        """Append an event to the outbox of the current transaction."""


class EventDispatcherPort(Protocol):
    """In-process event subscription (contract section 21).

    Plugins subscribe to the *event id* string of another plugin's event. They
    never import the publishing plugin, and the publisher has no way to know who
    is listening — the registry is the only channel (contract section 9).
    """

    def subscribe(self, event_id: EventId, subscriber: Callable[[DomainEvent], None]) -> None:
        """Register ``subscriber`` to be called whenever ``event_id`` is dispatched."""
        ...

    def unsubscribe(self, event_id: EventId, subscriber: Callable[[DomainEvent], None]) -> None: ...


class ContractInvokerPort(Protocol):
    """Call a contract provided by *some* plugin, discovered by id (§9, §13).

    The caller never knows which plugin implements the contract. The registry
    resolves the declaration; this port runs the bound instance. Invoking an
    unbound contract — no enabled plugin provides it — raises
    :class:`~atlas_sdk.NotFoundError`.
    """

    def invoke(self, contract_id: ContractId, request: object) -> object:
        """Run the single enabled implementation of ``contract_id``."""
        ...

    def invoke_all(self, contract_id: ContractId, request: object) -> list[object]:
        """Run every enabled implementation; composability (contract section 13)."""
        ...


@dataclass(frozen=True)
class PluginContext:
    """Everything a plugin may reach. Plugins import this package, not core."""

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


__all__ = [
    "AssignmentPort",
    "AuditPort",
    "AuthorizationPort",
    "ContractInvokerPort",
    "EventDispatcherPort",
    "EventPublisherPort",
    "JobsPort",
    "NotificationPort",
    "PeoplePort",
    "PluginContext",
    "PolicyPort",
    "SchedulingPort",
    "ScopePort",
    "WorkflowPort",
    "OrganizationPort",
]
