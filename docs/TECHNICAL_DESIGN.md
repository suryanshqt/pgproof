# pgproof technical design

**Status:** accepted implementation baseline  
**Companion documents:** `PRODUCT_SPEC.md`, `ARCHITECTURE.md`, `INTERFACE_DESIGN.md`, `PR_ROADMAP.md`

## 1. Technology baseline

### Backend

- Python 3.11+
- Click CLI
- Pydantic v2 transport/config models and generated JSON Schema
- frozen dataclasses or Pydantic frozen domain models
- psycopg 3
- PostgreSQL-derived parsing via pglast/libpg_query
- SQLAlchemy event API for the pytest capture plugin
- Docker Engine API for disposable runners/databases
- FastAPI loopback server and server-sent events
- pytest, Hypothesis, Ruff, mypy, and coverage gates

### Frontend

- React + TypeScript
- Vite
- React Flow for interactive schema/operation graphs
- generated TypeScript contract types
- Vitest + Testing Library
- Playwright for end-to-end flows
- product-owned CSS tokens and accessible primitives; no dependency-heavy dashboard kit

Versions are pinned in `BE-01` and `FE-01` after compatibility spikes. This document defines capabilities rather than stale version numbers.

## 2. CLI contract

```text
pgproof doctor [PATH] [--json]
pgproof inspect PATH [--format terminal|json] [--force]
pgproof configure PATH [--non-interactive]
pgproof capture PATH -- COMMAND [ARGS...]
pgproof review PATH [--scenario launch|growth|availability]
pgproof verify PATH [--finding ID] [--scale NAME]
pgproof ui PATH [--no-open] [--keep-open]
pgproof report PATH [--static] [--check-share]
pgproof reproduce PROOF_DIR
pgproof clean PATH [--runs] [--containers]
```

### Global behavior

- `--help` describes execution and network behavior for every command.
- `--json` writes one machine-readable result to stdout and diagnostics to stderr.
- Terminal output detects color/Unicode support and has plain ASCII/no-color fallbacks.
- `NO_COLOR` is honored.
- Non-interactive mode never prompts and fails with the missing decision.
- Findings do not change the process exit code in v1; command execution status does.

### Exit codes

| Code | Meaning |
|---:|---|
| 0 | Command completed and its output contract is valid |
| 2 | Invalid arguments or configuration |
| 3 | Required environment capability unavailable |
| 4 | Approved migration/test/benchmark command failed |
| 5 | Artifact incompatible, corrupt, or incomplete |
| 6 | User cancellation |
| 7 | Unexpected internal error; bug report bundle available |

## 3. Configuration model

`pgproof.toml` is project-owned and safe to commit. Secrets and private binds never belong in it.

```toml
config_version = 1

[project]
orm = "sqlalchemy"
migrations = "alembic"
postgres_version = "17"
base_ref = "main"

[runner]
image = "storefront-dev@sha256:..."
migration_command = ["alembic", "upgrade", "head"]
database_url_env = "DATABASE_URL"
environment_allowlist = ["APP_ENV"]
network = false
cpu = 2
memory = "2GB"
pids = 256
timeout_seconds = 900

[context]
critical_operations = ["checkout", "list tenant orders"]
read_write_ratio = "80:20"
peak_requests_per_second = 100
tenant_model = "shared_schema_tenant_id"
read_after_write = ["checkout", "invoice-created"]
rpo = "5m"
rto = "30m"

[dataset]
seed = "82f3d1"
epoch = "2026-01-01T00:00:00Z"
scales = ["small", "target"]

[dataset.rows.small]
users = 1_000
orders = 10_000

[dataset.rows.target]
users = 100_000
orders = 1_000_000

[verification]
warmups = 3
samples = 7
max_candidates_per_query = 5
min_absolute_saving_ms = 5
min_relative_improvement = 1.20
max_iqr_fraction = 0.20
statement_timeout_ms = 30_000
```

Validation rules:

- unsupported config major version fails;
- unknown keys warn in interactive mode and fail under `--strict-config`;
- scales require explicit per-table row counts for relevant tables;
- resource and timeout limits have safe minimums/maximums;
- arbitrary database URLs are not accepted;
- migration/test execution requires a runner image or build configuration;
- context may remain unknown, but dependent recommendations become blocked/advisory.

