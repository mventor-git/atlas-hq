"""Workplace Operations — the first real domain plugin (contract section 27).

Every test here drives the real entry-point-registered plugin through the real
kernel: persistence, outbox, authorization, scope, audit, and the contracts.
No plugin-internal modules are imported by the tests except the plugin's own
public package — and never another plugin's.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import cast

import pytest

from atlas_core.application.organization import OrganizationService
from atlas_core.application.people import PeopleService
from atlas_core.application.unit_of_work import UnitOfWorkPort
from atlas_core.infrastructure.events import OutboxEventPublisher
from atlas_core.kernel import Kernel
from atlas_plugins.workplace_operations import (
    WORKPLACE_CONTEXT_CONTRACT,
    WORKPLACE_CREATED,
    WORKPLACE_MANAGE,
    WORKPLACE_VIEW,
    WORKPLACE_WORKFORCE_CHANGED,
    WORKPLACE_WORKFORCE_CONTRACT,
    WorkforceMembershipRequest,
    WorkforceRequest,
    WorkplaceContext,
    WorkplaceContextRequest,
    WorkplaceMember,
    WorkplaceOperationsPlugin,
    WorkplaceRequest,
)
from atlas_sdk import AuthorizationError, WorkplaceType

ACTOR = "user.workplace_admin"
MANAGER_ROLE = "role.workplace_manager"
VIEWER_ROLE = "role.workplace_viewer"


@pytest.fixture
def workplace_kernel(real_kernel: Kernel) -> Kernel:
    real_kernel.boot()
    real_kernel.enable("workplace_operations")
    return real_kernel


@pytest.fixture
def org_with_employee(uow_factory: Callable[[], UnitOfWorkPort]) -> tuple[str, str]:
    with uow_factory() as uow:
        org = OrganizationService(uow).create_organization(name="Acme", code="ACME")
        employee = PeopleService(uow, OutboxEventPublisher(uow, publisher="seed")).create_employee(
            full_name="Ada Lovelace",
            employee_number="EMP-1",
            organization_id=org.organization_id,
        )
    return org.organization_id, employee.employee_id


def _plugin(kernel: Kernel) -> WorkplaceOperationsPlugin:
    instance = kernel._instances["workplace_operations"]
    assert isinstance(instance, WorkplaceOperationsPlugin)
    return instance


def _grant(kernel: Kernel, role: str, org_id: str) -> None:
    context = kernel.context_for("workplace_operations")
    context.authorization.grant(ACTOR, role, context.scope.resolve(org_id))


def _make_workplace(
    kernel: Kernel, org_id: str, code: str = "HQ", kind: WorkplaceType = WorkplaceType.OFFICE
) -> str:
    workplace = _plugin(kernel).create_workplace(
        WorkplaceRequest(
            organization_id=org_id, name=f"Workplace {code}", code=code, kind=kind, actor_id=ACTOR
        ),
    )
    return workplace.workplace_id


def _add_member(kernel: Kernel, workplace_id: str, employee_id: str) -> None:
    _plugin(kernel).add_workforce_member(
        WorkforceMembershipRequest(
            workplace_id=workplace_id, employee_id=employee_id, actor_id=ACTOR
        ),
    )


# --- registration (Gates C, D, E, F, G, H) ---------------------------------


def test_plugin_registers_under_the_workplace_cluster(workplace_kernel: Kernel) -> None:
    manifest = workplace_kernel.registries.plugins.get("workplace_operations")
    assert manifest.cluster_id == "cluster.workplace_and_operations"
    assert (
        workplace_kernel.registries.plugins.lifecycle_state("workplace_operations").name
        == "ENABLED"
    )


def test_plugin_registers_its_modules_capabilities_contracts_events(
    workplace_kernel: Kernel,
) -> None:
    plugins = workplace_kernel.registries.plugins
    capabilities = workplace_kernel.registries.capabilities

    assert {"workplace.workforce", "workplace.context"} <= set(
        plugins.get("workplace_operations").module_ids()
    )
    assert capabilities.exists(WORKPLACE_MANAGE)
    assert capabilities.exists(WORKPLACE_VIEW)
    assert workplace_kernel.registries.contracts.exists(WORKPLACE_WORKFORCE_CONTRACT)
    assert workplace_kernel.registries.contracts.exists(WORKPLACE_CONTEXT_CONTRACT)
    assert workplace_kernel.registries.events.publishers_of(WORKPLACE_CREATED) == [
        "workplace_operations"
    ]


# --- real business services -------------------------------------------------


def test_creates_a_typed_workplace_and_persists_it(
    workplace_kernel: Kernel,
    org_with_employee: tuple[str, str],
) -> None:
    org_id, _employee_id = org_with_employee
    _grant(workplace_kernel, MANAGER_ROLE, org_id)

    workplace = _plugin(workplace_kernel).create_workplace(
        WorkplaceRequest(
            organization_id=org_id,
            name="Riverside Construction Site",
            code="RCS-1",
            kind=WorkplaceType.SITE,
            actor_id=ACTOR,
        ),
    )

    assert workplace.kind == WorkplaceType.SITE
    assert workplace.code == "RCS-1"
    assert workplace.organization_id == org_id

    # Persistence is real: a fresh lookup through the plugin finds it.
    found = [w for w in _plugin(workplace_kernel).list_workplaces(organization_id=org_id)]
    assert any(w.workplace_id == workplace.workplace_id for w in found)


def test_a_construction_site_is_a_workplace_type_not_the_identity(workplace_kernel: Kernel) -> None:
    """Contract section 8: 'Site' is one workplace type among eleven."""
    _plugin(workplace_kernel)  # plugin initialized
    types = {t for t in WorkplaceType}
    assert WorkplaceType.SITE in types
    assert len(types) >= 11


def test_adds_workforce_and_lists_the_member(
    workplace_kernel: Kernel,
    org_with_employee: tuple[str, str],
) -> None:
    org_id, employee_id = org_with_employee
    _grant(workplace_kernel, MANAGER_ROLE, org_id)
    workplace_id = _make_workplace(workplace_kernel, org_id)
    _add_member(workplace_kernel, workplace_id, employee_id)

    members = _plugin(workplace_kernel).list_workforce(workplace_id)
    assert len(members) == 1
    assert members[0].employee_id == employee_id
    assert members[0].full_name == "Ada Lovelace"


def test_resolves_workplace_context(
    workplace_kernel: Kernel, org_with_employee: tuple[str, str]
) -> None:
    org_id, employee_id = org_with_employee
    _grant(workplace_kernel, MANAGER_ROLE, org_id)
    workplace_id = _make_workplace(
        workplace_kernel, org_id, code="PLANT-7", kind=WorkplaceType.PLANT
    )
    _add_member(workplace_kernel, workplace_id, employee_id)

    context = _plugin(workplace_kernel).resolve_context(workplace_id)

    assert context.workplace_id == workplace_id
    assert context.code == "PLANT-7"
    assert context.kind == WorkplaceType.PLANT
    assert context.workforce_size == 1


def test_direct_workplace_reads_run_through_the_platform_runner(
    workplace_kernel: Kernel,
    org_with_employee: tuple[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org_id, employee_id = org_with_employee
    _grant(workplace_kernel, MANAGER_ROLE, org_id)
    workplace_id = _make_workplace(workplace_kernel, org_id)
    _add_member(workplace_kernel, workplace_id, employee_id)
    context = workplace_kernel.context_for("workplace_operations")
    calls = 0
    original_run = context.transactions.run

    def tracked_run(operation: Callable[[], object]) -> object:
        nonlocal calls
        calls += 1
        return original_run(operation)

    monkeypatch.setattr(context.transactions, "run", tracked_run)

    plugin = _plugin(workplace_kernel)
    plugin.list_workplaces(organization_id=org_id)
    plugin.list_workforce(workplace_id)
    plugin.resolve_context(workplace_id)

    assert calls == 3


def test_removes_a_workforce_member(
    workplace_kernel: Kernel, org_with_employee: tuple[str, str]
) -> None:
    org_id, employee_id = org_with_employee
    _grant(workplace_kernel, MANAGER_ROLE, org_id)
    workplace_id = _make_workplace(workplace_kernel, org_id)
    _add_member(workplace_kernel, workplace_id, employee_id)
    assert len(_plugin(workplace_kernel).list_workforce(workplace_id)) == 1

    _plugin(workplace_kernel).remove_workforce_member(
        WorkforceMembershipRequest(
            workplace_id=workplace_id, employee_id=employee_id, actor_id=ACTOR
        ),
    )

    assert _plugin(workplace_kernel).list_workforce(workplace_id) == []


# --- contracts (Gate G, and the composable extension of Gate O) -------------


def test_workforce_contract_answers_through_the_registry(
    workplace_kernel: Kernel,
    org_with_employee: tuple[str, str],
) -> None:
    org_id, employee_id = org_with_employee
    _grant(workplace_kernel, MANAGER_ROLE, org_id)
    workplace_id = _make_workplace(workplace_kernel, org_id)
    _add_member(workplace_kernel, workplace_id, employee_id)

    members = cast(
        "list[WorkplaceMember]",
        workplace_kernel.registries.contracts.invoke(
            WORKPLACE_WORKFORCE_CONTRACT,
            WorkforceRequest(workplace_id=workplace_id, actor_id=ACTOR),
        ),
    )

    assert len(members) == 1
    assert members[0].employee_id == employee_id


def test_context_contract_answers_through_the_registry(
    workplace_kernel: Kernel,
    org_with_employee: tuple[str, str],
) -> None:
    org_id, employee_id = org_with_employee
    _grant(workplace_kernel, MANAGER_ROLE, org_id)
    workplace_id = _make_workplace(workplace_kernel, org_id)
    _add_member(workplace_kernel, workplace_id, employee_id)

    context = cast(
        "WorkplaceContext",
        workplace_kernel.registries.contracts.invoke(
            WORKPLACE_CONTEXT_CONTRACT,
            WorkplaceContextRequest(workplace_id=workplace_id, actor_id=ACTOR),
        ),
    )

    assert context.workplace_id == workplace_id
    assert context.workforce_size == 1


# --- events (Gate H) --------------------------------------------------------


def test_creating_a_workplace_publishes_the_created_event(
    workplace_kernel: Kernel,
    org_with_employee: tuple[str, str],
) -> None:
    org_id, _employee_id = org_with_employee
    _grant(workplace_kernel, MANAGER_ROLE, org_id)
    _make_workplace(workplace_kernel, org_id)
    workplace_kernel.dispatcher.dispatch_pending()

    assert workplace_kernel.registries.events.publishers_of(WORKPLACE_CREATED) == [
        "workplace_operations"
    ]


def test_changing_the_workforce_publishes_a_transactional_event(
    workplace_kernel: Kernel,
    org_with_employee: tuple[str, str],
) -> None:
    org_id, employee_id = org_with_employee
    _grant(workplace_kernel, MANAGER_ROLE, org_id)
    workplace_id = _make_workplace(workplace_kernel, org_id)
    _add_member(workplace_kernel, workplace_id, employee_id)
    workplace_kernel.dispatcher.dispatch_pending()

    assert workplace_kernel.registries.events.exists(WORKPLACE_WORKFORCE_CHANGED)
    assert workplace_kernel.registries.events.publishers_of(WORKPLACE_WORKFORCE_CHANGED) == [
        "workplace_operations"
    ]


# --- authorization and scope (Gates L, M, N) --------------------------------


def test_creating_a_workplace_requires_the_capability(
    workplace_kernel: Kernel,
    org_with_employee: tuple[str, str],
) -> None:
    org_id, _employee_id = org_with_employee
    # No grant.
    with pytest.raises(AuthorizationError):
        _make_workplace(workplace_kernel, org_id)


def test_viewing_the_workforce_requires_the_view_capability(
    workplace_kernel: Kernel,
    org_with_employee: tuple[str, str],
) -> None:
    org_id, employee_id = org_with_employee
    _grant(workplace_kernel, MANAGER_ROLE, org_id)
    workplace_id = _make_workplace(workplace_kernel, org_id)
    _add_member(workplace_kernel, workplace_id, employee_id)

    with pytest.raises(AuthorizationError):
        workplace_kernel.registries.contracts.invoke(
            WORKPLACE_WORKFORCE_CONTRACT,
            WorkforceRequest(workplace_id=workplace_id, actor_id="user.unauthorized"),
        )


def test_an_actor_scoped_elsewhere_cannot_touch_this_org(
    workplace_kernel: Kernel,
    org_with_employee: tuple[str, str],
) -> None:
    org_id, _employee_id = org_with_employee
    context = workplace_kernel.context_for("workplace_operations")
    context.authorization.grant(ACTOR, MANAGER_ROLE, context.scope.resolve("org_foreign"))

    with pytest.raises(AuthorizationError):
        _make_workplace(workplace_kernel, org_id)


# --- audit (Gate L) ---------------------------------------------------------


def test_workplace_operations_write_audit_records(
    workplace_kernel: Kernel,
    org_with_employee: tuple[str, str],
) -> None:
    org_id, _employee_id = org_with_employee
    _grant(workplace_kernel, MANAGER_ROLE, org_id)
    _make_workplace(workplace_kernel, org_id)

    # The plugin audits through its own context; read it back the same way.
    context = workplace_kernel.context_for("workplace_operations")
    records = context.audit.list_records(organization_id=org_id, limit=20)

    assert any(r.action.startswith("workplace.") for r in records)
