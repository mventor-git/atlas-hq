# Development Guide

How to add a plugin, how to verify, and where everything lives.

## Where things live

| Path | Contents |
|---|---|
| `src/atlas_sdk/` | the Plugin SDK boundary — the only package a plugin imports |
| `src/atlas_core/domain/` | domain model (entities, enums, the cluster map) |
| `src/atlas_core/application/` | application services + ports (people, org, jobs, audit, authz, scope, policy, workflow, notification, scheduling, unit of work) |
| `src/atlas_core/infrastructure/persistence/` | orm, repositories, session, `SqlUnitOfWork` |
| `src/atlas_core/infrastructure/events/` | outbox publisher + dispatcher |
| `src/atlas_core/infrastructure/discovery/` | entry-point discovery |
| `src/atlas_core/infrastructure/registry/` | in-memory registries + manifest/dependency validation |
| `src/atlas_core/kernel.py` | boot + plugin lifecycle |
| `src/atlas_plugins/` | the 8 shipped plugins, one directory each |
| `src/atlas_hq/cli.py` | the `atlas-hq` admin command |
| `tests/` | mirrors src; `conftest.py` holds the fixtures, `synthetic.py` builds fake distributions |
| `docs/` | this directory |
| `contract.md` | the binding directive — 37 sections |

## Adding a plugin — the entry point is the step that matters

1. Write the plugin class (see [PLUGIN_SPEC.md](PLUGIN_SPEC.md) § how-to-write-one).
2. **Register the entry point** in `pyproject.toml`. This is what makes it
   discoverable — no core file is ever edited to add a plugin:

   ```toml
   [project.entry-points."atlas.plugins"]
   my_plugin = "my_package:MyPlugin"
   ```

3. Reinstall the distribution so `importlib.metadata` sees it:
   `uv pip install -e . --no-deps`
4. Verify: `& .\.venv\Scripts\atlas-hq.exe boot` — the plugin appears in the
   registry report; `& .\.venv\Scripts\atlas-hq.exe enable my_plugin` moves it
   to `enabled`.

The entry-point group is `atlas.plugins`
(`PLUGIN_ENTRY_POINT_GROUP` in `src/atlas_core/infrastructure/discovery/entry_points.py`).
Discovery reads distribution metadata only — **no folder scan** (`contract.md`
§17, §30). A built-in plugin and an external package distribution look
identical from the discovery code, so the plugin contract never changes when a
plugin is later shipped as its own package.

Caveat worth knowing: discovery walks `importlib.metadata.distributions()` per
distribution rather than using the `entry_points(group=...)` selector, because
on Python 3.12 the selector collapses same-named entry points across
distributions into one. If you hand-write a `.dist-info`, give the entry point
a unique name.

## Adding a cluster

Register it exactly like the seed clusters do — `ClusterManifest` through the
cluster registry. `Kernel._seed_clusters()` iterates `INITIAL_CLUSTERS` from
`atlas_core/domain/clusters.py`. Nothing about a new cluster is special-cased;
the map is extensible by design (`contract.md` §7).

## Running the checks

```powershell
$env:ATLAS_TEST_DATABASE_URL = "postgresql+psycopg://atlas:atlas@localhost:5433/atlas_hq"
& .\.venv\Scripts\python.exe -m pytest          # PostgreSQL-only tests
& .\.venv\Scripts\ruff.exe check src tests      # lint
& .\.venv\Scripts\ruff.exe format --check src tests
& .\.venv\Scripts\pyright.exe src               # type check (0 errors)
```

Ruff config (`pyproject.toml`): line-length 100, target py312, rules
`E,F,W,I,N,UP,B,SIM`. Pyright: basic mode, `include = ["src","tests"]`,
`reportMissingImports = "error"`.

Tests run from the repo root; `pyproject.toml` sets `testpaths = ["tests"]` and
`pythonpath = ["src"]`, so `src` is importable without an install for the test
run (but discovery needs the editable install).

### Test layout

- `tests/conftest.py` — fixtures: `database_url` (real PostgreSQL test database),
  `session_factory`, `uow_factory`, `kernel`, `clean_uow`, `real_kernel`,
  `isolated_plugins`.
- `tests/synthetic.py` — writes a real `.dist-info` + module onto `sys.path` so
  `importlib.metadata` discovers a synthetic plugin exactly as it would any
  installed package. Proves discovery works without editing core.
- Unit-test kernels boot against the test-only group `atlas.test.plugins`
  (`TEST_ENTRY_POINT_GROUP`) so the 8 shipped plugins stay invisible; the
  acceptance tests use `real_kernel` (the real `atlas.plugins` group).

Every architectural concept has automated tests (`contract.md` §32): kernel,
discovery, manifest validation, plugin/cluster/capability/contract/event
registries, lifecycle, outbox + dispatcher, authorization, scope, audit,
people/org/jobs/assignments, the CLI, the two demo plugins, and Report Studio.

### Acceptance tests worth reading

- `tests/test_demo_plugin_a.py` — Gates C–N for one plugin.
- `tests/test_demo_plugin_b.py` — Gate K: B consumes A's contract without
  importing A.
- `tests/test_report_studio.py` — Gate O: two dataset providers, no provider
  named in the test or in Report Studio source.

## Database — PostgreSQL only

`contract.md` §3 and §22 require PostgreSQL. The adapter accepts only
`postgresql+psycopg` URLs; there is no alternate database fallback or
substitute.

Start the local service from `docker-compose.yml`:

```powershell
docker compose up -d
```

Configure the runtime:

```powershell
$env:ATLAS_DATABASE_URL = "postgresql+psycopg://atlas:atlas@localhost:5433/atlas_hq"
$env:ATLAS_DATABASE_SCHEMA = "atlas"
```

`ATLAS_DATABASE_SCHEMA` defaults to `atlas`. Tests use `ATLAS_TEST_DATABASE_URL`;
set it to the same local service or a separately configured PostgreSQL database:

```powershell
$env:ATLAS_TEST_DATABASE_URL = "postgresql+psycopg://atlas:atlas@localhost:5433/atlas_hq"
```

The exact PostgreSQL-only test command is:

```powershell
& .\.venv\Scripts\python.exe -m pytest
```

Tests create and remove an isolated PostgreSQL schema per test. The developer
database and `public` schema are not reset.

## The CLI

```text
atlas-hq [--entry-point-group GROUP] [--json] boot
atlas-hq plugins | clusters | contracts | capabilities | events
atlas-hq enable <plugin_id> | disable <plugin_id>
atlas-hq audit [--limit N]
atlas-hq report <organization_id> [--actor ID]
atlas-hq workplace list <organization_id> [--kind KIND]
atlas-hq workplace workforce <workplace_id>
```

Every subcommand hits the real registry or runtime — there is no command that
reports a capability the kernel does not have (`contract.md` §24). `--json`
emits machine-readable registry state.

## Conventions

- Docs cross-reference each other instead of duplicating; every doc ends with
  `Last updated: YYYY-MM-DD`.
- `# ponytail:` comments mark deliberate simplifications with a known ceiling
  and the upgrade path (e.g. the minimal `requires_core` matcher).
- Core tables are owned by core alone; plugins never read or join them
  (`contract.md` §9, §22).

Last updated: 2026-09-24
