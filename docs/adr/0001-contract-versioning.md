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
5. **Any change to a stable enum is a major change**, including adding a member.
   An unknown enum value is rejected, not tolerated, at every layer.
6. `tool_version` and `schema_version` move independently. The tool may release
   without moving the contract, and the contract may move without a tool release.
7. A malformed or incomplete document produces a field-level validation error
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
| Adding an enum member as a minor change | Tried first and withdrawn. It requires every consumer to tolerate an unknown value, but the Pydantic models, the generated JSON Schemas and the generated TypeScript unions all reject one, and none of the three can be made permissive without losing the exhaustiveness that makes a closed enum useful. Documenting a tolerance that no implementation provides would have been a false claim, so the policy was changed to match the implementations rather than the reverse. |
| Open enums with a catch-all member | Would let an unknown value through as a silent `other`, which is worse than a rejection: a consumer would render an unrecognised evidence label as if it were understood. `EvidenceKind` in particular must stay closed, because the four labels are the product's trust boundary. |

## Consequences

- Easier: a frontend built against `1.0` keeps working when the backend emits
  `1.3`, and a new optional field needs no coordinated release.
- Harder: an unknown field is silently dropped on round trip, so a typo in a
  field name is not reported. Required-field errors still catch the common case,
  and the frozen fixtures catch the rest.
- A major bump is deliberately expensive: it requires a new ADR, a migration
  note, and regenerated schemas, fixtures and TypeScript types.
- Harder: adding one enum member now costs a major version. That is a real price,
  accepted for v1 because the alternative is a tolerance no layer implements. The
  enums most likely to grow already carry an explicit `unknown` or `unresolved`
  member, so a producer that cannot classify a value has somewhere to put it
  without inventing a new one.
- Consumers do **not** need unknown-value handling. All three layers reject an
  unknown member identically, which is what makes exhaustive matching safe in
  TypeScript.

## Product boundary impact

- local-first operation: unaffected
- absence of telemetry: unaffected
- absence of a production database connection: unaffected
- execution of project code outside the isolated runner: unaffected
- the four evidence labels: unaffected, and now doubly protected. `EvidenceKind`
  is a closed enum whose members are rejected if unrecognised, and changing it
  remains both an ADR-gated decision per ARCHITECTURE section 16 and, under rule
  5, a major contract change.
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
- An unknown enum value is rejected by the Pydantic model, by independent JSON
  Schema validation in Python, and by Ajv in TypeScript, **including when the
  document declares a higher compatible minor**. The frozen fixture
  `unknown-enum-on-higher-minor` exists for exactly that case, so the policy
  cannot drift back to a documented-but-unimplemented tolerance.
