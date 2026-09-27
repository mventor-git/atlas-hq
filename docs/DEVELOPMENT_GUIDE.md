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
| `src/atlas_plugins/` | the 9 shipped plugins, one directory each |
| `src/atlas_hq/cli.py` | the `atlas-hq` admin command |
| `tests/` | mirrors src; `conftest.py` holds the fixtures, `synthetic.py` builds fake distributions |
| `docs/` | this directory |
| `contract.md` | the binding directive — 39 sections |

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

Discovery walks `importlib.metadata.distributions()` per distribution rather than
using the `entry_points(group=...)` selector, because on Python 3.12 the selector
collapses same-named entry points across distributions into one. Identical
distribution/entry-point metadata records are deduplicated. Distinct
distributions claiming the same plugin ID are reported as a conflict for that
plugin only; boot marks it `FAILED` and continues with unrelated plugins.

## Adding a cluster

Register it exactly like the seed clusters do — `ClusterManifest` through the
cluster registry. `Kernel._seed_clusters()` iterates `INITIAL_CLUSTERS` from
`atlas_core/domain/clusters.py`. Nothing about a new cluster is special-cased;
the map is extensible by design (`contract.md` §7).

## Running the checks

```powershell
$env:ATLAS_TEST_DATABASE_URL = "postgresql+psycopg://atlas:atlas@127.0.0.1:5433/atlas_hq"
& .\.venv\Scripts\python.exe -m pytest          # PostgreSQL-only tests
& .\.venv\Scripts\ruff.exe check src tests      # lint
& .\.venv\Scripts\ruff.exe format --check src tests
& .\.venv\Scripts\pyright.exe                    # type check (0 errors)
```

Ruff config (`pyproject.toml`): line-length 100, target py312, rules
`E,F,W,I,N,UP,B,SIM`. Pyright: basic mode, `include = ["src","tests"]`,
`reportMissingImports = "error"`.

## Continuous integration

`.github/workflows/ci.yml` runs the PostgreSQL-only checks against an ephemeral
PostgreSQL 16 service. The `test_engine` fixture creates and drops an isolated
`atlas_test_*` schema for each test that uses it; CI never uses production data.
Production deployment configuration is intentionally not defined yet.

The same file has a second job, `windows-scripts`, on `windows-latest`. It
parses `install.ps1`, `start-demo.ps1` and `tests/windows/verify_scripts.ps1`
with the Windows PowerShell 5.1 parser, then runs that gate, which drives both
scripts with `-DryRun` and proves the installer's own SHA-256 check by running
it against a throwaway stub bundle (§40.4). That job starts no server,
container or database and needs no secret (`contract.md` §40.6). Run the same
thing locally with:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tests\windows\verify_scripts.ps1
```

`.github/workflows/release.yml` runs on a `v*` tag push and is the only
distribution path (§40.4). It has two jobs. `windows-scripts` checks out the
tag itself on `windows-latest`, parses the three PowerShell files with the 5.1
parser, runs `tests/windows/verify_scripts.ps1`, and dry-runs both
`install.ps1` and `start-demo.ps1` — no server, no container, no secret. The
`release` job declares `needs: windows-scripts`, so a tag whose own scripts do
not validate cannot publish. It builds the tag's source ZIP with `git archive`,
writes `SHA256SUMS.txt` over the three uploaded files, and attaches exactly
four assets to the release: the ZIP, `install.ps1`, `start-demo.ps1` and
`SHA256SUMS.txt`. It holds `contents: write` and nothing else; the gate holds
`contents: read`.

`web/` is installed the same way in CI and in `install.ps1`: `npm ci
--ignore-scripts`, then `npm rebuild esbuild @tailwindcss/oxide`, then both
products are run (`esbuild --version`, `node -e "require('@tailwindcss/oxide')"`)
so a rebuild that quietly built nothing fails in CI. No npm prompt is answered
anywhere, which is what keeps the path identical under npm 10, 11 and 12.

`src/atlas_web/http.py` refuses to serve on a non-loopback host while
`ATLAS_WEB_DEV_LOGIN` is on, before the socket is bound. The switch mints a
session for a fixed principal for anybody who can reach the listener, so the
two are refused together rather than allowed to meet; `start-demo.ps1` binds
loopback, so the demo never trips it. `tests/test_web_bind_guard.py` covers it
without a database, a kernel or a socket.

Tests run from the repo root; `pyproject.toml` sets `testpaths = ["tests"]` and
`pythonpath = ["src"]`, so `src` is importable without an install for the test
run. Runtime plugin discovery needs installed distribution metadata: local
development uses the editable install above, while CI intentionally uses the
non-editable `.venv/bin/python -m pip install ".[dev]"` so it does not combine
editable and source-tree metadata.

`tests/test_discovery.py::test_installed_metadata_exposes_every_shipped_plugin`
compares the entry points in the *installed* metadata with the ones declared in
`pyproject.toml`. A stale editable install fails it, and reinstalling with
`uv pip install -e . --no-deps` fixes it. Generated `.dist-info` metadata lives
in `.venv/` and is never committed.

### Test layout

- `tests/conftest.py` — fixtures: `database_url` (real PostgreSQL test database),
  `session_factory`, `uow_factory`, `kernel`, `clean_uow`, `real_kernel`,
  `isolated_plugins`.
- `tests/synthetic.py` — writes a real `.dist-info` + module onto `sys.path` so
  `importlib.metadata` discovers a synthetic plugin exactly as it would any
  installed package. Proves discovery works without editing core.
- Unit-test kernels boot against the test-only group `atlas.test.plugins`
  (`TEST_ENTRY_POINT_GROUP`) so the 9 shipped plugins stay invisible; the
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
- `tests/test_design_token_contrast.py` — `contract.md` §39.5: parses the §39.2
  token table and measures every pair in both themes, with the three named
  exceptions and the forbidden pair checked as forbidden. No UI yet (§39.7).

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
$env:ATLAS_DATABASE_URL = "postgresql+psycopg://atlas:atlas@127.0.0.1:5433/atlas_hq"
$env:ATLAS_DATABASE_SCHEMA = "atlas"
```

`ATLAS_DATABASE_SCHEMA` defaults to `atlas`. Tests use `ATLAS_TEST_DATABASE_URL`;
set it to the same local service or a separately configured PostgreSQL database:

```powershell
$env:ATLAS_TEST_DATABASE_URL = "postgresql+psycopg://atlas:atlas@127.0.0.1:5433/atlas_hq"
```

The exact PostgreSQL-only test command is:

```powershell
& .\.venv\Scripts\python.exe -m pytest
```

The `test_engine` fixture creates and removes an isolated PostgreSQL schema for
each test that uses it. The developer database and `public` schema are not reset.

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

Last updated: 2026-09-25
