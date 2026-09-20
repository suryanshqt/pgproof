"""`pgproof.local_api.app`: every route, `docs/ARCHITECTURE.md` section 9's API boundary."""

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from pgproof.domain.envelope import ArtifactType, Envelope
from pgproof.domain.registry import envelope_model_for
from pgproof.local_api.app import create_app
from pgproof.store.artifacts import write_artifact
from pgproof.store.paths import ProjectLayout

_TOKEN = "test-token"
_ORIGIN = "http://127.0.0.1:1"
_RUN = "01JQ0X3M4N5P6R7S8T9V0W1X2Y"


def _client(tmp_path: Path) -> tuple[TestClient, ProjectLayout]:
    layout = ProjectLayout(tmp_path)
    layout.ensure_base_layout()
    app = create_app(layout=layout, session_token=_TOKEN, allowed_origin=_ORIGIN)
    client = TestClient(app, headers={"x-pgproof-session-token": _TOKEN})
    return client, layout


def _schema_envelope() -> Envelope[Any]:
    envelope_cls = envelope_model_for(ArtifactType.SCHEMA)
    return envelope_cls(
        tool_version="0.1.0",
        artifact_type=ArtifactType.SCHEMA,
        created_at="2026-01-01T00:00:00Z",
        run_id=_RUN,
        data={"provenance": "physical_catalog"},
    )


def _context_document() -> dict[str, Any]:
    envelope_cls = envelope_model_for(ArtifactType.CONTEXT)
    envelope = envelope_cls(
        tool_version="0.1.0",
        artifact_type=ArtifactType.CONTEXT,
        created_at="2026-01-01T00:00:00Z",
        run_id=_RUN,
        data={},
    )
    return envelope.canonical_dict()


# --------------------------------------------------------------------------- #
# Authentication and static hosting cut across every route
# --------------------------------------------------------------------------- #
def test_every_api_route_requires_the_session_token(tmp_path: Path) -> None:
    layout = ProjectLayout(tmp_path)
    layout.ensure_base_layout()
    app = create_app(layout=layout, session_token=_TOKEN, allowed_origin=_ORIGIN)
    unauthenticated = TestClient(app)
    assert unauthenticated.get("/api/v1/session").status_code == 401


def test_the_placeholder_ui_is_served_at_root_without_a_token(tmp_path: Path) -> None:
    layout = ProjectLayout(tmp_path)
    layout.ensure_base_layout()
    app = create_app(layout=layout, session_token=_TOKEN, allowed_origin=_ORIGIN)
    response = TestClient(app).get("/")
    assert response.status_code == 200
    assert "pgproof" in response.text


