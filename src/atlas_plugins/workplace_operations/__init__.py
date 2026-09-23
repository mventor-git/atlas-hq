"""Workplace Operations — the first real domain plugin (contract section 27).

A Workplace is a *typed* business location. ``Site`` is one ``WorkplaceType``
among eleven, not the platform's identity: a construction site is a workplace
configured as ``site``, nothing more. That typing is the rule this plugin
establishes, and the ``WorkplaceType`` enum lives in the SDK where every plugin
can read it without importing this one.

Three rules this plugin establishes and obeys:

1. **Plugin-owned tables.** ``wpop_workplace`` and ``wpop_workforce_membership``
   belong to this plugin alone (contract sections 9 and 22). Nothing else reads
   them; other plugins reach the domain through the contracts below.
2. **The platform owns the transaction.** This plugin writes through
   ``context.sessions``, the session of the unit of work the platform commits, so
   a workplace change and its ``workplace.*`` event land in one transaction or
   not at all (contract section 21). The plugin never commits.
3. **The workforce contract is composable.** ``workplace.workforce`` is *also*
   published as a ``reporting.dataset`` provider, so Report Studio discovers it
   without a code change (contract sections 13 and 26). The contract is the
   channel; the plugin id is not.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from atlas_sdk import (
    CapabilityId,
    Contract,
    ContractDeclaration,
    ContractId,
    EventId,
    ModuleDeclaration,
    Plugin,
    PluginManifest,
    WorkplaceType,
)
from atlas_sdk.reporting import (
    REPORT_DATASET_CONTRACT,
    REPORT_DATASET_DECLARATION,
    DatasetRequest,
    DatasetResponse,
)

from .domain import Workplace, WorkplaceContext, WorkplaceMember
from .persistence import WorkplaceOperationsRepository
from .services import WorkplaceOperationsService

if TYPE_CHECKING:
    from atlas_sdk import PluginContext

#: Capabilities every mutating operation requires (Gates L/M/N).
WORKPLACE_MANAGE = CapabilityId("workplace.manage")
WORKPLACE_VIEW = CapabilityId("workplace.view")

#: Events this plugin publishes through the outbox (contract section 20).
WORKPLACE_CREATED = EventId("workplace.created")
WORKPLACE_WORKFORCE_CHANGED = EventId("workplace.workforce.changed")

#: The contracts this plugin provides (contract section 15).
WORKPLACE_WORKFORCE_CONTRACT = ContractId("workplace.workforce")
WORKPLACE_CONTEXT_CONTRACT = ContractId("workplace.context")


@dataclass(frozen=True)
class WorkplaceRequest:
    """Request shape of ``workplace.create`` — register a typed workplace."""

    organization_id: str
    name: str
    code: str
    kind: WorkplaceType = WorkplaceType.OFFICE
    parent_workplace_id: str | None = None
    actor_id: str = ""


@dataclass(frozen=True)
class WorkforceMembershipRequest:
    """Request shape of ``workplace.workforce.add`` / ``.remove``."""

    workplace_id: str
    employee_id: str
    actor_id: str = ""


@dataclass(frozen=True)
class WorkforceRequest:
    """Request shape of ``workplace.workforce`` — the workforce of a workplace."""

    workplace_id: str
    actor_id: str = ""


@dataclass(frozen=True)
class WorkplaceContextRequest:
    """Request shape of ``workplace.context`` — resolve context for a scope."""

    workplace_id: str
    actor_id: str = ""


class WorkplaceWorkforceContract(Contract[WorkforceRequest, list[WorkplaceMember]]):
    """``workplace.workforce``: the workforce of one workplace.

    The contract is the *only* sanctioned channel (contract section 9). A
    consumer that needs this roster calls the contract; it never imports this
    plugin or reads ``wpop_workforce_membership``.
    """

    contract_id = WORKPLACE_WORKFORCE_CONTRACT

    def __init__(self, service: WorkplaceOperationsService) -> None:
        self._service = service

    def handle(self, request: WorkforceRequest) -> list[WorkplaceMember]:
        self._service.assert_workforce_visible(request.workplace_id, request.actor_id)
        return self._service.list_workforce(request.workplace_id)


class WorkplaceContextContract(Contract[WorkplaceContextRequest, WorkplaceContext]):
    """``workplace.context``: resolve the workplace context for a scope.

    Attendance's module declares it consumes this contract (contract section 15);
    this is the provider that answers.
    """

    contract_id = WORKPLACE_CONTEXT_CONTRACT

    def __init__(self, service: WorkplaceOperationsService) -> None:
        self._service = service

    def handle(self, request: WorkplaceContextRequest) -> WorkplaceContext:
        return self._service.resolve_context(request.workplace_id)


class WorkplaceWorkforceDatasetContract(Contract[DatasetRequest, DatasetResponse]):
    """The same workforce, exposed as a ``reporting.dataset`` provider (Gate O).

    Report Studio discovers this dataset by asking the registry for
    ``reporting.dataset`` implementations and never names this plugin (contract
    section 13). One workforce, two contracts: the typed one for domain
    consumers, this one for any reporting consumer.
    """

    contract_id = REPORT_DATASET_CONTRACT

    def __init__(self, service: WorkplaceOperationsService) -> None:
        self._service = service

    def handle(self, request: DatasetRequest) -> DatasetResponse:
        return self._service.workforce_dataset(request.organization_id)


class WorkplaceOperationsPlugin(Plugin):
    manifest = PluginManifest(
        plugin_id="workplace_operations",
        name="Workplace Operations",
        version="0.1.0",
        # contract section 8: Workplace & Operations. "Site" is a workplace
        # type, never the cluster's or the platform's identity.
        cluster_id="cluster.workplace_and_operations",
        requires_core="0.1.0",
        modules=(
            ModuleDeclaration(
                module_id="workplace.workforce",
                provides=("workplace.workforce", "reporting.dataset"),
                consumes=("people.employee.read",),
                publishes=(WORKPLACE_WORKFORCE_CHANGED,),
            ),
            ModuleDeclaration(
                module_id="workplace.context",
                provides=("workplace.context",),
                consumes=("workplace.workforce",),
            ),
        ),
        provides_capabilities=(WORKPLACE_MANAGE, WORKPLACE_VIEW),
        provides_contracts=(
            ContractDeclaration(
                contract_id=WORKPLACE_WORKFORCE_CONTRACT,
                version="1.0",
                schema={
                    "type": "object",
                    "properties": {
                        "workplace_id": {"type": "string"},
                        "actor_id": {"type": "string"},
                    },
                    "required": ["workplace_id"],
                },
                description="The workforce of one workplace.",
            ),
            ContractDeclaration(
                contract_id=WORKPLACE_CONTEXT_CONTRACT,
                version="1.0",
                schema={
                    "type": "object",
                    "properties": {
                        "workplace_id": {"type": "string"},
                        "actor_id": {"type": "string"},
                    },
                    "required": ["workplace_id"],
                },
                description="The workplace context for a scope: identity plus workforce size.",
            ),
            # Gate O — the workforce is also a composable reporting dataset.
            REPORT_DATASET_DECLARATION,
        ),
        publishes_events=(WORKPLACE_CREATED, WORKPLACE_WORKFORCE_CHANGED),
    )

    context: PluginContext

    def initialize(self, context: PluginContext) -> None:
        self.context = context
        # The plugin owns its tables: create them from the plugin's own
        # metadata, in the plugin's own transaction (contract section 22).
        WorkplaceOperationsRepository(context.sessions()).create_schema()
        self._service = WorkplaceOperationsService(context)
        # Publish the roles that carry this plugin's capabilities, so an
        # administrator can grant them (Gate M needs the grant to be possible).
        context.authorization.register_role(
            "role.workplace_manager",
            "Workplace Manager",
            frozenset({WORKPLACE_MANAGE, WORKPLACE_VIEW}),
        )
        context.authorization.register_role(
            "role.workplace_viewer",
            "Workplace Viewer",
            frozenset({WORKPLACE_VIEW}),
        )

    def bind_contracts(self) -> None:
        contracts = self.context.contracts
        contracts.bind(
            WORKPLACE_WORKFORCE_CONTRACT,
            self.manifest.plugin_id,
            WorkplaceWorkforceContract(self._service),
        )
        contracts.bind(
            WORKPLACE_CONTEXT_CONTRACT,
            self.manifest.plugin_id,
            WorkplaceContextContract(self._service),
        )
        # The same workforce, discoverable as a reporting dataset.
        contracts.bind(
            REPORT_DATASET_CONTRACT,
            self.manifest.plugin_id,
            WorkplaceWorkforceDatasetContract(self._service),
        )

    # --- the plugin's service surface -------------------------------------

    def create_workplace(self, request: WorkplaceRequest) -> Workplace:
        return self._service.create_workplace(
            organization_id=request.organization_id,
            name=request.name,
            code=request.code,
            kind=request.kind,
            parent_workplace_id=request.parent_workplace_id,
            actor=request.actor_id,
        )

    def add_workforce_member(self, request: WorkforceMembershipRequest) -> WorkplaceMember:
        return self._service.add_workforce_member(
            workplace_id=request.workplace_id,
            employee_id=request.employee_id,
            actor=request.actor_id,
        )

    def remove_workforce_member(self, request: WorkforceMembershipRequest) -> None:
        self._service.remove_workforce_member(
            workplace_id=request.workplace_id,
            employee_id=request.employee_id,
            actor=request.actor_id,
        )

    def list_workplaces(
        self,
        organization_id: str | None = None,
        kind: WorkplaceType | None = None,
    ) -> list[Workplace]:
        return self._service.list_workplaces(organization_id, kind)

    def list_workforce(self, workplace_id: str) -> list[WorkplaceMember]:
        return self._service.list_workforce(workplace_id)

    def resolve_context(self, workplace_id: str) -> WorkplaceContext:
        return self._service.resolve_context(workplace_id)


__all__ = [
    "WORKPLACE_CONTEXT_CONTRACT",
    "WORKPLACE_CREATED",
    "WORKPLACE_MANAGE",
    "WORKPLACE_VIEW",
    "WORKPLACE_WORKFORCE_CHANGED",
    "WORKPLACE_WORKFORCE_CONTRACT",
    "WorkforceMembershipRequest",
    "WorkforceRequest",
    "WorkplaceContextRequest",
    "WorkplaceOperationsPlugin",
    "WorkplaceRequest",
]
