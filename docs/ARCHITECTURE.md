# Architecture

The four levels, the package layout, and how a boot actually proceeds. Every
name here is a real identifier in `src/`. Cross-check with `contract.md`
sections 4, 17, 18, 21, 22.

## The four levels

```text
CORE      universal platform foundation          (src/atlas_core, src/atlas_sdk)
  ↓
CLUSTER   business ecosystem of related plugins  (cluster.workforce_and_time, …)
  ↓
PLUGIN    composable business capability package  (atlas_demo, report_studio, …)
  ↓
MODULE    functional component inside a plugin    (demo.greeting, report.compose)
```

Levels are distinct concepts and are never collapsed: a cluster is not a
plugin, a module is not a contract. A module *provides* contract ids; a plugin
*declares* them; a cluster *groups* plugins.

## Hexagonal layout

```text
                    src/atlas_sdk  (ports, manifests, value types)
                  ┌──────────────────────────────────────────────┐
                  │  PluginContext · context Ports · 5          │
                  │  registry Ports · error hierarchy            │
                  └──────────────▲───────────────▲───────────────┘
        plugins import only this  │               │ core implements every port
                                 │               │  (never the reverse)
src/atlas_plugins                 │     src/atlas_core
  atlas_demo, atlas_demo_consumer │       domain          (entities, enums)
  attendance_operations,          │       application     (services + ports)
  attendance_summary              │       infrastructure (persistence, events,
  construction_reporting,         │                        discovery, registries)
  report_studio, workforce_summary│       kernel.py        (boot + lifecycle)
  workplace_operations            │
                                  └───────────────┘

```

- The dependency direction is **one-way**: `atlas_core` imports `atlas_sdk`;
  `atlas_plugins` imports `atlas_sdk`. Nothing in `atlas_sdk` imports either.
- Every service a plugin may call is a `Protocol` **owned by the SDK**
  (`src/atlas_sdk/context.py`). Core provides the implementations. That
  inversion *is* the hexagonal boundary — core depends on the SDK's published
  language, never the reverse.
- Core domain entities (`atlas_core/domain/`) are **not importable by plugins**.
  Core maps them to SDK value types (`atlas_sdk/types.py`) at the
  application-service boundary — the anti-corruption layer.

## Package map

| Package | Role | Key contents |
|---|---|---|
| `atlas_sdk` | the public boundary | `Plugin`, `PluginManifest`, `PluginContext`, `Contract*`, `DomainEvent`, `Command`/`Query`, 5 registry Ports, error hierarchy, `reporting.py` |
| `atlas_core/domain` | domain model | `employee`, `organization`, `job`, `assignment`, `audit`, `policy`, `role`, `scope`, `identifiers`, `clusters` |
| `atlas_core/application` | application services | `people`, `organization`, `jobs`, `assignments`, `audit`, `authorization`, `scope`, `policy`, `workflow`, `notification`, `scheduling`, `unit_of_work`, `repositories` |
| `atlas_core/infrastructure` | adapters | `persistence/` (orm, repositories, session, unit_of_work), `events/` (outbox + dispatcher), `discovery/` (entry points), `registry/` (in-memory registries + validation) |
| `atlas_core/kernel.py` | boot + lifecycle | `Kernel`, `RegistryBundle`, `BootResult` |
| `atlas_plugins` | shipped plugins | 8 plugins, each one directory, each registered by entry point |
| `atlas_hq` | admin shell | `cli.py` — the `atlas-hq` command |

## How the kernel boots

`Kernel.boot()` (`src/atlas_core/kernel.py`) runs this sequence per plugin:

```text
_seed_clusters()          register the 8 initial clusters (INITIAL_CLUSTERS)
discover_plugins(group)   importlib.metadata, group "atlas.plugins"
  ↓ per candidate
_advance_to_discovered    mark DISCOVERED
_validate                 assert_valid(manifest, known_clusters) → VALIDATED
_check_dependencies       assert_dependencies(manifest, registered) → DEPENDENCIES_CHECKED
_register                 plugin manifest → plugin registry
                          capabilities → capability registry
                          contract declarations → contract registry
                          published/subscribed events → event registry
                          → REGISTERED
```

Any exception marks the plugin `FAILED` with a recorded reason and **boot
continues** — one broken distribution must not stop the core
(`kernel.boot()` catches `Exception` per candidate and appends to
`BootResult.failed`).

Enable/disable (`Kernel.enable`, `Kernel.disable`, `Kernel.stop`,
`Kernel.enable_all`) move a plugin through `INITIALIZED → ENABLED → RUNNING`
and back. See [PLUGIN_SPEC.md](PLUGIN_SPEC.md) § lifecycle.