# --------------------------------------------------------------------------- #
# GET /session, /project
# --------------------------------------------------------------------------- #
def test_session_confirms_a_valid_token(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    assert client.get("/api/v1/session").json() == {"valid": True}


def test_project_is_not_yet_implemented(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    response = client.get("/api/v1/project")
    assert response.status_code == 501


# --------------------------------------------------------------------------- #
# GET /artifacts/{kind}
# --------------------------------------------------------------------------- #
def test_reading_an_artifact_before_it_exists_is_a_404(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    assert client.get("/api/v1/artifacts/schema").status_code == 404


def test_reading_a_written_analysis_artifact_returns_it(tmp_path: Path) -> None:
    client, layout = _client(tmp_path)
    envelope = _schema_envelope()
    write_artifact(layout.analysis_path(ArtifactType.SCHEMA), envelope)
    response = client.get("/api/v1/artifacts/schema")
    assert response.status_code == 200
    assert response.json() == envelope.canonical_dict()


def test_an_unknown_artifact_kind_is_a_404(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    assert client.get("/api/v1/artifacts/not-a-real-kind").status_code == 404


def test_reading_context_before_it_is_written_is_a_404(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    assert client.get("/api/v1/artifacts/context").status_code == 404


def test_graph_defaults_to_the_current_view(tmp_path: Path) -> None:
    client, layout = _client(tmp_path)
    envelope_cls = envelope_model_for(ArtifactType.GRAPH)
    envelope = envelope_cls(
        tool_version="0.1.0",
        artifact_type=ArtifactType.GRAPH,
        created_at="2026-01-01T00:00:00Z",
        run_id=_RUN,
        data={"view": "current"},
    )
    write_artifact(layout.diagram_path("current"), envelope)
    response = client.get("/api/v1/artifacts/graph")
    assert response.status_code == 200
    assert response.json()["data"]["view"] == "current"


def test_graph_rejects_an_unknown_view(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    assert client.get("/api/v1/artifacts/graph", params={"view": "bogus"}).status_code == 422


# --------------------------------------------------------------------------- #
# GET /runs, /runs/{id}, /runs/{id}/events
# --------------------------------------------------------------------------- #
def test_listing_runs_when_none_exist_is_empty(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    assert client.get("/api/v1/runs").json() == {"runs": []}


def test_listing_runs_finds_run_directories(tmp_path: Path) -> None:
    client, layout = _client(tmp_path)
    (layout.run_dir(_RUN)).mkdir(parents=True)
    assert client.get("/api/v1/runs").json() == {"runs": [_RUN]}


def test_listing_runs_before_any_run_has_ever_happened(tmp_path: Path) -> None:
    """No `runs/` directory at all, not just an empty one."""
    layout = ProjectLayout(tmp_path)
    app = create_app(layout=layout, session_token=_TOKEN, allowed_origin=_ORIGIN)
    client = TestClient(app, headers={"x-pgproof-session-token": _TOKEN})
    assert client.get("/api/v1/runs").json() == {"runs": []}


def test_getting_an_unknown_run_is_a_404(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    assert client.get(f"/api/v1/runs/{_RUN}").status_code == 404


def test_getting_a_run_returns_its_result(tmp_path: Path) -> None:
    client, layout = _client(tmp_path)
    envelope_cls = envelope_model_for(ArtifactType.STAGES)
    envelope = envelope_cls(
        tool_version="0.1.0",
        artifact_type=ArtifactType.STAGES,
        created_at="2026-01-01T00:00:00Z",
        run_id=_RUN,
        data={"stages": []},
    )
    write_artifact(layout.run_result_path(_RUN), envelope)
    response = client.get(f"/api/v1/runs/{_RUN}")
    assert response.status_code == 200
    assert response.json()["data"]["stages"] == []


def test_events_for_an_unknown_run_is_a_404(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    assert client.get(f"/api/v1/runs/{_RUN}/events").status_code == 404


def test_events_stream_replays_every_recorded_line(tmp_path: Path) -> None:
    client, layout = _client(tmp_path)
    events_path = layout.run_events_path(_RUN)
    events_path.parent.mkdir(parents=True)
    events_path.write_text('{"kind": "stage_started"}\n{"kind": "stage_completed"}\n')
    response = client.get(f"/api/v1/runs/{_RUN}/events")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.text == (
        'data: {"kind": "stage_started"}\n\ndata: {"kind": "stage_completed"}\n\n'
    )


# --------------------------------------------------------------------------- #
# GET /proofs/{id}
# --------------------------------------------------------------------------- #
def test_proofs_are_not_yet_implemented(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    assert client.get("/api/v1/proofs/IDX-004").status_code == 501


# --------------------------------------------------------------------------- #
# PUT /context, /decisions/{id}
# --------------------------------------------------------------------------- #
def test_put_context_writes_a_validated_context_artifact(tmp_path: Path) -> None:
    client, layout = _client(tmp_path)
    response = client.put("/api/v1/context", json=_context_document())
    assert response.status_code == 200
    assert layout.context_path.is_file()


def test_put_context_rejects_a_document_of_the_wrong_artifact_type(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    wrong = _schema_envelope().canonical_dict()
    assert client.put("/api/v1/context", json=wrong).status_code == 422


def test_put_context_rejects_a_malformed_document(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    assert client.put("/api/v1/context", json={"not": "an envelope"}).status_code == 422


def test_put_decision_is_not_yet_implemented(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    response = client.put("/api/v1/decisions/some-id", json={"anything": True})
    assert response.status_code == 501


@pytest.mark.parametrize("method", ["get", "put"])
def test_the_origin_check_still_applies_to_api_routes(tmp_path: Path, method: str) -> None:
    client, _ = _client(tmp_path)
    response = client.request(
        method,
        "/api/v1/session" if method == "get" else "/api/v1/context",
        headers={"origin": "https://evil.example"},
        json=_context_document() if method == "put" else None,
    )
    assert response.status_code == 403
