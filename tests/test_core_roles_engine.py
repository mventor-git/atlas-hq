"""Focused acceptance tests for the persistent Core Roles Engine."""

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
    CapabilityId,
    CapabilityKind,
    Channel,
    NotFoundError,
    Scope,
    ScopeError,
)

PRINCIPAL = "principal.alice"
OTHER_PRINCIPAL = "principal.bob"
REPORT_VIEW = CapabilityId("self.monthly.report.view")
ASSISTANT_USE = CapabilityId("assistant.use")
ORG = Scope(organization_id="org-a")
SELF = Scope(principal_id=PRINCIPAL)


def _authorize_with_issued_context(
    authorization: AuthorizationService,
    request: AuthorizationIntent,
):
    """Convert a test intent into a context through the Core issuer."""
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


def _check(
    authorization: AuthorizationService,
    principal_id: str,
    capability: CapabilityId,
    scope: Scope,
) -> bool:
    try:
        context = authorization.issue_handle(
            principal_id=principal_id,
            capability=capability,
            action=str(capability),
            scope=scope,
            channel=Channel.WEB,
        )
    except AuthorizationError:
        return False
    return authorization.authorize(context, capability, scope).allowed


def _authorization_for(uow: UnitOfWorkPort) -> AuthorizationService:
    """A Core evaluator wired the way production wires one: a denial-audit UoW."""
    return AuthorizationService(
        uow=uow,
        policy=PolicyService(uow=uow),
        uow_factory=uow.independent_uow_factory,
    )


def _management(
    uow: UnitOfWorkPort,
) -> tuple[AuthorizationService, AuthorizationManagementService]:
    authorization = _authorization_for(uow)
    return authorization, AuthorizationManagementService(uow, authorization=authorization)


def test_direct_grant_and_revoke_are_persistent_and_audited(
    uow_factory: Callable[[], UnitOfWorkPort],
) -> None:
    with uow_factory() as uow:
        authorization, management = _management(uow)  # type: ignore[arg-type]
        authorization.register_capability(REPORT_VIEW, CapabilityKind.VIEW)
        management.create_principal(PRINCIPAL)
        management.grant_capability(PRINCIPAL, REPORT_VIEW, SELF, actor="admin")

    with uow_factory() as uow:
        authorization, management = _management(uow)  # type: ignore[arg-type]
        assert _check(authorization, PRINCIPAL, REPORT_VIEW, SELF)
        assert management.effective_capabilities(PRINCIPAL, SELF) == frozenset({REPORT_VIEW})
        management.revoke_capability(PRINCIPAL, REPORT_VIEW, SELF, actor="admin")

    with uow_factory() as uow:
        authorization, management = _management(uow)  # type: ignore[arg-type]
        assert not _check(authorization, PRINCIPAL, REPORT_VIEW, SELF)
        assert {record.action for record in uow.audit.all()} >= {
            "authorization.capability.granted",
            "authorization.capability.revoked",
        }


def test_role_assignment_unions_with_direct_grants_without_inheritance(
    uow_factory: Callable[[], UnitOfWorkPort],
) -> None:
    direct = CapabilityId("report.view")
    bundled = CapabilityId("report.schedule")

    with uow_factory() as uow:
        authorization, management = _management(uow)  # type: ignore[arg-type]
        authorization.register_capability(direct, CapabilityKind.VIEW)
        authorization.register_capability(bundled, CapabilityKind.SCHEDULE)
        authorization.register_role("role.reporter", "Reporter", frozenset({bundled}))
        management.create_principal(PRINCIPAL)
        management.assign_role(PRINCIPAL, "role.reporter", ORG, actor="admin")
        management.grant_capability(PRINCIPAL, direct, ORG, actor="admin")

        assert management.effective_capabilities(PRINCIPAL, ORG) == frozenset({direct, bundled})
        assert _check(authorization, PRINCIPAL, direct, ORG)
        assert _check(authorization, PRINCIPAL, bundled, ORG)
        assert not _check(authorization, PRINCIPAL, CapabilityId("report.manage"), ORG)


def test_default_deny_and_self_scope_isolation(
    uow_factory: Callable[[], UnitOfWorkPort],
) -> None:
    with uow_factory() as uow:
        authorization, management = _management(uow)  # type: ignore[arg-type]
        authorization.register_capability(REPORT_VIEW, CapabilityKind.VIEW)
        management.create_principal(PRINCIPAL)
        management.create_principal(OTHER_PRINCIPAL)
        management.grant_capability(PRINCIPAL, REPORT_VIEW, SELF, actor="admin")

        assert _check(authorization, PRINCIPAL, REPORT_VIEW, SELF)
        assert not _check(authorization, OTHER_PRINCIPAL, REPORT_VIEW, SELF)
        assert not _check(authorization, PRINCIPAL, REPORT_VIEW, ORG)
        assert not _check(authorization, PRINCIPAL, CapabilityId("unknown.view"), SELF)


