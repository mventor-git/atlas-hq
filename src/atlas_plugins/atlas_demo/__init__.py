"""Demo Plugin A — the first real plugin (contract section 25).

It is deliberately small but exercises every part of the platform a plugin can
touch: it declares itself and its cluster, declares a module, consumes a real
core service, provides one typed contract, publishes an event through the
outbox, writes an audit record, obeys a capability and respects scope.

It is the proof that a plugin can be written against the SDK alone.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from atlas_sdk import (
    CapabilityId,
    Contract,
    ContractDeclaration,
    ContractId,
    DomainEvent,
    EventId,
    ModuleDeclaration,
    Plugin,
    PluginManifest,
    Scope,
)

if TYPE_CHECKING:
    from atlas_sdk import PluginContext

#: The contract this plugin provides. The *id* is the public contract between
#: Demo Plugin A and Demo Plugin B; B spells it as a literal string and never
#: imports this module (contract section 9, Gate K).
DEMO_GREETING_CONTRACT = ContractId("demo.greeting")

#: Capability this plugin's privileged action requires (contract section 35).
DEMO_GREET = CapabilityId("demo.greet")

#: The event this plugin publishes when it records a greeting.
DEMO_GREETED = EventId("demo.greeted")


@dataclass(frozen=True)
class GreetingRequest:
    """Request shape of the ``demo.greeting`` contract."""

    employee_id: str
    actor_id: str
    organization_id: str


@dataclass(frozen=True)
class GreetingResponse:
    """Response shape of the ``demo.greeting`` contract."""

    greeting: str
    employee_id: str
    audit_id: str
    scope: Scope


class GreetingContract(Contract[GreetingRequest, GreetingResponse]):
    """The runtime half of ``demo.greeting``.

    Every call consumes a real core service (people), resolves scope, checks a
    capability, writes audit and publishes an event — all in one transaction.
    """

    contract_id = DEMO_GREETING_CONTRACT

    def __init__(self, context: PluginContext) -> None:
        self._context = context

    def handle(self, request: GreetingRequest) -> GreetingResponse:
        from atlas_sdk import AuthorizationError

        context = self._context
        scope = context.scope.resolve(request.organization_id)

        # Gate N — scope: the operation only ever sees the org it asked for.
        # Gate M — capability: without the grant, the action is denied.
        if not context.authorization.check(DEMO_GREET, scope, request.actor_id):
            raise AuthorizationError(
                f"{request.actor_id!r} lacks capability {DEMO_GREET} in scope {scope}",
            )

        # Gate J — consume a real core service through the context.
        employee = context.people.get_employee(request.employee_id)
        if employee is None:
            from atlas_sdk import NotFoundError

            raise NotFoundError(
                f"employee {request.employee_id!r} not found",
                kind="employee",
                key=request.employee_id,
            )

        greeting = f"Hello, {employee.full_name}!"

        # Gate L — audit, in the same transaction as the state change.
        audit_id = context.audit.record(
            action="demo.greeting",
            actor=request.actor_id,
            scope=scope,
            details={"employee_id": employee.employee_id, "greeting": greeting},
        )

        # Gate H — publish an event through the outbox (contract section 21).
        context.events.publish(
            DomainEvent(
                event_id=DEMO_GREETED,
                payload={
                    "employee_id": employee.employee_id,
                    "full_name": employee.full_name,
                    "actor_id": request.actor_id,
                    "audit_id": audit_id,
                },
            ),
        )

        return GreetingResponse(
            greeting=greeting,
            employee_id=employee.employee_id,
            audit_id=audit_id,
            scope=scope,
        )


class AtlasDemoPlugin(Plugin):
    """Demo Plugin A."""

    manifest = PluginManifest(
        plugin_id="atlas_demo",
        name="Atlas Demo",
        version="0.1.0",
        # No orphan plugins (contract section 5). A demo of platform plumbing
        # belongs with the platform's own governance cluster.
        cluster_id="cluster.governance_and_management",
        requires_core="0.1.0",
        modules=(
            ModuleDeclaration(
                module_id="demo.greeting",
                provides=("demo.greeting",),
                consumes=("people.employee.read",),
                publishes=(DEMO_GREETED,),
                requires=(),
                supports=(),
            ),
        ),
        provides_capabilities=(DEMO_GREET,),
        provides_contracts=(
            ContractDeclaration(
                contract_id=DEMO_GREETING_CONTRACT,
                version="1.0",
                schema={
                    "type": "object",
                    "properties": {
                        "employee_id": {"type": "string"},
                        "actor_id": {"type": "string"},
                        "organization_id": {"type": "string"},
                    },
                    "required": ["employee_id", "actor_id", "organization_id"],
                },
                description="Produce a greeting for an employee, audited and event-backed.",
            ),
        ),
        publishes_events=(DEMO_GREETED,),
    )

    context: PluginContext

    def bind_contracts(self) -> None:
        self.context.contracts.bind(
            DEMO_GREETING_CONTRACT,
            self.manifest.plugin_id,
            self._handler,
        )

    def initialize(self, context: PluginContext) -> None:
        self.context = context
        self._handler = GreetingContract(context)
        # Publish the role that carries this plugin's capability so an
        # administrator can grant it (Gate M needs the grant to be possible).
        context.authorization.register_role(
            "role.demo_greeter",
            "Demo Greeter",
            frozenset({DEMO_GREET}),
        )


__all__ = [
    "AtlasDemoPlugin",
    "DEMO_GREET",
    "DEMO_GREETED",
    "DEMO_GREETING_CONTRACT",
    "GreetingRequest",
    "GreetingResponse",
]