## 4. Transport envelope

Every top-level artifact uses:

```json
{
  "schema_version": "1.0",
  "tool_version": "0.1.0",
  "artifact_type": "schema",
  "created_at": "2026-09-12T12:00:00Z",
  "run_id": "01J7...",
  "inputs": {"repository": "sha256:..."},
  "data": {}
}
```

Rules:

- RFC 3339 UTC timestamps;
- SHA-256 prefixed hashes;
- repository-relative POSIX paths;
- decimal values serialized as strings when exactness matters;
- durations serialized as integer microseconds in raw evidence and formatted at presentation;
- stable enum strings use lowercase snake case;
- additive minor schema changes allowed; breaking changes increment major.

## 5. Repository inventory

`inspect` begins with a bounded inventory:

- respects `.gitignore` plus pgproof exclusions;
- never follows symlinks outside the selected root;
- limits file size and total bytes parsed;
- identifies `pyproject.toml`, Alembic configs/directories, SQLAlchemy imports, test layout, Docker files, and likely app roots;
- records content hashes for relevant files;
- excludes virtual environments, dependencies, build output, VCS internals, and `.pgproof`;
- reports skipped files and reasons.

Repository-relative source locations are content-hash-backed so stale line references can be detected.

## 6. Static Alembic analysis

The parser reads Python AST without importing modules. It supports direct calls for common operations:

- create/drop/rename table;
- add/drop/alter column;
- primary, foreign, unique, and check constraints;
- create/drop index;
- enum and raw SQL markers;
- revision/down_revision/branch labels/dependencies.

Dynamic values, helper wrappers, conditionals, loops, imported constants, and `op.execute` payloads not safely resolved become `UnresolvedMigrationOp` values.

The revision graph detects roots, heads, branches, missing predecessors, cycles, and merge revisions. Multiple heads are reported; execution never auto-selects one.

Static reconstruction is provisional. It MUST NOT masquerade as final physical truth.

## 7. Static SQLAlchemy analysis

AST support targets declarative SQLAlchemy 2.x/SQLModel patterns:

- model/table name;
- mapped columns and common types;
- primary key, foreign key, nullable, unique, index, and server/default metadata;
- relationship target, cardinality hints, `back_populates`, secondary table, cascade, passive deletes, and loading strategy;
- source locations.

Dynamic declarations remain unresolved. Application import for metadata inspection is not a hidden fallback; any future runtime metadata adapter uses the isolated execution trust mode.

## 8. Physical schema reconstruction

When migration execution is approved:

1. resolve Alembic heads statically;
2. start the pinned PostgreSQL image;
3. start the network-isolated project runner;
4. pass only generated DB URL and allowlisted environment;
5. run the exact configured migration command;
6. on success, query PostgreSQL catalogs;
7. produce canonical schema-only SQL and `SchemaIR`;
8. compare static migration, ORM intent, and physical catalog;
9. stop analysis if migrations failed or schema validation is incomplete.

Catalog queries cover:

- namespaces and relations;
- columns, defaults, generated/identity properties;
- constraints and actions;
- indexes, methods, expressions, predicates, ordering, included columns;
- enum/domain types;
- partitions (observed but advisory/unsupported in v1 analysis);
- views/materialized views;
- functions/procedures, volatility, security mode, and dependencies;
- triggers;
- RLS enablement and policies;
- extensions and versions;
- comments when present.

The canonical schema snapshot is produced from the successful database, not by concatenating migration source.

## 9. Schema/code reconciliation

Objects are matched by canonical schema/table/column identity. Findings include:

- ORM-only relationship;
- physical FK without ORM relationship;
- mismatched type/nullability/default/uniqueness;
- relationship optionality inconsistent with nullability;
- cascade mismatch;
- model references missing physical objects;
- physical objects absent from known models.

The tool does not assume every physical object must have an ORM model; it asks or marks intent unknown.

## 10. Query capture

The pytest plugin registers SQLAlchemy engine-level `before_cursor_execute` and `after_cursor_execute` listeners.

Captured event fields:

- monotonic start/end time;
- exact DBAPI SQL string;
- driver/dialect;
- parameter shape, types, count, and safe hashes;
- optional permission-restricted values;
- executemany flag and batch size;
- rowcount when meaningful;
- transaction/session correlation id;
- pytest node id and phase (`setup`, `call`, `teardown`);
- filtered application stack;
- outcome/error class;
- process/thread/task correlation when available.

The listener MUST NOT consume pending results or change statements.

Events are written incrementally as NDJSON to survive test failure. Parameters are encoded with bounded type-aware serializers; unsupported values record type and hash rather than `repr` secrets.

Framework/migration/introspection/setup queries are classified, not deleted. The UI defaults to test-body application operations with toggles for excluded classes.

## 11. SQL parsing and query identity

Pipeline:

1. accept captured DBAPI placeholder style;
2. convert to a typed canonical positional representation;
3. parse with PostgreSQL-derived parser;
4. replace literal constants while preserving type casts/operators;
5. normalize non-semantic formatting and aliases when safe;
6. resolve referenced relations against the physical catalog/search path;
7. attach parameter types;
8. serialize canonical tree;
9. SHA-256 fingerprint.

Queries with equal text but different resolved relations are distinct. PostgreSQL `queryid` may be retained as observed metadata but is not the cross-fixture identity.

Unsupported statements remain visible with parser errors and source occurrences.

## 12. Operation and transaction reconstruction

Primary operation boundary: pytest node id + phase. Within an operation:

- order events by monotonic sequence;
- track connection and transaction correlations;
- group identical fingerprints;
- attach first application frame and all distinct call sites;
- classify read/write/schema/transaction/control statements;
- build operation → transaction → query → relation edges.

The model states observed DB calls; it does not infer HTTP production frequency from test names.

## 13. Evidence and rule engine

Evidence refs are immutable:

```python
@dataclass(frozen=True)
class EvidenceRef:
    id: str
    kind: Literal["observed", "user_confirmed", "inferred", "verified_in_fixture"]
    source: SourceRef
    summary: str
    content_hash: str | None
```

Rule output:

```python
@dataclass(frozen=True)
class RuleResult:
    observations: tuple[Observation, ...]
    questions: tuple[MaterialQuestion, ...]
    recommendations: tuple[RecommendationCandidate, ...]
    hypotheses: tuple[ExperimentHypothesis, ...]
    unsupported: tuple[UnsupportedReason, ...]
```

Questions include affected decision ids. Recommendation identity remains stable when wording changes but affected objects/rule do not.

Rule snapshots and expected results are golden-tested. A rule change increments rule version and invalidates its derived artifacts.

## 14. Initial rule families

### Schema integrity

- ORM relationship without physical FK;
- FK/referenced type mismatch;
- ORM/catalog nullability disagreement;
- optionality/nullability disagreement;
- tenant-scoped uniqueness mismatch;
- association table lacking duplicate protection;
- cascade cycle or ambiguous delete ownership;
- likely closed-set field without database enforcement;
- money-like floating type;
- ORM/server default disagreement;
- generated identity/sequence risk after data migrations;
- sensitive/tenant table without confirmed owner path.

### Workload/index

- repeated observed filter/join column lacks structural index support;
- recurring filter + order lacks compatible composite index;
- large filtered scan produces a physical index hypothesis;
- sort spill, high nested-loop inner count, >100x cardinality mismatch, hash batching, or ignored compatible index as diagnostics;
- unindexed FK stays advisory unless a declared/captured operation makes it testable.

### Migration

- multiple/divergent heads;
- destructive operation without staged plan;
- constraint introduced without repair/backfill;
- risky type conversion;
- potentially blocking index strategy;
- schema/application compatibility requiring expand-contract;
- irreversible downgrade.

### Architecture

- procedure candidacy based on observed multi-statement operation plus context;
- HA requirement based on RPO/RTO gap;
- read-replica candidacy based on read operations and lag tolerance;
- tenant isolation based on confirmed tenancy model.

Rule wording must be concrete and object-specific. Generic “consider an index” findings fail review.

## 15. Context and scenario engine

Questions have:

