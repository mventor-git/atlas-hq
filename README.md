# Atlas-HQ

HR-centered modular plugin platform. Greenfield; not a continuation of atlas-bot (legacy/archived).

Foundation layout:

- `src/atlas_sdk/` — the stable Plugin SDK boundary. Plugins may import **only** this package.
- `src/atlas_core/` — the platform: domain, application ports + services, infrastructure
  (persistence, outbox event bus, entry-point plugin discovery, registries) and the boot kernel.
- `src/atlas_hq/` — admin app shell (CLI in D1).
- `tests/` — mirrors `src`.
- `docs/` — filled in D3.

## Quick commands

```bash
uv venv --python 3.12 .venv          # create venv (or: python -m venv .venv)
uv pip install -e ".[dev]"           # editable install + pytest/ruff/pyright

.venv/Scripts/pytest                # tests
.venv/Scripts/ruff check src tests  # lint
.venv/Scripts/ruff format --check src tests
.venv/Scripts/pyright               # type check
atlas-hq                            # boot kernel, print registry state
```