The CLI mirrors this exactly: `atlas-hq [--entry-point-group GROUP] [--json]
boot|plugins|clusters|contracts|capabilities|events|enable|disable|audit|report|workplace`
(`src/atlas_hq/cli.py`). `workplace` has `list` and `workforce` subcommands;
the persistence-backed commands use the configured PostgreSQL UoW.

## The transaction boundary — the platform commits, not the plugin

This is the single most important runtime rule. The SDK exposes one small
seam, `TransactionRunnerPort.run(operation)`, and `Kernel.context_for()` binds
one context-owned adapter to each plugin's internal unit of work:

```python
uow = self._require_uow_factory()()
transactions = SqlTransactionRunner(uow)
owner = TransactionOwner(commit=uow.commit, rollback=uow.rollback)
self.registries.contracts.register_transaction_owner(plugin_id, owner)
```

A direct plugin write uses the adapter:

```python
def record_attendance(self, request):
    return self.context.transactions.run(lambda: self._service.record_attendance(request))
```

The adapter begins the transaction, executes the operation, and commits only
after a normal return. If begin, the operation, or commit raises, it rolls back
and re-raises; a rollback failure is attached as a note to the original error
and poisons the cached UoW so no later operation can commit. This is a deep
Module: the plugin learns one operation-shaped method, while the core retains
the unit-of-work implementation. Plugin-owned tables use the restricted
`context.persistence` Adapter, never the raw session.

A bound contract handler takes the other path: it calls its uncommitted
internal implementation, and `InMemoryContractRegistry._invoke_one()` remains
the outer transaction owner. A handler must not call
`context.transactions.run`; that would nest the same platform transaction.
The registry commits once after a normal handler return and rolls back when the
handler or its commit fails. The explicit owner is registered only after
initialization, subscription binding, and contract binding succeed; an
`on_enable` failure unregisters it during cleanup. It is unregistered on disable
and registered again on re-enable.

Consequences:

- A plugin **never** receives a commit, rollback, or unit-of-work lifecycle.
- Direct writes, audit records, and outbox envelopes share one transaction;
  a failed publication leaves none of them visible to a fresh transaction.
- A **disabled** plugin has no transaction owner and no binding, so its
  contracts are genuinely uncallable (`invoke` raises `NotFoundError`).

See [EVENT_SPEC.md](EVENT_SPEC.md) for the outbox half of this guarantee.

## Clusters are a graph, not a tree

Clusters group plugins by **business coherence** only. Explicitly *not*:
permission inheritance, dependency inheritance, or a database foreign-key graph
(`contract.md` §6).

- Cluster **membership is not a dependency** — validated as such:
  `check_dependencies()` in `infrastructure/registry/validation.py` looks only
  at `requires_plugins`, never at `cluster_id`.
- The actual communication relationships are created by **contracts and
  events**, not by cluster topology. Payroll may consume contracts from many
  clusters; Report Studio may consume datasets from many clusters; a
  notification plugin may subscribe to events from many clusters. High
  connectivity, low coupling.

See [CLUSTER_SPEC.md](CLUSTER_SPEC.md).

## The SDK boundary

A plugin may import **only** `atlas_sdk`. Everything else — `atlas_core.*`,
another plugin's package, core ORM tables — is off-limits
([CORE_CONSTITUTION.md](CORE_CONSTITUTION.md) § 2, § 3).

What the SDK exports (`src/atlas_sdk/__init__.py`): `Plugin`, `PluginManifest`,
`ClusterManifest`, `ModuleDeclaration`, `PluginContext` + its published Ports,
`Contract` / `ContractDeclaration` / `ContractId` / `ContractImplementation`,
`DomainEvent` / `EventEnvelope` / `EventId`, `CapabilityId`, `Command` /
`Query` (+ handlers), 5 registry Ports, the value types, and the full error
hierarchy. See [PLUGIN_SDK.md](PLUGIN_SDK.md).

## Persistence

- PostgreSQL is the only supported runtime and test database (`contract.md` §3, §22).
- The local service is defined in `docker-compose.yml` and starts with
  `docker compose up -d`.
- Configure the runtime with:

  ```text
  ATLAS_DATABASE_URL=postgresql+psycopg://atlas:atlas@localhost:5433/atlas_hq
  ATLAS_DATABASE_SCHEMA=atlas
  ```

  `ATLAS_DATABASE_SCHEMA` defaults to `atlas`.
- Tests require `ATLAS_TEST_DATABASE_URL`; it may use the same local service or
  a separately configured PostgreSQL database. Each test uses an isolated
  PostgreSQL schema.
- URLs must use `postgresql+psycopg`; there is no alternate database fallback or
  substitute.
- Core tables, owned by core alone, logical schema `atlas`: `employee`,
  `organization`, `workplace`, `job`, `assignment`, `audit`, `outbox`.
  `outbox` deliberately lives in the same schema as the business tables.
- Plugins never touch these tables.

Last updated: 2026-09-24