- stable id;
- answer schema;
- derivation/evidence;
- affected rules/scenarios;
- materiality explanation;
- default of unknown, never a fabricated guess.

Scenarios are deterministic projections:

- **launch-minimal:** confirmed launch scale and simplest satisfying design;
- **growth-ready:** 12-month scale and critical-path needs;
- **availability-ready:** adds RPO/RTO and routing requirements.

Scenario diff lists added/removed/changed recommendations and the context answer causing each delta.

## 16. ER and architecture graph generation

Canonical graph nodes represent schemas, tables, columns, operations, transactions, queries, procedures, and topology components. Edges include physical FK, ORM-only relationship, reads, writes, contains, calls, routes-to, owns, and proposed.

ER exports include table/column/key relationships only. Procedures, operations, and replicas belong in focused overlays/architecture graphs.

Physical and ORM-only relationships differ in line style and text label, never color alone. Proposed additions/removals include status icons/labels.

Layout is not canonical evidence. Frontend positions persist separately keyed by graph/node hash.

## 17. Migration-plan generation

Every accepted/proposed change becomes one or more plan steps with:

- dependency ids;
- schema action;
- required application action;
- data backfill/validation;
- deployment boundary;
- rollback/reversibility;
- evidence and scenario;
- verification requirement.

The planner topologically sorts steps and detects cycles. Known patterns expand into staged templates: nullable-add/backfill/not-null, unique-index/constraint, FK-not-valid/validate, dual-write/read-switch/remove, and concurrent index creation guidance where supported.

Plans are proposals. Production duration and lock impact remain unknown unless supported evidence exists.

## 18. Deterministic data generator

### Seed identity

```text
component_seed = H(global_seed, schema, table, component_id, generator_version)
```

Components include individual columns, composite constraints, and relationships. Unrelated schema additions do not shift existing streams.

### Table order

- build FK dependency graph;
- populate acyclic parents before children;
- nullable cycles use create-then-fill;
- deferrable supported cycles use deferred constraints;
- non-null unsupported cycles fail explicitly;
- preserve migration-inserted rows and adjust requested totals;
- synchronize sequences after generation.

### Generation hierarchy

1. user-declared distribution/correlation;
2. enum/check/unique/FK/boolean/type facts;
3. recognized high-cardinality/timestamp signals;
4. uniform fallback marked as inferred.

The fixed dataset epoch replaces wall-clock `now` assumptions. `ANALYZE` runs after every completed scale.

Property tests assert FK validity, uniqueness, checks, nullability, determinism, and unrelated-stream stability.

## 19. Parameter selection

Supported predicates receive values from actual generated data at:

- highly selective real value;
- moderate selectivity;
- broad selectivity;
- most-common value.

Timestamp ranges use recent, monthly, and full-window variants. Each selector stores its method and realized row count/selectivity.

Captured test binds are hashed/redacted by default. They are replayed only when safely serializable and present/meaningful in the generated dataset, or when explicitly enabled locally.

Generic and custom prepared plans are evaluated separately when driver behavior is unknown and parameter sensitivity could matter.

## 20. Benchmark protocol

For each query, parameter probe, scale, and candidate:

1. set resource/PostgreSQL settings;
2. execute 3 discarded warmups;
3. execute 7 raw-query samples using declared fetch policy;
4. compute median, quartiles, IQR, min, and max;
5. collect one separate diagnostic `EXPLAIN (ANALYZE, BUFFERS, WAL, TIMING OFF, FORMAT JSON)`;
6. suppress verdict if IQR/median exceeds configured threshold.

Seven samples do not support a useful p95; none is reported.

Experiment order:

```text
A1 control → B physical treatment → A2 treatment removed
```

A2 detects drift/cache/environment artifacts. A1/A2 mismatch beyond configured tolerance makes the result inconclusive.

Raw latency includes the declared fetch policy. Diagnostic plan time is not substituted as end-user latency.

## 21. Candidate generation and screening

v1 index candidates:

- single-column B-tree;
- composite B-tree: equality prefix, then range/order support.

Structural deduplication accounts for column order, expressions, predicate, method, sort direction, include columns, and uniqueness. v1 generates no partial/expression/include/unique indexes, though existing ones are understood when possible.

