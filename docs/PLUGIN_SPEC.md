# Plugin Specification

A plugin is a Python class subclassing `atlas_sdk.Plugin` that carries a
`PluginManifest` as a class attribute and is reachable through an
`atlas.plugins` entry point.

Authority: `contract.md` §5, §12, §13, §16, §17, §18.

## Manifest fields — the real ones

`atlas_sdk.manifest.PluginManifest` (frozen dataclass). These and only these:

| Field | Type | Required | Notes |
|---|---|---|---|
| `plugin_id` | `str` | **yes** | unique; validated non-blank |
| `name` | `str` | **yes** | human label |
| `version` | `str` | **yes** | |
| `cluster_id` | `str` | **yes** | must be a registered cluster (no orphans) |
| `requires_core` | `str \| None` | no | exact version or `X.*` major series |
| `requires_plugins` | `tuple[str, ...]` | no | hard plugin dependencies (`contract.md` §5 calls these `dependencies`) |
| `modules` | `tuple[ModuleDeclaration, ...]` | no | see [MODULE_SPEC.md](MODULE_SPEC.md) |
| `provides_capabilities` | `tuple[CapabilityId, ...]` | no | who-may-act ids |
| `consumes_capabilities` | `tuple[CapabilityId, ...]` | no | may not overlap with provides |
| `provides_contracts` | `tuple[ContractDeclaration, ...]` | no | typed contracts |
| `consumes_contracts` | `tuple[ContractId, ...]` | no | literal id strings |
| `publishes_events` | `tuple[EventId, ...]` | no | |
| `subscribes_events` | `tuple[EventId, ...]` | no | |

Helper: `manifest.module_ids()` returns the tuple of module ids.

`contract.md` §5 lists the declaration shape conceptually; every field there
maps onto the above. Do not invent manifest fields — validation reads exactly
these.

## Validation — what gets rejected

`atlas_core/infrastructure/registry/validation.py::validate_manifest` rejects:

- blank `cluster_id`, `plugin_id`, `name`, or `version`
- duplicate module ids within one manifest
- a capability that is **both** provided and consumed by the same plugin
- a provided contract with a blank `contract_id`
- an unsatisfied `requires_core` (exact match or same major series via `X.*`)

Plus `validate_cluster`: an unknown `cluster_id`.
Plus `check_dependencies`: any `requires_plugins` id not registered.

`requires_core` matching is deliberately minimal (exact or `X.*`); a full
PEP 440 resolver is out of scope until a real requirement appears.

## Lifecycle states — the real enum

`atlas_sdk.plugin.PluginLifecycle`:

```python
DISCOVERED → VALIDATED → DEPENDENCIES_CHECKED → REGISTERED → INITIALIZED → ENABLED → RUNNING
                                            \→ FAILED (terminal, any stage)
DISABLED · STOPPED · UPGRADED · FAILED
```

Boot (`Kernel.boot`) covers `DISCOVERED → REGISTERED`. `Kernel.initialize`,
`Kernel.enable`, `Kernel.stop` cover the rest. `RUNNING` is set by
`Kernel.enable_all()` after a successful enable.

| State | Reached by | Effect |
|---|---|---|
| `DISCOVERED` | `_advance_to_discovered` | entry point loaded |
| `VALIDATED` | `_validate` | manifest sound, cluster known |
| `DEPENDENCIES_CHECKED` | `_check_dependencies` | `requires_plugins` present |
| `REGISTERED` | `_register` | manifest + capabilities + contracts + events indexed |
| `INITIALIZED` | `Kernel.initialize` | `initialize(context)` hook ran |
| `ENABLED` | `Kernel.enable` | contracts bound, subscriptions active |
| `RUNNING` | `enable_all` | enabled and marked running |
| `DISABLED` | `Kernel.disable` | contracts unbound, subscriptions removed |
| `STOPPED` | `Kernel.stop` | instance shut down and dropped |
| `UPGRADED` | — | defined, not yet exercised |
| `FAILED` | any failure | reason recorded; boot continues |