def test_authorization_mutation_and_audit_roll_back_together(
    uow_factory: Callable[[], UnitOfWorkPort],
) -> None:
    with pytest.raises(RuntimeError, match="abort"), uow_factory() as uow:
        authorization, management = _management(uow)  # type: ignore[arg-type]
        authorization.register_capability(REPORT_VIEW, CapabilityKind.VIEW)
        management.create_principal(PRINCIPAL)
        management.grant_capability(PRINCIPAL, REPORT_VIEW, SELF, actor="admin")
        raise RuntimeError("abort")

    with uow_factory() as uow:
        authorization, _ = _management(uow)  # type: ignore[arg-type]
        assert not _check(authorization, PRINCIPAL, REPORT_VIEW, SELF)
        assert not uow.authorization.get_principal(PRINCIPAL)
        assert not uow.audit.all()


def test_plugin_metadata_does_not_grant_and_management_is_not_in_plugin_context(
    kernel,
) -> None:
    capability = CapabilityId("plugin.metadata")
    kernel._authorization.register_capability(capability, CapabilityKind.VIEW)
    kernel._authorization.register_role(
        "role.plugin.metadata",
        "Plugin Metadata",
        frozenset({capability}),
    )

    assert not kernel._authorization.effective_permissions(PRINCIPAL, ORG).capabilities
    context = kernel.context_for("metadata.plugin")
    assert not hasattr(context, "authorization_management")
    assert not hasattr(context.authorization, "grant_capability")
    assert not hasattr(context.authorization, "revoke_capability")


def test_role_assignment_can_be_revoked_without_leaving_a_permission(
    uow_factory: Callable[[], UnitOfWorkPort],
) -> None:
    capability = CapabilityId("report.revocable")
    with uow_factory() as uow:
        authorization, management = _management(uow)  # type: ignore[arg-type]
        authorization.register_capability(capability, CapabilityKind.VIEW)
        authorization.register_role("role.revocable", "Revocable", frozenset({capability}))
        management.create_principal(PRINCIPAL)
        management.assign_role(PRINCIPAL, "role.revocable", ORG, actor="admin")
        assert _check(authorization, PRINCIPAL, capability, ORG)
        management.revoke_role(PRINCIPAL, "role.revocable", ORG, actor="admin")
        assert not _check(authorization, PRINCIPAL, capability, ORG)
        assert "authorization.role.revoked" in {record.action for record in uow.audit.all()}


def test_grant_state_reports_direct_grants_roles_and_their_sources(
    uow_factory: Callable[[], UnitOfWorkPort],
) -> None:
    """One query a management view hydrates its checkboxes from.

    A capability can arrive by more than one route, and the view has to be able
    to say which: ``direct`` is the explicit grant, ``role_ids`` is every role
    that also carries it, and the union is what the principal may actually do.
    """
    direct = CapabilityId("report.view")
    mixed = CapabilityId("report.schedule")
    unheld = CapabilityId("report.manage")

    with uow_factory() as uow:
        authorization, management = _management(uow)  # type: ignore[arg-type]
        for capability in (direct, mixed, unheld):
            authorization.register_capability(capability, CapabilityKind.VIEW)
        authorization.register_role("role.reporter", "Reporter", frozenset({mixed}))
        management.create_principal(PRINCIPAL)
        management.grant_capability(PRINCIPAL, direct, ORG, actor="admin")
        management.grant_capability(PRINCIPAL, mixed, ORG, actor="admin")
        management.assign_role(PRINCIPAL, "role.reporter", ORG, actor="admin")

        state = management.grant_state(PRINCIPAL, ORG)

    by_capability = {item.capability_id: item for item in state.capabilities}
    assert by_capability[direct].direct is True
    assert by_capability[direct].role_ids == ()
    # Granted directly *and* carried by a role: both sources are reported.
    assert by_capability[mixed].direct is True
    assert by_capability[mixed].role_ids == ("role.reporter",)
    assert by_capability[unheld].direct is False
    assert by_capability[unheld].role_ids == ()
    assigned = {item.role_id: item.assigned for item in state.roles}
    assert assigned["role.reporter"] is True
    # A role the principal does not hold is reported, not hidden: the view must
    # be able to render its checkbox too.
    assert assigned["role.manager"] is False
    assert state.effective_capability_ids == frozenset({direct, mixed})
    assert state.principal_id == PRINCIPAL
    assert state.scope == ORG


