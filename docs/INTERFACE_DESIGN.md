# pgproof interface design

**Status:** accepted implementation baseline  
**Scope:** terminal UI, local browser UI, diagrams, reports, accessibility, and visual QA

## 1. Design intent

pgproof should feel like a calm technical instrument: precise, restrained, information-dense, and trustworthy.

The interface MUST NOT resemble:

- a generic admin dashboard full of cards;
- a security scanner using alarmist red everywhere;
- a terminal demo using decorative gradients and spinners;
- an AI chat interface hiding deterministic analysis;
- a score-driven audit with no evidence trail.

### Visual principles

1. Evidence precedes decoration.
2. One clear visual hierarchy per screen.
3. Color reinforces meaning but never carries meaning alone.
4. Progressive disclosure keeps first output short.
5. Source, assumption, and verification state stay one action away.
6. Terminal and browser use identical language and status semantics.
7. Partial analysis looks intentionally partial, never broken or complete.
8. Dense information remains readable at laptop widths.

## 2. Shared language

Use these labels consistently:

| Concept | Display label |
|---|---|
| Direct source/catalog/test fact | Observed |
| Developer-provided requirement | User-confirmed |
| Rule interpretation | Inferred |
| Stable measured treatment | Verified in fixture |
| Missing material answer | Question |
| Unsupported input | Unresolved |
| Unstable experiment | Inconclusive |
| Candidate that failed thresholds | Rejected |

Never shorten “Verified in fixture” to “Verified” in a headline where the fixture boundary is not already visible.

## 3. Visual character

### Color

- Neutral surfaces dominate.
- One PostgreSQL-inspired blue accent identifies current selection, links, and active evidence.
- Green means a completed/verified state, not general decoration.
- Amber means material attention or unanswered decision.
- Red is reserved for execution failure, destructive migration risk, or invalid state.
- Purple or secondary hues MAY distinguish scenario alternatives in graphs, paired with labels/line patterns.
- Light and dark themes receive equal design and screenshot coverage.

### Typography

- UI: system sans-serif for fast native rendering.
- Code, SQL, paths, identifiers, aligned measurements: system monospace.
- Use regular and medium weight only.
- Headings are compact; no oversized marketing typography inside the product.
- Numbers in comparisons use tabular figures.

### Shape and depth

- Moderate 8–12 px radii.
- Thin neutral dividers.
- Shadows only for true overlays and terminal/window separation.
- Avoid nested cards.
- Tables and repeated rows remain unframed, separated by rhythm/dividers.
- Selected graph nodes use a clear accent surface/ring plus label, not a glow.

### Density

- Default: balanced laptop density.
- Optional compact density for large designs and expert users.
- No spacious marketing mode.

## 4. Terminal design system

### Output anatomy

Every command uses the same order:

```text
command context
stage progress
important results
analysis boundary
artifact path
single recommended next command
```

### Semantic marks

| Unicode | ASCII | Meaning |
|---:|---:|---|
| `✓` | `[ok]` | completed fact/stage |
| `!` | `[!]` | material attention |
| `×` | `[x]` | failure |
| `○` | `[-]` | not run/not available |
| `→` | `->` | next action or transition |
| `↳` | `>` | supporting evidence/source |

Icons never appear without nearby text.

### Rendering rules

- Honor `NO_COLOR` and non-TTY output.
- Detect Unicode support; `--ascii` forces fallback.
- Use no more than one animated spinner at a time.
- In CI/non-TTY, emit stable stage-start/stage-end lines without animation.
- Never show percentage unless total work is known.
- Avoid tables wider than the terminal; use stacked decision blocks at narrow widths.
- Default output shows at most three consequential decisions.
- `--verbose` reveals rejected candidates and detailed evidence.
- `--json` writes only the contract result to stdout.
- Diagnostics and progress go to stderr in JSON mode.

### `inspect` reference

```text
❯ pgproof inspect .

✓ SQLAlchemy 2.x + Alembic detected             12 revisions
✓ Reconstructed provisional design              14 tables · 19 relations
! 3 relationships exist only in ORM code        review needed
○ Runtime query behavior not inspected           capture not approved

2 required     integrity decisions
4 questions    material context missing
0 verified     no experiments run

required  Enforce tenant ownership for orders
          The ORM links orders to tenants, but PostgreSQL does not.
        ↳ app/models/order.py:31 · migration 6a912e

question  Must invoice reads be immediately consistent after checkout?
        ↳ affects primary/replica routing in Availability-ready

Report  .pgproof/report/
Next    pgproof configure .
```