**Binding is what makes ENABLED meaningful**: a contract declaration is indexed
at boot, but the live handler is attached only at `bind_contracts()` and
detached at disable. `invoke` on an unbound contract raises `NotFoundError`.

## Plugin base class — the hooks

`atlas_sdk.plugin.Plugin`. Override as needed:

| Hook | When it runs | Purpose |
|---|---|---|
| `initialize(context)` | once, after registration | store the context, build handlers, `register_role` |
| `bind_contracts()` | on enable | `context.contracts.bind(contract_id, plugin_id, handler)` |
| `bind_subscriptions()` | on enable | return `{event_id: handler}`; unsubscribe is automatic |
| `on_enable()` / `on_disable()` | on transition | |
| `shutdown()` | on stop | |

`bind_subscriptions()` returns a mapping of **another plugin's published event
id** to a handler. The ids are literal strings; the publisher's module is never
imported.

## Fixed vs composable plugins

| | Fixed / domain-specific | Composable |
|---|---|---|
| Depends on | a known contract id | a declared capability/contract |
| Example | a report that always calls `construction.daily_workforce` | Report Studio asking for every `reporting.dataset` |
| Discovery | `invoker.invoke(id, req)` | `invoker.invoke_all(id, req)` |
| Allowed? | **yes** (`contract.md` §12) | **required** (`contract.md` §13) |

Both use the same manifest, same lifecycle, same entry-point registration.

## How to write one — the minimum

```python
from atlas_sdk import (CapabilityId, Contract, ContractDeclaration, ContractId,
                       DomainEvent, EventId, ModuleDeclaration, Plugin, PluginManifest)

MY_CONTRACT = ContractId("my.thing")          # the public id — spell it, don't import it
MY_EVENT    = EventId("my.thing.done")
MY_CAP      = CapabilityId("my.thing.do")

class MyContract(Contract[MyRequest, MyResponse]):
    contract_id = MY_CONTRACT
    def handle(self, request: MyRequest) -> MyResponse: ...

class MyPlugin(Plugin):
    manifest = PluginManifest(
        plugin_id="my_plugin",
        name="My Plugin",
        version="0.1.0",
        cluster_id="cluster.workforce_and_time",      # must be a registered cluster
        requires_core="0.1.0",
        modules=(ModuleDeclaration(module_id="my.thing",
                                   provides=("my.thing",),
                                   publishes=(MY_EVENT,)),),
        provides_capabilities=(MY_CAP,),
        provides_contracts=(ContractDeclaration(contract_id=MY_CONTRACT, version="1.0",
                                                description="…"),),
        publishes_events=(MY_EVENT,),
    )

    def initialize(self, context):
        self.context = context
        self._handler = MyContract(context)
        context.authorization.register_role("role.my_operator", "My Operator",
                                            frozenset({MY_CAP}))

    def bind_contracts(self):
        self.context.contracts.bind(MY_CONTRACT, self.manifest.plugin_id, self._handler)
```

Then register the entry point (this is the step that makes it discoverable —
see [DEVELOPMENT_GUIDE.md](DEVELOPMENT_GUIDE.md)):

```toml
[project.entry-points."atlas.plugins"]
my_plugin = "my_package:MyPlugin"
```

See `src/atlas_plugins/atlas_demo/__init__.py` for a complete worked example and
`src/atlas_plugins/report_studio/__init__.py` for the composable variant.

## Contract request/response typing

Two plugins that must agree on a contract agree on the **id string**, not on a
shared module. The consumer builds its own request object with the same fields;
the provider accepts it structurally (see `AtlasDemoConsumerPlugin._GreetingRequest`
and its `call_greeting` returning `object`). For shared *vocabulary* without
shared implementation, the SDK holds the shapes — that is what
`atlas_sdk/reporting.py` is for. See [CONTRACT_SPEC.md](CONTRACT_SPEC.md).

Last updated: 2026-09-23