Maximum five candidates per query. HypoPG may screen plan/cost changes, but:

- screening is not evidence of improvement;
- unsupported hypothetical forms are skipped;
- only a physical treatment may become verified;
- every screened/rejected candidate is counted.

## 22. Index write-cost guard

For identical generated operations before/after treatment, record:

- insert batch latency;
- update of indexed columns;
- update of unrelated columns;
- WAL records/bytes when available;
- index build duration and final size.

Read benefit and write/storage cost are separate verified observations. A universal keep/drop verdict requires user-confirmed workload weighting and policy thresholds.

## 23. N+1 and amplification

Candidate observed amplification requires:

- parent query then repeated child fingerprint in one operation;
- child binds vary with parent identities;
- application frame indicates relationship/repository repetition;
- minimum repetition threshold configurable, default 5.

Classifications:

- `repeated_query`: fact only;
- `possible_amplification`: pattern lacks semantic link;
- `observed_n_plus_one`: parent/child/bind/source relationship established;
- `verified_treatment`: optimized operation executed, result-equivalence contract passed, and query/time comparison stable.

Supported treatments include `selectinload`, `joinedload`, and explicit set-based queries. Generated patches remain sketches in v1.

Equivalence compares declared result semantics, not raw unordered row order. Unsupported object graphs require a user-supplied assertion/test.

## 24. Stored-procedure assessment

Candidate signals:

- repeated critical multi-statement transaction;
- measurable round-trip overhead;
- invariant spanning statements not expressible by constraints alone;
- row-by-row work replaceable by set-based SQL;
- shared operation across services.

Blocking context:

- portability requirements;
- ownership/deployment responsibility;
- permission/security-definer policy;
- transaction/error semantics;
- testing/rollback expectations.

Output includes alternatives, proposed signature, permissions, transaction behavior, versioning, migration ordering, and fallback. v1 verifies only a user-supplied procedure and equivalent application treatment.

## 25. Primary/replica assessment

HA and read scale use separate decision trees.

HA inputs: RPO, RTO, failure domain, managed-provider capabilities. Read-scale inputs: confirmed read load, operation read-only status, lag tolerance, read-after-write, transaction mixing, and operational complexity tolerance.

Every operation receives one of:

- primary required;
- replica eligible;
- either;
- unknown/blocked.

No throughput, failover duration, data-loss guarantee, or replica-lag number is invented. Deployment/testing remains outside v1.

## 26. Proof bundle and reproduction

```text
proofs/<id>/
  proof.yaml
  schema.sql
  query.sql
  parameters.json
  dataset.yaml
  config.yaml
  evidence/
    control-a1.json
    treatment-b.json
    control-a2.json
    plans/
  README.md
```

Manifest includes tool/generator/schema version, repository state, PostgreSQL/container/extension identity, schema and input hashes, dataset assumptions, SQL/fingerprint/parameter/fetch policy, resources/settings, intervention, evidence hashes, stability, and verdict.

Reproduction verifies:

- compatible input/tool versions;
- artifact hashes;
- stable measurements;
- same direction of effect;
- configured improvement threshold;
- compatible normalized plan shape.

It never requires exact milliseconds.

## 27. Local UI API

Loopback endpoints, versioned under `/api/v1`:

```text
GET  /session
GET  /project
GET  /artifacts/{kind}
GET  /runs
GET  /runs/{id}
GET  /runs/{id}/events          SSE
GET  /proofs/{id}
PUT  /context
PUT  /decisions/{id}
POST /commands/{command}/prepare
POST /commands/{command}/confirm
```

Command preparation returns exact arguments, execution mode, network state, files, cache invalidation, and estimated stage set. Confirmation requires a short-lived nonce. Only allowlisted structured commands exist; no shell strings cross the API.

Security headers deny framing and remote resources. CORS is disabled except the exact local origin. Session token is required. API never exposes private artifacts.

## 28. CLI rendering

The terminal renderer uses semantic components:

- stage line;
- progress line;
- evidence label;
- finding summary;
- decision/question block;
- measurement comparison;
- unresolved/error block;
- next command.

Rendering data is separate from ANSI styling. Snapshot tests cover Unicode/color, Unicode/no-color, and ASCII/no-color modes at 80 and 120 columns.