### `capture` approval reference

```text
pgproof needs permission to execute project code

Command       pytest tests/critical/
Runner        storefront-dev@sha256:8f2…
Database      disposable PostgreSQL 17
Network       disabled
Repository    copied; host source is not writable
Limits        2 CPU · 2 GB · 15 minutes
Environment   APP_ENV plus generated DATABASE_URL

Run this command? [y/N]
```

The approval is a factual execution contract, not a frightening warning wall.

### `verify` reference

```text
❯ pgproof verify . --finding IDX-004

Dataset  target · orders 1,000,000 · seed 82f3d1
Query    list tenant orders · status=active

✓ Control A1      86.2 ms median   IQR 4.1%
✓ Treatment B     14.3 ms median   IQR 5.0%
✓ Drift control   84.9 ms median   IQR 4.4%

Verified in fixture
  read             71.9 ms faster per declared operation
  insert 1k        +11%
  unrelated update +3%
  indexed update   +29% · HOT behavior changed
  index size        38 MB

Proof  .pgproof/proofs/IDX-004/
Next   pgproof reproduce .pgproof/proofs/IDX-004/
```

Percentage improvement may appear as secondary context. Absolute time saved leads.

### Error reference

```text
× Migration stopped at revision 91ca21

PostgreSQL rejected: column "tenant_id" contains null values

No partial schema was analysed.
Logs  .pgproof/runs/01J7D/migration.log
Next  repair the migration or use parse-only `pgproof inspect .`
```

Errors state impact and recovery without dumping a traceback by default.

## 5. Local application shell

### Navigation

Persistent left navigation on desktop, horizontal compact navigation at narrow widths:

1. Overview
2. Design
3. Operations
4. Questions
5. Decisions
6. Proofs
7. Migration path

Trust/limitations is available from the run status/footer and report metadata, not hidden in settings.

### Header

- project name and PostgreSQL/mode context;
- current scenario selector;
- current run state;
- one relevant primary action;
- no global marketing/search chrome unless the data size requires search.

### Overview

Lead with:

- three decisions that matter now;
- required/open/verified/unresolved counts as quiet ruled metrics;
- small target-design fragment;
- current analysis boundary;
- next useful action.

Do not show fabricated health, risk, readiness, or confidence scores.

## 6. Screen specifications

### Design

- interactive physical ER graph;
- switches for ORM-only, proposed, index, tenancy, and operation overlays;
- search by table/column/source;
- selected-object inspector;
- current/target diff;
- readable list/table alternative;
- layout persistence separate from graph evidence.

Physical FK: solid labeled edge. ORM-only: dashed edge with “ORM only.” Proposed: distinct addition/removal marker and status label. Color is secondary.

### Operations

- operation list grouped by endpoint/job/test identity;
- sequence view for transaction and queries;
- query-count/amplification markers;
- tables read/written;
- source stack;
- routing eligibility;
- fixture/test boundary always visible.

### Questions

- one material question per focused row/screen region;
- why it matters;
- affected decisions/scenarios;
- unknown is a first-class answer;
- save feedback and immediate affected-decision diff;
- no conversational chat metaphor.

### Decisions

- dependency-sorted list;
- evidence label and category;
- concise recommendation;
- sources, assumptions, alternatives, trade-offs;
- current/target fragment;
- exact patch sketch;
- accept/reject/defer with reason and revisit condition.

### Scenarios

Launch-minimal, Growth-ready, and Availability-ready use a true diff view:

- requirements satisfied;
- schema/topology delta;
- operational complexity;
- unresolved blockers;
- evidence available;
- migration dependencies.

Avoid feature-comparison pricing-table aesthetics.

### Proofs

- state: queued/running/verified/rejected/inconclusive/unsupported;
- parameter and fixture context;
- A1/B/A2 distribution;
- normalized plan diff;
- read/write/WAL/storage comparison;
- raw evidence download and reproduction command;
- rejected candidates visible but secondary.

### Migration path

- dependency graph plus ordered list;
- expand/backfill/validate/contract grouping;
- schema and application actions paired;
- deployment boundaries;
- rollback notes;
- planned PR identifier once roadmap generation exists.

## 7. Graph usability

- Default layout favors table clusters and minimizes crossings.
- Large schemas start collapsed by schema/domain when available.
- Search focuses without destroying layout.
- Keyboard selection and pan/zoom controls are available.
- Selected entity shows direct neighbors; non-neighbors de-emphasize.
- Edge details are accessible by focus/click, not hover alone.
- All graphs have a semantic table/list fallback.
- Operation and architecture nodes never contaminate the canonical ER view.
- Exported Mermaid/DBML/SVG preserves evidence labels where the format allows.

