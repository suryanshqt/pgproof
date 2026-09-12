# Raw measurement evidence

Every statistic in [`../MEASUREMENT.md`](../MEASUREMENT.md) is computed from
these files. They exist so a reader can recompute the medians, IQRs, drift,
savings and ratios instead of trusting them.

## Files

| Path | Contents |
|---|---|
| `cases.json` | The exact SQL, parameters, index name and index DDL measured. Input to `collect`. |
| `environment.json` | Declared dataset facts and session settings every run must match. |
| `<case>/run-N.json` | One complete A1/B/A2 experiment: all warmups and all samples. |
| `<case>/plan-a1.json` | `EXPLAIN` for the control arm, timing disabled. |
| `<case>/plan-b.json` | `EXPLAIN` for the treatment arm, timing disabled. |
| `nplus1-001/evidence.json` | Statement counts, returned order ids and checksums for both fixtures. |
| `summary.json` | Derived statistics. Regenerated from the runs; never edited by hand. |

`nplus1-001/evidence.json` covers both fixtures even though it lives under
`demo-broken`, because the N+1 finding is a comparison between them and
`demo-broken` owns the baseline. `demo-clean` has no `measurements/` directory:
it is the control, not the subject.

## Run file fields

| Field | Meaning |
|---|---|
| `units` | Always `microseconds`. Every sample is an integer count. |
| `protocol.warmups` / `protocol.samples` | 3 and 7. Asserted by the test suite. |
| `protocol.fetch_policy` | What the timed region covers. |
| `arms.<arm>.warmups` | The discarded warmups, retained so the discard is visible. |
| `arms.<arm>.samples` | The seven retained samples the statistics come from. |
| `arms.<arm>.rows` | Rows returned, so a changed result set is detectable. |
| `index` | Name, DDL, build microseconds, size in bytes and pretty form. |
| `dataset` | Row counts and `total_cents_checksum`, tying the run to a dataset. |
| `server` | Server version string and the image digest it ran on. |
| `client` | Python, SQLAlchemy, Alembic, psycopg and pytest versions. |
| `host` | OS and architecture only. No machine name, user or path. |
| `session_settings` | The exact `SET` statements applied before timing. |
| `formulas` | The arithmetic, written out, so the statistics are checkable. |

## Required inventory

Exactly `IDX-001` runs 1, 2, 3 and `IDX-002` runs 1, 2, 3. No duplicate, missing
or additional identifier is accepted, and each file's declared `case_id` and
`run` must match its own path. Accepting "any non-empty set" would let a noisy
run be deleted and the remainder re-summarised without the omission showing.

## Provenance every run must match

| Field | Declared by |
|---|---|
| `server.image_digest` | `fixtures/benchmark-corpus.yaml` `runtime.postgres_digest` |
| `server.version` | `fixtures/benchmark-corpus.yaml` `runtime.postgres_server_version` |
| `client.{sqlalchemy,alembic,psycopg,pytest}` | `fixtures/demo-broken/uv.lock` |
| `client.python` | `fixtures/demo-broken/.python-version` |
| `dataset` | `environment.json` |
| `session_settings` | `environment.json` |
| `query.sql`, `query.params`, `index.name`, `index.ddl` | `cases.json` |

All runs in one committed session must additionally agree with each other on
`host`, `client`, `server`, `session_settings` and `recorded_at`. Host
architecture is compared across runs but not pinned to a value, so a reproducer
on another platform can commit its own session.

## Formulas

For seven samples, with `s = sorted(samples)`:

```text
median          = s[3]
q1, q3          = s[1], s[5]
iqr_fraction    = (s[5] - s[1]) / median
drift_fraction  = abs(median_a2 - median_a1) / median_a1
absolute_saving = median_a1 - median_b
ratio           = median_a1 / median_b
```

## Deliberately absent

No credentials, no absolute paths, no machine identifiers. The database password
in the reproduction commands is a throwaway container value that is published in
`../MEASUREMENT.md` anyway.

No write-cost, WAL or HOT measurements: those belong to `BE-28`.

## Commands

```bash
# From the repository root.
uv run python scripts/fixture_measurements.py summarize \
  --measurements fixtures/demo-broken/measurements --write
uv run python scripts/fixture_measurements.py check \
  --measurements fixtures/demo-broken/measurements
```

`check` fails if `summary.json` or the generated block in `../MEASUREMENT.md`
disagrees with these files, if a run is missing samples, or if plan evidence is
absent. The same checks run in the pytest suite.
