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
   removing a field, narrowing a type, changing a field's meaning, or removing or
   renaming an enum member is a **major** change.
5. Adding an enum member is a minor change. Consumers must therefore treat an
   unrecognised enum value as unknown rather than as an error, which is why
   several enums already carry an explicit `unknown` or `unresolved` member.
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

## Consequences

- Easier: a frontend built against `1.0` keeps working when the backend emits
  `1.3`, and a new optional field needs no coordinated release.
- Harder: an unknown field is silently dropped on round trip, so a typo in a
  field name is not reported. Required-field errors still catch the common case,
  and the frozen fixtures catch the rest.
- A major bump is deliberately expensive: it requires a new ADR, a migration
  note, and regenerated schemas, fixtures and TypeScript types.
- Consumers must tolerate unrecognised enum members. This is stated here because
  it is not enforceable by the schema alone.

## Product boundary impact

- local-first operation: unaffected
- absence of telemetry: unaffected
- absence of a production database connection: unaffected
- execution of project code outside the isolated runner: unaffected
- the four evidence labels: unaffected. `EvidenceKind` is a closed enum, and
  changing it remains an ADR-gated decision per ARCHITECTURE section 16.
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
