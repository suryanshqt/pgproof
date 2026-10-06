"""`adapters.proof.bundle` round-trip and tamper detection.
`docs/TECHNICAL_DESIGN.md` section 26: "reproduction verifies... artifact
hashes." Pure file I/O, no database.
"""

from __future__ import annotations

from pathlib import Path

from pgproof.adapters.proof.bundle import read_proof_bundle, write_proof_bundle


def _write(directory: Path) -> None:
    write_proof_bundle(
        directory,
        proof_id="IDX-001@sha256:" + "a" * 64,
        tool_version="0.1.0",
        generator_version=1,
        schema_sql="CREATE TABLE orders (id serial primary key);",
        query_sql="SELECT id FROM orders WHERE user_id = %(user_id)s",
        parameters={"user_id": {"value_hash": "sha256:" + "b" * 64, "is_redacted": True}},
        dataset={
            "global_seed": 42,
            "scale": {"public.orders": 1000},
            "epoch": "2026-01-01T00:00:00+00:00",
        },
        config={"candidate": {"apply_sql": "CREATE INDEX ...", "revert_sql": "DROP INDEX ..."}},
        evidence={
            "control-a1": {
                "median_us": 5000.0,
                "samples_us": [4800, 4900, 5000, 5100, 5200, 5300, 5400],
            },
            "treatment-b": {"median_us": 500.0, "samples_us": [480, 490, 500, 510, 520, 530, 540]},
            "control-a2": {
                "median_us": 5050.0,
                "samples_us": [4900, 4950, 5050, 5100, 5150, 5200, 5250],
            },
        },
        plans={
            "treatment-b": {
                "plan_fingerprint": "sha256:" + "c" * 64,
                "normalized_shape": "Index Scan",
            }
        },
        readme="# Proof IDX-001\n",
    )


def test_a_freshly_written_bundle_round_trips_with_no_tamper_problems(tmp_path: Path) -> None:
    _write(tmp_path)
    contents, problems = read_proof_bundle(tmp_path)
    assert problems == ()
    assert contents is not None
    assert contents.manifest.proof_id == "IDX-001@sha256:" + "a" * 64
    assert "CREATE TABLE orders" in contents.schema_sql
    assert contents.parameters == {
        "user_id": {"value_hash": "sha256:" + "b" * 64, "is_redacted": True}
    }
    control_a1 = contents.evidence["control-a1"]
    treatment_b_plan = contents.plans["treatment-b"]
    assert isinstance(control_a1, dict)
    assert isinstance(treatment_b_plan, dict)
    assert control_a1["median_us"] == 5000.0
    assert treatment_b_plan["plan_fingerprint"] == "sha256:" + "c" * 64


def test_editing_a_text_file_after_writing_is_detected_as_tampered(tmp_path: Path) -> None:
    _write(tmp_path)
    (tmp_path / "query.sql").write_text("SELECT * FROM orders", encoding="utf-8")
    contents, problems = read_proof_bundle(tmp_path)
    assert contents is None
    assert any("query.sql" in problem and "tampered" in problem for problem in problems)


def test_editing_an_evidence_file_after_writing_is_detected_as_tampered(tmp_path: Path) -> None:
    _write(tmp_path)
    (tmp_path / "evidence" / "control-a1.json").write_text('{"median_us": 1.0}', encoding="utf-8")
    contents, problems = read_proof_bundle(tmp_path)
    assert contents is None
    assert any("control-a1" in problem for problem in problems)


def test_a_missing_declared_file_is_reported_not_raised(tmp_path: Path) -> None:
    _write(tmp_path)
    (tmp_path / "config.yaml").unlink()
    contents, problems = read_proof_bundle(tmp_path)
    assert contents is None
    assert any("config.yaml" in problem and "missing" in problem for problem in problems)


def test_a_missing_manifest_is_reported_not_raised(tmp_path: Path) -> None:
    contents, problems = read_proof_bundle(tmp_path)
    assert contents is None
    assert problems == ("proof.yaml is missing",)


def test_a_malformed_manifest_is_reported_not_raised(tmp_path: Path) -> None:
    (tmp_path / "proof.yaml").write_text("not: valid: yaml: at: all: ][", encoding="utf-8")
    contents, problems = read_proof_bundle(tmp_path)
    assert contents is None
    assert len(problems) == 1
    assert "not valid YAML" in problems[0]
