# Contract Specification

A **contract** is the only sanctioned channel for plugin-to-plugin
communication. It is a typed, versioned, registry-discoverable agreement
between a provider and any number of consumers — neither side knows the other's
module.

Authority: `contract.md` §9, §13, §14.

## The two halves

| Half | Type | Lives in | Purpose |
|---|---|---|---|
| Declaration | `ContractDeclaration` | `atlas_sdk/contract.py` | static metadata: id, version, schema, description |
| Implementation | `Contract` (Protocol) + `ContractImplementation` | `atlas_sdk/contract.py` | the runtime handler a plugin binds at enable |

```python
@dataclass(frozen=True)
class ContractDeclaration:
    contract_id: ContractId
    version: str = "1.0"
    schema: Mapping[str, object] = field(
        default_factory=dict
    )  # JSON-schema-ish; NOT validated at runtime in D1
    description: str = ""


class Contract(Protocol[RequestT, ResponseT]):
    contract_id: ContractId

    def handle(self, request: RequestT) -> ResponseT: ...
```

`ContractImplementation` is the registry record: a declaration, the providing
`plugin_id`, and the live `instance` (present only while the plugin is
ENABLED). `is_bound` is the property Gate I checks.

`ContractId` is a `NewType` over `str`. Ids are dotted strings:
`demo.greeting`, `reporting.dataset`, `payroll.attendance_input`.

## How to agree on an id without importing anything

Two plugins spell the **same literal string**. Never share a constants module —
that is implementation coupling by another name.

```python
# provider
MY_CONTRACT = ContractId("demo.greeting")

# consumer — a literal, typed so the compiler still sees ContractId
GREETING_CONTRACT = ContractId("demo.greeting")
```

`shared_contract_id(value)` exists in `atlas_sdk/contract.py` to document this
rule; it is never required. `SHARED = "shared"` is a documentation sentinel.

## Register → bind → invoke

**1. Register** (automatic, at boot). `Kernel._register()` puts every
`provides_contracts` declaration into the contract registry. From that moment
the contract is discoverable — but **not callable**.

**2. Bind** (on enable). The plugin's `bind_contracts()` hook:

```python
def bind_contracts(self) -> None:
    self.context.contracts.bind(MY_CONTRACT, self.manifest.plugin_id, self._handler)
```

`bind()` refuses to bind a contract the plugin never declared: *"plugin X cannot
bind Y: it declares no such contract"*.

**3. Invoke** (runtime). Through the context:

```python
response = self.context.invoker.invoke(SOME_CONTRACT, request)
```

Unbinding happens automatically at disable (`Kernel._tear_down` →
`contracts.unbind(plugin_id)`), which is what makes a disabled plugin's
contracts uncallable.

## `invoke` vs `invoke_all`

| | `invoke(contract_id, request)` | `invoke_all(contract_id, request)` |
|---|---|---|
| Returns | `object` — the single bound implementation's result | `list[object]` — every bound implementation's result |
| No binding | raises `NotFoundError` | returns `[]` |
| Order | first bound | registration order |
| Use for | fixed plugins (`contract.md` §12) | **composable** plugins (`contract.md` §13) |

`invoke` picks `bound[0]`. If several plugins bind the same contract id, `invoke`
is ambiguous by design — prefer `invoke_all` when more than one provider may
exist. Both commit through the provider's committer (see
[ARCHITECTURE.md](ARCHITECTURE.md) § transaction boundary).

## Composable discovery — the Report Studio pattern

Report Studio renders a report from every `reporting.dataset` provider that
happens to be installed. It never names, imports, or knows any provider's
plugin id:

```python
responses = self.context.invoker.invoke_all(
    REPORT_DATASET_CONTRACT,
    DatasetRequest(organization_id=...),
)
datasets = [r for r in responses if isinstance(r, DatasetResponse)]
```

The shared vocabulary lives in **the SDK**, not in a plugin:
`atlas_sdk/reporting.py` exports `REPORT_DATASET_CONTRACT` (`"reporting.dataset"`),
`REPORT_DATASET_DECLARATION`, `DatasetRequest`, `DatasetResponse`. Both
`workforce_summary` and `attendance_summary` provide that contract; Report
Studio composes both. Adding a third provider is an installation, not a code
change. This is Gate O, acceptance-tested by `tests/test_report_studio.py`.

Discovery is deterministic and metadata-driven — the registry lookup plus the
invoker. No table scanning, no field guessing (`contract.md` §14).

## Registry queries

`ContractRegistryPort` (`atlas_sdk/registry.py`), implemented by
`InMemoryContractRegistry`:

| Method | Returns |
|---|---|
| `get(contract_id)` | the `ContractImplementation` (raises `NotFoundError`) |
| `all()` | every implementation, with bound instance attached |
| `exists(contract_id)` | bool |
| `implementations_of(contract_id)` | every implementation of a contract |
| `provided_by(plugin_id)` | every contract a plugin provides |

Every implementation is kept, not just the first — composability depends on a
consumer being able to learn there may be several.

## Response typing for consumers

The consumer knows the contract's **id**, not the provider's response class.
`invoke` returns `object`; the consumer narrows with `isinstance` against an
SDK-published shape (`DatasetResponse`) or treats the result structurally. See
`AtlasDemoConsumerPlugin.call_greeting` returning `object` deliberately.

## Where contracts appear in a manifest

```python
provides_contracts = (ContractDeclaration(contract_id=..., version="1.0", schema={...}),)
consumes_contracts = (ContractId("reporting.dataset"),)
```

Declaring `consumes_contracts` is **not** a hard dependency — it is metadata
that makes the consumer's needs discoverable. Nothing currently rejects a
consumer whose contract has no provider; `invoke` raises at runtime instead.
Hard dependencies go in `requires_plugins`.

Last updated: 2026-09-23