## 8. Interaction states

Every screen explicitly supports:

- pristine/no run;
- loading known work;
- streaming stage progress;
- complete;
- partial with visible boundary;
- failed with recovery;
- stale due to changed inputs;
- incompatible artifact version;
- empty but valid;
- permission required.

Skeletons may indicate known layout for brief loads. Long stages use named progress events, not indefinite shimmer.

## 9. Responsive behavior

- Primary design target: 1024–1440 px laptop/desktop.
- Fully usable review target: 768 px.
- Essential reading/question/decision flows: 320–430 px.
- Complex graphs may use focused single-node mode on mobile.
- Navigation becomes horizontally scrollable or compact, not an overlay blocking content.
- Tables wrap or receive contained horizontal scrolling.
- Actions remain labeled and reachable without hover.

## 10. Accessibility

- WCAG 2.2 AA contrast target.
- Native semantic controls and headings.
- Visible focus indicators.
- Logical keyboard order.
- Reduced motion honored.
- Status changes use polite live regions; failures use alerts.
- Graphs expose accessible summaries and list alternatives.
- Color always paired with text, shape, or line style.
- Minimum coarse-pointer target around 44 px where practical.
- Editable fields use 16 px effective text on mobile.

## 11. Motion

- No looping decorative animation.
- Progress spinner only during active unknown-duration work.
- Graph changes animate position briefly to preserve spatial context.
- Scenario/answer changes animate the affected diff, not the whole screen.
- Reduced-motion mode removes nonessential transitions.

## 12. Content style

- Lead with outcome: “Enforce tenant ownership for orders.”
- Explain evidence in plain language.
- Avoid “best practice,” “obviously,” “simply,” “AI-powered,” and breach claims.
- Use “primary/replica,” not “master/slave.”
- Use “PostgreSQL,” not “Postgres,” in formal headings; either is acceptable in compact prose.
- Always state fixture scale with measured results.
- Use exact code identifiers only when they help action.
- One recommendation, one decision.

## 13. Frontend design tokens

Token families, implemented for light/dark themes:

```text
surface.page
surface.base
surface.raised
text.primary
text.secondary
border.subtle
accent.primary
accent.soft
semantic.success
semantic.warning
semantic.danger
semantic.info
code.surface
code.text
radius.small / medium / large
space.1 ... space.8
```

Components consume semantic tokens, never raw palette values. Graph category colors have stable mappings and accessible redundant encodings.

## 14. Component inventory

Build only recurring primitives:

- AppShell
- ProjectContext
- ScenarioSelector
- RunStatus
- StageProgress
- EvidenceLabel
- SourceReference
- DecisionRow/Detail
- QuestionField
- MetricRule
- AnalysisBoundary
- Empty/Partial/FailureState
- SchemaGraph
- OperationSequence
- ScenarioDiff
- MeasurementComparison
- PlanDiff
- MigrationStep
- ApprovalDialog
- ShareInventory

Do not create a generic design-system package before two real features need a component.

## 15. Visual QA

### CLI snapshots

Matrix:

- 80/120 columns;
- color/no-color;
- Unicode/ASCII;
- interactive/non-TTY;
- success/partial/failure;
- macOS/Linux terminal assumptions.

### Browser screenshots

Core states in light and dark at 1440, 1024, and 390 px:

- Overview complete and partial
- Design graph physical/ORM/proposed
- Questions with affected diff
- Decision detail
- Experiment verified/inconclusive
- Migration path
- Approval dialog
- Share inventory

Screenshot changes require explicit review; snapshots are not blindly updated.

### Usability gates

- User identifies execution mode and analysis boundary in under five seconds.
- User distinguishes physical and ORM-only relationships without legend hunting.
- User can reach source evidence from a recommendation in one action.
- User can answer a question and identify changed decisions.
- User can reproduce a proof from its detail screen.
- CLI and UI report the same counts and terminology from one artifact fixture.

## 16. Interface PR gates

- `BE-05` establishes terminal capability detection and snapshot harness.
- `BE-02` freezes artifact vocabulary and status enums.
- `FE-01` establishes tokens, app shell, accessibility, and screenshot harness.
- `FE-02` validates the schema graph on real fixture sizes before more screens.
- Each backend feature ships polished terminal output in its own PR.
- Each frontend feature ships complete/partial/failure states and visual baselines.
- No release may defer CLI/UI polish to a final “design cleanup” PR.
