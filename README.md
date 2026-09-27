# Atlas-HQ

HR-centered modular plugin platform. PostgreSQL is the only supported runtime and test database.

Foundation layout:

- `src/atlas_sdk/` — the stable Plugin SDK boundary. Plugins may import **only** this package.
- `src/atlas_core/` — the platform: domain, application ports + services, infrastructure
  (persistence, outbox event bus, entry-point plugin discovery, registries) and the boot kernel.
- `src/atlas_hq/` — admin CLI and report commands.
- `tests/` — mirrors `src`.
- `docs/` — architecture, plugin, event, and development documentation.
- [`docs/PLATFORM_VISION.md`](docs/PLATFORM_VISION.md) — a non-normative
  introduction to the Atlas product family. It decides nothing.

## Shipped plugins

The editable distribution registers nine plugins through the `atlas.plugins`
entry-point group: `atlas_demo`, `atlas_demo_consumer`, `attendance_operations`,
`attendance_summary`, `construction_reporting`, `report_studio`,
`self_reporting`, `workforce_summary`, and `workplace_operations`.

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

The `postgres` service publishes `127.0.0.1:5433` and nothing else: the host
port binds to loopback only (`contract.md` §40.3), so the database is reachable
from this machine and from nowhere on the network.

Set the runtime and test database configuration:

```text
ATLAS_DATABASE_URL=postgresql+psycopg://atlas:atlas@127.0.0.1:5433/atlas_hq
ATLAS_TEST_DATABASE_URL=postgresql+psycopg://atlas:atlas@127.0.0.1:5433/atlas_hq
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

## Web console

The browser console lives in [`web/`](web/README.md) and talks to
`src/atlas_web` over the opaque `atlas_session` cookie and nothing else. The
API contract is [docs/WEB_API.md](docs/WEB_API.md); the design tokens are
contract §39.

```bash
# 1. create the operator the dev login acts as (once per database)
ATLAS_DATABASE_URL=postgresql+psycopg://atlas:atlas@127.0.0.1:5433/atlas_hq \
  .venv/Scripts/atlas-hq.exe operator-init \
  --principal atlas.local.operator \
  --organization org_local \
  --create-organization \
  --organization-name "Atlas Local" \
  --grant authorization.manage \
  --grant report.render \
  --grant self.monthly.report.view

# 2. the API (from the repository root, in one shell)
ATLAS_DATABASE_URL=postgresql+psycopg://atlas:atlas@127.0.0.1:5433/atlas_hq \
ATLAS_WEB_DEV_LOGIN=1 \
ATLAS_WEB_OPERATOR_PRINCIPAL=atlas.local.operator \
  .venv/Scripts/python.exe -m atlas_web --port 8000

# 3. the console (in another shell)
cd web
npm ci --ignore-scripts && npm rebuild esbuild @tailwindcss/oxide
npm run dev                               # http://127.0.0.1:5175, /api -> 127.0.0.1:8000
```

`--ignore-scripts` plus the named rebuild is how the console is installed
everywhere else too — CI, [`install.ps1`](install.ps1) and
[docs/INSTALL.md](docs/INSTALL.md): no dependency's install script runs while
the tree is installed, and the only two packages that need building
(`esbuild` and `@tailwindcss/oxide`, the ones `web/package.json#allowScripts`
names) are then built by name. No npm prompt is answered at any point.

Step 1 is what the `No operator principal is configured` message on the sign-in
page is telling you: `POST /api/session` refuses until the principal named by
`ATLAS_WEB_OPERATOR_PRINCIPAL` exists and is active. `--principal` and
`--organization` are both required and there is no default, and each `--grant` is
a capability named out loud — an unrecognised name is refused, not skipped.
`--create-organization` is the one opt-in write, and only because a database
that is reachable but empty has no organization id to name: it creates the
`--organization` you gave under the `--organization-name` you gave, refuses
without itself, and leaves an organization that already exists untouched.

The dev server is pinned to 5175 with `strictPort`, and proxies `/api`, so the
browser only ever talks to its own origin and the `SameSite=Strict` cookie needs
no CORS exception. It fails rather than drifting to 5176 if the port is busy.
`ATLAS_WEB_API_URL` points the proxy elsewhere; it carries no authority.