Rules:

- one accent color plus semantic success/warning/error;
- no rainbow table output;
- no spinner in logs/non-TTY;
- stable lines in CI;
- source references align but wrap safely;
- terminal output shows at most three important decisions before a summary/path;
- exact numbers use tabular alignment;
- every icon has ASCII fallback;
- progress never implies a percentage without a known denominator.

## 29. Frontend rendering and accessibility

- theme-aware light/dark tokens;
- information hierarchy over decorative cards;
- physical/ORM/proposed graph meaning encoded with label and line style, not color alone;
- keyboard navigation for graphs, filters, dialogs, tabs, and recommendation actions;
- minimum WCAG AA contrast;
- reduced-motion support;
- responsive down to 320 px, optimized for desktop review;
- all critical content accessible without hover;
- raw evidence has text/table fallback for graphs;
- loading, empty, partial, failed, incompatible, and stale states are designed explicitly.

Visual regression tests cover core screens in both themes and 1440, 1024, and 390 px widths.

## 30. Logging and diagnostics

- structured local log per run;
- user-facing terminal remains concise;
- secrets and private binds redacted before logging;
- container stdout/stderr stored with size caps;
- bug bundle includes versions, sanitized config, stage events, stack trace, and artifact manifests—not repository source or private parameters;
- no remote telemetry in v1.

## 31. Cancellation and cleanup

SIGINT behavior:

1. first signal requests graceful cancellation and prints cleanup stage;
2. current query receives cancellation/timeout;
3. owned containers and network stop;
4. complete upstream artifacts remain;
5. running stage manifest is absent or marked cancelled;
6. second signal forces local process termination with cleanup warning.

`pgproof doctor` detects orphaned owned resources. `pgproof clean --containers` lists exact resources and asks before removal.

## 32. Test strategy

### Unit

- IR validation and identity;
- parsers/normalizers;
- rules/questions/scenarios;
- graph generation;
- migration dependency planner;
- statistics and verdicts;
- redaction;
- CLI render models.

### Property

- deterministic seed stability;
- generated constraint validity;
- normalization idempotence;
- artifact encode/decode round trip;
- topological-plan invariants.

### Contract

- Python JSON Schema validation;
- generated TypeScript type fixtures;
- backward-compatible minor artifacts;
- invalid/incompatible fixture rejection.

### Integration

- Alembic success, multiple heads, failure, DML migration, and extensions;
- SQLAlchemy sync/async capture;
- test failure/partial workload;
- PostgreSQL catalog features;
- Docker isolation and cleanup;
- index A1/B/A2 verification;
- proof reproduction.

### End-to-end

- broken fixture from `doctor` through static report;
- clean fixture with no headline findings;
- no-Docker parse-only journey;
- failed migration journey;
- UI context edit recomputes scenario;
- UI experiment stream and proof view;
- privacy-safe share export.

### Golden/visual

- CLI snapshots;
- Markdown/JSON report snapshots;
- current/target graph fixtures;
- local UI screenshots in theme/viewport matrix.

## 33. Quality gates

Every PR MUST include:

- acceptance tests for its contract;
- failure and partial-state behavior;
- security/privacy impact note;
- artifact-schema compatibility note;
- documentation update;
- no unrelated scope.

Release gates:

- type/lint/test/contract suites pass;
- broken/clean E2E oracle passes;
- no high-severity dependency/security issue without documented decision;
- proof reproduction passes on macOS arm64 and Linux amd64;
- static share inventory contains no seeded private canaries;
- CLI and local UI visual baselines approved;
- performance budgets in product spec pass on pinned benchmark commit.

## 34. Open implementation spikes

Resolve in the named PR, not before:

- `BE-04`: pglast compatibility and bind-style canonicalization;
- `BE-10`: Docker image/build workflow across arm64/amd64;
- `BE-17`: PostgreSQL catalog coverage and schema snapshot portability;
- `BE-21`: stable raw fetch policy across psycopg modes;
- `FE-02`: React Flow layout strategy for large schemas;
- `FE-08`: readable plan comparison visualization.

Spike outcomes become ADRs when they change this baseline.
