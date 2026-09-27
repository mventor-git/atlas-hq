"""Gate K — plugin-to-plugin communication through a contract (contract §9).

Demo Plugin B consumes Demo Plugin A's contract without importing A's modules,
classes, or package. This file proves that mechanically: it boots the real
distribution, drives B, and asserts the coupling rules hold rather than trusting
the source to look decoupled.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from tests.conftest import (
    assign_role_for_test,
    issue_handle_for_test,
    issue_uow_handle_for_test,
)

from atlas_core.application.organization import OrganizationService
from atlas_core.application.people import PeopleService
from atlas_core.application.unit_of_work import UnitOfWorkPort
from atlas_core.domain.role import (
    AUDIT_READ,
    ORGANIZATION_MANAGE,
    PEOPLE_EMPLOYEE_CREATE,
    PEOPLE_EMPLOYEE_READ,
)
from atlas_core.infrastructure.events import OutboxEventPublisher
from atlas_core.kernel import Kernel
from atlas_plugins.atlas_demo_consumer import AtlasDemoConsumerPlugin
from atlas_sdk import AuthorizationError, CapabilityId, Scope

ACTOR = "user.demo_admin"


@pytest.fixture
def both(real_kernel: Kernel) -> Kernel:
    real_kernel.boot()
    real_kernel.enable("atlas_demo")
    real_kernel.enable("atlas_demo_consumer")
    return real_kernel


@pytest.fixture
def org_with_employee(uow_factory: Callable[[], UnitOfWorkPort]) -> tuple[str, str]:
    with uow_factory() as uow:
        org_handle = issue_uow_handle_for_test(
            uow_factory,
            ORGANIZATION_MANAGE,
            "organization.create",
            Scope(principal_id="seed.consumer"),
            principal_id="seed.consumer",
        )
        org = OrganizationService(uow).create_organization(
            name="Acme", code="ACME", execution_handle=org_handle
        )
        employee_handle = issue_uow_handle_for_test(
            uow_factory,
            PEOPLE_EMPLOYEE_CREATE,
            "people.employee.create",
            Scope(organization_id=org.organization_id),
        )
        employee = PeopleService(uow, OutboxEventPublisher(uow, publisher="seed")).create_employee(
            full_name="Ada Lovelace",
            employee_number="EMP-1",
            organization_id=org.organization_id,
            execution_handle=employee_handle,
        )
    return org.organization_id, employee.employee_id


def _grant(kernel: Kernel, org_id: str) -> None:
    assign_role_for_test(
        kernel,
        ACTOR,
        "role.demo_greeter",
        kernel.context_for("atlas_demo").scope.resolve(org_id),
    )
    kernel.authorization_management.grant_capability(
        ACTOR,
        PEOPLE_EMPLOYEE_READ,
        kernel.context_for("atlas_demo").scope.resolve(org_id),
        actor="tests",
    )
    kernel.authorization_management.grant_capability(
        ACTOR,
        AUDIT_READ,
        kernel.context_for("atlas_demo").scope.resolve(org_id),
        actor="tests",
    )


def _context(kernel: Kernel, org_id: str, *, actor: str = ACTOR):
    return issue_handle_for_test(
        kernel,
        actor,
        CapabilityId("demo.greet"),
        "demo.greet",
        kernel.context_for("atlas_demo_consumer").scope.resolve(org_id),
        resource_id="greeting",
        additional_capabilities=(PEOPLE_EMPLOYEE_READ, AUDIT_READ),
    )


def _consumer(kernel: Kernel) -> AtlasDemoConsumerPlugin:
    instance = kernel._instances["atlas_demo_consumer"]
    assert isinstance(instance, AtlasDemoConsumerPlugin)
    return instance


def test_b_consumes_as_contract_without_importing_a(
    both: Kernel,
    org_with_employee: tuple[str, str],
) -> None:
    """B invokes A's contract through the registry and receives a greeting."""
    org_id, employee_id = org_with_employee
    _grant(both, org_id)

    result = _consumer(both).call_greeting(
        employee_id,
        org_id,
        execution_handle=_context(both, org_id),
    )

    # B sees only the contract's structural promise: a greeting text and an id.
    assert getattr(result, "greeting", None) == "Hello, Ada Lovelace!"
    assert getattr(result, "employee_id", None) == employee_id


def test_never_imports_the_provider_implementation(both: Kernel) -> None:
    """The consumer's module never imports the provider's package.

    The mechanical half of Gate K: B's own source must not reach into A. A is
    loaded by the kernel (it is enabled), so what matters is that loading B
    alone never pulled A in — checked statically against B's imports and at
    runtime against the module's namespace.
    """
    import ast
    import inspect

    import atlas_plugins.atlas_demo_consumer as consumer_module

    tree = ast.parse(inspect.getsource(consumer_module))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    assert not any("atlas_plugins.atlas_demo" in name for name in imported), imported

    # No object on B's module is owned by A's package. B's own classes live in
    # atlas_demo_consumer, which shares a prefix — compare past the plugin id.
    for _name, value in vars(consumer_module).items():
        owner = getattr(value, "__module__", None)
        if owner is None:
            continue
        assert not owner.startswith("atlas_plugins.atlas_demo."), owner


def test_consumer_is_denied_when_actor_lacks_the_capability(
    both: Kernel,
    org_with_employee: tuple[str, str],
) -> None:
    """Gate M at the inter-plugin boundary: no grant, no greeting."""
    org_id, employee_id = org_with_employee
    with pytest.raises(AuthorizationError):
        _consumer(both).call_greeting(
            employee_id,
            org_id,
            execution_handle=_context(both, org_id),
        )


def test_consumer_observes_the_event_the_provider_published(
    both: Kernel,
    org_with_employee: tuple[str, str],
) -> None:
    """B subscribes to A's event id; dispatching the outbox delivers it."""
    org_id, employee_id = org_with_employee
    _grant(both, org_id)

    _consumer(both).call_greeting(
        employee_id,
        org_id,
        execution_handle=_context(both, org_id),
    )
    both.dispatcher.dispatch_pending()

    observed = _consumer(both).observed
    assert len(observed) == 1
    assert observed[0].employee_id == employee_id
    assert observed[0].full_name == "Ada Lovelace"
