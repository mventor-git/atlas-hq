"""Adversarial acceptance tests for the opaque PostgreSQL execution handle."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Barrier

import pytest
from tests.conftest import issue_uow_handle_for_test

from atlas_core.application.authorization import AuthorizationService
from atlas_core.application.management import AuthorizationManagementService
from atlas_core.application.policy import PolicyService
from atlas_core.application.unit_of_work import UnitOfWorkPort
from atlas_core.infrastructure.persistence.orm import OrganizationORM
from atlas_sdk import (
    AuthorizationError,
    CapabilityId,
    CapabilityKind,
    Channel,
    ExecutionHandle,
    Scope,
)

PRINCIPAL = "principal.handle"
REPORT = CapabilityId("handle.report")
SELF = Scope(principal_id=PRINCIPAL)


def _setup(
    uow: UnitOfWorkPort,
    uow_factory=None,
) -> tuple[AuthorizationService, AuthorizationManagementService]:
    policy = PolicyService()
    policy.register("handle.default", date.min)
    authorization = AuthorizationService(uow=uow, policy=policy, uow_factory=uow_factory)
    management = AuthorizationManagementService(uow, authorization=authorization)
    authorization.register_capability(REPORT, CapabilityKind.VIEW)
    management.create_principal(PRINCIPAL)
    return authorization, management


def _handle(authorization: AuthorizationService, **kwargs):
    return authorization.issue_handle(
        principal_id=PRINCIPAL,
        capability=REPORT,
        action="handle.report",
        scope=SELF,
        channel=Channel.WEB,
        **kwargs,
    )


def test_handle_is_opaque_and_non_forgeable(uow_factory) -> None:
    with uow_factory() as uow:
        authorization, management = _setup(uow, uow_factory)
        management.grant_capability(PRINCIPAL, REPORT, SELF)
        handle = _handle(authorization, resource_id="report-1")

        assert isinstance(handle, ExecutionHandle)
        assert not hasattr(handle, "principal_id")
        assert not hasattr(handle, "scope")
        assert not hasattr(handle, "channel")
        assert "redacted" in repr(handle)
        assert authorization.authorize(handle, REPORT, SELF).allowed
        with pytest.raises(AttributeError):
            handle.principal_id = "attacker"  # type: ignore[attr-defined]
        forged_decision = authorization.authorize(
            object.__new__(ExecutionHandle),  # type: ignore[arg-type]
            REPORT,
            SELF,
        )
        assert not forged_decision.allowed
        assert forged_decision.code == "handle_invalid"


def test_copied_handle_token_is_a_replay_and_denies(uow_factory) -> None:
    with uow_factory() as uow:
        authorization, management = _setup(uow, uow_factory)
        management.grant_capability(PRINCIPAL, REPORT, SELF)
        handle = _handle(authorization)
        copied = object.__new__(ExecutionHandle)
        object.__setattr__(
            copied,
            "_ExecutionHandle__token",
            object.__getattribute__(handle, "_ExecutionHandle__token"),
        )
        assert not authorization.authorize(copied, REPORT, SELF).allowed


def test_scope_and_caller_fact_cannot_override_canonical_record(uow_factory) -> None:
    with uow_factory() as uow:
        authorization, management = _setup(uow, uow_factory)
        management.grant_capability(PRINCIPAL, REPORT, SELF)
        handle = _handle(authorization)
        assert not authorization.authorize(handle, REPORT, Scope(principal_id="other")).allowed
        assert not authorization.authorize(handle, CapabilityId("unknown.view"), SELF).allowed


def test_expiry_and_revocation_fail_closed(uow_factory) -> None:
    with uow_factory() as uow:
        authorization, management = _setup(uow, uow_factory)
        management.grant_capability(PRINCIPAL, REPORT, SELF)
        expired = authorization.issue_handle(
            principal_id=PRINCIPAL,
            capability=REPORT,
            action="handle.report",
            scope=SELF,
            channel=Channel.WEB,
            ttl_seconds=1,
        )
        time.sleep(1.1)
        assert not authorization.authorize(expired, REPORT, SELF).allowed
        revoked = _handle(authorization)
        assert authorization.revoke_handle(revoked)
        assert not authorization.authorize(revoked, REPORT, SELF).allowed


def test_missing_handle_denies_and_denial_audit_survives_rollback(uow_factory) -> None:
    with pytest.raises(RuntimeError, match="business rollback"), uow_factory() as uow:
        authorization, _ = _setup(uow, uow_factory)
        decision = authorization.authorize(None, REPORT, SELF)  # type: ignore[arg-type]
        assert not decision.allowed
        assert decision.code == "handle_required"
        raise RuntimeError("business rollback")

    with uow_factory() as uow:
        assert any(
            record.action == "authorization.decision" and record.details.get("allowed") is False
            for record in uow.audit.all(limit=20)
        )


def test_registry_only_authorization_cannot_issue_or_authorize() -> None:
    authorization = AuthorizationService()
    with pytest.raises(RuntimeError, match="PostgreSQL"):
        authorization.issue_handle(
            principal_id=PRINCIPAL,
            capability=REPORT,
            action="handle.report",
            scope=SELF,
            channel=Channel.WEB,
        )
    # No persistence means no durable denial audit, so even the denial fails
    # closed hard instead of being reported as a decision.
    with pytest.raises(AuthorizationError, match="denial-audit"):
        authorization.authorize(object(), REPORT, SELF)  # type: ignore[arg-type]


def test_confirmation_is_bound_and_consumed_once(uow_factory) -> None:
    with uow_factory() as uow:
        policy = PolicyService()
        policy.register(
            "handle.confirmation",
            date.min,
            condition={"confirmation_required": "true"},
            capability=REPORT,
            action="handle.delete",
            channel=Channel.WEB,
        )
        authorization = AuthorizationService(uow=uow, policy=policy, uow_factory=uow_factory)
        management = AuthorizationManagementService(uow, authorization=authorization)
        authorization.register_capability(REPORT, CapabilityKind.MANAGE)
        management.create_principal(PRINCIPAL)
        management.grant_capability(PRINCIPAL, REPORT, SELF)
        handle = authorization.issue_handle(
            principal_id=PRINCIPAL,
            capability=REPORT,
            action="handle.delete",
            scope=SELF,
            channel=Channel.WEB,
            resource_id="report-1",
        )
        confirmation_id = management.confirm_handle(handle, REPORT)
        assert authorization.authorize(
            handle, REPORT, SELF, confirmation_id=confirmation_id
        ).allowed
        assert not authorization.authorize(
            handle, REPORT, SELF, confirmation_id=confirmation_id
        ).allowed


def test_confirmation_allows_narrower_in_scope_request(uow_factory) -> None:
    with uow_factory() as uow:
        policy = PolicyService()
        policy.register(
            "handle.narrow",
            date.min,
            condition={"confirmation_required": "true"},
            capability=REPORT,
            action="handle.delete",
            channel=Channel.WEB,
        )
        authorization = AuthorizationService(uow=uow, policy=policy, uow_factory=uow_factory)
        management = AuthorizationManagementService(uow, authorization=authorization)
        authorization.register_capability(REPORT, CapabilityKind.MANAGE)
        management.create_principal(PRINCIPAL)
        broad = Scope(organization_id="org-narrow")
        narrow = Scope(organization_id="org-narrow", workplace_id="wp-narrow")
        management.grant_capability(PRINCIPAL, REPORT, broad)
        handle = authorization.issue_handle(
            principal_id=PRINCIPAL,
            capability=REPORT,
            action="handle.delete",
            scope=broad,
            channel=Channel.WEB,
        )
        confirmation_id = management.confirm_handle(handle, REPORT)
        assert authorization.authorize(
            handle, REPORT, narrow, confirmation_id=confirmation_id
        ).allowed


def test_confirmation_race_has_one_success(uow_factory) -> None:
    with uow_factory() as uow:
        policy = PolicyService()
        policy.register(
            "handle.race",
            date.min,
            condition={"confirmation_required": "true"},
            capability=REPORT,
            action="handle.delete",
            channel=Channel.WEB,
        )
        authorization = AuthorizationService(uow=uow, policy=policy, uow_factory=uow_factory)
        management = AuthorizationManagementService(uow, authorization=authorization)
        authorization.register_capability(REPORT, CapabilityKind.MANAGE)
        management.create_principal(PRINCIPAL)
        management.grant_capability(PRINCIPAL, REPORT, SELF)
        handle = authorization.issue_handle(
            principal_id=PRINCIPAL,
            capability=REPORT,
            action="handle.delete",
            scope=SELF,
            channel=Channel.WEB,
        )
        confirmation_id = management.confirm_handle(handle, REPORT)

    barrier = Barrier(2)

    def consume() -> bool:
        with uow_factory() as uow:
            service = AuthorizationService(
                uow=uow,
                policy=PolicyService(),
                uow_factory=uow_factory,
            )
            # Bind the persisted policy explicitly for this service view.
            service._policy = PolicyService()
            service._policy.register(
                "handle.race",
                date.min,
                condition={"confirmation_required": "true"},
                capability=REPORT,
                action="handle.delete",
                channel=Channel.WEB,
            )
            barrier.wait()
            return service.authorize(handle, REPORT, SELF, confirmation_id=confirmation_id).allowed

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [f.result() for f in (pool.submit(consume), pool.submit(consume))]
    assert sorted(results) == [False, True]


def test_identity_link_race_has_one_success(uow_factory) -> None:
    with uow_factory() as uow:
        authorization, management = _setup(uow, uow_factory)
        management.create_principal("principal.link-a")
        management.create_principal("principal.link-b")
        management.create_identity("identity.link", Channel.TELEGRAM, "external-link")

    barrier = Barrier(2)

    def link(principal_id: str) -> str:
        with uow_factory() as uow:
            service = AuthorizationService(uow=uow, uow_factory=uow_factory)
            management = AuthorizationManagementService(uow, authorization=service)
            barrier.wait()
            try:
                return management.link_identity("identity.link", principal_id).principal_id or ""
            except Exception as error:  # noqa: BLE001 - race result is the assertion
                return type(error).__name__

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [
            f.result()
            for f in (pool.submit(link, "principal.link-a"), pool.submit(link, "principal.link-b"))
        ]
    assert sorted(results) in (
        ["NotFoundError", "principal.link-a"],
        ["NotFoundError", "principal.link-b"],
    )


def test_plugin_persistence_rejects_core_and_foreign_tables(uow_factory) -> None:
    with uow_factory() as uow:
        adapter = uow.plugin_persistence("plugin.a", ("plugin_a_table",))
        with pytest.raises(PermissionError):
            adapter.get(OrganizationORM, "anything")
        assert not hasattr(adapter, "query")
        assert not hasattr(adapter, "create_schema")


def test_denied_direct_service_without_independent_audit_factory_fails_closed(
    uow_factory,
) -> None:
    """A same-UoW audit fallback must never make a denial look durable."""
    from atlas_core.domain.organization import Organization

    with uow_factory() as uow:
        authorization, _ = _setup(uow, lambda: uow)
        uow.organizations.add(Organization(name="staged", code="STAGED"))
        with pytest.raises(AuthorizationError, match="caller transaction"):
            authorization.authorize(_handle(authorization), REPORT, SELF)
        # The caller's own unit of work is still usable; it is never closed here.
        assert uow.organizations.get_by_code("STAGED") is not None


def test_denied_direct_service_writes_its_denial_through_an_independent_uow(
    uow_factory,
) -> None:
    """A self-constructed Core service still leaves a durable denial Audit record."""
    from atlas_core.application.organization import OrganizationService

    with uow_factory() as uow:
        service = OrganizationService(uow)
        with pytest.raises(AuthorizationError, match="organization operation denied"):
            service.create_organization(
                name="Undenied",
                code="UNDENIED",
                execution_handle=issue_uow_handle_for_test(
                    uow_factory, REPORT, "handle.report", SELF, principal_id=PRINCIPAL
                ),
            )

    with uow_factory() as check:
        assert any(
            record.action == "authorization.decision" and record.details.get("allowed") is False
            for record in check.audit.all(limit=20)
        )


def test_denied_kernel_audit_is_separate_from_staged_business_state(
    uow_factory,
) -> None:
    from atlas_core.domain.organization import Organization

    with pytest.raises(RuntimeError, match="business rollback"), uow_factory() as caller:
        policy = PolicyService()
        policy.register("kernel.default", date.min)
        authorization = AuthorizationService(
            uow=caller,
            policy=policy,
            uow_factory=uow_factory,
        )
        management = AuthorizationManagementService(caller, authorization=authorization)
        authorization.register_capability(REPORT, CapabilityKind.VIEW)
        management.create_principal(PRINCIPAL)
        handle = authorization.issue_handle(
            principal_id=PRINCIPAL,
            capability=REPORT,
            action="handle.report",
            scope=SELF,
            channel=Channel.WEB,
        )
        caller.organizations.add(Organization(name="staged-kernel", code="STAGEDK"))
        decision = authorization.authorize(handle, REPORT, SELF)
        assert not decision.allowed
        raise RuntimeError("business rollback")

    with uow_factory() as check:
        assert not check.organizations.get_by_code("STAGEDK")
        assert any(
            record.action == "authorization.decision" and record.details.get("allowed") is False
            for record in check.audit.all(limit=20)
        )


def test_handle_is_bound_to_issued_capability(uow_factory) -> None:
    manage = CapabilityId("handle.manage")
    with uow_factory() as uow:
        authorization, management = _setup(uow, uow_factory)
        authorization.register_capability(manage, CapabilityKind.MANAGE)
        management.grant_capability(PRINCIPAL, manage, SELF)
        handle = _handle(authorization)
        assert not authorization.authorize(handle, manage, SELF).allowed


def test_bare_contract_registry_fails_closed_without_core_validator() -> None:
    from tests.conftest import opaque_handle_for_test

    from atlas_core.infrastructure.registry import InMemoryContractRegistry, TransactionOwner
    from atlas_sdk import ContractDeclaration, ContractId

    class Handler:
        def handle(self, request, *, execution_handle):
            return "handled"

    contract_id = ContractId("security.bare")
    registry = InMemoryContractRegistry()
    registry.register(ContractDeclaration(contract_id=contract_id), "provider")
    registry.bind(contract_id, "provider", Handler())
    registry.register_transaction_owner(
        "provider", TransactionOwner(commit=lambda: None, rollback=lambda: None)
    )
    with pytest.raises(AuthorizationError):
        registry.invoke(contract_id, object(), execution_handle=opaque_handle_for_test())


def test_plugin_services_expose_no_core_uow_or_policy_state(real_kernel) -> None:
    real_kernel.boot()
    context = real_kernel.context_for("atlas_demo")
    for service in (context.people, context.organization, context.jobs, context.assignments):
        assert not hasattr(service, "_uow")
        assert not hasattr(service, "_session")
    assert not hasattr(context.audit, "_uow")
    assert not hasattr(context.authorization, "_service")
    assert not hasattr(context.policy, "_authorization")
    assert not hasattr(context.policy, "_service")


def test_management_confirmation_requires_handle_and_explicit_capability(
    uow_factory,
) -> None:
    with uow_factory() as uow:
        authorization, management = _setup(uow, uow_factory)
        with pytest.raises(TypeError):
            management.confirm(  # type: ignore[call-arg]
                PRINCIPAL,
                "handle.report",
                SELF,  # type: ignore[call-arg]
            )
        with pytest.raises(TypeError):
            management.confirm_handle(_handle(authorization))  # type: ignore[call-arg]


def test_migration_record_cannot_falsely_skip_execution_table(database_url, test_schema) -> None:
    """This test builds its own engine, so it must drop its own schema too."""
    from sqlalchemy import create_engine, text

    from atlas_core.infrastructure.persistence.session import (
        create_schema,
        create_session_factory_with_engine,
        drop_schema,
        resolve_database_url,
    )

    _factory, engine = create_session_factory_with_engine(
        resolve_database_url(database_url), schema=test_schema
    )
    try:
        create_schema(engine, test_schema)
        with engine.begin() as connection:
            connection.execute(text("DROP TABLE execution_handle"))
        with pytest.raises(RuntimeError, match="migration"):
            create_schema(engine, test_schema)
    finally:
        engine.dispose()
        admin_engine = create_engine(resolve_database_url(database_url), future=True)
        try:
            drop_schema(admin_engine, test_schema)
        finally:
            admin_engine.dispose()


def test_workflow_scheduling_notification_reject_forged_expired_revoked(real_kernel) -> None:
    from datetime import UTC, datetime, timedelta

    real_kernel.boot()
    real_kernel.enable("atlas_demo")
    context = real_kernel.context_for("atlas_demo")
    management = real_kernel.authorization_management
    management.create_principal("ports.operator")
    management.grant_capability(
        "ports.operator", CapabilityId("demo.greet"), Scope(principal_id="ports.operator")
    )
    real_kernel.issue_execution_handle(
        principal_id="ports.operator",
        capability=CapabilityId("demo.greet"),
        action="ports.operate",
        scope=Scope(principal_id="ports.operator"),
        channel=Channel.CORE,
    )
    expired = real_kernel.issue_execution_handle(
        principal_id="ports.operator",
        capability=CapabilityId("demo.greet"),
        action="ports.operate",
        scope=Scope(principal_id="ports.operator"),
        channel=Channel.CORE,
        ttl_seconds=1,
    )
    time.sleep(1.1)
    revoked = real_kernel.issue_execution_handle(
        principal_id="ports.operator",
        capability=CapabilityId("demo.greet"),
        action="ports.operate",
        scope=Scope(principal_id="ports.operator"),
        channel=Channel.CORE,
    )
    real_kernel.revoke_execution_handle(revoked)
    forged = object.__new__(ExecutionHandle)
    for handle in (forged, expired, revoked):
        with pytest.raises(AuthorizationError):
            context.workflow.define("wf", "new", {}, execution_handle=handle)
        with pytest.raises(AuthorizationError):
            context.scheduling.schedule(
                "job",
                datetime.now(UTC) + timedelta(hours=1),
                execution_handle=handle,
            )
        with pytest.raises(AuthorizationError):
            context.notification.send("web", "x", "s", "b", execution_handle=handle)


def test_real_kernel_confirmation_policy_evaluation_is_concurrency_safe(uow_factory) -> None:
    from atlas_core.kernel import Kernel
    from atlas_plugins.atlas_demo import DEMO_GREET

    kernel = Kernel(uow_factory=uow_factory)
    kernel.boot()
    kernel.enable("atlas_demo")
    management = kernel.authorization_management
    management.create_principal("policy.operator")
    management.register_policy(
        "concurrent.confirmation",
        date.min,
        condition={"confirmation_required": "true"},
        capability=DEMO_GREET,
        action="demo.greet",
        channel=Channel.WEB,
    )
    management.grant_capability(
        "policy.operator", DEMO_GREET, Scope(principal_id="policy.operator")
    )
    handle = kernel.issue_execution_handle(
        principal_id="policy.operator",
        capability=DEMO_GREET,
        action="demo.greet",
        scope=Scope(principal_id="policy.operator"),
        channel=Channel.WEB,
    )
    confirmation_id = management.confirm_handle(handle, DEMO_GREET)
    auth = kernel.context_for("atlas_demo").authorization
    barrier = Barrier(8)

    def decide() -> bool:
        barrier.wait()
        return auth.authorize(
            handle,
            DEMO_GREET,
            Scope(principal_id="policy.operator"),
            confirmation_id=confirmation_id,
        ).allowed


def test_cli_does_not_self_authorize_from_actor_input(
    uow_factory, database_url, test_schema, monkeypatch
) -> None:
    from atlas_core.application.organization import OrganizationService
    from atlas_core.domain.role import ORGANIZATION_MANAGE
    from atlas_hq.cli import main

    with uow_factory() as uow:
        handle = issue_uow_handle_for_test(
            uow_factory,
            ORGANIZATION_MANAGE,
            "organization.create",
            Scope(principal_id="cli-test"),
            principal_id="cli-test",
        )
        org = OrganizationService(uow).create_organization(
            name="CLI Untrusted",
            code="CLIU",
            execution_handle=handle,
        )
    monkeypatch.setenv("ATLAS_DATABASE_URL", database_url)
    monkeypatch.setenv("ATLAS_DATABASE_SCHEMA", test_schema)
    with pytest.raises(SystemExit):
        main(["report", org.organization_id, "--actor", "attacker"])
    with uow_factory() as check:
        assert check.authorization.get_principal("attacker") is None


def test_event_bus_rejects_forged_and_foreign_owner_handles(real_kernel) -> None:
    real_kernel.boot()
    real_kernel.enable("atlas_demo")
    real_kernel.enable("atlas_demo_consumer")
    first = real_kernel.context_for("atlas_demo")
    second = real_kernel.context_for("atlas_demo_consumer")

    def callback(_event) -> None:
        return None

    forged = object.__new__(ExecutionHandle)
    with pytest.raises(AuthorizationError):
        first.dispatcher.subscribe("demo.greeted", callback, execution_handle=forged)
    with pytest.raises(AuthorizationError):
        second.dispatcher.unsubscribe("demo.greeted", callback, execution_handle=forged)
    management = real_kernel.authorization_management
    management.create_principal("event.operator")
    management.grant_capability(
        "event.operator",
        CapabilityId("plugin.admin"),
        Scope(principal_id="event.operator"),
    )
    owner_handle = real_kernel.issue_execution_handle(
        principal_id="event.operator",
        capability=CapabilityId("plugin.admin"),
        action="events.subscribe",
        scope=Scope(principal_id="event.operator"),
        channel=Channel.CORE,
        resource_id="demo.greeted",
    )
    first.dispatcher.subscribe("demo.greeted", callback, execution_handle=owner_handle)
    with pytest.raises(AuthorizationError):
        second.dispatcher.unsubscribe("demo.greeted", callback, execution_handle=owner_handle)


def test_action_binding_rejects_a_handle_for_another_action(uow_factory) -> None:
    with uow_factory() as uow:
        authorization, management = _setup(uow, uow_factory)
        management.grant_capability(PRINCIPAL, REPORT, SELF)
        handle = authorization.issue_handle(
            principal_id=PRINCIPAL,
            capability=REPORT,
            action="handle.one",
            scope=SELF,
            channel=Channel.WEB,
        )
        decision = authorization.authorize(
            handle,
            REPORT,
            SELF,
            requested_action="handle.two",  # type: ignore[call-arg]
        )
        assert not decision.allowed
