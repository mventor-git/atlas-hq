"""PostgreSQL repository for Core-owned principals and authorization state."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from atlas_sdk import CapabilityId, CapabilityKind, Scope

from ...application.repositories import AuthorizationRepositoryPort
from ...domain.role import (
    Capability,
    CapabilityGrant,
    Confirmation,
    Principal,
    PrincipalIdentity,
    Role,
    RoleAssignment,
)
from ...domain.scope import covers
from .orm import (
    CapabilityGrantORM,
    CapabilityORM,
    ConfirmationORM,
    IdentityORM,
    PrincipalORM,
    RoleAssignmentORM,
    RoleCapabilityORM,
    RoleORM,
)


def _now() -> datetime:
    return datetime.now(UTC)


def _scope(scope: Scope) -> tuple[str | None, str | None, str | None]:
    return scope.organization_id, scope.workplace_id, scope.principal_id


def _scope_from_row(row: RoleAssignmentORM | CapabilityGrantORM) -> Scope:
    return Scope(
        organization_id=row.organization_id,
        workplace_id=row.workplace_id,
        principal_id=row.principal_scope_id,
    )


def _channel(value: str) -> str:
    return str(getattr(value, "value", value))


class AuthorizationRepository(AuthorizationRepositoryPort):
    """All Core authorization tables behind one UoW-bound adapter."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_principal(self, principal_id: str) -> Principal | None:
        row = self._session.get(PrincipalORM, principal_id)
        return _to_principal(row) if row is not None else None

    def add_principal(self, principal: Principal) -> None:
        row = self._session.get(PrincipalORM, principal.principal_id)
        if row is None:
            self._session.add(
                PrincipalORM(
                    principal_id=principal.principal_id,
                    display_name=principal.display_name,
                    active=principal.active,
                    metadata_json=dict(principal.metadata),
                    created_at=principal.created_at,
                    updated_at=principal.updated_at,
                ),
            )
            return
        row.display_name = principal.display_name
        row.active = principal.active
        row.metadata_json = dict(principal.metadata)
        row.updated_at = principal.updated_at

    def list_principals(self) -> list[Principal]:
        rows = self._session.scalars(select(PrincipalORM).order_by(PrincipalORM.principal_id))
        return [_to_principal(row) for row in rows]

    def get_identity(self, identity_id: str) -> PrincipalIdentity | None:
        row = self._session.get(IdentityORM, identity_id)
        return _to_identity(row) if row is not None else None

    def find_identity(self, channel: str, external_id: str) -> PrincipalIdentity | None:
        stmt = select(IdentityORM).where(
            IdentityORM.channel == _channel(channel),
            IdentityORM.external_id == external_id,
        )
        row = self._session.scalars(stmt).first()
        return _to_identity(row) if row is not None else None

    def list_identities(self) -> list[PrincipalIdentity]:
        rows = self._session.scalars(select(IdentityORM).order_by(IdentityORM.identity_id))
        return [_to_identity(row) for row in rows]

    def add_identity(self, identity: PrincipalIdentity) -> None:
        row = self._session.get(IdentityORM, identity.identity_id)
        if row is None:
            self._session.add(
                IdentityORM(
                    identity_id=identity.identity_id,
                    principal_id=identity.principal_id,
                    channel=_channel(identity.channel),
                    external_id=identity.external_id,
                    trusted=identity.trusted,
                    active=identity.active,
                    linked_at=identity.linked_at,
                    created_at=identity.created_at,
                    updated_at=identity.updated_at,
                ),
            )
            return
        self._write_identity(row, identity)

    def update_identity(self, identity: PrincipalIdentity) -> None:
        row = self._session.get(IdentityORM, identity.identity_id)
        if row is None:
            self.add_identity(identity)
            return
        self._write_identity(row, identity)

    @staticmethod
    def _write_identity(row: IdentityORM, identity: PrincipalIdentity) -> None:
        row.principal_id = identity.principal_id
        row.channel = _channel(identity.channel)
        row.external_id = identity.external_id
        row.trusted = identity.trusted
        row.active = identity.active
        row.linked_at = identity.linked_at
        row.updated_at = identity.updated_at

    def link_identity_once(
        self,
        identity_id: str,
        principal_id: str,
    ) -> PrincipalIdentity | None:
        """Link an unlinked identity while holding its PostgreSQL row lock."""
        row = self._session.scalars(
            select(IdentityORM).where(IdentityORM.identity_id == identity_id).with_for_update()
        ).first()
        if row is None or row.principal_id is not None:
            return None
        now = _now()
        row.principal_id = principal_id
        row.trusted = True
        row.active = True
        row.linked_at = now
        row.updated_at = now
        return _to_identity(row)

    def get_capability(self, capability_id: CapabilityId) -> Capability | None:
        row = self._session.get(CapabilityORM, str(capability_id))
        return _to_capability(row) if row is not None else None

    def upsert_capability(self, capability: Capability) -> None:
        row = self._session.get(CapabilityORM, str(capability.capability_id))
        if row is None:
            self._session.add(
                CapabilityORM(
                    capability_id=str(capability.capability_id),
                    kind=capability.kind.value,
                    name=capability.name,
                    provider_id=capability.provider_id,
                    active=capability.active,
                    metadata_json=dict(capability.metadata),
                    created_at=capability.created_at,
                    updated_at=capability.updated_at,
                ),
            )
            return
        row.kind = capability.kind.value
        row.name = capability.name
        row.provider_id = capability.provider_id
        row.active = capability.active
        row.metadata_json = dict(capability.metadata)
        row.updated_at = capability.updated_at

    def list_capabilities(self, *, active_only: bool = True) -> list[Capability]:
        stmt = select(CapabilityORM).order_by(CapabilityORM.capability_id)
        if active_only:
            stmt = stmt.where(CapabilityORM.active.is_(True))
        return [_to_capability(row) for row in self._session.scalars(stmt)]

    def get_role(self, role_id: str) -> Role | None:
        row = self._session.get(RoleORM, role_id)
        return _to_role(row, self._role_capabilities(role_id)) if row is not None else None

    def upsert_role(self, role: Role) -> None:
        row = self._session.get(RoleORM, role.role_id)
        if row is None:
            row = RoleORM(
                role_id=role.role_id,
                name=role.name,
                owner_plugin_id=role.owner_plugin_id,
                active=role.active,
                metadata_json=dict(role.metadata),
                created_at=role.created_at,
                updated_at=role.updated_at,
            )
            self._session.add(row)
        else:
            row.name = role.name
            row.owner_plugin_id = role.owner_plugin_id
            row.active = role.active
            row.metadata_json = dict(role.metadata)
            row.updated_at = role.updated_at

        desired = {str(capability_id) for capability_id in role.capabilities}
        existing_links = list(
            self._session.scalars(
                select(RoleCapabilityORM).where(RoleCapabilityORM.role_id == role.role_id)
            )
        )
        for link in existing_links:
            if link.capability_id not in desired:
                self._session.delete(link)

        for capability_id in role.capabilities:
            existing = self._session.get(
                RoleCapabilityORM,
                (role.role_id, str(capability_id)),
            )
            if existing is None:
                self._session.add(
                    RoleCapabilityORM(
                        role_id=role.role_id,
                        capability_id=str(capability_id),
                    ),
                )

    def list_roles(self, *, active_only: bool = True) -> list[Role]:
        stmt = select(RoleORM).order_by(RoleORM.role_id)
        if active_only:
            stmt = stmt.where(RoleORM.active.is_(True))
        return [
            _to_role(row, self._role_capabilities(row.role_id))
            for row in self._session.scalars(stmt)
        ]

    def add_assignment(self, assignment: RoleAssignment) -> None:
        organization_id, workplace_id, principal_id = _scope(assignment.scope)
        self._session.add(
            RoleAssignmentORM(
                role_assignment_id=assignment.role_assignment_id,
                principal_id=assignment.principal_id,
                role_id=assignment.role_id,
                organization_id=organization_id,
                workplace_id=workplace_id,
                principal_scope_id=principal_id,
                active=assignment.active,
                audit_id=assignment.audit_id,
                created_at=assignment.created_at,
                updated_at=assignment.updated_at,
            ),
        )

    def revoke_assignment(
        self,
        principal_id: str,
        role_id: str,
        scope: Scope,
    ) -> list[RoleAssignment]:
        organization_id, workplace_id, scoped_principal_id = _scope(scope)
        stmt = select(RoleAssignmentORM).where(
            RoleAssignmentORM.principal_id == principal_id,
            RoleAssignmentORM.role_id == role_id,
            RoleAssignmentORM.organization_id == organization_id,
            RoleAssignmentORM.workplace_id == workplace_id,
            RoleAssignmentORM.principal_scope_id == scoped_principal_id,
            RoleAssignmentORM.active.is_(True),
        )
        rows = list(self._session.scalars(stmt))
        result = [_to_assignment(row) for row in rows]
        now = _now()
        for row in rows:
            row.active = False
            row.updated_at = now
        return result

    def assignments_for(self, principal_id: str) -> list[RoleAssignment]:
        stmt = (
            select(RoleAssignmentORM)
            .where(
                RoleAssignmentORM.principal_id == principal_id,
                RoleAssignmentORM.active.is_(True),
            )
            .order_by(RoleAssignmentORM.created_at, RoleAssignmentORM.role_assignment_id)
        )
        return [_to_assignment(row) for row in self._session.scalars(stmt)]

    def add_grant(self, grant: CapabilityGrant) -> None:
        organization_id, workplace_id, principal_id = _scope(grant.scope)
        self._session.add(
            CapabilityGrantORM(
                grant_id=grant.grant_id,
                principal_id=grant.principal_id,
                capability_id=str(grant.capability_id),
                organization_id=organization_id,
                workplace_id=workplace_id,
                principal_scope_id=principal_id,
                active=grant.active,
                audit_id=grant.audit_id,
                created_at=grant.created_at,
                updated_at=grant.updated_at,
            ),
        )

    def revoke_grant(
        self,
        principal_id: str,
        capability_id: CapabilityId,
        scope: Scope,
    ) -> list[CapabilityGrant]:
        organization_id, workplace_id, scoped_principal_id = _scope(scope)
        stmt = select(CapabilityGrantORM).where(
            CapabilityGrantORM.principal_id == principal_id,
            CapabilityGrantORM.capability_id == str(capability_id),
            CapabilityGrantORM.organization_id == organization_id,
            CapabilityGrantORM.workplace_id == workplace_id,
            CapabilityGrantORM.principal_scope_id == scoped_principal_id,
            CapabilityGrantORM.active.is_(True),
        )
        rows = list(self._session.scalars(stmt))
        result = [_to_grant(row) for row in rows]
        now = _now()
        for row in rows:
            row.active = False
            row.updated_at = now
        return result

    def grants_for(self, principal_id: str) -> list[CapabilityGrant]:
        stmt = (
            select(CapabilityGrantORM)
            .where(
                CapabilityGrantORM.principal_id == principal_id,
                CapabilityGrantORM.active.is_(True),
            )
            .order_by(CapabilityGrantORM.created_at, CapabilityGrantORM.grant_id)
        )
        return [_to_grant(row) for row in self._session.scalars(stmt)]

    def add_confirmation(self, confirmation: Confirmation) -> None:
        organization_id, workplace_id, principal_id = _scope(confirmation.scope)
        self._session.add(
            ConfirmationORM(
                confirmation_id=confirmation.confirmation_id,
                principal_id=confirmation.principal_id,
                action=confirmation.action,
                organization_id=organization_id,
                workplace_id=workplace_id,
                principal_scope_id=principal_id,
                capability_id=str(confirmation.capability_id),
                channel=_channel(confirmation.channel),
                resource_id=confirmation.resource_id,
                active=confirmation.active,
                used_at=confirmation.used_at,
                audit_id=confirmation.audit_id,
                created_at=confirmation.created_at,
            ),
        )

    def get_confirmation(self, confirmation_id: str) -> Confirmation | None:
        self._session.flush()
        row = self._session.get(ConfirmationORM, confirmation_id)
        return _to_confirmation(row) if row is not None else None

    def consume_confirmation(
        self,
        confirmation_id: str,
        *,
        principal_id: str | None = None,
        capability_id: CapabilityId | None = None,
        action: str | None = None,
        resource_id: str | None = None,
        channel: str | None = None,
        scope: Scope | None = None,
    ) -> Confirmation | None:
        """Consume under a PostgreSQL row lock, checking every binding fact."""
        self._session.flush()
        row = self._session.scalars(
            select(ConfirmationORM)
            .where(ConfirmationORM.confirmation_id == confirmation_id)
            .with_for_update()
        ).first()
        if row is None or not row.active:
            return None
        if principal_id is not None and row.principal_id != principal_id:
            return None
        if capability_id is not None and row.capability_id != str(capability_id):
            return None
        if action is not None and row.action != action:
            return None
        # Strictly bound to the target: a confirmation with no target is not a
        # wildcard, so it cannot be spent on somebody else's record.
        if resource_id is not None and row.resource_id != resource_id:
            return None
        if channel is not None and row.channel and row.channel != _channel(channel):
            return None
        if scope is not None and not covers(_scope_from_confirmation(row), scope):
            return None
        row.active = False
        row.used_at = _now()
        return _to_confirmation(row)

    def _role_capabilities(self, role_id: str) -> dict[CapabilityId, CapabilityKind]:
        stmt = select(RoleCapabilityORM).where(RoleCapabilityORM.role_id == role_id)
        result: dict[CapabilityId, CapabilityKind] = {}
        for link in self._session.scalars(stmt):
            capability = self.get_capability(CapabilityId(link.capability_id))
            if capability is not None and capability.active:
                result[capability.capability_id] = capability.kind
        return result


