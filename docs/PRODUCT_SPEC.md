# pgproof product specification

**Status:** accepted implementation baseline  
**Audience:** product, design, backend, frontend, contributors  
**Initial release:** local-first open-source CLI and local interactive report

## 1. Summary

pgproof reconstructs the database design expressed by a Python codebase, asks the developer for material business context absent from code, and returns:

1. an accurate current physical/logical ER design;
2. a traceable database design review;
3. context-aware launch, growth, and availability architecture scenarios;
4. experimentally verified proofs for supported performance changes; and
5. an ordered, reviewable path from the current design to the selected target.

### Product promise

> Show me the database my application actually defines, identify decisions that could fail at launch or growth, ask only what you need to know, and prove the recommendations that can be safely tested.

pgproof is not an autonomous DBA. It distinguishes facts from interpretations, and verified fixture behavior from production predictions.

## 2. Problem

Early-stage backend developers often design schemas and queries without a dedicated database specialist. The relevant information is fragmented across:

- Alembic history;
- the final PostgreSQL catalog;
- SQLAlchemy models and relationships;
- repositories, services, endpoints, and jobs;
- executed test queries and transaction boundaries; and
- business requirements that no source-code parser can infer.

Existing static checks can identify patterns, while production observability sees real workloads only after deployment. The pre-launch developer needs a joined-up design review before production traffic exists.

## 3. First user

The first user is an early-stage Python backend developer preparing a PostgreSQL application for launch without a dedicated DBA.

They use:

- Python 3.11 or newer;
- SQLAlchemy 2.x or SQLModel;
- Alembic;
- PostgreSQL;
- pytest; and
- Docker for optional deep analysis.

### Primary trigger

- preparing an application for launch;
- reviewing a substantial schema/query change; or
- checking whether the current design can handle the next expected scale.

## 4. Jobs to be done

- Reconstruct the actual schema and relationships.
- Reveal ORM relationships not enforced by PostgreSQL.
- Find correctness, integrity, tenancy, migration, and query-design risks.
- Connect database behavior to application operations.
- Detect observed N+1 and broader query amplification.
- determine whether supported indexes improve real captured query shapes.
- Assess whether a workflow is a candidate for a stored procedure.
- Separate high-availability needs from read-scaling needs.
- Identify which operations can tolerate replica lag.
- Produce current and target ER/architecture diagrams.
- Produce an implementation and rollback sequence.
- Explain what could not be concluded and why.

## 5. Product principles

1. **Code is evidence, not omniscience.**
2. **Ask only questions that materially change a decision.**
3. **Never blend observation, user context, inference, and measurement.**
4. **Verification in a synthetic fixture is not a production forecast.**
5. **A recommendation must expose its evidence, assumptions, alternatives, and trade-offs.**
6. **Few consequential decisions beat many warnings.**
7. **Rejected experiments are evidence of rigor.**
8. **Local-first trust precedes hosted convenience.**
9. **The simplest design satisfying confirmed requirements wins.**
10. **Operational complexity requires evidence.**

## 6. Product model: database design twin

The central product object connects:

```text
entry point
  → application operation
  → transaction boundary
  → SQL fingerprint
  → tables and relationships
  → constraints and indexes
  → ownership and tenancy
  → consistency and routing requirements
```

Every edge has provenance or remains unresolved. The twin powers ER diagrams, operation maps, recommendation reasoning, scenario differences, and migration planning.

## 7. Evidence contract

| Label | Definition | Allowed claims |
|---|---|---|
| Observed | Directly found in code, catalogs, migrations, or selected test execution | Structural and captured behavior facts |
| User-confirmed | Supplied or accepted by the developer | Requirements and workload context |
| Inferred | Deterministic interpretation with named assumptions | Risks, alternatives, and advisory recommendations |
| Verified in fixture | Stable control/treatment measurement on the declared disposable dataset | Measured behavior in that fixture only |

