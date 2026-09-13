# ADR 0001: Contract versioning and compatibility

**Status:** accepted
**Date:** 2026-09-12
**Roadmap item:** BE-03
**Supersedes:** none

## Context

`docs/ARCHITECTURE.md` section 7 states that readers reject unsupported major
versions and tolerate additive compatible fields. `docs/TECHNICAL_DESIGN.md`
section 4 states that additive minor schema changes are allowed and breaking
changes increment major. Neither document fixes what "additive" means in
practice, what a reader does with an unknown field, or how the contract version
relates to the tool version.

BE-03 introduces the models that generate the JSON Schemas the frontend consumes,
so the policy has to be decided now rather than when the first incompatible
change is proposed.

## Decision

The artifact contract carries a two-part `schema_version`, starting at `1.0`,
independent of `tool_version`.

1. A reader rejects a document whose **major** differs from the major it was
   built for. This build reads major `1`.
2. A reader accepts any **minor** within its supported major, including a minor
   higher than its own, because minors are additive by definition.
3. Unknown fields are **ignored**, not rejected. Contract models are configured
   `extra="ignore"`.
4. A minor increment may only **add optional fields**. Adding a required field,
   removing a field, narrowing a type, or changing a field's meaning is a
   **major** change.
5. **Closed semantic enums are major-only.** Adding, removing or renaming a
   member of an enum that carries product meaning is a **major** change, and an
   unknown value is rejected at every layer. These are the enums a consumer
   matches exhaustively to decide what something *means*: `EvidenceKind`,
   `RecommendationPriority`, `VerificationState`, `ProofVerdict`, `StageStatus`,
   `EdgeKind`, `AmplificationClass` and the rest of the domain vocabulary.
6. **The artifact-kind registry is additive.** `ArtifactType` is not a semantic
   enum; it is the set of top-level document kinds. **Adding a new independent
   artifact kind is a minor change.** Removing or renaming a kind is major.

   An older reader keeps reading every kind it knows, because each kind is a
   separate document validated against its own schema. It may reject an unknown
   kind when it is explicitly asked to parse one, and `parse_artifact` does
   exactly that, naming the kinds it does know.

   Each generated per-artifact schema is **strictly discriminated**: its
   `artifact_type` is a `const` of that one kind. A document of an unknown kind
   therefore cannot accidentally validate against a known contract, and a `code`
   document cannot be read through the `schema` contract.
7. `tool_version` and `schema_version` move independently. The tool may release
   without moving the contract, and the contract may move without a tool release.
8. A malformed or incomplete document produces a field-level validation error
   naming the path that failed. A future-major document produces a version error
   before any payload validation is attempted, so the diagnosis is the version
   rather than a confusing field error.

## Alternatives considered

| Alternative | Why it was not chosen |
|---|---|
| Single integer version | Cannot express an additive change, so every addition would force every reader to update. |
| `extra="forbid"` on transport models | Directly contradicts the tolerate-additive-fields rule in ARCHITECTURE section 7; an older reader would reject a newer writer's harmless addition. |
| Reject minors above the reader's own | Makes a writer upgrade a breaking change for every reader, defeating the purpose of minors. |
| Tie `schema_version` to `tool_version` | Couples a contract promise to a release cadence, and would force a contract bump for an unrelated bug fix. |
| Semantic version with a patch component | No behavioural difference from a minor for a data contract; a third component would be decorative. |
| Adding any enum member as a minor change | Tried first and withdrawn. For a semantic enum it requires every consumer to tolerate an unknown value, but the Pydantic models, the generated JSON Schemas and the generated TypeScript unions all reject one, and none can be made permissive without losing the exhaustiveness that makes a closed enum useful. |
| Treating every enum, including `ArtifactType`, as major-only | Tried second and withdrawn. `ArtifactType` deliberately omits `project` (BE-04), `migration-plan` (BE-14) and `decisions` (BE-33), so a blanket rule would have forced a major contract bump merely to finish the declared roadmap. That is a cost with no corresponding safety gain: a new document kind cannot change how an existing kind is read. Splitting the rule keeps the strict guarantee where it protects meaning and drops it where it only obstructed planned work. |
| Open enums with a catch-all member | Would let an unknown value through as a silent `other`, which is worse than a rejection: a consumer would render an unrecognised evidence label as if it were understood. `EvidenceKind` in particular must stay closed, because the four labels are the product's trust boundary. |

## Consequences

- Easier: a frontend built against `1.0` keeps working when the backend emits
  `1.3`, and a new optional field needs no coordinated release.
- Harder: an unknown field is silently dropped on round trip, so a typo in a
  field name is not reported. Required-field errors still catch the common case,
  and the frozen fixtures catch the rest.
- A major bump is deliberately expensive: it requires a new ADR, a migration
  note, and regenerated schemas, fixtures and TypeScript types.
- Harder: adding one **semantic** enum member costs a major version. That is a
  real price, accepted for v1 because the alternative is a tolerance no layer
  implements. The enums most likely to grow already carry an explicit `unknown`
  or `unresolved` member, so a producer that cannot classify a value has
  somewhere to put it without inventing one.
- Easier: the remaining roadmap artifacts — `project` in BE-04, `migration-plan`
  in BE-14, `decisions` in BE-33 — arrive as **minor** bumps. None of them is
  implemented here; only the rule that lets them land additively.
- Consumers do **not** need unknown-value handling for semantic enums. All three
  layers reject an unknown member identically, which is what makes exhaustive
  matching safe in TypeScript.
- A consumer that dispatches on `artifact_type` must handle "a kind I do not
  know" as a named outcome rather than a crash. In Python that is the
  `unknown artifact_type` error from `parse_artifact`; in TypeScript it is the
  absent schema lookup in the fixture validator.

## Product boundary impact

- local-first operation: unaffected
- absence of telemetry: unaffected
- absence of a production database connection: unaffected
- execution of project code outside the isolated runner: unaffected
- the four evidence labels: unaffected, and doubly protected. `EvidenceKind` is a
  closed semantic enum whose members are rejected if unrecognised, and changing
  it remains both an ADR-gated decision per ARCHITECTURE section 16 and, under
  rule 5, a major contract change. Rule 6 does not apply to it: `EvidenceKind` is
  not the artifact-kind registry.
- artifact compatibility rules: **this ADR is the statement of them**
- repository mutation: unaffected

## Verification

- `require_supported` rejects majors other than `1` and accepts every minor
  within it, covered by `tests/unit/test_contract_models.py`.
- `Envelope` rejects a future major at field validation, and `parse_artifact`
  reports the version before the payload.
- Every frozen fixture stays valid when an unknown top-level field, an unknown
  field inside `data`, and a raised minor are added, covered by
  `tests/contract/test_contract_fixtures.py`.
- The generated JSON Schema pins `schema_version` to `^1\.(0|[1-9][0-9]*)$`, so
  an independent validator enforces the same major rule.
- An unknown **semantic** enum value is rejected by the Pydantic model, by
  independent JSON Schema validation in Python, and by Ajv in TypeScript,
  **including when the document declares a higher compatible minor**. The frozen
  fixture `unknown-enum-on-higher-minor` exists for exactly that case, so the
  policy cannot drift back to a documented-but-unimplemented tolerance.
- Each per-artifact schema pins `artifact_type` to a `const`, so a `code`
  document is rejected by the `schema` contract in Python and by an independent
  validator. Tests assert both directions.
- A document of an unknown artifact kind fails with a message naming the known
  kinds, while every known kind still parses. A test asserts that pair, which is
  what makes rule 6 additive in practice rather than only on paper.
