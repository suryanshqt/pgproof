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
- `store` may import `domain`, `ports`, and `store`, and is the only layer besides
  `contracts` that touches the filesystem outside a composition root
- `cli` and `local_api` are composition roots and may import any layer

`domain`, `ports`, `application`, and `rules` may not import infrastructure libraries
(Click, FastAPI, Docker, psycopg, SQLAlchemy, SQLModel, Alembic, pglast).

The check fails closed: a new top-level package under `src/pgproof/` must be given an
explicit rule in `ALLOWED_INTERNAL` and `BANNED_EXTERNAL` before its tests pass.

## Artifact contracts

`src/pgproof/domain/` holds the frozen Pydantic transport and identity models.
They are pure: no filesystem access, no adapter, and no library other than
Pydantic and the standard library, all enforced by
`tests/unit/test_dependency_boundaries.py`.

Generated and frozen artefacts live under `contracts/`; see
[`contracts/README.md`](contracts/README.md).

| Purpose | Command |
|---|---|
| Regenerate the JSON Schemas | `uv run python scripts/generate_contracts.py --write` |
| Check the schemas for drift | `uv run python scripts/generate_contracts.py --check` |
| Install the TypeScript toolchain | `cd contracts/types && npm ci` |
| Regenerate the TypeScript types | `cd contracts/types && npm run generate` |
| Check the types for drift | `cd contracts/types && npm run check` |
| Compile the generated types | `cd contracts/types && npm run compile` |

Both generators are byte-stable, and CI fails on drift in either. Changing a
model therefore requires regenerating both, which is intentional: the contract is
reviewed, not silently regenerated.

Fixtures under `contracts/fixtures/` are **committed data, not build output**. A
model change that breaks one is meant to fail the suite. Edit them by hand.

Contract versioning is governed by
[ADR 0001](docs/adr/0001-contract-versioning.md). A major bump requires a new ADR.

## Ground-truth fixtures

`fixtures/` holds the broken and clean demo repositories that the rule engine is
judged against, plus their `EXPECTED.yaml` oracles. See
[`fixtures/README.md`](fixtures/README.md).

They are analysed as data. They are never imported or installed by this
repository's test suite, and they are excluded from Ruff; mypy and pytest do not
reach them because both are scoped to `src` and `tests`. Do not lint or reformat
them, because that would erase the defects they exist to carry.

`tests/unit/test_fixture_oracle.py` enforces the fixture contract without
executing fixture code: every oracle source reference must resolve to real text,
`demo-clean` must report no headline finding, the two fixtures must differ only in
the planted cases, and no `EXPECTED.yaml` may state a measured quantity.

To work on the fixtures by hand you need Docker. Each fixture carries its own
`pyproject.toml`, `.python-version`, and `uv.lock` pinning SQLAlchemy, Alembic,
psycopg, and pytest exactly; none of them is a dependency of pgproof itself. Run
`uv sync --all-groups --frozen` inside the fixture directory, never a fresh
resolution, and start PostgreSQL from the recorded image digest rather than the
floating version tag. The exact procedure is in
[`fixtures/demo-broken/MEASUREMENT.md`](fixtures/demo-broken/MEASUREMENT.md).

Measured numbers are attributed to those pins, so changing them invalidates
`MEASUREMENT.md`. Re-measure and record what you observe; never carry a number
forward across a stack change.

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
