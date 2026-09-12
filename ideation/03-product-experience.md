# Iteration 3 — product experience and adoption loop

**Status:** accepted

## Experience principle

pgproof should feel like a careful database architect reviewing the application with the developer—not like a scanner dumping warnings.

The product follows this sequence:

```text
show what exists
  → show what is unknown
  → ask only material questions
  → show the decisions those answers change
  → verify eligible changes
  → produce an ordered path forward
```

The user receives useful output before granting permission to execute migrations or tests.

## Product surfaces

### CLI

The CLI owns repository inspection, isolated execution, experiments, artifacts, and automation. Every UI action corresponds to a visible CLI command so the workflow remains scriptable and debuggable.

```bash
pgproof doctor
pgproof inspect .
pgproof configure .
pgproof capture . -- pytest tests/
pgproof review .
pgproof verify .
pgproof ui .
pgproof reproduce .pgproof/proofs/IDX-004/
```

### Local interactive report

`pgproof ui .` opens a locally served web application backed only by artifacts in `.pgproof/`. The server binds to loopback, performs no telemetry, and makes no external network requests.

The frontend is not a separate hosted product. It is a visual explorer for CLI-generated, versioned artifacts. This keeps the trust boundary and deployment model simple while creating meaningful `FE-*` work.

### Static shareable report

`pgproof report --static` emits a self-contained report bundle suitable for a CI artifact or teammate review. Private bind values, credentials, absolute home paths, and unapproved source excerpts are removed.

## Ten-minute first run

### Minute 0–1: environment check

```bash
pgproof doctor
```

The command reports supported Python/PostgreSQL tooling, repository adapters found, Docker availability, and which modes can run. Missing Docker does not block parse-only inspection.

### Minute 1–2: parse-only inspection

```bash
pgproof inspect .
```

The user immediately receives:

- detected framework and migration layout
- provisional current ERD
- physical claims versus ORM-only/inferred edges
- unresolved dynamic code
- exact explanation of what deeper modes would execute

### Minute 2–5: context interview

```bash
pgproof configure .
```

The local UI or terminal asks no more than seven core questions. Each question includes “why this matters” and previews which decision categories it can affect.

### Minute 5–7: first design review

```bash
pgproof review .
```

The first report prioritizes:

- correctness and integrity issues
- unresolved decisions blocking a recommendation
- current versus target ER changes
- architecture alternatives based on confirmed requirements
- work eligible for experimental verification

### Optional deep run

The user explicitly approves migration/test execution:

```bash
pgproof capture . -- pytest tests/critical/
pgproof verify .
```

The UI streams stage progress from artifacts, not an opaque background service.

## Information architecture

### 1. Overview

- analyzed boundary and current mode
- launch, growth, and availability scenario selector
- three most important decisions
- verified improvements
- blocked decisions and unresolved inputs
- current-to-target migration summary

There is no universal health score. Completion and uncertainty are shown directly.

### 2. Current design

- searchable physical ERD
- toggle ORM-only relationships
- table detail with constraints, indexes, policies, and provenance
- migration revision and model source references
- schema/model disagreement view

### 3. Operation map

- endpoints, jobs, commands, or selected test operations
- transaction and query sequence
- tables read/written
- repeated queries and lazy loads
- primary/replica eligibility
- source stack and test provenance

### 4. Design questions

- answered, unknown, and inferred context
- recommendations affected by each answer
- immediate “what changed?” preview after editing an answer
- answers saved locally in reviewable config

### 5. Recommendations

Filterable by:

- correctness requirement
- user requirement
- verified improvement
- worth evaluating
- optional hardening
- schema, query, tenancy, procedure, topology, or migration category

Each recommendation page contains:

- concise decision
- evidence and source links
- assumption and confidence labels
- alternatives and trade-offs
- current and target diagram fragment
- exact proposed SQL/Alembic/SQLAlchemy sketch
- verification status and raw proof link
- invalidating context changes
- accept, reject, or defer decision state with a local note

### 6. Scenario comparison

Compare launch-minimal, growth-ready, and availability-ready designs:

- schema changes
- topology changes
- operational complexity
- requirements satisfied
- unresolved blockers
- verified evidence
- migration dependencies

The comparison never invents capacity, cost, or availability numbers.

### 7. Experiments

- queued, running, verified, rejected, inconclusive, and unsupported candidates
- control A1, treatment B, and drift control A2
- raw latency distribution and plan-shape comparison
- parameter and dataset assumptions
- read benefit plus write/WAL/storage trade-offs
- reproduction command

Rejected candidates are first-class evidence that the tool tests rather than asserts.

### 8. Migration path

- dependency-ordered changes
- expand/backfill/validate/contract stages
- application changes paired with schema changes
- reversible boundaries
- rollback notes
- recommended PR grouping