def _to_principal(row: PrincipalORM) -> Principal:
    return Principal(
        principal_id=row.principal_id,
        display_name=row.display_name,
        active=row.active,
        metadata=dict(row.metadata_json or {}),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _scope_from_confirmation(row: ConfirmationORM) -> Scope:
    return Scope(
        organization_id=row.organization_id,
        workplace_id=row.workplace_id,
        principal_id=row.principal_scope_id,
    )


def _to_confirmation(row: ConfirmationORM) -> Confirmation:
    return Confirmation(
        confirmation_id=row.confirmation_id,
        principal_id=row.principal_id,
        action=row.action,
        scope=_scope_from_confirmation(row),
        capability_id=CapabilityId(row.capability_id),
        channel=row.channel,
        resource_id=row.resource_id,
        active=row.active,
        used_at=row.used_at,
        audit_id=row.audit_id,
        created_at=row.created_at,
    )


def _to_identity(row: IdentityORM) -> PrincipalIdentity:
    return PrincipalIdentity(
        identity_id=row.identity_id,
        channel=row.channel,
        external_id=row.external_id,
        principal_id=row.principal_id,
        trusted=row.trusted,
        active=row.active,
        linked_at=row.linked_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _to_capability(row: CapabilityORM) -> Capability:
    return Capability(
        capability_id=CapabilityId(row.capability_id),
        kind=CapabilityKind(row.kind),
        name=row.name,
        active=row.active,
        metadata=dict(row.metadata_json or {}),
        provider_id=row.provider_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _to_role(row: RoleORM, capability_kinds: dict[CapabilityId, CapabilityKind]) -> Role:
    return Role(
        role_id=row.role_id,
        name=row.name,
        capabilities=frozenset(capability_kinds),
        capability_kinds=capability_kinds,
        active=row.active,
        metadata=dict(row.metadata_json or {}),
        owner_plugin_id=row.owner_plugin_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _to_assignment(row: RoleAssignmentORM) -> RoleAssignment:
    return RoleAssignment(
        role_assignment_id=row.role_assignment_id,
        subject_id=row.principal_id,
        role_id=row.role_id,
        scope=_scope_from_row(row),
        active=row.active,
        audit_id=row.audit_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _to_grant(row: CapabilityGrantORM) -> CapabilityGrant:
    return CapabilityGrant(
        grant_id=row.grant_id,
        principal_id=row.principal_id,
        capability_id=CapabilityId(row.capability_id),
        scope=_scope_from_row(row),
        active=row.active,
        audit_id=row.audit_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


__all__ = ["AuthorizationRepository"]
