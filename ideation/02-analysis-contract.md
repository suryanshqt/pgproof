# Iteration 2 — analysis and trust contract

**Status:** accepted

## Knowledge boundaries

### What code can establish

- final migrated tables, columns, types, defaults, constraints, indexes, functions, triggers, policies, and extensions
- physical foreign keys and ORM-only relationships
- migration history and schema/model disagreements
- SQL shapes and bind types exercised by selected tests
- query amplification and N+1 behavior observed during a test operation
- transactions, database round trips, and code locations visible in captured execution

### What code may suggest but cannot establish alone

- whether a status-like text field is a closed business enum
- whether an optional relationship is intentionally nullable
- whether a workflow belongs in a stored procedure
- whether denormalization is worth its consistency cost
- whether reads can tolerate replica lag
- which operations matter enough to optimize first

### What the user must confirm

- critical operations
- present and expected table sizes
- read/write mix and peak traffic
- tenant and isolation model
- immediate consistency requirements
- RPO and RTO
- retention, deletion, audit, and regulatory constraints

### What pgproof can experimentally verify

- supported physical indexes
- supported eager-loading or set-based query treatments
- a user-supplied stored-procedure treatment against its application equivalent
- result equivalence for supported query treatments
- read improvement and controlled write/storage costs in the declared fixture

Primary/replica architecture remains advisory in v1 because a local fixture cannot prove production failover behavior or acceptable consistency.

## Evidence labels

Every report statement is labeled:

1. **Observed** — directly present in code, catalogs, or captured tests.
2. **User-confirmed** — supplied through the design interview.
3. **Inferred** — rule-based interpretation with explicit assumptions.
4. **Verified in fixture** — measured control and treatment under a recorded setup.

## Recommendation lifecycle

```text
observe → identify ambiguity → ask only if material → recommend
        → verify when eligible → produce migration-ready guidance
```

Every recommendation cites its code/catalog evidence, user answers, assumptions, trade-offs, invalidating conditions, and verification state.

## Database design twin

The central product model is a **database design twin**, not a flat list of lint findings. It connects:

```text
endpoint / job / command
  → application operation
  → transaction boundary
  → SQL fingerprints
  → tables and relationships
  → constraints and indexes
  → data ownership and tenancy
  → primary/replica routing requirements
```

This enables pgproof to answer questions that a schema-only linter cannot:

- which user operations depend on a proposed schema change
- which tables form one consistency boundary
- which query is responsible for an N+1 rather than merely repeated SQL
- which read paths are safe candidates for a replica
- which repeated multi-statement workflows may justify a stored procedure
- which ORM relationships exist only in application memory and are not protected by PostgreSQL

Every edge retains provenance. Unknown edges remain unknown rather than being guessed.

## Operation and transaction map

The report groups captured database activity by meaningful application operation, such as an API request test, background job test, CLI command, or user-declared critical flow. Each operation displays:

- entry point and application stack
- query sequence and count
- transaction begin/commit/rollback boundary
- tables read and written
- repeated round trips
- lazy relationship loads
- lock-sensitive or consistency-sensitive steps
- suitability for primary, replica, or either

This map is the basis for N+1, stored-procedure, transaction, and routing recommendations.

## Scenario studio

Instead of pretending there is one universally correct target architecture, pgproof generates and compares scenarios:

1. **Launch-minimal** — the simplest design that preserves integrity and handles confirmed launch scale.
2. **Growth-ready** — changes justified by the user’s 12-month scale and critical operations.
3. **Availability-ready** — additional topology justified by confirmed RPO/RTO.

Users can change a small number of inputs—row counts, traffic, stale-read tolerance, tenant count, RPO/RTO—and see which decisions change. A scenario contains:

- target ER and architecture diagrams
- required versus optional changes
- operational complexity introduced
- verified evidence available
- assumptions and unanswered blockers
- ordered implementation plan

pgproof never attaches invented cloud cost or throughput to a scenario. It can compare relative operational complexity and cite user-supplied limits.

## Architecture alternatives, not a single oracle

For consequential choices, the report presents a small decision set rather than announcing “best practice.” Examples:

- constraint versus application-only validation
- normalized relation versus deliberately duplicated read model
- application transaction versus stored procedure
- primary-only versus HA standby versus routed read replica
- `selectinload` versus `joinedload` for a captured relationship access

