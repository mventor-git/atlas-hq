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
                  │  PluginContext · 15 service Ports · 5        │
                  │  registry Ports · error hierarchy            │
                  └──────────────▲───────────────▲───────────────┘
        plugins import only this  │               │ core implements every port
                                 │               │  (never the reverse)
src/atlas_plugins                 │     src/atlas_core
  atlas_demo, atlas_demo_consumer │       domain          (entities, enums)
  report_studio, workforce_summary│       application     (services + ports)
  attendance_summary              │       infrastructure (persistence, events,
                                  │                        discovery, registries)
                                  │       kernel.py        (boot + lifecycle)
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
| `atlas_plugins` | shipped plugins | 5 plugins, each one directory, each registered by entry point |
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

The CLI mirrors this exactly: `atlas-hq boot|plugins|clusters|contracts|
capabilities|events|enable|disable|audit|report` (`src/atlas_hq/cli.py`).

## The transaction boundary — the platform commits, not the plugin

This is the single most important runtime rule. From `Kernel.context_for()`:

```python
# The platform — not the plugin — owns the transaction (contract §21).
self.registries.contracts.register_committer(plugin_id, uow.commit)
```

And in `InMemoryContractRegistry._invoke_one()`:

```python
result = instance.handle(request)  # plugin code runs
...
if commit is not None:
    commit()  # the *platform* commits
```

Consequences:

- A plugin **never** manages a transaction itself. It calls `context.*` ports
  and returns; the platform commits the state change and any outbox event
  together, or not at all.
- A handler that raises is rolled back (`_rollback_safely(commit)` walks the
  bound method to `uow.rollback`) — no half-applied state.
- A **disabled** plugin has no committer and no binding, so its contracts are
  genuinely uncallable (`invoke` raises `NotFoundError`).

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
`ClusterManifest`, `ModuleDeclaration`, `PluginContext` + 15 service Ports,
`Contract` / `ContractDeclaration` / `ContractId` / `ContractImplementation`,
`DomainEvent` / `EventEnvelope` / `EventId`, `CapabilityId`, `Command` /
`Query` (+ handlers), 5 registry Ports, the value types, and the full error
hierarchy. See [PLUGIN_SDK.md](PLUGIN_SDK.md).

## Persistence

- PostgreSQL is the **contractual primary** (`contract.md` §3, §22).
- The current adapter is **SQLite**: default URL `sqlite:///atlas.db`
  (`infrastructure/persistence/session.py`). Reason: no Postgres server is
  reachable on the development machine. The swap is one URL — set
  `ATLAS_DATABASE_URL` to a `postgresql+psycopg://` URL; no core or application
  code changes.
- Core tables, owned by core alone, logical schema `atlas`: `employee`,
  `organization`, `workplace`, `job`, `assignment`, `audit`, `outbox`.
  `outbox` deliberately lives in the same schema as the business tables.
- Plugins never touch these tables.

Last updated: 2026-09-23