This screen later becomes the source for the implementation PR roadmap.

### 9. Trust and limitations

- commands that were executed
- containers, images, limits, and network state
- files read and artifacts written
- redactions applied
- unsupported syntax and failed tests
- evidence-label glossary
- exact limits of synthetic verification

## Frontend/backend artifact contract

The CLI writes immutable, versioned artifacts. The UI never reinterprets source code itself.

```text
.pgproof/
  project.json
  context.json
  analysis/
    schema.json
    code.json
    workload.json
    evidence.json
    recommendations.json
    scenarios.json
    migration-plan.json
  diagrams/
    current.graph.json
    target.graph.json
  runs/<run-id>/
    manifest.json
    events.ndjson
    result.json
  proofs/<finding-id>/
  report/
```

All artifact schemas have an explicit `schema_version`. Backend changes either remain backward compatible or ship a documented migration. This contract allows backend and frontend PRs to proceed independently once fixtures are frozen.

## Progress and resumability

Long work is divided into visible, cacheable stages:

```text
repository inventory
→ schema reconstruction
→ context resolution
→ migration sandbox
→ query capture
→ dataset build
→ candidate screening
→ physical verification
→ report generation
```

Each stage records inputs, output hashes, start/end times, status, warnings, and failure reason. A retry resumes from the last valid artifact when its inputs are unchanged.

Estimated completion times are based on earlier stages in the same local run, not global fabricated averages.

## Failure experience

### Unsupported dynamic model code

Keep the partial parse-only graph, mark unresolved nodes, and offer isolated migration/catalog reconstruction. Never quietly guess the missing schema.

### Migration failure

Report command, revision, safe stderr excerpt, and container logs. Do not inspect or analyze a partially migrated database.

### Some tests fail

Record selected/pass/fail counts and allow captured queries from completed passing operations to remain visible, but label the workload incomplete. Verification requires an explicit user choice to continue with that boundary.

### Unstable measurement

Mark the experiment inconclusive and show variance. Do not downgrade it to an advisory recommendation containing the unstable numbers.

### Missing Docker

Keep `inspect`, `configure`, provisional ERD, and static review available. Clearly identify experiments and physical catalog checks that could not run.

## Privacy and sharing

- no telemetry by default
- loopback-only local UI
- no production connection in v1
- bind values hashed/redacted in shareable output
- source excerpts minimized and explicitly listed
- private artifacts stored separately with restrictive permissions
- `pgproof report --check-share` inventories everything included in an export

## Local decision log

Users may accept, reject, or defer a recommendation with a reason. Decisions are stored as reviewable local data:

```yaml
recommendation: REPLICA-002
decision: deferred
reason: "Launch traffic does not justify operational complexity. Revisit at 500 RPS."
review_when:
  peak_requests_per_second: 500
```

This is not hidden product telemetry. It prevents the same recommendation from reappearing without changed evidence and creates explicit revisit conditions.

## Adoption loop

The local workflow must create value before CI integration:

```text
inspect repository
→ discuss a concrete design decision
→ accept a target change
→ verify when possible
→ implement through a small PR
→ share current/target diagram and proof
```

The later GitHub Action focuses on changes introduced by the pull request and links to a static report artifact. It does not paste a full audit into every PR.

Suggested PR comment:

```text
pgproof reviewed this database change

1 required integrity change
1 verified index improvement: 86 ms → 14 ms in the declared 1M-row fixture
1 architecture question: must invoice reads be immediately consistent?

Evidence, assumptions, target ER diff, and reproduction are in the report artifact.
```

## Product performance budgets

- `doctor`: under 5 seconds
- parse-only `inspect`: useful first output under 30 seconds on the benchmark repository
- local UI: interactive under 2 seconds after artifacts exist
- core interview: median six questions or fewer
- static `review`: under 60 seconds after inspection artifacts exist
- capture: bounded primarily by the selected test command and displayed separately
- verification: declares candidate count and per-stage progress; no misleading universal five-minute promise

## Experience success criteria

- A first-time SQLAlchemy developer can explain the four evidence labels after one report.
- The current ERD distinguishes physical and ORM-only relationships without documentation.
- Users can trace every recommendation to code, catalog evidence, or an answer.
- Editing a context answer visibly changes affected scenarios or explains why it does not.
- A failed deep run still leaves honest, useful parse-only output.
- One external user moves from report to an accepted design decision without author guidance.
- One teammate can reproduce a verified index finding from a shared proof bundle.

## Proposed Loop 3 decision

The v1 product is a local-first CLI with a loopback interactive frontend and a shareable static report. The CLI is the execution authority; the frontend consumes only versioned artifacts. No hosted account, service, or telemetry is required.
