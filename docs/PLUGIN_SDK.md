# Plugin SDK

`atlas_sdk` is the **stable boundary**. A plugin imports this package and
nothing else from the platform.

## What a plugin may import

| Allowed | Forbidden |
|---|---|
| `atlas_sdk` (anything in `__all__`) | `atlas_core.*` — any module, incl. the ORM |
| (the SDK's shared vocabulary, e.g. `atlas_sdk.reporting`) | another plugin's package — agree on the **id string**, not an import |
| | core database tables, directly or via SQL |

The one exception in the codebase is the admin app, not a plugin:
`atlas_hq/cli.py::_run_report` imports `atlas_plugins.report_studio` for the
single `report` command that must call a plugin's own API. Everything else in
the CLI uses registry metadata alone.

The one-way dependency: `atlas_core` imports `atlas_sdk`; `atlas_plugins`
imports `atlas_sdk`. Nothing in `atlas_sdk` imports either. A plugin developer
needs to understand the SDK, not every core file.

## The public surface

`src/atlas_sdk/__init__.py` re-exports everything a plugin may use:

| Group | Names |
|---|---|
| Plugin | `Plugin`, `PluginLifecycle`, `PluginManifest`, `ClusterManifest`, `ModuleDeclaration` |
| Context | `PluginContext` + the context Ports below |
| Contracts | `Contract`, `ContractDeclaration`, `ContractId`, `ContractImplementation` |
| Events | `DomainEvent`, `EventEnvelope`, `EventId` |
| Capabilities | `CapabilityId` |
| Command/Query | `Command`, `CommandHandler`, `Query`, `QueryHandler` |
| Registries | `PluginRegistryPort`, `ClusterRegistryPort`, `CapabilityRegistryPort`, `ContractRegistryPort`, `EventRegistryPort` |
| Value types | `Employee`, `Organization`, `Workplace`, `Job`, `Assignment`, `AuditEntry`, `WorkflowCase`, `Notification`, `ScheduledJob`, `Scope`, `WorkplaceType` |
| Reporting vocabulary | `atlas_sdk.reporting`: `REPORT_DATASET_CONTRACT`, `REPORT_DATASET_DECLARATION`, `DatasetRequest`, `DatasetResponse`, `REPORT_DEFINITION_CONTRACT`, `REPORT_DEFINITION_DECLARATION`, `ReportDefinitionRequest`, `ColumnFilter`, `ReportDefinition` |
| Errors | see below |

## PluginContext — the one handle a plugin receives

```python
@dataclass(frozen=True)
class PluginContext:
    plugin_id: str
    people: PeoplePort
    organization: OrganizationPort
    jobs: JobsPort
    assignments: AssignmentPort
    authorization: AuthorizationPort
    scope: ScopePort
    policy: PolicyPort
    audit: AuditPort
    workflow: WorkflowPort
    notification: NotificationPort
    scheduling: SchedulingPort
    events: EventPublisherPort
    dispatcher: EventDispatcherPort
    invoker: ContractInvokerPort
    capabilities: CapabilityRegistryPort
    contracts: ContractRegistryPort
    events_registry: EventRegistryPort
    persistence: PluginPersistencePort
    transactions: TransactionRunnerPort
```

One context per plugin, cached on the kernel (`Kernel.context_for`), so a
plugin's stateful services share one platform-owned transaction. Plugin-owned
tables use `context.persistence`, a restricted adapter exposing only `add`,
`delete`, `get`, `query`, and `create_schema`; it never returns the raw session
or transaction lifecycle. Direct reads and writes use
`context.transactions.run(operation)`, which begins, commits on normal return,
and rolls back on operation or commit failure; a rollback failure poisons the
cached UoW so no later call can commit leaked state.

A bound contract handler is different: it calls its uncommitted internal
implementation, while the contract registry remains the outer transaction
owner. Never call `context.transactions.run` inside a bound handler.

### The context ports

| Port | Methods | Status |
|---|---|---|
| `PeoplePort` | `create_employee`, `get_employee`, `list_employees` | real, persisted |
| `OrganizationPort` | `create_organization`, `get_organization`, `add_workplace`, `list_workplaces` | real, persisted |
| `JobsPort` | `create_job`, `get_job`, `list_jobs` | real, persisted |
| `AssignmentPort` | `assign`, `get_assignment`, `assignments_for` | real, persisted |
| `AuthorizationPort` | `check`, `grant`, `register_role` | real, in-memory |
| `ScopePort` | `resolve`, `narrow` | real, in-memory |
| `PolicyPort` | `register`, `evaluate` | real, in-memory |
| `AuditPort` | `record`, `list_records` | real, persisted, append-only |
| `WorkflowPort` | `define`, `start`, `transition`, `get_case` | **skeleton** — in-memory state machine |
| `NotificationPort` | `send`, `list_sent` | **skeleton** — in-memory out-tray |
| `SchedulingPort` | `schedule`, `due` | **skeleton** — in-memory job list |
| `EventPublisherPort` | `publish` | real, outbox-backed |
| `EventDispatcherPort` | `subscribe`, `unsubscribe` | real, in-process |
| `ContractInvokerPort` | `invoke`, `invoke_all` | real, registry-backed |
| `PluginPersistencePort` | `add`, `delete`, `get`, `query`, `create_schema` | real, restricted |
| `TransactionRunnerPort` | `run` | real, platform-owned direct-call seam |

Ports are `Protocol`s owned by the SDK; `atlas_core` provides every
implementation. "Skeleton" means callable today with a stable port but an
in-memory backing store — persistence and richer behaviour come later.

### The 3 registry Ports on the context

| Port | Read-only surface a plugin uses |
|---|---|
| `capabilities` | `all`, `exists`, `providers_of`, `provided_by` |
| `contracts` | `get`, `all`, `exists`, `implementations_of`, `provided_by`, plus `bind` (enable only) |
| `events_registry` | `all`, `exists`, `publishers_of`, `subscribers_of`, `published_by`, `subscribed_by` |

## Value types

`atlas_sdk.types` — frozen dataclasses, the published language of the platform.
Core maps its rich domain entities to these at the application-service boundary
(the anti-corruption layer). Plugins never see core domain objects.

`Scope` is the important one:

```python
@dataclass(frozen=True)
class Scope:
    organization_id: str | None = None
    workplace_id: str | None = None

    @property
    def is_empty(self) -> bool: ...  # organization_id is None ⇒ "no access"
```

`scope.narrow(requested, subject)` intersects what an operation wants with what
an actor may see; the result never grants more than `subject`, and disjoint
scopes yield an empty scope rather than an error.

`AttendanceStatus` (`present`, `absent`, `on_leave`, `remote`, `other`) is published in `atlas_sdk.types` for the same reason: any plugin reads the attendance-status vocabulary without importing the plugin that owns attendance records.

## Capabilities and authorization

`CapabilityId` names *who may perform an action* — dotted strings such as
`people.employee.create`, `demo.greet`, `report.render`.

```python
# at initialize — publish the role that carries your capability
context.authorization.register_role(
    "role.demo_greeter", "Demo Greeter", frozenset({CapabilityId("demo.greet")})
)

# at runtime — check before acting
if not context.authorization.check(MY_CAP, scope, actor_id):
    raise AuthorizationError(...)
```

A capability is useless until a role carrying it exists and is granted to a
subject in a scope. Platform roles in `atlas_core/domain/role.py`:
`role.hr_admin`, `role.manager`, `role.employee`, `role.platform`. Plugin roles
are registered at initialize time (e.g. `role.demo_greeter`,
`role.report_renderer`).

## Error hierarchy

Every error a plugin can expect derives from `AtlasError`
(`atlas_sdk/errors.py`):

```text
AtlasError
├── PluginError
│    ├── PluginDiscoveryError        # distribution failed to load
│    ├── PluginValidationError      # manifest rejected (.errors: list[str])
│    ├── PluginDependencyError      # requires_plugins unmet (.errors)
│    ├── PluginRegistrationError
│    └── PluginLifecycleError       # illegal transition
├── RegistryError                   # carries .kind and .key
│    ├── NotFoundError              # e.g. invoke on an unbound contract
│    └── AlreadyRegisteredError
├── DuplicateError                  # business value must be unique
├── AuthorizationError              # capability check failed
├── ScopeError
├── PolicyError
└── OutboxError
```

## Command and Query markers

`Command` (intent to change state) and `Query` (current information now) are
marker base classes with a `result_type` and a `CommandHandler` /
`QueryHandler` protocol. They exist to make the query/command split explicit
and greppable (`contract.md` §20); plugins are not required to wrap every call
in one — the ports are the primary surface.

Last updated: 2026-09-24
