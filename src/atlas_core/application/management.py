"""Core-only management operations for persistent authorization state."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime
from typing import Protocol

from atlas_sdk import (
    AuthorizationError,
    CapabilityId,
    CapabilityKind,
    Channel,
    ExecutionHandle,
    NotFoundError,
    Scope,
    ScopeError,
)

from ..domain.audit import AuditRecord
from ..domain.role import (
    Capability,
    CapabilityGrant,
    Confirmation,
    EffectivePermissions,
    GrantState,
    Principal,
    PrincipalIdentity,
    Role,
    RoleAssignment,
)
from .authorization import AuthorizationService
from .unit_of_work import UnitOfWorkPort


class AuthorizationManagementPort(Protocol):
    """Core-only administrative seam; never placed on ``PluginContext``."""

    def list_capabilities(self, *, active_only: bool = True) -> list[Capability]: ...
    def register_policy(
        self,
        policy_id: str,
        effective_from,
        effective_to=None,
        enabled: bool = True,
        condition: Mapping[str, str] | None = None,
        *,
        capability: str | None = None,
        action: str | None = None,
        channel: str | Channel | None = None,
    ) -> None: ...
    def set_principal_active(
        self, principal_id: str, active: bool, *, actor: str = ...
    ) -> Principal: ...
    def set_principal_metadata(
        self, principal_id: str, key: str, value: str, *, actor: str = ...
    ) -> Principal: ...
    def grant_capability(
        self, principal_id: str, capability: CapabilityId, scope: Scope, *, actor: str = ...
    ) -> CapabilityGrant: ...
    def revoke_capability(
        self, principal_id: str, capability: CapabilityId, scope: Scope, *, actor: str = ...
    ) -> None: ...
    def assign_role(
        self, principal_id: str, role_id: str, scope: Scope, *, actor: str = ...
    ) -> RoleAssignment: ...
    def revoke_role(
        self, principal_id: str, role_id: str, scope: Scope, *, actor: str = ...
    ) -> None: ...
    def effective_permissions(self, principal_id: str, scope: Scope) -> EffectivePermissions: ...
    def grant_state(self, principal_id: str, scope: Scope) -> GrantState: ...
    def confirm(self, handle: ExecutionHandle, capability: CapabilityId) -> str: ...


class AuthorizationManagementService(AuthorizationManagementPort):
    """The administrative boundary; plugins never receive this object."""

    def __init__(
        self,
        uow: UnitOfWorkPort | None = None,
        *,
        authorization: AuthorizationService | None = None,
        uow_factory=None,
    ) -> None:
        self._uow_factory = uow_factory
        self._uow = uow if uow is not None else (uow_factory() if uow_factory is not None else None)
        if self._uow is None and authorization is None:
            msg = "authorization management requires a PostgreSQL UoW"
            raise RuntimeError(msg)
        if self._uow is not None and (authorization is None or authorization._uow is None):
            if authorization is not None and authorization._policy is not None:
                bound_policy = authorization._policy.bind_uow(self._uow)
                self._authorization = authorization.for_uow(self._uow, policy=bound_policy)
            else:
                self._authorization = AuthorizationService(
                    uow=self._uow,
                    uow_factory=self._uow.independent_uow_factory,
                )
        else:
            self._authorization = authorization or AuthorizationService()

    def register_policy(
        self,
        policy_id: str,
        effective_from,
        effective_to=None,
        enabled: bool = True,
        condition: Mapping[str, str] | None = None,
        *,
        capability: str | None = None,
        action: str | None = None,
        channel: str | Channel | None = None,
    ) -> None:
        """Register policy through Core management only."""
        if self._authorization._uow is None:
            msg = "policy registration requires a persistent Core UoW"
            raise RuntimeError(msg)
        if self._authorization._policy is None:
            msg = "Core policy service is unavailable"
            raise RuntimeError(msg)
        policy = self._authorization._policy
        self._authorization._run_mutation(
            lambda: policy.register(
                policy_id,
                effective_from,
                effective_to,
                enabled,
                condition,
                capability=capability,
                action=action,
                channel=channel,
            )
        )

    def _read(self, operation):
        try:
            return operation()
        finally:
            self._authorization._finish_read()

    def list_capabilities(self, *, active_only: bool = True) -> list[Capability]:
        return self._read(
            lambda: self._authorization._repository.list_capabilities(active_only=active_only)
        )

    def list_capability_ids(self, *, active_only: bool = True) -> list[CapabilityId]:
        return [
            capability.capability_id
            for capability in self.list_capabilities(active_only=active_only)
        ]

    def list_roles(self, *, active_only: bool = True) -> list[Role]:
        return self._read(
            lambda: self._authorization._repository.list_roles(active_only=active_only)
        )

    def list_principals(self) -> list[Principal]:
        return self._read(lambda: self._authorization._repository.list_principals())

    def get_principal(self, principal_id: str) -> Principal | None:
        return self._read(lambda: self._authorization._repository.get_principal(principal_id))

    def register_capability(
        self,
        capability: CapabilityId,
        kind: CapabilityKind = CapabilityKind.VIEW,
        name: str = "",
        metadata: Mapping[str, object] | None = None,
        *,
        provider_id: str | None = None,
    ) -> None:
        self._authorization.register_capability(
            capability,
            kind,
            name,
            metadata,
            provider_id=provider_id or "core",
        )

    def register_role(
        self,
        role_id: str,
        name: str,
        capabilities: frozenset[CapabilityId],
        capability_kinds: Mapping[CapabilityId, CapabilityKind] | None = None,
    ) -> None:
        self._authorization.register_role(role_id, name, capabilities, capability_kinds)

    def create_principal(
        self,
        principal_id: str,
        display_name: str = "",
        metadata: Mapping[str, object] | None = None,
        *,
        actor: str = "core",
    ) -> Principal:
        if not principal_id.strip():
            raise ValueError("principal_id is required")
        repository = self._authorization._repository
        existing = repository.get_principal(principal_id)
        if existing is not None:
            self._authorization._finish_read()
            return existing
        principal = Principal(
            principal_id=principal_id,
            display_name=display_name,
            metadata=dict(metadata or {}),
        )
        self._authorization._run_mutation(
            lambda: self._mutate_create_principal(principal, actor),
        )
        return principal

    def _mutate_create_principal(self, principal: Principal, actor: str) -> None:
        self._authorization._repository.add_principal(principal)
        self._audit(
            action="authorization.principal.created",
            actor=actor,
            scope=Scope(principal_id=principal.principal_id),
            details={"principal_id": principal.principal_id},
        )

    def set_principal_active(
        self,
        principal_id: str,
        active: bool,
        *,
        actor: str = "core",
    ) -> Principal:
        repository = self._authorization._repository
        principal = repository.get_principal(principal_id)
        if principal is None:
            self._authorization._finish_read()
            raise NotFoundError(
                f"principal {principal_id!r} is not registered",
                kind="principal",
                key=principal_id,
            )
        updated = replace(principal, active=active, updated_at=datetime.now(UTC))
        self._authorization._run_mutation(
            lambda: self._mutate_principal_active(updated, actor),
        )
        return updated

    def _mutate_principal_active(self, principal: Principal, actor: str) -> None:
        self._authorization._repository.add_principal(principal)
        self._audit(
            action="authorization.principal.active_changed",
            actor=actor,
            scope=Scope(principal_id=principal.principal_id),
            details={"principal_id": principal.principal_id, "active": principal.active},
        )

    def deactivate_principal(self, principal_id: str, *, actor: str = "core") -> Principal:
        return self.set_principal_active(principal_id, False, actor=actor)

    def set_principal_metadata(
        self,
        principal_id: str,
        key: str,
        value: str,
        *,
        actor: str = "core",
    ) -> Principal:
        """Write one principal-owned metadata entry, and nothing else.

        This is the only Core path for a principal's own stored preferences (the
        web console's light/dark theme, for example). It is deliberately *not* a
        second authorization seam: effective permissions are computed from
        grants, assignments, scope, and policy alone (contract §38.3), so nothing
        written here can widen what a principal may do. The write is audited
        because principal state changed, and it never silently replaces another
        key the principal already had.
        """
        if not key.strip() or not key.replace("_", "").replace(".", "").isalnum():
            msg = "a principal metadata key must be a simple identifier"
            raise ValueError(msg)
        repository = self._authorization._repository
        principal = repository.get_principal(principal_id)
        if principal is None:
            self._authorization._finish_read()
            raise NotFoundError(
                f"principal {principal_id!r} is not registered",
                kind="principal",
                key=principal_id,
            )
        updated = replace(
            principal,
            metadata={**principal.metadata, key: value},
            updated_at=datetime.now(UTC),
        )
        self._authorization._run_mutation(
            lambda: self._mutate_principal_metadata(updated, key, value, actor),
        )
        return updated

    def _mutate_principal_metadata(
        self,
        principal: Principal,
        key: str,
        value: str,
        actor: str,
    ) -> None:
        self._authorization._repository.add_principal(principal)
        self._audit(
            action="authorization.principal.metadata_updated",
            actor=actor,
            scope=Scope(principal_id=principal.principal_id),
            details={"principal_id": principal.principal_id, "key": key, "value": value},
        )

    def create_identity(
        self,
        identity_id: str,
        channel: str | Channel,
        external_id: str,
        *,
        trusted: bool = False,
        principal_id: str | None = None,
        actor: str = "core",
    ) -> PrincipalIdentity:
        try:
            selected_channel = Channel(channel)
        except (TypeError, ValueError) as exc:
            msg = f"unknown identity channel {channel!r}"
            raise ValueError(msg) from exc
        channel_value = selected_channel.value
        external = selected_channel not in {Channel.WEB, Channel.CORE}
        if external and trusted:
            msg = "external identities cannot be created trusted"
            raise ValueError(msg)
        if external and principal_id is not None:
            msg = "external identities must be explicitly linked by Core"
            raise ValueError(msg)
        repository = self._authorization._repository
        existing = repository.get_identity(identity_id)
        if existing is None:
            existing = repository.find_identity(channel_value, external_id)
        if existing is not None:
            self._authorization._finish_read()
            if existing.identity_id != identity_id:
                raise ValueError("channel identity is already registered")
            return existing
        if principal_id is not None:
            principal = repository.get_principal(principal_id)
            if principal is None or not principal.active:
                self._authorization._finish_read()
                raise NotFoundError(
                    f"principal {principal_id!r} is not active",
                    kind="principal",
                    key=principal_id,
                )
        identity = PrincipalIdentity(
            identity_id=identity_id,
            channel=channel_value,
            external_id=external_id,
            principal_id=principal_id,
            trusted=trusted if not external else False,
            active=not external,
        )
        self._authorization._run_mutation(
            lambda: self._mutate_create_identity(identity, actor),
        )
        return identity

    def _mutate_create_identity(self, identity: PrincipalIdentity, actor: str) -> None:
        self._authorization._repository.add_identity(identity)
        self._audit(
            action="authorization.identity.created",
            actor=actor,
            scope=Scope(principal_id=identity.principal_id) if identity.principal_id else Scope(),
            details={"identity_id": identity.identity_id, "channel": identity.channel},
        )
        if identity.principal_id is not None:
            self._audit(
                action="authorization.identity.linked",
                actor=actor,
                scope=Scope(principal_id=identity.principal_id),
                details={
                    "identity_id": identity.identity_id,
                    "principal_id": identity.principal_id,
                },
            )

    def link_identity(
        self,
        identity_id: str,
        principal_id: str,
        *,
        actor: str = "core",
    ) -> PrincipalIdentity:
        def mutate() -> PrincipalIdentity:
            repository = self._authorization._repository
            principal = repository.get_principal(principal_id)
            if principal is None or not principal.active:
                raise NotFoundError(
                    f"principal {principal_id!r} is not active",
                    kind="principal",
                    key=principal_id,
                )
            linked = repository.link_identity_once(identity_id, principal_id)
            if linked is None:
                raise NotFoundError(
                    f"identity {identity_id!r} is missing or already linked",
                    kind="identity",
                    key=identity_id,
                )
            self._audit(
                action="authorization.identity.linked",
                actor=actor,
                scope=Scope(principal_id=linked.principal_id),
                details={
                    "identity_id": linked.identity_id,
                    "principal_id": linked.principal_id,
                },
            )
            return linked

        return self._authorization._run_mutation(mutate)

    def list_identities(self) -> list[PrincipalIdentity]:
        return self._read(lambda: self._authorization._repository.list_identities())

    def resolve_identity(self, identity_id: str) -> PrincipalIdentity | None:
        return self._read(lambda: self._authorization._repository.get_identity(identity_id))

    def grant_capability(
        self,
        principal_id: str,
        capability: CapabilityId,
        scope: Scope,
        *,
        actor: str = "core",
    ) -> CapabilityGrant:
        if scope.is_empty:
            raise ScopeError("a capability grant needs a non-empty scope")
        repository = self._authorization._repository
        principal = repository.get_principal(principal_id)
        if principal is None or not principal.active:
            self._authorization._finish_read()
            raise NotFoundError(
                f"principal {principal_id!r} is not active",
                kind="principal",
                key=principal_id,
            )
        definition = repository.get_capability(capability)
        if definition is None or not definition.active:
            self._authorization._finish_read()
            raise NotFoundError(
                f"capability {capability!r} is not registered",
                kind="capability",
                key=str(capability),
            )
        for existing in repository.grants_for(principal_id):
            if existing.capability_id == capability and existing.scope == scope:
                self._authorization._finish_read()
                return existing
        grant = CapabilityGrant(
            principal_id=principal_id,
            capability_id=capability,
            scope=scope,
        )
        self._authorization._run_mutation(
            lambda: self._mutate_grant(grant, actor),
        )
        return grant

    def _mutate_grant(self, grant: CapabilityGrant, actor: str) -> None:
        audit_id = self._audit(
            action="authorization.capability.granted",
            actor=actor,
            scope=grant.scope,
            details={
                "principal_id": grant.principal_id,
                "capability_id": str(grant.capability_id),
            },
        )
        self._authorization._repository.add_grant(
            CapabilityGrant(
                grant_id=grant.grant_id,
                principal_id=grant.principal_id,
                capability_id=grant.capability_id,
                scope=grant.scope,
                audit_id=audit_id,
                created_at=grant.created_at,
            ),
        )

    def revoke_capability(
        self,
        principal_id: str,
        capability: CapabilityId,
        scope: Scope,
        *,
        actor: str = "core",
    ) -> None:
        self._authorization._run_mutation(
            lambda: self._mutate_revoke_capability(principal_id, capability, scope, actor),
        )

    def _mutate_revoke_capability(
        self,
        principal_id: str,
        capability: CapabilityId,
        scope: Scope,
        actor: str,
    ) -> None:
        removed = self._authorization._repository.revoke_grant(principal_id, capability, scope)
        if removed:
            self._audit(
                action="authorization.capability.revoked",
                actor=actor,
                scope=scope,
                details={
                    "principal_id": principal_id,
                    "capability_id": str(capability),
                    "grant_ids": [grant.grant_id for grant in removed],
                },
            )

    def assign_role(
        self,
        principal_id: str,
        role_id: str,
        scope: Scope,
        *,
        actor: str = "core",
    ) -> RoleAssignment:
        if scope.is_empty:
            raise ScopeError("a role assignment needs a non-empty scope")
        repository = self._authorization._repository
        principal = repository.get_principal(principal_id)
        if principal is None or not principal.active:
            self._authorization._finish_read()
            raise NotFoundError(
                f"principal {principal_id!r} is not active",
                kind="principal",
                key=principal_id,
            )
        role = (
            repository.get_role(role_id)
            if self._authorization._uow is not None
            else self._authorization.roles.get(role_id)
        )
        if role is None or not role.active:
            self._authorization._finish_read()
            raise NotFoundError(f"unknown role {role_id!r}", kind="role", key=role_id)
        for existing in repository.assignments_for(principal_id):
            if existing.role_id == role_id and existing.scope == scope:
                self._authorization._finish_read()
                return existing
        assignment = RoleAssignment(subject_id=principal_id, role_id=role_id, scope=scope)
        self._authorization._run_mutation(lambda: self._mutate_assign(assignment, actor))
        return assignment

    def _mutate_assign(self, assignment: RoleAssignment, actor: str) -> None:
        audit_id = self._audit(
            action="authorization.role.assigned",
            actor=actor,
            scope=assignment.scope,
            details={
                "principal_id": assignment.principal_id,
                "role_id": assignment.role_id,
            },
        )
        self._authorization._repository.add_assignment(
            RoleAssignment(
                role_assignment_id=assignment.role_assignment_id,
                subject_id=assignment.subject_id,
                role_id=assignment.role_id,
                scope=assignment.scope,
                audit_id=audit_id,
                created_at=assignment.created_at,
            ),
        )

    def revoke_role(
        self,
        principal_id: str,
        role_id: str,
        scope: Scope,
        *,
        actor: str = "core",
    ) -> None:
        self._authorization._run_mutation(
            lambda: self._mutate_revoke_role(principal_id, role_id, scope, actor),
        )

    def _mutate_revoke_role(
        self,
        principal_id: str,
        role_id: str,
        scope: Scope,
        actor: str,
    ) -> None:
        removed = self._authorization._repository.revoke_assignment(principal_id, role_id, scope)
        if removed:
            self._audit(
                action="authorization.role.revoked",
                actor=actor,
                scope=scope,
                details={
                    "principal_id": principal_id,
                    "role_id": role_id,
                    "assignment_ids": [assignment.role_assignment_id for assignment in removed],
                },
            )

    def grant_user_capability(
        self,
        principal_id: str,
        capability: CapabilityId,
        scope: Scope,
        *,
        actor: str = "core",
    ) -> CapabilityGrant:
        return self.grant_capability(principal_id, capability, scope, actor=actor)

    def revoke_user_capability(
        self,
        principal_id: str,
        capability: CapabilityId,
        scope: Scope,
        *,
        actor: str = "core",
    ) -> None:
        self.revoke_capability(principal_id, capability, scope, actor=actor)

    def assign_user_role(
        self,
        principal_id: str,
        role_id: str,
        scope: Scope,
        *,
        actor: str = "core",
    ) -> RoleAssignment:
        return self.assign_role(principal_id, role_id, scope, actor=actor)

    def revoke_user_role(
        self,
        principal_id: str,
        role_id: str,
        scope: Scope,
        *,
        actor: str = "core",
    ) -> None:
        self.revoke_role(principal_id, role_id, scope, actor=actor)

    def effective_capabilities(self, principal_id: str, scope: Scope) -> frozenset[CapabilityId]:
        return self._authorization.effective_permissions(principal_id, scope).capabilities

    def effective_permissions(self, principal_id: str, scope: Scope) -> EffectivePermissions:
        return self._authorization.effective_permissions(principal_id, scope)

    def compute_effective_permissions(
        self, principal_id: str, scope: Scope
    ) -> EffectivePermissions:
        return self.effective_permissions(principal_id, scope)

    def grant_state(self, principal_id: str, scope: Scope) -> GrantState:
        """Every capability and role's state for one principal in one scope.

        A read the management view hydrates from. It delegates to the one Core
        evaluator rather than re-deriving anything, so the view, the CLI, and
        the authorization decision can never disagree about what is granted.
        """
        return self._authorization.grant_state(principal_id, scope)

    def confirm(self, handle: ExecutionHandle, capability: CapabilityId) -> str:
        """Create a confirmation only from an authorized Core execution handle."""
        if not isinstance(handle, ExecutionHandle):
            raise TypeError("confirm requires an ExecutionHandle")
        facts = self._authorization.resolve_handle(handle)
        decision = self._authorization.authorize_confirmation_request(
            handle, capability, facts.scope
        )
        if not decision.allowed:
            raise AuthorizationError(f"confirmation request denied: {decision.code}")
        confirmation = Confirmation(
            principal_id=facts.principal_id,
            action=facts.action,
            scope=facts.scope,
            capability_id=capability,
            channel=facts.channel.value,
            resource_id=facts.resource_id,
        )
        self._authorization._run_mutation(
            lambda: self._mutate_confirmation(confirmation, facts.principal_id),
        )
        return confirmation.confirmation_id

    def confirm_handle(self, handle: ExecutionHandle, capability: CapabilityId) -> str:
        """Compatibility spelling of the handle-bound confirmation API."""
        return self.confirm(handle, capability)

    def _mutate_confirmation(self, confirmation: Confirmation, actor: str) -> None:
        audit_id = self._audit(
            action="authorization.confirmed",
            actor=actor,
            scope=confirmation.scope,
            details={
                "confirmation_id": confirmation.confirmation_id,
                "principal_id": confirmation.principal_id,
                "capability_id": str(confirmation.capability_id),
                "action": confirmation.action,
                "channel": confirmation.channel,
                "resource_id": confirmation.resource_id,
            },
        )
        self._authorization._repository.add_confirmation(
            replace(confirmation, audit_id=audit_id),
        )

    def _audit(
        self,
        *,
        action: str,
        actor: str,
        scope: Scope,
        details: Mapping[str, object],
    ) -> str:
        if self._authorization._uow is None:
            return ""
        record = AuditRecord(
            actor=actor,
            action=action,
            organization_id=scope.organization_id,
            workplace_id=scope.workplace_id,
            principal_id=scope.principal_id,
            details=dict(details),
        )
        self._authorization._uow.audit.append(record)
        return record.audit_id


__all__ = [
    "AuthorizationManagementPort",
    "AuthorizationManagementService",
]
