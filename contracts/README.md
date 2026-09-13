# pgproof artifact contracts

The durable boundary between analysis stages, and between the backend and the
frontend. `docs/ARCHITECTURE.md` section 7 defines the rules; ADR 0001 defines
the versioning policy.

| Path | Contents | In the wheel |
|---|---|---|
| `schemas/` | Generated JSON Schema 2020-12, one per top-level artifact | yes, at `pgproof/contracts/schemas` |
| `fixtures/valid/` | Frozen valid example of every artifact | no |
| `fixtures/invalid/` | Frozen counter-examples, one per rejection rule | no |
| `types/` | Contract-only TypeScript toolchain and generated types | no |

Only the schemas ship. Fixtures and the TypeScript toolchain are development
assets, verified absent from the wheel by test.

## Regenerating

```bash
# JSON Schemas from the Pydantic models.
uv run python scripts/generate_contracts.py --write
uv run python scripts/generate_contracts.py --check

# TypeScript types from the JSON Schemas.
cd contracts/types && npm ci && npm run generate && npm run check && npm run compile
```

Both generators are byte-stable and both support `--check`, which CI runs as a
drift gate. A Pydantic or generator upgrade that changes output shows up as
reviewable drift rather than a silent change.

## Validating the fixtures in both languages

`docs/ARCHITECTURE.md` section 7 requires the same frozen fixtures to validate in
Python and in TypeScript. Both halves exist:

```bash
uv run pytest tests/contract                       # Python: Pydantic and jsonschema
cd contracts/types && npm run validate:fixtures    # TypeScript: Ajv 2020
```

Each half validates all ten valid fixtures against the generated schemas and
asserts that every schema-enforceable invalid fixture is rejected. Both halves
carry the same explicit list of cases JSON Schema **cannot** enforce, so neither
over-claims.

## Enum policy

Two rules, because two different things were being conflated.

**Closed semantic enums** — `EvidenceKind`, `RecommendationPriority`,
`VerificationState`, `ProofVerdict`, `EdgeKind` and the rest of the domain
vocabulary. Adding, removing or renaming a member is a **major** change, and an
unknown value is rejected by Pydantic, by independent JSON Schema validation and
by Ajv, including when the document declares a higher compatible minor.

**The artifact-kind registry** — `ArtifactType`. Adding a new independent
artifact kind is a **minor** change; removing or renaming one is major. An older
reader keeps reading every kind it knows and rejects an unknown kind only when
explicitly asked to parse one, naming the kinds it does know.

That split matters concretely: `project` (BE-04), `migration-plan` (BE-14) and
`decisions` (BE-33) are still to come. A blanket major-only rule would have
forced a major bump merely to finish the declared roadmap.

Each per-artifact schema is **strictly discriminated**: its `artifact_type` is a
`const` of that one kind, so a `code` document cannot validate against the
`schema` contract in Python, in `jsonschema`, or in Ajv. The generated
TypeScript reflects it too — `schema.ts` declares
`export type ArtifactType = "schema"`.

See [ADR 0001](../docs/adr/0001-contract-versioning.md) rules 5 and 6.

## Composite identity framing

Composite identities use canonical compact JSON framing rather than delimiter
joining, because a PostgreSQL logical name may contain any delimiter. Two real
collisions motivated it:

```text
column_id(table_id("a", "b,c"), "d")     joined to  a.b,c.d
table_id("a", "b"), table_id("c", "d")   joined to  a.b,c.d

SourceRef(path="app/model#1")            joined to  app/model#1@<hash>
SourceRef(path="app/model", line=1)      joined to  app/model#1@<hash>
```

Framed, they are distinct and reversible:

```text
["a.b",["a.b,c.d"]]           vs  ["a.b",["a.b","c.d"]]
["app/model#1",null,"<hash>"] vs  ["app/model",1,"<hash>"]
```

`node_id` and `proof_id` keep single-delimiter joining because their prefixes
cannot contain the delimiter — a node kind matches `[a-z][a-z0-9_]*` and a
recommendation id and sha256 digest contain no `@`. Both are validated
separately and both carry collision tests.

## Validating a throwaway copy

`npm run validate:fixtures` accepts `--root <dir>`, or `PGPROOF_CONTRACTS_ROOT`,
pointing at a directory containing `schemas/` and `fixtures/`. Tests use it to
validate a copy under `tmp_path` so a tracked fixture is never written during a
test run. CI passes nothing and gets the repository paths.

## Identity encoding

Table and column identities are built from **logical** schema, table and column
names, never from database OIDs. Parts are joined with `.` after escaping `\` as
`\\` and `.` as `\.`, which makes the encoding reversible and collision-free:
`public` + `a.b` encodes to `public.a\.b`, while `public.a` + `b` encodes to
`public\.a.b`.

Every legal PostgreSQL name is representable, including quoted numeric names,
mixed case, embedded spaces, Unicode, embedded double quotes and embedded dots.
Empty names and NUL are rejected. A numeric name such as `"2024"` is **not**
rejected: that would confuse "this name is numeric" with "this identity came from
an OID". OIDs are excluded because no contract model has an OID field, asserted
by test.

## Frozen fixtures are data, not output

`fixtures/` is **not** generated by the build. The files were produced once from
the models and are now committed data, edited by hand. That is deliberate: a
model change that breaks a fixture is supposed to fail the test suite, which it
cannot do if the fixture is regenerated from the model it is meant to check.

Every fixture uses synthetic data only, asserted by test.

## What each invalid fixture proves

| Fixture | Rejected by | Reason |
|---|---|---|
| `unsupported-major-version` | version check | `schema_version` is a future major |
| `malformed-digest` | model and schema | digest is not 64 lowercase hex characters |
| `absolute-path` | model and schema | source path is absolute |
| `non-posix-path` | model and schema | source path uses a Windows separator |
| `non-utc-timestamp` | model and schema | `created_at` carries an offset instead of `Z` |
| `invalid-enum` | model and schema | evidence kind outside the four labels |
| `missing-required-field` | model and schema | `tool_version` absent |
| `dangling-graph-edge` | model only | edge names a node the graph does not hold |
| `recommendation-missing-evidence` | integrity check only | cites an evidence id that does not exist |
| `measurement-without-verified-state` | model only | a fixture measurement without `verified_in_fixture` |
| `unqualified-table-id` | model **and** schema | table id does not decode to two logical names |
| `overqualified-column-id` | model **and** schema | column id decodes to four logical names |
| `dangling-identity-escape` | model **and** schema | identity ends with a dangling escape |
| `unknown-enum-on-higher-minor` | model **and** schema | unknown enum value, on a compatible minor |

The last three are not expressible in JSON Schema. A test asserts exactly that,
so the boundary of independent validation stays honest rather than implied.
