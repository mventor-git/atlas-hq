# Core Constitution

The inviolable rules of the platform. Every rule below is enforced by code that
exists today; the enforcing file is named. Violate one and the platform rejects
or isolates the plugin rather than silently misbehaving.

Authority: `contract.md` §2, §5, §9, §10, §12, §13, §19, §20, §21, §22, §30.

## Rule 1 — No orphan plugins

> No Plugin may exist without belonging to a Cluster.

- Enforced: `cluster_id` is a mandatory, non-blank field on `PluginManifest`
  (`atlas_sdk/manifest.py`); `validate_manifest()` in
  `atlas_core/infrastructure/registry/validation.py` rejects a blank one with
  *"cluster_id is required: a plugin may not exist without a cluster"*.
- A second check rejects a `cluster_id` that is not a registered cluster
  (`validate_cluster()`): an unknown cluster id is refused even if it is
  non-blank.

## Rule 2 — No cross-plugin implementation access

> Plugins must NOT directly depend on another Plugin's implementation.

Forbidden: `import another_plugin`, joining another plugin's tables, reaching
another plugin's objects. Sanctioned channels, in order:

| Need | Channel | SDK surface |
|---|---|---|
| Information now | **Query** / contract `invoke` | `context.invoker.invoke(...)` |
| Something happened | **Event** | `context.events.publish`, `context.dispatcher.subscribe` |
| Who may act | **Capability** | `context.authorization.check` |
| Which records | **Scope** | `context.scope.resolve` / `narrow` |
| Mutate core state | **Core service port** | `context.people`, `context.jobs`, … |

Proven mechanically by `tests/test_demo_plugin_b.py`, which boots the real
distribution and drives Plugin B without importing Plugin A's package.

## Rule 3 — Single source of truth

Every important business fact has **one owner**. Consuming a fact does not
transfer ownership: Payroll consumes Attendance's `payroll.attendance_input`
contract and still owns nothing about attendance records.

Ownership today: core owns people, organization, jobs, assignments, audit and
the outbox (`atlas_core/infrastructure/persistence/orm.py`, schema `atlas`).
A plugin's own state (e.g. `AtlasDemoConsumerPlugin.observed`) is private to
that plugin and reachable by others **only** through a contract.

## Rule 4 — Query vs event, both, neither is a table read

- **Query** when something needs information **now**: `get_employee`,
  `list_employees`, `assignments_for`, `policy.evaluate`.
- **Event** when something **happened**: `demo.greeted`, `report.generated`.
- Events are not a universal replacement for queries, and direct table access
  is not a replacement for either.

See [EVENT_SPEC.md](EVENT_SPEC.md) § when-event-vs-query and
[CONTRACT_SPEC.md](CONTRACT_SPEC.md).

## Rule 5 — The platform owns the transaction

A plugin never commits, rolls back, or opens a transaction. `Kernel.context_for()`
registers `uow.commit` as the plugin's committer with the contract registry;
`InMemoryContractRegistry._invoke_one()` commits after `handle()` returns and
rolls back if it raises. Therefore a business state change and the event it
published commit together or not at all (`contract.md` §21).

## Rule 6 — The core is a service layer, not a utilities folder

The core owns platform-wide truth and infrastructure and **exposes it through
explicit ports**. A plugin holds one `PluginContext` and that is its entire
reach into the core (`contract.md` §2). The 15 service Ports are listed in
[PLUGIN_SDK.md](PLUGIN_SDK.md).

## Rule 7 — Validation preceds visibility

A manifest is validated **before** the plugin is registered and before its
declarations become visible to any other plugin. A malformed declaration never
enters a registry (`kernel._validate` runs before `_register`).

## Rule 8 — A broken plugin must not corrupt the core

Any failure during discovery, validation, dependency checking, registration,
initialization, binding, or enabling marks the plugin `FAILED` with a recorded
reason and the boot continues. The failure is **observable**, not invisible:
`InMemoryPluginRegistry` keeps FAILED ids visible with `failure_reason()`, and
`BootResult.failed` lists them for the CLI and tests.

## Rule 9 — Smart composition is deterministic

Composability is based on metadata — capabilities, typed contracts, module
declarations, event declarations, the registry — never on inspecting arbitrary
tables or guessing field meanings (`contract.md` §14). Report Studio's entire
discovery is one registry lookup plus `invoke_all` (`report_studio/__init__.py`,
`render()`).

## Rule 10 — Fixed plugins are allowed; composable plugins are required

- **Fixed / domain-specific** plugins may hardcode a known contract id (e.g. a
  report that always calls `construction.daily_workforce`). Valid.
- **Composable** plugins depend on declared capabilities/contracts, never on an
  implementation name. Both classes are first-class; the platform must support
  both without changing the plugin contract.

See [PLUGIN_SPEC.md](PLUGIN_SPEC.md) § fixed-vs-composable.

## What is not yet implemented

The rules above are enforced today. These core services from `contract.md` §2
are **skeletons — callable, in-memory, not persisted**:

| Service | Status | File |
|---|---|---|
| Workflow engine | skeleton: in-memory state machine, no persistence or compensation | `application/workflow.py` |
| Notification engine | skeleton: in-memory out-tray | `application/notification.py` |
| Scheduling engine | skeleton: in-memory job list | `application/scheduling.py` |
| Case engine | not implemented (Workflow is the nearest thing) | — |
| Document / evidence foundation | not implemented | — |
| Effective-dated policies | implemented (in-memory store) | `application/policy.py` |

The ports are stable; the backing stores are the only thing that changes.

Last updated: 2026-09-23