Every recommendation MUST include evidence references, assumptions, trade-offs, invalidating context, verification status, and a proposed change or question.

The product MUST NOT:

- present synthetic latency as expected production latency;
- convert test execution count into production frequency;
- declare a replica necessary from code alone;
- call a query treatment verified without running it and checking supported equivalence;
- use a universal database-health score; or
- hide unsupported inputs.

## 8. Context interview

The first interview asks at most seven core questions and stores answers locally:

1. Which operations are latency-critical?
2. What are present and 12-month row counts for the largest tables?
3. What is the approximate read/write mix and peak traffic?
4. What is the tenant and isolation model?
5. Which flows need immediate read-after-write consistency?
6. What RPO and RTO matter?
7. What retention, deletion, audit, or regulatory constraints apply?

Questions are dynamic. Unknown is a valid answer. The product MAY ask a targeted clarification attached to an ambiguous finding.

Editing an answer MUST recompute affected recommendations and show what changed. If no recommendation changes, the UI explains why.

## 9. Modes

### Parse-only

- no imports, migrations, tests, containers, or database connections;
- provisional ERD, repository inventory, static facts, and unresolved constructs;
- useful even without Docker.

### Migration/catalog

- explicitly executes configured migration code in an isolated runner;
- final disposable PostgreSQL catalog becomes physical-schema truth;
- no partial-schema analysis after migration failure.

### Test capture

- explicitly executes the selected tests in the isolated runner;
- captures SQLAlchemy cursor activity grouped by test operation and transaction;
- never treats the test suite as complete production coverage.

### Verification

- generates a deterministic fixture;
- replays supported read queries;
- physically tests supported treatments;
- produces portable evidence bundles.

## 10. Core capabilities

### Current design

- physical tables, fields, keys, constraints, indexes, functions, triggers, RLS policies, and extensions;
- ORM relationships and loading configuration;
- physical versus ORM-only relationship distinction;
- schema/model drift;
- source and migration provenance;
- searchable ERD and focused overlays.

### Design review

- relationship and referential integrity;
- nullability and type agreement;
- uniqueness and tenant scoping;
- association-table integrity;
- delete/cascade behavior;
- closed-set and money-type modeling;
- defaults and generated identities;
- captured query/index compatibility;
- observed N+1/amplification;
- migration sequencing and reversibility;
- tenant-ownership paths.

### Architecture assessment

- application transaction versus stored-procedure alternatives;
- primary-only, HA standby, or read-replica alternatives;
- operation-level primary/replica routing matrix;
- normalized versus deliberately duplicated read-model alternatives when context supports comparison;
- launch-minimal, growth-ready, and availability-ready target scenarios.

These are advisory unless an eligible treatment is physically verified.

### Verification

v1 physically verifies:

- single-column B-tree indexes;
- composite B-tree indexes;
- supported eager-loading/set-based query treatments supplied by the tool or user;
- a user-supplied stored-procedure treatment when equivalence and measurement contracts are satisfied.

## 11. User journey

```bash
pgproof doctor
pgproof inspect .
pgproof configure .
pgproof capture . -- pytest tests/critical/
pgproof review .
pgproof verify .
pgproof ui .
pgproof reproduce .pgproof/proofs/IDX-004/
```

The user receives value after `inspect`; deeper execution always requires visible permission.

### Local UI sections

1. Overview and analysis boundary
2. Current ER design
3. Operation and transaction map
4. Design questions
5. Traceable recommendations
6. Scenario comparison
7. Experiments and proof details
8. Migration path
9. Trust, commands, redactions, and limitations

## 12. Recommendation priority

Recommendations are grouped without an arbitrary numerical score:

1. Required for correctness
2. Required by confirmed requirements
3. Verified improvement
4. Worth evaluating
5. Optional hardening

Within verified performance work, sort by absolute time saved for the declared operation. Architecture work sorts by dependency and reversibility.

## 13. Decision log and invariants

The user can accept, reject, or defer a recommendation with a reason and revisit condition. Accepted decisions may become proposed machine-checkable invariants and tests.

