"""Red/green review tests for the repaired Core Roles Engine boundary."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

import pytest
from tests.conftest import AuthorizationIntent

from atlas_core.application.authorization import AuthorizationService
from atlas_core.application.management import AuthorizationManagementService
from atlas_core.application.policy import PolicyService
from atlas_core.application.unit_of_work import UnitOfWorkPort
from atlas_sdk import (
    AuthorizationError,
    AuthorizationPort,
    CapabilityId,
    CapabilityKind,
    Channel,
    PluginRegistrationError,
    Scope,
    WorkplaceId,
)

PRINCIPAL = "principal.review"
CAPABILITY = CapabilityId("review.export")


def _authorize_with_issued_context(
    authorization: AuthorizationService,
    request: AuthorizationIntent,
):
    context = authorization.issue_handle(
        principal_id=request.principal_id or "",
        capability=request.capability,
        action=request.action,
        scope=request.scope,
        channel=request.channel,
        resource_id=request.resource_id,
        identity_id=request.identity_id,
    )
    return authorization.authorize(
        context,
        request.capability,
        request.scope,
        confirmation_id=request.confirmation_id,
    )


def _services(
    uow: UnitOfWorkPort,
    policy: PolicyService | None = None,
) -> tuple[AuthorizationService, AuthorizationManagementService]:
    authorization = AuthorizationService(
        uow=uow, policy=policy, uow_factory=uow.independent_uow_factory
    )
    return authorization, AuthorizationManagementService(uow, authorization=authorization)


def test_plugin_authorization_port_has_no_grant_mutation(kernel) -> None:
    assert not hasattr(AuthorizationPort, "grant")
    assert not hasattr(kernel.context_for("review.plugin").authorization, "grant")


def test_plugin_cannot_overwrite_another_plugins_role(
    uow_factory: Callable[[], UnitOfWorkPort],
) -> None:
    with uow_factory() as uow:
        authorization, _ = _services(uow)
        other_capability = CapabilityId("review.export.other")
        authorization.register_capability(CAPABILITY, CapabilityKind.VIEW, provider_id="plugin.a")
        authorization.register_capability(
            other_capability,
            CapabilityKind.VIEW,
            provider_id="plugin.b",
        )
        first = authorization.for_uow(
            uow,
            plugin_id="plugin.a",
            allowed_capabilities=frozenset({CAPABILITY}),
        )
        second = authorization.for_uow(
            uow,
            plugin_id="plugin.b",
            allowed_capabilities=frozenset({other_capability}),
        )
        first.register_role("role.review", "Review", frozenset({CAPABILITY}))

        with pytest.raises(PluginRegistrationError):
            second.register_role("role.review", "Foreign", frozenset({other_capability}))


def test_same_owner_cannot_widen_an_immutable_role(
    uow_factory: Callable[[], UnitOfWorkPort],
) -> None:
    second_capability = CapabilityId("review.export.second")
    with uow_factory() as uow:
        authorization, _ = _services(uow)
        authorization.register_capability(CAPABILITY, CapabilityKind.VIEW, provider_id="plugin.a")
        authorization.register_capability(
            second_capability,
            CapabilityKind.VIEW,
            provider_id="plugin.a",
        )
        plugin = authorization.for_uow(
            uow,
            plugin_id="plugin.a",
            allowed_capabilities=frozenset({CAPABILITY, second_capability}),
        )
        plugin.register_role("role.review", "Review", frozenset({CAPABILITY}))

        with pytest.raises(PluginRegistrationError):
            plugin.register_role(
                "role.review",
                "Review",
                frozenset({CAPABILITY, second_capability}),
            )


def test_new_decision_defaults_deny_and_requires_explicit_conditions(
    uow_factory: Callable[[], UnitOfWorkPort],
) -> None:
    policy = PolicyService()
    policy.register("review.default", date.min)
    with uow_factory() as uow:
        authorization, management = _services(uow, policy)
        authorization.register_capability(CAPABILITY, CapabilityKind.VIEW)
        management.create_principal(PRINCIPAL)
        management.grant_capability(PRINCIPAL, CAPABILITY, Scope(principal_id=PRINCIPAL))

        with pytest.raises(AuthorizationError):
            _authorize_with_issued_context(
                authorization,
                AuthorizationIntent(
                    capability=CAPABILITY,
                    scope=Scope(principal_id=PRINCIPAL),
                    channel=Channel.WEB,
                    action="",
                    principal_id=PRINCIPAL,
                ),
            )

        decision = _authorize_with_issued_context(
            authorization,
            AuthorizationIntent(
                capability=CAPABILITY,
                scope=Scope(principal_id=PRINCIPAL),
                channel=Channel.WEB,
                action="review.export",
                principal_id=PRINCIPAL,
            ),
        )
        assert decision.allowed
        assert decision.audit_id
        assert any(
            record.audit_id == decision.audit_id and record.action == "authorization.decision"
            for record in uow.audit.all()
        )


def test_forged_channel_and_policy_inputs_are_not_accepted(
    uow_factory: Callable[[], UnitOfWorkPort],
) -> None:
    policy = PolicyService()
    policy.register(
        "review.web",
        date.min,
        condition={"channel": Channel.WEB.value},
        capability=CAPABILITY,
        action="review.export",
        channel=Channel.WEB,
    )
    with uow_factory() as uow:
        authorization, management = _services(uow, policy)
        authorization.register_capability(CAPABILITY, CapabilityKind.VIEW)
        management.create_principal(PRINCIPAL)
        management.grant_capability(PRINCIPAL, CAPABILITY, Scope(principal_id=PRINCIPAL))

        web = _authorize_with_issued_context(
            authorization,
            AuthorizationIntent(
                capability=CAPABILITY,
                scope=Scope(principal_id=PRINCIPAL),
                channel=Channel.WEB,
                action="review.export",
                principal_id=PRINCIPAL,
            ),
        )
        web_context = authorization.issue_handle(
            principal_id=PRINCIPAL,
            capability=CAPABILITY,
            action="review.export",
            scope=Scope(principal_id=PRINCIPAL),
            channel=Channel.WEB,
        )
        assert web.allowed
        with pytest.raises(TypeError):
            authorization.authorize(  # type: ignore[call-arg]
                web_context,
                CAPABILITY,
                Scope(principal_id=PRINCIPAL),
                channel=Channel.TELEGRAM,  # type: ignore[call-arg]
            )


def test_plugin_policy_port_is_read_only(kernel) -> None:
    context = kernel.context_for("policy.review")
    assert not hasattr(context.policy, "register")
    assert hasattr(context.policy, "evaluate")


def test_management_without_a_uow_fails_closed() -> None:
    with pytest.raises(RuntimeError, match="PostgreSQL"):
        AuthorizationManagementService()


def test_external_identity_cannot_be_created_trusted_and_link_activates_it(
    uow_factory: Callable[[], UnitOfWorkPort],
) -> None:
    with uow_factory() as uow:
        authorization, management = _services(uow)
        management.create_principal(PRINCIPAL)

        with pytest.raises(ValueError, match="trusted"):
            management.create_identity(
                "identity.review.telegram",
                Channel.TELEGRAM,
                "telegram-review",
                trusted=True,
            )
        identity = management.create_identity(
            "identity.review.telegram",
            Channel.TELEGRAM,
            "telegram-review",
        )
        assert not identity.trusted
        assert not identity.active
        linked = management.link_identity(identity.identity_id, PRINCIPAL)
        assert linked.trusted
        assert linked.active


def test_confirmation_is_a_typed_core_record(
    uow_factory: Callable[[], UnitOfWorkPort],
) -> None:
    with uow_factory() as uow:
        authorization, management = _services(uow, PolicyService(uow))
        management.create_principal(PRINCIPAL)
        authorization.register_capability(CAPABILITY, CapabilityKind.VIEW)
        management.grant_capability(PRINCIPAL, CAPABILITY, Scope(principal_id=PRINCIPAL))
        handle = authorization.issue_handle(
            principal_id=PRINCIPAL,
            capability=CAPABILITY,
            action="review.export",
            scope=Scope(principal_id=PRINCIPAL),
            channel=Channel.WEB,
        )
        confirmation_id = management.confirm(handle, CAPABILITY)
        confirmation = uow.authorization.get_confirmation(confirmation_id)
        assert confirmation is not None
        assert confirmation.principal_id == PRINCIPAL
        assert confirmation.action == "review.export"


def test_capability_kind_and_provider_overwrite_are_validated(
    uow_factory: Callable[[], UnitOfWorkPort],
) -> None:
    with uow_factory() as uow:
        authorization, _ = _services(uow)
        authorization.register_capability(CAPABILITY, CapabilityKind.VIEW, provider_id="plugin.a")
        with pytest.raises(PluginRegistrationError):
            authorization.register_capability(
                CAPABILITY,
                CapabilityKind.VIEW,
                provider_id="plugin.b",
            )
        with pytest.raises(ValueError, match="kind"):
            authorization.register_capability(
                CapabilityId("review.invalid"),
                "not-a-kind",  # type: ignore[arg-type]
                provider_id="plugin.a",
            )


def test_workplace_id_public_compatibility_export() -> None:
    value = WorkplaceId("wp-public")
    assert value == "wp-public"
