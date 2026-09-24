# Atlas-HQ

HR-centered modular plugin platform. PostgreSQL is the only supported runtime and test database.

Foundation layout:

- `src/atlas_sdk/` — the stable Plugin SDK boundary. Plugins may import **only** this package.
- `src/atlas_core/` — the platform: domain, application ports + services, infrastructure
  (persistence, outbox event bus, entry-point plugin discovery, registries) and the boot kernel.
- `src/atlas_hq/` — admin CLI and report commands.
- `tests/` — mirrors `src`.
- `docs/` — architecture, plugin, event, and development documentation.

## Shipped plugins

The editable distribution registers eight plugins through the `atlas.plugins`
entry-point group: `atlas_demo`, `atlas_demo_consumer`, `attendance_operations`,
`attendance_summary`, `construction_reporting`, `report_studio`,
`workforce_summary`, and `workplace_operations`.

## CLI inventory

`python -m atlas_hq.cli` accepts the global `--entry-point-group` and `--json`
options. Registry commands are `boot`, `plugins`, `clusters`, `contracts`,
`capabilities`, and `events`. Database-backed commands are `enable`, `disable`,
`audit`, `report`, and `workplace list` / `workplace workforce`.

## Local PostgreSQL

Start the service from `docker-compose.yml` before running database-backed commands:

```bash
docker compose up -d
```

Set the runtime and test database configuration:

```text
ATLAS_DATABASE_URL=postgresql+psycopg://atlas:atlas@localhost:5433/atlas_hq
ATLAS_TEST_DATABASE_URL=postgresql+psycopg://atlas:atlas@localhost:5433/atlas_hq
ATLAS_DATABASE_SCHEMA=atlas
```

`ATLAS_TEST_DATABASE_URL` may use a separate PostgreSQL database when one is
configured. There is no alternate database fallback or substitute.

## Continuous integration

The [development guide](docs/DEVELOPMENT_GUIDE.md#continuous-integration)
documents the PostgreSQL-only CI workflow. Production deployment configuration
is intentionally not defined yet.

## Quick commands

For local development, use the editable install below. CI intentionally uses the
non-editable `.venv/bin/python -m pip install ".[dev]"` command to avoid combining
editable and source-tree metadata.

```bash
uv venv --python 3.12 .venv          # create venv (or: python -m venv .venv)
uv pip install -e ".[dev]"           # local editable install + pytest/ruff/pyright

.venv/Scripts/python.exe -m pytest  # PostgreSQL-only tests
.venv/Scripts/ruff check src tests  # lint
.venv/Scripts/ruff format --check src tests
.venv/Scripts/pyright               # type check
atlas-hq                            # boot kernel, print registry state
```
