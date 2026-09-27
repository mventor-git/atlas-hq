"""Core authorization over persistent roles, grants, policies, and handles."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import replace
from datetime import UTC, datetime
from threading import RLock
from types import MappingProxyType
from typing import Any

from atlas_sdk import (
    AuthorizationDecision,
    AuthorizationError,
    CapabilityId,
    CapabilityKind,
    Channel,
    ExecutionHandle,
    NotFoundError,
    PluginRegistrationError,
    Scope,
    ScopeError,
)
from atlas_sdk.context import AuthorizationPort

from ..domain.audit import AuditRecord
from ..domain.execution import ExecutionFacts
from ..domain.role import (
    ASSISTANT_USE,
    AUTHORIZATION_MANAGE,
    CORE_CAPABILITY_KINDS,
    DEFAULT_ROLE_CATALOG,
    Capability,
    CapabilityGrant,
    CapabilityGrantState,
    Confirmation,
    EffectivePermissions,
    GrantState,
    Principal,
    PrincipalIdentity,
    Role,
    RoleAssignment,
    RoleAssignmentState,
)
from ..domain.scope import covers
from .execution import (
    ExecutionHandleIssuer,
    ExecutionHandleResolver,
    ExecutionHandleStore,
)
from .policy import PolicyService
from .repositories import AuthorizationRepositoryPort
from .unit_of_work import UnitOfWorkPort

EMPTY_CAPABILITY = CapabilityId("")


class InMemoryAuthorizationRepository(AuthorizationRepositoryPort):
    """Small adapter for non-authorizing registry/unit construction only."""

    def __init__(self) -> None:
        self.principals: dict[str, Principal] = {}
        self.identities: dict[str, PrincipalIdentity] = {}
        self.capabilities: dict[CapabilityId, Capability] = {}
        self.roles: dict[str, Role] = {}
        self.assignments: list[RoleAssignment] = []
        self.grants: list[CapabilityGrant] = []
        self.confirmations: dict[str, Confirmation] = {}
        self._lock = RLock()

    def get_principal(self, principal_id: str) -> Principal | None:
        return self.principals.get(principal_id)

    def add_principal(self, principal: Principal) -> None:
        self.principals[principal.principal_id] = principal

    def list_principals(self) -> list[Principal]:
        return list(self.principals.values())

    def get_identity(self, identity_id: str) -> PrincipalIdentity | None:
        return self.identities.get(identity_id)

    def find_identity(self, channel: str, external_id: str) -> PrincipalIdentity | None:
        channel_value = str(getattr(channel, "value", channel))
        return next(
            (
                identity
                for identity in self.identities.values()
                if identity.channel == channel_value and identity.external_id == external_id
            ),
            None,
        )

    def list_identities(self) -> list[PrincipalIdentity]:
        return list(self.identities.values())

    def add_identity(self, identity: PrincipalIdentity) -> None:
        self.identities[identity.identity_id] = identity

    def update_identity(self, identity: PrincipalIdentity) -> None:
        self.identities[identity.identity_id] = identity

    def link_identity_once(self, identity_id: str, principal_id: str) -> PrincipalIdentity | None:
        with self._lock:
            identity = self.identities.get(identity_id)
            if identity is None or identity.principal_id is not None:
                return None
            linked = replace(
                identity,
                principal_id=principal_id,
                trusted=True,
                active=True,
                linked_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
            self.identities[identity_id] = linked
            return linked

    def get_capability(self, capability_id: CapabilityId) -> Capability | None:
        return self.capabilities.get(capability_id)

    def upsert_capability(self, capability: Capability) -> None:
        self.capabilities[capability.capability_id] = capability

    def list_capabilities(self, *, active_only: bool = True) -> list[Capability]:
        return [
            capability
            for capability in self.capabilities.values()
            if capability.active or not active_only
        ]

    def get_role(self, role_id: str) -> Role | None:
        return self.roles.get(role_id)

    def upsert_role(self, role: Role) -> None:
        self.roles[role.role_id] = role

    def list_roles(self, *, active_only: bool = True) -> list[Role]:
        return [role for role in self.roles.values() if role.active or not active_only]

    def add_assignment(self, assignment: RoleAssignment) -> None:
        self.assignments.append(assignment)

    def revoke_assignment(
        self, principal_id: str, role_id: str, scope: Scope
    ) -> list[RoleAssignment]:
        found = [
            assignment
            for assignment in self.assignments
            if assignment.active
            and assignment.principal_id == principal_id
            and assignment.role_id == role_id
            and assignment.scope == scope
        ]
        for assignment in found:
            index = self.assignments.index(assignment)
            self.assignments[index] = replace(assignment, active=False)
        return found

    def assignments_for(self, principal_id: str) -> list[RoleAssignment]:
        return [
            assignment
            for assignment in self.assignments
            if assignment.active and assignment.principal_id == principal_id
        ]

    def add_grant(self, grant: CapabilityGrant) -> None:
        self.grants.append(grant)

    def revoke_grant(
        self, principal_id: str, capability_id: CapabilityId, scope: Scope
    ) -> list[CapabilityGrant]:
        found = [
            grant
            for grant in self.grants
            if grant.active
            and grant.principal_id == principal_id
            and grant.capability_id == capability_id
            and grant.scope == scope
        ]
        for grant in found:
            index = self.grants.index(grant)
            self.grants[index] = replace(grant, active=False)
        return found

    def grants_for(self, principal_id: str) -> list[CapabilityGrant]:
        return [
            grant for grant in self.grants if grant.active and grant.principal_id == principal_id
        ]

    def add_confirmation(self, confirmation: Confirmation) -> None:
        self.confirmations[confirmation.confirmation_id] = confirmation

    def get_confirmation(self, confirmation_id: str) -> Confirmation | None:
        return self.confirmations.get(confirmation_id)

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
        with self._lock:
            confirmation = self.confirmations.get(confirmation_id)
            if confirmation is None or not confirmation.active:
                return None
            if principal_id is not None and confirmation.principal_id != principal_id:
                return None
            if capability_id is not None and confirmation.capability_id != capability_id:
                return None
            if action is not None and confirmation.action != action:
                return None
            # Strictly bound to the target: no target is not a wildcard.
            if resource_id is not None and confirmation.resource_id != resource_id:
                return None
            if channel is not None and confirmation.channel not in {"", channel}:
                return None
            if scope is not None and not covers(confirmation.scope, scope):
                return None
            consumed = replace(confirmation, active=False, used_at=datetime.now(UTC))
            self.confirmations[confirmation_id] = consumed
            return consumed


class PluginAuthorizationAdapter(AuthorizationPort):
    """Plugin-safe facade: handle authorization and metadata declaration only."""

    def __init__(self, service: AuthorizationService) -> None:
        self._service = service

    def authorize(
        self,
        handle: ExecutionHandle,
        capability: CapabilityId,
        requested_scope: Scope,
        *,
        confirmation_id: str | None = None,
        requested_action: str | None = None,
        requested_resource_id: str | None = None,
    ) -> AuthorizationDecision:
        return self._service.authorize(
            handle,
            capability,
            requested_scope,
            confirmation_id=confirmation_id,
            requested_action=requested_action,
            requested_resource_id=requested_resource_id,
        )

    def register_capability(
        self,
        capability: CapabilityId,
        kind: CapabilityKind = CapabilityKind.VIEW,
        name: str = "",
        metadata: Mapping[str, object] | None = None,
    ) -> None:
        self._service.register_capability(capability, kind, name, metadata)

    def resolve_identity(self, identity_id: str) -> str | None:
        return self._service.resolve_identity(identity_id)

    def resolve_principal(self, handle: ExecutionHandle) -> str | None:
        return self._service.resolve_principal(handle)

    def register_role(
        self,
        role_id: str,
        name: str,
        capabilities: frozenset[CapabilityId],
    ) -> None:
        self._service.register_role(role_id, name, capabilities)


class AuthorizationService(AuthorizationPort):
    """The sole evaluator for roles, grants, policy, and canonical execution facts."""

    def __init__(
        self,
        role_catalog: Iterable[Role] = DEFAULT_ROLE_CATALOG,
        *,
        uow: UnitOfWorkPort | None = None,
        repository: AuthorizationRepositoryPort | None = None,
        policy: PolicyService | None = None,
        uow_factory: Callable[[], UnitOfWorkPort] | None = None,
        plugin_id: str | None = None,
        allowed_capabilities: frozenset[CapabilityId] | None = None,
        declared_capability_kinds: Mapping[CapabilityId, CapabilityKind] | None = None,
        _shared: AuthorizationService | None = None,
        initialize: bool = True,
    ) -> None:
        if _shared is None:
            self._shared = self
            self._roles = {role.role_id: role for role in role_catalog}
            self._memory = InMemoryAuthorizationRepository()
            self._policy = policy
            self._uow_factory = uow_factory
        else:
            self._shared = _shared
            self._roles = _shared._roles
            self._memory = _shared._memory
            self._policy = policy or _shared._policy
            self._uow_factory = uow_factory or _shared._uow_factory
        self._uow = uow
        self._repository = repository or (uow.authorization if uow is not None else self._memory)
        self._plugin_id = plugin_id
        self._allowed_capabilities = allowed_capabilities
        self._declared_capability_kinds = dict(declared_capability_kinds or {})
        self._handle_store = ExecutionHandleStore(uow) if uow is not None else None
        self._handle_issuer = (
            ExecutionHandleIssuer(uow, self._handle_store)
            if uow is not None and self._handle_store is not None
            else None
        )
        self._handle_resolver = (
            ExecutionHandleResolver(uow, self._handle_store)
            if uow is not None and self._handle_store is not None
            else None
        )
        if initialize:
            self._run_mutation(self._seed_core_capabilities)
            self._seed_roles()
            if self._uow is not None and self._allowed_capabilities:
                self._run_mutation(self._persist_declared_capabilities)

    @property
    def roles(self) -> Mapping[str, Role]:
        return MappingProxyType(self._roles)

    @property
    def assignments(self) -> list[RoleAssignment]:
        if self._uow is None:
            return list(self._memory.assignments)
        try:
            return [
                assignment
                for principal in self._repository.list_principals()
                for assignment in self._repository.assignments_for(principal.principal_id)
            ]
        finally:
            self._finish_read()

    @property
    def capabilities(self) -> list[Capability]:
        try:
            return self._repository.list_capabilities()
        finally:
            self._finish_read()

    def for_uow(
        self,
        uow: UnitOfWorkPort,
        *,
        plugin_id: str | None = None,
        allowed_capabilities: frozenset[CapabilityId] | None = None,
        declared_capability_kinds: Mapping[CapabilityId, CapabilityKind] | None = None,
        policy: PolicyService | None = None,
    ) -> AuthorizationService:
        return AuthorizationService(
            uow=uow,
            policy=policy or self._policy,
            uow_factory=self._uow_factory,
            plugin_id=plugin_id,
            allowed_capabilities=allowed_capabilities,
            declared_capability_kinds=declared_capability_kinds,
            _shared=self,
        )

    def register_capability(
        self,
        capability: CapabilityId,
        kind: CapabilityKind = CapabilityKind.VIEW,
        name: str = "",
        metadata: Mapping[str, object] | None = None,
        *,
        provider_id: str | None = None,
    ) -> None:
        """Register metadata only; this method never grants a principal access."""
        if self._allowed_capabilities is not None and capability not in self._allowed_capabilities:
            msg = f"plugin {self._plugin_id!r} cannot declare undeclared capability {capability!r}"
            raise PluginRegistrationError(msg)
        owner = provider_id or self._plugin_id or "core"
        if self._plugin_id is not None and provider_id not in (None, self._plugin_id):
            raise PluginRegistrationError(
                f"plugin {self._plugin_id!r} cannot claim capability {capability!r}"
            )
        normalized_kind = CapabilityKind(kind)
        existing = self._repository.get_capability(capability)
        if existing is not None and existing.provider_id != owner:
            raise PluginRegistrationError(
                f"capability {capability!r} is owned by {existing.provider_id!r}"
            )
        if existing is not None and existing.kind != normalized_kind:
            raise PluginRegistrationError(f"capability {capability!r} already has a different kind")
        if existing is not None and (
            existing.name != name or dict(existing.metadata) != dict(metadata or {})
        ):
            raise PluginRegistrationError(
                f"capability {capability!r} was already declared with different metadata"
            )
        definition = Capability(
            capability_id=capability,
            kind=normalized_kind,
            name=name,
            provider_id=owner,
            metadata=dict(metadata or {}),
        )
        self._run_mutation(lambda: self._repository.upsert_capability(definition))
        if self._plugin_id is None:
            self._ensure_default_policy(capability)

    def register_role(
        self,
        role_id: str,
        name: str,
        capabilities: frozenset[CapabilityId],
        capability_kinds: Mapping[CapabilityId, CapabilityKind] | None = None,
    ) -> None:
        """Declare a role bundle; it does not assign it or grant permission."""
        if self._allowed_capabilities is not None:
            undeclared = set(capabilities) - self._allowed_capabilities
            if undeclared:
                raise PluginRegistrationError(
                    f"plugin {self._plugin_id!r} role {role_id!r} declares undeclared capabilities"
                )
        owner = self._plugin_id or "core"
        role = Role(
            role_id=role_id,
            name=name,
            capabilities=frozenset(capabilities),
            capability_kinds=dict(capability_kinds or {}),
            owner_plugin_id=owner,
        )

        def persist() -> None:
            existing_role = self._repository.get_role(role_id)
            if existing_role is not None:
                if existing_role.owner_plugin_id != owner:
                    raise PluginRegistrationError(
                        f"role {role_id!r} is owned by {existing_role.owner_plugin_id!r}"
                    )
                # Only the kinds the caller actually declared are comparable. The
                # repository rebuilds ``capability_kinds`` from the capability
                # catalogue rather than storing it, so a role that declared none
                # still reads back fully populated. Comparing that derived mapping
                # against a declaration of ``{}`` would refuse every role on every
                # boot after the first, which is a declaration conflict that never
                # existed. A caller that does declare kinds is still checked.
                declared_kinds = dict(capability_kinds or {})
                if (
                    existing_role.name != name
                    or existing_role.capabilities != role.capabilities
                    or (declared_kinds and dict(existing_role.capability_kinds) != declared_kinds)
                ):
                    raise PluginRegistrationError(
                        f"role {role_id!r} was already declared with different metadata"
                    )
            for capability in capabilities:
                definition = self._repository.get_capability(capability)
                if definition is None:
                    raise PluginRegistrationError(
                        f"role {role_id!r} references unknown capability {capability!r}"
                    )
                if definition.provider_id != owner and owner != "core":
                    raise PluginRegistrationError(
                        f"role {role_id!r} references foreign capability {capability!r}"
                    )
            self._repository.upsert_role(role)

        self._run_mutation(persist)
        self._roles[role_id] = role

    def issue_handle(
        self,
        *,
        principal_id: str,
        capability: CapabilityId,
        action: str,
        scope: Scope,
        channel: Channel | str,
        resource_id: str | None = None,
        identity_id: str | None = None,
        policy_context: Mapping[str, Any] | None = None,
        additional_capabilities: Iterable[CapabilityId] = (),
        ttl_seconds: int = 15 * 60,
    ) -> ExecutionHandle:
        issuer = self._handle_issuer
        if issuer is None:
            raise RuntimeError("ExecutionHandle issuance requires a PostgreSQL UoW")
        return self._run_mutation(
            lambda: issuer.issue(
                principal_id=principal_id,
                capability=capability,
                action=action,
                scope=scope,
                channel=channel,
                resource_id=resource_id,
                identity_id=identity_id,
                policy_context=policy_context,
                additional_capabilities=additional_capabilities,
                ttl_seconds=ttl_seconds,
            )
        )

    def resolve_handle(
        self,
        handle: ExecutionHandle,
        *,
        requested_scope: Scope | None = None,
        requested_action: str | None = None,
        requested_resource_id: str | None = None,
    ) -> ExecutionFacts:
        if self._handle_resolver is None:
            raise RuntimeError("ExecutionHandle resolution requires a PostgreSQL UoW")
        return self._handle_resolver.resolve(
            handle,
            requested_scope=requested_scope,
            requested_action=requested_action,
            requested_resource_id=requested_resource_id,
        )

    def revoke_handle(self, handle: ExecutionHandle) -> bool:
        store = self._handle_store
        if store is None:
            raise RuntimeError("ExecutionHandle revocation requires a PostgreSQL UoW")
        return self._run_mutation(lambda: store.revoke(handle))

    def expire_handles(self, now: datetime | None = None) -> int:
        store = self._handle_store
        if store is None:
            raise RuntimeError("ExecutionHandle expiry requires a PostgreSQL UoW")
        return self._run_mutation(lambda: store.expire_due(now))

    def authorize_confirmation_request(
        self,
        handle: ExecutionHandle,
        capability: CapabilityId,
        requested_scope: Scope,
    ) -> AuthorizationDecision:
        """Authorize issuing a confirmation, without consuming one first."""
        if not isinstance(handle, ExecutionHandle) or self._uow is None:
            return self._record_decision(
                AuthorizationDecision(
                    False,
                    None,
                    CapabilityId(capability),
                    requested_scope,
                    Channel.WEB,
                    reason="a persistent ExecutionHandle is required",
                    code="handle_required",
                )
            )
        try:
            facts = self.resolve_handle(handle, requested_scope=requested_scope)
        except (AuthorizationError, TypeError, ValueError) as error:
            return self._record_decision(
                AuthorizationDecision(
                    False,
                    None,
                    CapabilityId(capability),
                    requested_scope,
                    Channel.WEB,
                    reason=str(error),
                    code="handle_invalid",
                )
            )
        effective = CapabilityId(capability)
        if effective not in facts.allowed_capability_ids:
            return self._record_decision(
                self._deny(
                    facts,
                    "capability_binding_mismatch",
                    "confirmation capability is not bound to the handle",
                    capability=effective,
                )
            )
        if self._policy is not None:
            self._policy.refresh()
        if self._policy is None or not self._policy.evaluate(facts, effective):
            return self._record_decision(
                self._deny(
                    facts,
                    "policy_denied",
                    "Core policy denied the confirmation request",
                    capability=effective,
                )
            )
        if not self._check_unchecked(effective, requested_scope, facts.principal_id):
            return self._record_decision(
                self._deny(
                    facts,
                    "capability_denied",
                    "effective permissions do not include the capability",
                    capability=effective,
                )
            )
        if facts.channel is Channel.AI and not self._check_unchecked(
            ASSISTANT_USE, requested_scope, facts.principal_id
        ):
            return self._record_decision(
                self._deny(
                    facts,
                    "assistant_required",
                    "AI access requires assistant.use",
                    capability=effective,
                )
            )
        return self._record_decision(self._allow(facts, effective))

    def authorize(
        self,
        handle: ExecutionHandle,
        capability: CapabilityId,
        requested_scope: Scope,
        *,
        confirmation_id: str | None = None,
        requested_action: str | None = None,
        requested_resource_id: str | None = None,
    ) -> AuthorizationDecision:
        """Authorize only the capability and scope bound to the handle."""
        if not isinstance(handle, ExecutionHandle):
            return self._record_decision(
                AuthorizationDecision(
                    False,
                    None,
                    CapabilityId(capability),
                    requested_scope,
                    Channel.WEB,
                    reason="a server-issued ExecutionHandle is required",
                    code="handle_required",
                )
            )
        if self._uow is None or self._handle_resolver is None:
            return self._record_decision(
                AuthorizationDecision(
                    False,
                    None,
                    CapabilityId(capability),
                    requested_scope,
                    Channel.WEB,
                    reason="authorization requires a persistent PostgreSQL execution record",
                    code="persistence_required",
                )
            )
        try:
            facts = self.resolve_handle(
                handle,
                requested_scope=requested_scope,
                requested_action=requested_action,
                requested_resource_id=requested_resource_id,
            )
        except (AuthorizationError, TypeError, ValueError) as error:
            return self._record_decision(
                AuthorizationDecision(
                    False,
                    None,
                    CapabilityId(capability),
                    requested_scope,
                    Channel.WEB,
                    reason=str(error),
                    code="handle_invalid",
                    confirmation_id=confirmation_id,
                )
            )
        effective_capability = CapabilityId(capability)
        if effective_capability not in facts.allowed_capability_ids:
            return self._record_decision(
                self._deny(
                    facts,
                    "capability_binding_mismatch",
                    "requested capability is not the capability bound to the handle",
                    capability=effective_capability,
                    confirmation_id=confirmation_id,
                )
            )
        if self._policy is not None:
            self._policy.refresh()
        if not facts.action.strip() or facts.scope.is_empty:
            return self._record_decision(
                self._deny(
                    facts,
                    "request_invalid",
                    "action and scope are required",
                    confirmation_id=confirmation_id,
                )
            )
        if self._policy is None or not self._policy.evaluate(facts, effective_capability):
            return self._record_decision(
                self._deny(
                    facts,
                    "policy_denied",
                    "Core policy denied the action",
                    confirmation_id=confirmation_id,
                )
            )
        if not self._check_unchecked(effective_capability, requested_scope, facts.principal_id):
            return self._record_decision(
                self._deny(
                    facts,
                    "capability_denied",
                    "effective permissions do not include the capability",
                    confirmation_id=confirmation_id,
                )
            )
        if facts.channel is Channel.AI and not self._check_unchecked(
            ASSISTANT_USE, requested_scope, facts.principal_id
        ):
            return self._record_decision(
                self._deny(
                    facts,
                    "assistant_required",
                    "AI access requires assistant.use",
                    confirmation_id=confirmation_id,
                )
            )
        if self._policy.requires_confirmation(facts, effective_capability):
            confirmation = self._confirmation_record(
                facts, effective_capability, confirmation_id, requested_scope
            )
            if confirmation is None:
                return self._record_decision(
                    self._deny(
                        facts,
                        "confirmation_required",
                        "a valid typed confirmation is required",
                        confirmation_id=confirmation_id,
                    )
                )
            consumed = self._repository.consume_confirmation(
                confirmation.confirmation_id,
                principal_id=facts.principal_id,
                capability_id=effective_capability,
                action=facts.action,
                resource_id=facts.resource_id,
                channel=facts.channel.value,
                scope=requested_scope,
            )
            if consumed is None:
                return self._record_decision(
                    self._deny(
                        facts,
                        "confirmation_consumed",
                        "the typed confirmation was already consumed",
                        confirmation_id=confirmation_id,
                    )
                )
        return self._record_decision(
            self._allow(facts, effective_capability, confirmation_id=confirmation_id)
        )

    def _evaluate_policy(
        self,
        handle: ExecutionHandle,
        capability: CapabilityId,
        requested_scope: Scope,
    ) -> bool:
        if self._handle_resolver is None or self._policy is None:
            return False
        try:
            facts = self.resolve_handle(handle, requested_scope=requested_scope)
        except AuthorizationError:
            return False
        self._policy.refresh()
        return self._policy.evaluate(facts, CapabilityId(capability))

    def _check_unchecked(self, capability: CapabilityId, scope: Scope, subject_id: str) -> bool:
        principal = self._repository.get_principal(subject_id)
        if principal is not None and not principal.active:
            return False
        if self._uow is not None and principal is None:
            return False
        if scope.is_empty:
            return False
        direct = {
            grant.capability_id
            for grant in self._repository.grants_for(subject_id)
            if grant.active and covers(grant.scope, scope)
        }
        if capability in direct:
            return True
        for assignment in self._repository.assignments_for(subject_id):
            if not assignment.active or not covers(assignment.scope, scope):
                continue
            role = (
                self._repository.get_role(assignment.role_id)
                if self._uow is not None
                else self._roles.get(assignment.role_id)
            )
            if role is not None and role.active and capability in role.capabilities:
                return True
        return False

    def effective_permissions(self, principal_id: str, scope: Scope) -> EffectivePermissions:
        if self._uow is None:
            return EffectivePermissions(principal_id, scope, frozenset())
        try:
            principal = self._repository.get_principal(principal_id)
            if principal is None or not principal.active or scope.is_empty:
                return EffectivePermissions(principal_id, scope, frozenset())
            direct = {
                grant.capability_id
                for grant in self._repository.grants_for(principal_id)
                if grant.active and covers(grant.scope, scope)
            }
            role_ids: set[str] = set()
            role_caps: set[CapabilityId] = set()
            for assignment in self._repository.assignments_for(principal_id):
                if not assignment.active or not covers(assignment.scope, scope):
                    continue
                role = self._repository.get_role(assignment.role_id)
                if role is not None and role.active:
                    role_ids.add(role.role_id)
                    role_caps.update(role.capabilities)
            return EffectivePermissions(
                principal_id=principal_id,
                scope=scope,
                capabilities=frozenset(direct | role_caps),
                role_ids=frozenset(role_ids),
                direct_capability_ids=frozenset(direct),
            )
        finally:
            self._finish_read()

    def grant_state(self, principal_id: str, scope: Scope) -> GrantState:
        """Every capability's and role's state for one principal in one scope.

        The management view hydrates its checkboxes from this instead of
        recomputing anything: the explicit grant, the roles that also carry the
        capability, and the union the server enforces. It is read-only Core
        state, so it grants nothing and the mutation still rechecks
        authorization (contract §38.3).

        A grant or a role counts only where it covers *this* scope, so a self
        grant never answers an organization question and an organization role
        does cover the workplace inside it. An empty scope would answer all of
        them at once, so it is refused rather than widened.
        """
        if scope.is_empty:
            raise ScopeError("grant state needs an explicit organization, workplace, or self scope")
        if self._uow is None:
            raise AuthorizationError("grant state requires a persistent Core UoW")
        try:
            principal = self._repository.get_principal(principal_id)
            if principal is None:
                raise NotFoundError(
                    f"principal {principal_id!r} is not registered",
                    kind="principal",
                    key=principal_id,
                )
            direct = {
                grant.capability_id
                for grant in self._repository.grants_for(principal_id)
                if grant.active and covers(grant.scope, scope)
            }
            assigned: set[str] = set()
            carried: dict[CapabilityId, set[str]] = {}
            for assignment in self._repository.assignments_for(principal_id):
                if not assignment.active or not covers(assignment.scope, scope):
                    continue
                role = self._repository.get_role(assignment.role_id)
                if role is None or not role.active:
                    continue
                assigned.add(role.role_id)
                for capability in role.capabilities:
                    carried.setdefault(capability, set()).add(role.role_id)
            capabilities = tuple(
                CapabilityGrantState(
                    capability_id=capability.capability_id,
                    direct=capability.capability_id in direct,
                    role_ids=tuple(sorted(carried.get(capability.capability_id, ()))),
                )
                for capability in self._repository.list_capabilities()
            )
            return GrantState(
                principal_id=principal_id,
                scope=scope,
                capabilities=capabilities,
                roles=tuple(
                    RoleAssignmentState(role_id=role.role_id, assigned=role.role_id in assigned)
                    for role in self._repository.list_roles()
                ),
                # A deactivated principal has no effective permission at all, so
                # the union is empty even though its stored state is reported.
                effective_capability_ids=frozenset(
                    item.capability_id
                    for item in capabilities
                    if principal.active and (item.direct or item.role_ids)
                ),
            )
        finally:
            self._finish_read()

    def resolve_identity(self, identity_id: str) -> str | None:
        if self._uow is None:
            return None
        try:
            identity = self._repository.get_identity(identity_id)
            if identity is None or not identity.active or not identity.trusted:
                return None
            return identity.principal_id
        finally:
            self._finish_read()

    def resolve_principal(self, handle: ExecutionHandle) -> str | None:
        """The authenticated principal of a valid handle, or ``None``.

        The SDK handle carries no facts, so a self-scoped read has to ask Core
        who it is acting for. This is deliberately the narrowest possible
        answer: one identifier, resolved from the same canonical record
        :meth:`authorize` validates, and ``None`` for any missing, unknown,
        expired, revoked, or no-longer-valid handle. It grants nothing — the
        capability, scope, policy and channel checks still belong to
        :meth:`authorize`.
        """
        if not isinstance(handle, ExecutionHandle) or self._handle_resolver is None:
            return None
        try:
            return self._handle_resolver.resolve(handle).principal_id
        except (AuthorizationError, TypeError, ValueError):
            return None

    def _confirmation_record(
        self,
        facts: ExecutionFacts,
        capability: CapabilityId,
        confirmation_id: str | None,
        requested_scope: Scope,
    ) -> Confirmation | None:
        if self._uow is None or confirmation_id is None:
            return None
        confirmation = self._repository.get_confirmation(confirmation_id)
        if confirmation is None or not confirmation.active:
            return None
        if confirmation.principal_id != facts.principal_id or confirmation.action != facts.action:
            return None
        if confirmation.capability_id != capability:
            return None
        # A confirmation is bound to the target it was issued for. An absent
        # target is not a wildcard: it matches only an execution that has no
        # target either, so a confirmation for one principal can never
        # authorize a change to another (contract §38.12).
        if confirmation.resource_id != facts.resource_id:
            return None
        if confirmation.channel not in {"", facts.channel.value}:
            return None
        if not covers(confirmation.scope, requested_scope):
            return None
        return confirmation

    def _deny(
        self,
        facts: ExecutionFacts,
        code: str,
        reason: str,
        *,
        capability: CapabilityId = EMPTY_CAPABILITY,
        confirmation_id: str | None = None,
    ) -> AuthorizationDecision:
        return AuthorizationDecision(
            False,
            facts.principal_id,
            capability,
            facts.scope,
            facts.channel,
            reason=reason,
            code=code,
            confirmation_id=confirmation_id,
        )

    @staticmethod
    def _allow(
        facts: ExecutionFacts,
        capability: CapabilityId,
        *,
        confirmation_id: str | None = None,
    ) -> AuthorizationDecision:
        return AuthorizationDecision(
            True,
            facts.principal_id,
            capability,
            facts.scope,
            facts.channel,
            reason="allowed",
            code="allowed",
            confirmation_id=confirmation_id,
        )

    def _record_decision(self, decision: AuthorizationDecision) -> AuthorizationDecision:
        record = AuditRecord(
            actor=decision.principal_id or "anonymous",
            action="authorization.decision",
            organization_id=decision.scope.organization_id,
            workplace_id=decision.scope.workplace_id,
            principal_id=decision.scope.principal_id,
            details={
                "allowed": decision.allowed,
                "capability_id": str(decision.capability),
                "channel": decision.channel.value,
                "code": decision.code,
                "reason": decision.reason,
            },
        )
        if decision.allowed:
            uow = self._uow
            if uow is None:
                return decision
            self._run_mutation(lambda: uow.audit.append(record))
            return replace(decision, audit_id=record.audit_id)
        # A denial must be durable even when the business transaction rolls back,
        # so it is written through a separate unit of work. Without one, the
        # decision fails closed with a hard error rather than quietly skipping
        # the required Audit record.
        if self._uow_factory is None:
            raise AuthorizationError(
                f"{decision.reason}; no independent denial-audit UoW is available"
            )
        audit_uow = self._uow_factory()
        if audit_uow is self._uow:
            raise AuthorizationError(
                f"{decision.reason}; the denial-audit UoW is the caller transaction"
            )
        try:
            with audit_uow:
                audit_uow.audit.append(record)
        except BaseException as error:
            raise AuthorizationError(
                f"{decision.reason}; durable denial audit failed: {error}"
            ) from error
        return replace(decision, audit_id=record.audit_id)

    def _ensure_default_policy(self, capability: CapabilityId) -> None:
        if self._policy is None:
            return
        self._policy.register_default(capability, Channel.WEB)
        self._policy.register_default(capability, Channel.CORE)

    def _seed_core_capabilities(self) -> None:
        capabilities = {ASSISTANT_USE, AUTHORIZATION_MANAGE}
        for role in self._roles.values():
            capabilities.update(role.capabilities)
        for capability in capabilities:
            if self._repository.get_capability(capability) is None:
                self._repository.upsert_capability(
                    Capability(
                        capability_id=capability,
                        kind=CORE_CAPABILITY_KINDS.get(capability, CapabilityKind.VIEW),
                        provider_id="core",
                    )
                )
            self._ensure_default_policy(capability)

    def _persist_declared_capabilities(self) -> None:
        for capability in self._allowed_capabilities or ():
            existing = self._repository.get_capability(capability)
            kind = self._declared_capability_kinds.get(capability, CapabilityKind.VIEW)
            if existing is not None and existing.provider_id != self._plugin_id:
                raise PluginRegistrationError(
                    f"capability {capability!r} is owned by {existing.provider_id!r}"
                )
            if existing is not None and existing.kind != kind:
                raise PluginRegistrationError(
                    f"capability {capability!r} already has a different kind"
                )
            if existing is None or capability in self._declared_capability_kinds:
                self._repository.upsert_capability(
                    Capability(
                        capability_id=capability,
                        kind=kind,
                        provider_id=self._plugin_id or "core",
                    )
                )

    def _seed_roles(self) -> None:
        for role in self._roles.values():
            if self._repository.get_role(role.role_id) is None:
                self._run_mutation(lambda role=role: self._repository.upsert_role(role))
            else:
                self._finish_read()

    def _finish_read(self) -> None:
        if self._uow is None:
            return
        finish = getattr(self._uow, "finish_read", None)
        if finish is not None:
            finish()

    def _run_mutation(self, operation: Callable[[], Any]) -> Any:
        if self._uow is None:
            return operation()
        if self._uow.in_transaction:
            return operation()
        try:
            self._uow.begin()
            result = operation()
            self._uow.commit()
        except BaseException as error:
            try:
                self._uow.rollback()
            except BaseException as rollback_error:
                error.add_note(f"transaction rollback failed: {rollback_error!r}")
                try:
                    self._uow.poison()
                except BaseException as poison_error:
                    error.add_note(f"transaction poison failed: {poison_error!r}")
            raise
        return result


__all__ = [
    "AuthorizationDecision",
    "AuthorizationService",
    "InMemoryAuthorizationRepository",
    "PluginAuthorizationAdapter",
]