The decision log is local project data, not telemetry. A rejected/deferred recommendation does not reappear unless its evidence or revisit condition changes.

## 14. Outputs

- Markdown review
- stable, versioned JSON artifacts
- current and target graph JSON
- Mermaid and DBML diagrams
- optional rendered SVG
- static shareable report bundle
- proof bundle per verified finding
- ordered migration plan with rollback notes
- later: compact PR-diff GitHub Action comment

## 15. Privacy and safety

- no telemetry by default;
- local UI binds to loopback only;
- no production connection in v1;
- explicit execution modes;
- network-disabled migration/test/benchmark runtime;
- non-root, resource-limited runners;
- environment allowlist rather than inherited secrets;
- parameter and absolute-path redaction in shared output;
- repository copy prevents runner writes to host source;
- share inventory before export.

## 16. Scope rings

### Ring A — trustworthy design core

- physical plus ORM ERD;
- evidence and context system;
- schema/tenant review;
- operation map;
- index and N+1 verification;
- target design and migration plan.

### Ring B — evolution and architecture

- branch/base schema diff;
- expand-contract guidance;
- design invariants and test proposals;
- stored-procedure candidacy;
- HA/read-replica assessment;
- scenario studio.

### Ring C — later operations

- concurrency and locks;
- explicitly consented production-statistics import;
- regression baselines;
- provider integrations;
- more ORMs and databases.

Ring A MUST complete as a vertical product before Ring B expands.

## 17. v1 non-goals

- mutate application or migration files automatically;
- connect to production;
- deploy indexes, procedures, replicas, or infrastructure;
- guarantee query or source coverage;
- predict production performance or cloud cost;
- automate stored-procedure conversion;
- test production failover;
- support Django, Prisma, Drizzle, MySQL, or arbitrary languages;
- require an LLM, account, hosted dashboard, or subscription.

## 18. Success measures

### Engineering

- supported physical ERD exactly matches the migrated catalog;
- physical and ORM-only edges are never blended;
- every unsupported construct is visible;
- two fixture index findings reproduce on two machines;
- one fixture N+1 treatment passes equivalence and reduces query amplification;
- the clean fixture produces no headline findings;
- median interview is six questions or fewer;
- every recommendation is traceable;
- a failed deep run leaves honest parse-only value;
- proof reproduction does not require the source repository for supported index cases.

### Experience

- `doctor` under 5 seconds;
- useful `inspect` output under 30 seconds on the benchmark repository;
- UI interactive under 2 seconds once artifacts exist;
- static review under 60 seconds from cached inspection artifacts;
- first-time users can explain the evidence labels from the report itself.

### Product

- five design partners complete inspection and questions;
- three change a real design or query decision;
- one shares a target diagram or proof with a teammate;
- users describe pgproof as a decision review with evidence, not a checklist.

## 19. Kill and pivot criteria

- If context answers do not materially change recommendations, remove the interview engine.
- If the physical/catalog ERD is unreliable, stop adding design rules.
- If local measurements do not reproduce qualitatively, stop calling them proof.
- If pytest capture works on fewer than half of the chosen corpus, make explicit workload files the permanent primary path.
- If users value design review but not verification, pivot toward design review.
- If users value proofs but not architecture scenarios, narrow toward the experiment engine.

## 20. Benchmark and adoption targets

- Broken demo repository with two index cases, one N+1 case, and one tenant-isolation case
- Clean counterpart with correct alternatives
- Pinned `fastapi/full-stack-fastapi-template` commit as the first living integration target
- Frozen Netflix Dispatch commit as a later stress corpus, not the primary compatibility target
- Five early design partners before GitHub Action investment

## 21. Release decision

v1 is ready to announce only when it can produce a trustworthy current ERD, ask a short context interview, identify and explain consequential design decisions, verify at least supported index/N+1 treatments, and emit a shareable current-to-target report with explicit limitations.
