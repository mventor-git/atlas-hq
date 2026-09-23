# Module Specification

A module is a **functional component inside a plugin** — the fourth level,
below PLUGIN. A plugin declares its modules; each module declares what it
provides, consumes, publishes, subscribes to, requires and supports.

Authority: `contract.md` §15.

## Declaration shape — the real fields

`atlas_sdk.manifest.ModuleDeclaration` (frozen dataclass):

| Field | Type | Default | Meaning |
|---|---|---|---|
| `module_id` | `str` | required | dotted id, unique within the plugin |
| `provides` | `tuple[str, ...]` | `()` | contract/capability ids this module offers |
| `consumes` | `tuple[str, ...]` | `()` | ids this module uses |
| `publishes` | `tuple[EventId, ...]` | `()` | events this module emits |
| `subscribes` | `tuple[EventId, ...]` | `()` | events this module reacts to |
| `requires` | `tuple[str, ...]` | `()` | ids that must be present for this module to work |
| `supports` | `tuple[str, ...]` | `()` | ids this module can use when present |

All six are plain string/`EventId` tuples. A module is **declaration only** —
no behaviour, no imports. The kernel inspects these before the plugin is
enabled.

## Worked examples (verbatim from the codebase)

```python
# src/atlas_plugins/atlas_demo/__init__.py
ModuleDeclaration(
    module_id="demo.greeting",
    provides=("demo.greeting",),
    consumes=("people.employee.read",),
    publishes=(DEMO_GREETED,),      # EventId("demo.greeted")
    requires=(),
    supports=(),
)
```

```python
# src/atlas_plugins/report_studio/__init__.py
ModuleDeclaration(
    module_id="report.compose",
    provides=("report.compose",),
    consumes=("reporting.dataset",),
    publishes=(REPORT_GENERATED,),
)
```

```python
# src/atlas_plugins/attendance_summary/__init__.py
ModuleDeclaration(
    module_id="attendance.summary",
    provides=("reporting.dataset",),
    consumes=("people.employee.read", "employee.assignment"),
)
```

Compare with `contract.md` §15's `workplace.workforce` and `attendance.daily`
examples — same six-field shape.

## Validation

- Duplicate `module_id` within one manifest is rejected
  (`validate_manifest()`: *"duplicate module ids"*).
- `requires` / `supports` are **declarative metadata today** — no code path
  currently rejects a module whose `requires` ids are unmet. They document
  intent for installers, report composers, and future compatibility checks.
  The hard dependency mechanism is the plugin-level `requires_plugins`.

## Modules vs contracts vs capabilities

| Concept | Declared where | Runtime effect today |
|---|---|---|
| Module | `manifest.modules[].module_id` | indexed in the plugin registry (via `manifest.module_ids()`) |
| Contract | `module.provides` + `manifest.provides_contracts` | **invokable** through `context.contracts` / `context.invoker` |
| Capability | `manifest.provides_capabilities` | checked by `context.authorization.check` |
| Event | `module.publishes` / `module.subscribes` | registered in the event registry, dispatched by the bus |

A module *names* an id; the plugin-level declarations (contracts, capabilities,
events) are what actually register it. Put the id in `provides` and the typed
`ContractDeclaration` in `manifest.provides_contracts`; both are needed for the
contract to be discoverable and callable.

Last updated: 2026-09-23