Each alternative shows prerequisites, benefits, failure modes, reversibility, and what evidence would select it. pgproof recommends one only when the known context distinguishes it.

## Schema-evolution and migration safety

The design twin includes Alembic history and a branch-to-base schema diff. pgproof can identify:

- multiple or divergent Alembic heads
- model/schema drift
- destructive column or table changes
- new `NOT NULL` or uniqueness constraints without a backfill path
- foreign keys added before invalid data is repaired
- type changes that require a table rewrite or explicit conversion
- index creation that may block writes when deployed normally
- application/schema changes that require an expand-and-contract rollout
- downgrade paths that cannot restore discarded data

The output is an ordered migration strategy such as:

```text
1. add nullable column
2. deploy dual-write application code
3. backfill in bounded batches
4. validate the invariant
5. add NOT NULL / constraint
6. switch reads
7. remove old column in a later release
```

Exact lock and rewrite behavior is PostgreSQL-version-sensitive and must be derived from supported operations, not generic warning text. Production duration is never predicted from repository code alone.

## Design invariants and generated checks

Accepted decisions become machine-checkable invariants in `pgproof.toml`, for example:

```toml
[[invariants]]
id = "tenant-order-ownership"
kind = "tenant_path"
table = "orders"
column = "tenant_id"
required = true

[[invariants]]
id = "checkout-primary-consistency"
kind = "routing"
operation = "checkout"
target = "primary"
```

Future reviews can detect drift from decisions the user explicitly accepted. pgproof can also generate proposed tests:

- schema/catalog assertions
- Alembic upgrade smoke tests
- relationship integrity tests
- `raiseload`-based N+1 guards for selected SQLAlchemy operations
- query-count budgets for critical tests
- result-equivalence tests for query or stored-procedure treatments

Generated checks remain proposals until the user adds them to the repository.

## ER and architecture overlays

The same canonical graph can render focused overlays rather than one unreadable diagram:

- physical relationships and cardinality
- ORM-only relationships and model/schema drift
- indexes and captured hot query paths
- tenant ownership and isolation boundaries
- write ownership and transaction boundaries
- sensitive-data classifications confirmed by the user
- primary/replica routing
- current versus proposed schema diff
- migration sequence and dependencies

This is more useful than trying to force tables, queries, procedures, and replicas into one ER diagram.

## Recommendation priority without a fake score

pgproof does not invent a universal “database health score.” It groups work by decision quality:

- **Required for correctness** — demonstrated integrity or migration problem
- **Required by confirmed requirements** — e.g. an RPO the current topology cannot satisfy
- **Verified improvement** — treatment passed the experiment contract
- **Worth evaluating** — evidence exists but a material answer or experiment is missing
- **Optional hardening** — defensible but not required by known context

Within a group, verified performance work sorts by absolute time saved for the declared operation. Advisory architecture work sorts by dependency order and reversibility, not arbitrary severity points.

## Capability rings

The expanded vision is delivered in rings so product depth does not destroy buildability.

### Ring A — trustworthy design core

- physical plus ORM ERD
- evidence graph and dynamic questions
- schema integrity and tenant ownership
- observed query/operation map
- index and N+1 verification
- current-to-target migration plan

### Ring B — evolution and architecture

- branch-to-base schema diff
- expand-and-contract migration guidance
- design invariants and proposed tests
- stored-procedure candidacy
- HA and read-replica routing assessment
- launch, growth, and availability scenarios

### Ring C — later operational depth

- concurrency and lock experiments
- production-statistics import with explicit consent
- regression baselines
- deployment-provider integrations
- other ORMs and databases

The final PR roadmap must complete Ring A vertically before broadening into Ring B.

## Design-decision graph

The local report exposes why the proposed architecture changes. For example:

```text
historical reporting is critical
  + 92% reads
  + stale reads up to 60 seconds are acceptable
  + reports do not follow writes
    → read-replica routing is reasonable

checkout requires immediate consistency
    → checkout and its follow-up reads remain on the primary
```

Changing an answer recomputes affected recommendations and shows the difference. This prevents the questionnaire from becoming decorative.

## Proposed mutation policy

The first release is read-only with respect to the user's repository. It produces:

- exact Alembic snippets
- exact index SQL
- SQLAlchemy loading/query patch sketches
- stored-procedure interface and migration sketches when justified
- an ordered migration and rollback plan

It does not modify application code or migration files automatically. Automatic patch generation can be considered only after recommendation precision is demonstrated.
