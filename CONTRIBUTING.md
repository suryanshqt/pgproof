# Contributing to pgproof

pgproof is a local-first tool. Every contribution must preserve three properties:
no telemetry, no production database connection, and no execution of project code
outside an explicitly approved isolated runner.

Read [`docs/README.md`](docs/README.md) before proposing a change. The accepted
design baseline in `docs/` and `ideation/` is authoritative; changing it requires an
ADR (see below).

## Requirements

- Python 3.11 or newer (`.python-version` pins 3.13 for development)
- [uv](https://docs.astral.sh/uv/) for dependency resolution and virtual environments
- Git

Docker and PostgreSQL are not required for the current roadmap items.

## Local development commands

| Purpose | Command |
|---|---|
| Install all dependencies from the lockfile | `uv sync --all-groups` |
| Refresh the lockfile after editing `pyproject.toml` | `uv lock` |
| Verify the lockfile is current without changing it | `uv lock --check` |
| Format | `uv run ruff format .` |
| Check formatting only | `uv run ruff format --check .` |
| Lint | `uv run ruff check .` |
| Lint with autofix | `uv run ruff check --fix .` |
| Type-check | `uv run mypy` |
| Test with coverage | `uv run pytest` |
| Run the CLI from the working tree | `uv run pgproof --help` |
| Build the sdist and wheel | `uv build` |

Run the full gate before pushing:

```bash
uv sync --all-groups
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest
uv build
```

### Validating the built package

The wheel must install and expose a working entry point without the source tree:

```bash
uv build
uv venv /tmp/pgproof-wheel-check
VIRTUAL_ENV=/tmp/pgproof-wheel-check uv pip install --no-cache dist/*.whl
/tmp/pgproof-wheel-check/bin/pgproof --version
/tmp/pgproof-wheel-check/bin/pgproof --help
```

CI runs the same gate on Linux amd64 (`ubuntu-latest`) and macOS arm64 (`macos-15`)
across Python 3.11 and 3.13.

## Repository layout

The package uses the `src` layout described in
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) section 5. Directories appear when the
roadmap item that owns them lands; this repository does not pre-create empty layers.

## Dependency boundaries

`docs/ARCHITECTURE.md` section 4 defines the layer dependency rule.
`tests/unit/test_dependency_boundaries.py` enforces it by parsing every module under
`src/` without importing it:

- `domain` may import only `domain`
- `ports` may import `domain` and `ports`
- `application` may import `domain`, `ports`, and `application`
- `rules` may import `domain` and `rules`, and performs no I/O
- `adapters` may import `domain`, `ports`, and `adapters`
- `cli` and `local_api` are composition roots and may import any layer

`domain`, `ports`, `application`, and `rules` may not import infrastructure libraries
(Click, FastAPI, Docker, psycopg, SQLAlchemy, SQLModel, Alembic, pglast).

The check fails closed: a new top-level package under `src/pgproof/` must be given an
explicit rule in `ALLOWED_INTERNAL` and `BANNED_EXTERNAL` before its tests pass.

## Branches and pull requests

Branch and title conventions come from
[`docs/PR_ROADMAP.md`](docs/PR_ROADMAP.md) section 1:

```text
PR title: [BE-07] Repository inventory
Branch:   be/07-repository-inventory
```

Work one roadmap item per pull request. Follow the preparation checklist in
`docs/PR_ROADMAP.md` section 8 and fill in
[`.github/PULL_REQUEST_TEMPLATE.md`](.github/PULL_REQUEST_TEMPLATE.md) completely,
including exact verification commands and their results.

Scope discipline is a review criterion. A change that is not required by the current
milestone gate is parked, not merged (`docs/PR_ROADMAP.md` section 7).

## Code standards

- Absolute imports only; relative imports are rejected by lint and by the boundary test.
- Public modules, classes, and functions carry type annotations; `mypy` runs in strict mode.
- Comments justify a decision, record a measurement, or name a bug they prevent. They do
  not restate the code.
- Terminal output follows [`docs/INTERFACE_DESIGN.md`](docs/INTERFACE_DESIGN.md): restrained,
  no decorative output, ASCII and no-color fallbacks, `NO_COLOR` honoured.
- Do not add a dependency that a few lines of the standard library can replace. New
  dependencies are pinned through `uv.lock` in the pull request that first imports them.

## Architectural decision records

`docs/ARCHITECTURE.md` section 16 lists the changes that require an ADR before
implementation, including any move toward a hosted service, telemetry, external
database URLs, repository mutation, or making an LLM part of evidence generation.

To add one, copy [`docs/adr/0000-template.md`](docs/adr/0000-template.md) to
`docs/adr/NNNN-short-title.md` using the next free number, and open it with the pull
request that depends on it.
