"""Demo Plugin A against the real kernel — contract section 25's 14 checklist.

Every item is exercised against the real entry-point-registered plugin and the
real PostgreSQL-backed services, not a mock. The plugin consumed here is the one
``importlib.metadata`` discovers from this distribution's entry points.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import cast

import pytest

from atlas_core.application.organization import OrganizationService
from atlas_core.application.people import PeopleService
from atlas_core.application.unit_of_work import UnitOfWorkPort
from atlas_core.infrastructure.events import EventDispatcher, OutboxEventPublisher
from atlas_core.kernel import Kernel
from atlas_plugins.atlas_demo import (
    DEMO_GREET,
    DEMO_GREETED,
    DEMO_GREETING_CONTRACT,
    AtlasDemoPlugin,
    GreetingRequest,
    GreetingResponse,
)
from atlas_sdk import AuthorizationError, PluginLifecycle

ACTOR = "user.demo_admin"


@pytest.fixture
def demo(real_kernel: Kernel, uow_factory: Callable[[], UnitOfWorkPort]) -> Kernel:
    """Boot the real distribution and enable the demo plugin."""
    real_kernel.boot()
    real_kernel.enable("atlas_demo")
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


def _grant(kernel: Kernel, org_id: str) -> None:
    """Give the actor the demo capability, through the role the plugin published."""
    context = kernel.context_for("atlas_demo")
    context.authorization.grant(ACTOR, "role.demo_greeter", context.scope.resolve(org_id))


# 1. declare itself; 2. declare its cluster; 3. declare one module


def test_the_plugin_declares_itself_and_its_cluster(demo: Kernel) -> None:
    manifest = demo.registries.plugins.get("atlas_demo")  # 1
    assert manifest.plugin_id == "atlas_demo"
    assert manifest.name
    assert manifest.version

    cluster = demo.registries.clusters.get(manifest.cluster_id)  # 2
    assert cluster.cluster_id == "cluster.governance_and_management"
    assert manifest.cluster_id in {c.cluster_id for c in demo.registries.clusters.all()}

    assert manifest.module_ids() == ("demo.greeting",)  # 3
    assert demo.registries.plugins.list_by_cluster(cluster.cluster_id)


# 4. consume a real core service


def test_the_plugin_consumes_a_real_core_service(
    demo: Kernel,
    org_with_employee: tuple[str, str],
) -> None:
    """The greeting contract reads an employee through context.people (Gate J)."""
    org_id, employee_id = org_with_employee
    _grant(demo, org_id)

    response = cast(
        "GreetingResponse",
        demo.registries.contracts.invoke(
            DEMO_GREETING_CONTRACT,
            GreetingRequest(employee_id=employee_id, actor_id=ACTOR, organization_id=org_id),
        ),
    )

    assert response.greeting == "Hello, Ada Lovelace!"


# 5. provide one typed contract


def test_the_plugin_provides_a_typed_contract(demo: Kernel) -> None:
    impl = demo.registries.contracts.get(DEMO_GREETING_CONTRACT)  # Gate G

    assert impl.plugin_id == "atlas_demo"
    assert impl.declaration.version == "1.0"
    assert impl.declaration.schema["type"] == "object"
    required = impl.declaration.schema.get("required")
    assert isinstance(required, list)
    assert "employee_id" in required
    assert impl.is_bound  # the plugin is enabled, so the contract is callable


# 6. publish one event


def test_the_plugin_publishes_an_event(
    demo: Kernel,
    org_with_employee: tuple[str, str],
) -> None:
    """Gate H: the state change and its event land in one transaction."""
    org_id, employee_id = org_with_employee
    _grant(demo, org_id)

    demo.registries.contracts.invoke(
        DEMO_GREETING_CONTRACT,
        GreetingRequest(employee_id=employee_id, actor_id=ACTOR, organization_id=org_id),
    )
    demo.dispatcher.dispatch_pending()

    assert DEMO_GREETED in demo.registries.events.all()  # Gate H registration
    assert demo.registries.events.publishers_of(DEMO_GREETED) == ["atlas_demo"]


# 7. be discovered by the core; 8. be registered


def test_the_plugin_is_discovered_and_registered(demo: Kernel) -> None:
    assert demo.boot_result.discovered >= 1  # 7
    assert demo.registries.plugins.exists("atlas_demo")  # 8
    assert demo.boot_result.is_clean


# 9. be enabled; 10. be disabled


def test_the_plugin_can_be_enabled_and_disabled(demo: Kernel) -> None:
    assert demo.registries.plugins.lifecycle_state("atlas_demo") is PluginLifecycle.ENABLED  # 9

    demo.disable("atlas_demo")

    assert demo.registries.plugins.lifecycle_state("atlas_demo") is PluginLifecycle.DISABLED  # 10
    assert not demo.registries.contracts.get(DEMO_GREETING_CONTRACT).is_bound


def test_disable_reenable_rebinds_the_contract_transaction_owner(
    demo: Kernel,
    org_with_employee: tuple[str, str],
    uow_factory: Callable[[], UnitOfWorkPort],
) -> None:
    org_id, employee_id = org_with_employee
    _grant(demo, org_id)
    first = cast(
        "GreetingResponse",
        demo.registries.contracts.invoke(
            DEMO_GREETING_CONTRACT,
            GreetingRequest(employee_id=employee_id, actor_id=ACTOR, organization_id=org_id),
        ),
    )

    demo.disable("atlas_demo")
    demo.enable("atlas_demo")
    second = cast(
        "GreetingResponse",
        demo.registries.contracts.invoke(
            DEMO_GREETING_CONTRACT,
            GreetingRequest(employee_id=employee_id, actor_id=ACTOR, organization_id=org_id),
        ),
    )

    with uow_factory() as uow:
        records = list(uow.audit.all(organization_id=org_id, limit=20))
        envelopes = list(uow.outbox.pending(limit=20))

    assert first.audit_id in {record.audit_id for record in records}
    assert second.audit_id in {record.audit_id for record in records}
    assert any(envelope.event.payload.get("audit_id") == second.audit_id for envelope in envelopes)


# 11. appear in Atlas-HQ


def test_the_plugin_appears_in_atlas_hq(demo: Kernel) -> None:
    from atlas_hq.cli import render_plugins

    report = "\n".join(render_plugins(demo))

    assert "atlas_demo" in report
    assert "[enabled]" in report
    assert "demo.greeting" in report
    assert "cluster.governance_and_management" in report


# 12. write to audit


def test_the_plugin_writes_an_audit_record(
    demo: Kernel,
    org_with_employee: tuple[str, str],
    uow_factory: Callable[[], UnitOfWorkPort],
) -> None:
    org_id, employee_id = org_with_employee
    _grant(demo, org_id)

    response = cast(
        "GreetingResponse",
        demo.registries.contracts.invoke(
            DEMO_GREETING_CONTRACT,
            GreetingRequest(employee_id=employee_id, actor_id=ACTOR, organization_id=org_id),
        ),
    )

    from atlas_core.application.audit import AuditService

    records = AuditService(uow_factory()).list_records(organization_id=org_id, limit=20)
    ours = [r for r in records if r.audit_id == response.audit_id]

    assert len(ours) == 1
    assert ours[0].action == "demo.greeting"
    assert ours[0].actor == ACTOR
    assert ours[0].scope.organization_id == org_id


# 13. obey a capability


def test_the_plugin_obeys_a_capability(
    demo: Kernel,
    org_with_employee: tuple[str, str],
) -> None:
    """Without the grant, the privileged action is denied (Gate M)."""
    org_id, employee_id = org_with_employee

    with pytest.raises(AuthorizationError):
        demo.registries.contracts.invoke(
            DEMO_GREETING_CONTRACT,
            GreetingRequest(employee_id=employee_id, actor_id=ACTOR, organization_id=org_id),
        )


def test_the_plugin_registers_its_capability(demo: Kernel) -> None:
    assert demo.registries.capabilities.providers_of(DEMO_GREET) == ["atlas_demo"]
    assert demo.registries.capabilities.exists(DEMO_GREET)


# 14. obey scope


def test_the_plugin_respects_scope(
    demo: Kernel,
    uow_factory: Callable[[], UnitOfWorkPort],
) -> None:
    """Gate N: an actor scoped to one org cannot greet an employee of another."""
    with uow_factory() as uow:
        org_a = OrganizationService(uow).create_organization(name="A", code="A")
        org_b = OrganizationService(uow).create_organization(name="B", code="B")
        publisher = OutboxEventPublisher(uow, publisher="seed")
        employee_b = PeopleService(uow, publisher).create_employee(
            full_name="Grace Hopper",
            employee_number="EMP-B",
            organization_id=org_b.organization_id,
        )

    _grant(demo, org_a.organization_id)

    with pytest.raises(AuthorizationError):
        demo.registries.contracts.invoke(
            DEMO_GREETING_CONTRACT,
            GreetingRequest(
                employee_id=employee_b.employee_id,
                actor_id=ACTOR,
                organization_id=org_b.organization_id,
            ),
        )


def test_the_plugin_class_is_a_real_plugin_subclass() -> None:
    from atlas_sdk import Plugin

    assert issubclass(AtlasDemoPlugin, Plugin)
    assert AtlasDemoPlugin.manifest.plugin_id == "atlas_demo"


def test_the_dispatcher_is_available_on_the_context(demo: Kernel) -> None:
    """A plugin's context exposes the dispatcher for subscribing (Gate K)."""
    context = demo.context_for("atlas_demo")

    assert isinstance(context.dispatcher, EventDispatcher)
    assert context.invoker is not None