def test_grant_state_is_scope_explicit_and_never_widens(
    uow_factory: Callable[[], UnitOfWorkPort],
) -> None:
    """A self grant never answers an organization question, and vice versa."""
    capability = CapabilityId("report.scoped")
    workplace = Scope(organization_id=ORG.organization_id, workplace_id="wp-a")

    with uow_factory() as uow:
        authorization, management = _management(uow)  # type: ignore[arg-type]
        authorization.register_capability(capability, CapabilityKind.VIEW)
        authorization.register_role("role.scoped", "Scoped", frozenset({capability}))
        management.create_principal(PRINCIPAL)
        management.create_principal(OTHER_PRINCIPAL)
        management.grant_capability(PRINCIPAL, capability, SELF, actor="admin")
        management.assign_role(PRINCIPAL, "role.scoped", ORG, actor="admin")

        at_self = management.grant_state(PRINCIPAL, SELF)
        at_org = management.grant_state(PRINCIPAL, ORG)
        at_workplace = management.grant_state(PRINCIPAL, workplace)
        # Another principal's self scope is not this principal's to read.
        at_foreign_self = management.grant_state(OTHER_PRINCIPAL, SELF)

        # An unspecified scope would answer every scope at once, so it is refused.
        with pytest.raises(ScopeError):
            management.grant_state(PRINCIPAL, Scope())

    def _lookup(state) -> dict:
        return {item.capability_id: item for item in state.capabilities}

    at_self_caps = _lookup(at_self)
    at_org_caps = _lookup(at_org)
    at_workplace_caps = _lookup(at_workplace)
    at_foreign_caps = _lookup(at_foreign_self)

    assert at_self_caps[capability].direct is True
    assert at_self_caps[capability].role_ids == ()
    assert at_self.effective_capability_ids == frozenset({capability})

    # A self grant is not an organization grant: it does not widen outwards.
    assert at_org_caps[capability].direct is False
    assert at_org_caps[capability].role_ids == ("role.scoped",)
    # An organization role covers the workplace inside it, which is narrowing.
    assert at_workplace_caps[capability].role_ids == ("role.scoped",)
    assert at_workplace.effective_capability_ids == frozenset({capability})

    assert at_foreign_caps[capability].direct is False
    assert at_foreign_caps[capability].role_ids == ()
    assert at_foreign_self.effective_capability_ids == frozenset()
    assert not any(item.assigned for item in at_foreign_self.roles)


def test_grant_state_fails_closed_for_an_unknown_principal(
    uow_factory: Callable[[], UnitOfWorkPort],
) -> None:
    """An unknown principal is a refusal, not an empty box list."""
    with uow_factory() as uow:
        _authorization, management = _management(uow)  # type: ignore[arg-type]

        with pytest.raises(NotFoundError):
            management.grant_state("principal.nobody", ORG)


def test_channel_parity_uses_one_core_decision(
    uow_factory: Callable[[], UnitOfWorkPort],
) -> None:
    policy = PolicyService()
    policy.register("channel.default", date(2020, 1, 1))
    policy.register(
        "channel.web-disabled",
        date(2020, 1, 1),
        enabled=False,
        capability=REPORT_VIEW,
        action="report.disabled",
        channel=Channel.WEB,
    )
    with uow_factory() as uow:
        authorization = AuthorizationService(
            uow=uow, policy=policy, uow_factory=uow.independent_uow_factory
        )
        management = AuthorizationManagementService(uow, authorization=authorization)
        authorization.register_capability(REPORT_VIEW, CapabilityKind.VIEW)
        authorization.register_capability(ASSISTANT_USE, CapabilityKind.VIEW)
        management.create_principal(PRINCIPAL)
        management.create_identity("identity.web", Channel.WEB, "web-session", trusted=True)
        management.link_identity("identity.web", PRINCIPAL)
        management.create_identity(
            "identity.telegram.unlinked", Channel.TELEGRAM, "telegram-user", trusted=False
        )
        management.create_identity("identity.telegram.linked", Channel.TELEGRAM, "telegram-2")
        management.link_identity("identity.telegram.linked", PRINCIPAL)
        management.grant_capability(PRINCIPAL, REPORT_VIEW, SELF, actor="admin")

        assert _authorize_with_issued_context(
            authorization,
            AuthorizationIntent(
                capability=REPORT_VIEW,
                scope=SELF,
                channel=Channel.WEB,
                action="report.render",
                principal_id=PRINCIPAL,
            ),
        ).allowed
        assert _authorize_with_issued_context(
            authorization,
            AuthorizationIntent(
                capability=REPORT_VIEW,
                scope=SELF,
                channel=Channel.TELEGRAM,
                action="report.render",
                principal_id=PRINCIPAL,
                identity_id="identity.telegram.linked",
            ),
        ).allowed
        with pytest.raises(AuthorizationError):
            _authorize_with_issued_context(
                authorization,
                AuthorizationIntent(
                    capability=REPORT_VIEW,
                    scope=SELF,
                    channel=Channel.TELEGRAM,
                    action="report.render",
                    identity_id="identity.telegram.unlinked",
                ),
            )

        assert not _authorize_with_issued_context(
            authorization,
            AuthorizationIntent(
                capability=REPORT_VIEW,
                scope=SELF,
                channel=Channel.AI,
                action="report.render",
                principal_id=PRINCIPAL,
            ),
        ).allowed

        management.grant_capability(PRINCIPAL, ASSISTANT_USE, SELF, actor="admin")
        assert _authorize_with_issued_context(
            authorization,
            AuthorizationIntent(
                capability=REPORT_VIEW,
                scope=SELF,
                channel=Channel.AI,
                action="report.render",
                principal_id=PRINCIPAL,
            ),
        ).allowed
        assert not _authorize_with_issued_context(
            authorization,
            AuthorizationIntent(
                capability=REPORT_VIEW,
                scope=SELF,
                channel=Channel.WEB,
                action="report.disabled",
                principal_id=PRINCIPAL,
            ),
        ).allowed


def test_policy_and_confirmation_are_authoritative_and_audited(
    uow_factory: Callable[[], UnitOfWorkPort],
) -> None:
    policy = PolicyService()
    policy.register(
        "report.web-only",
        date(2020, 1, 1),
        condition={
            "channel": Channel.WEB.value,
            "confirmation_required": "true",
        },
        capability=REPORT_VIEW,
        action="report.render",
        channel=Channel.WEB,
    )
    with uow_factory() as uow:
        authorization = AuthorizationService(
            uow=uow, policy=policy, uow_factory=uow.independent_uow_factory
        )
        management = AuthorizationManagementService(uow, authorization=authorization)
        authorization.register_capability(REPORT_VIEW, CapabilityKind.VIEW)
        management.create_principal(PRINCIPAL)
        management.create_identity("identity.policy.telegram", Channel.TELEGRAM, "policy-user")
        management.link_identity("identity.policy.telegram", PRINCIPAL)
        management.grant_capability(PRINCIPAL, REPORT_VIEW, SELF, actor="admin")

        assert not _authorize_with_issued_context(
            authorization,
            AuthorizationIntent(
                capability=REPORT_VIEW,
                scope=SELF,
                channel=Channel.TELEGRAM,
                action="report.render",
                principal_id=PRINCIPAL,
                identity_id="identity.policy.telegram",
            ),
        ).allowed
        assert not _authorize_with_issued_context(
            authorization,
            AuthorizationIntent(
                capability=REPORT_VIEW,
                scope=SELF,
                channel=Channel.WEB,
                action="report.render",
                principal_id=PRINCIPAL,
            ),
        ).allowed
        assert not _authorize_with_issued_context(
            authorization,
            AuthorizationIntent(
                capability=REPORT_VIEW,
                scope=SELF,
                channel=Channel.WEB,
                action="report.render",
                principal_id=PRINCIPAL,
            ),
        ).allowed

        confirmation_handle = authorization.issue_handle(
            principal_id=PRINCIPAL,
            capability=REPORT_VIEW,
            action="report.render",
            scope=SELF,
            channel=Channel.WEB,
        )
        confirmation_id = management.confirm(confirmation_handle, REPORT_VIEW)
        assert _authorize_with_issued_context(
            authorization,
            AuthorizationIntent(
                capability=REPORT_VIEW,
                scope=SELF,
                channel=Channel.WEB,
                action="report.render",
                principal_id=PRINCIPAL,
                confirmation_id=confirmation_id,
            ),
        ).allowed
        records = uow.audit.all()
        assert confirmation_id
        confirmation = uow.authorization.get_confirmation(confirmation_id)
        assert confirmation is not None
        assert any(
            record.audit_id == confirmation.audit_id and record.action == "authorization.confirmed"
            for record in records
        )
