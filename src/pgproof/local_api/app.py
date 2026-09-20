"""The loopback FastAPI application: routing, security middleware, and static hosting.

`docs/ARCHITECTURE.md` section 9's API boundary lists what is allowed
(list metadata, return validated public artifacts, stream events, validate
context/decision writes) and forbidden (arbitrary file access, accepting a
database URL, returning private bind values). Every route here reads or
writes only through `pgproof.store`, never a raw path the caller supplies.

`project.json`, `/proofs/{id}`, and `/decisions/{id}` have no domain model or
store location yet (`docs/PR_ROADMAP.md`: BE-04, BE-30, BE-33 respectively)
and answer `501` by name rather than a bare `404`, so the gap is visible
rather than looking like a typo'd URL.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any, Final

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from pgproof.domain.envelope import ArtifactType
from pgproof.domain.registry import parse_artifact
from pgproof.local_api.security import (
    OriginCheckMiddleware,
    SecurityHeadersMiddleware,
    require_session_token,
)
from pgproof.store.artifacts import read_artifact, write_artifact
from pgproof.store.paths import ProjectLayout

_STATIC_DIR: Final = Path(__file__).parent / "static"

_ANALYSIS_ARTIFACT_KINDS: Final[dict[str, ArtifactType]] = {
    "schema": ArtifactType.SCHEMA,
    "code": ArtifactType.CODE,
    "workload": ArtifactType.WORKLOAD,
    "evidence": ArtifactType.EVIDENCE,
    "recommendations": ArtifactType.RECOMMENDATIONS,
    "scenarios": ArtifactType.SCENARIOS,
}

api_router = APIRouter(dependencies=[Depends(require_session_token)])


def _layout(request: Request) -> ProjectLayout:
    layout: ProjectLayout = request.app.state.layout
    return layout


def _read_or_404(path: Path, artifact_type: ArtifactType, *, kind: str) -> dict[str, Any]:
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"{kind} has not been produced yet")
    return read_artifact(path, artifact_type).canonical_dict()


@api_router.get("/session")
def get_session() -> dict[str, bool]:
    return {"valid": True}


@api_router.get("/project")
def get_project() -> None:
    raise HTTPException(status_code=501, detail="project.json is not yet implemented")


@api_router.get("/artifacts/context")
def get_context(request: Request) -> dict[str, Any]:
    return _read_or_404(_layout(request).context_path, ArtifactType.CONTEXT, kind="context")


@api_router.get("/artifacts/graph")
def get_graph(request: Request, view: str = "current") -> dict[str, Any]:
    if view not in ("current", "target"):
        raise HTTPException(status_code=422, detail="view must be 'current' or 'target'")
    path = _layout(request).diagram_path(view)  # type: ignore[arg-type]
    return _read_or_404(path, ArtifactType.GRAPH, kind=f"graph ({view})")


@api_router.get("/artifacts/{kind}")
def get_analysis_artifact(kind: str, request: Request) -> dict[str, Any]:
    artifact_type = _ANALYSIS_ARTIFACT_KINDS.get(kind)
    if artifact_type is None:
        raise HTTPException(status_code=404, detail=f"unknown artifact kind {kind!r}")
    path = _layout(request).analysis_path(artifact_type)
    return _read_or_404(path, artifact_type, kind=kind)


@api_router.get("/runs")
def list_runs(request: Request) -> dict[str, list[str]]:
    runs_dir = _layout(request).runs_dir
    if not runs_dir.is_dir():
        return {"runs": []}
    return {"runs": sorted(entry.name for entry in runs_dir.iterdir() if entry.is_dir())}


@api_router.get("/runs/{run_id}")
def get_run(run_id: str, request: Request) -> dict[str, Any]:
    path = _layout(request).run_result_path(run_id)
    return _read_or_404(path, ArtifactType.STAGES, kind=f"run {run_id!r}")


@api_router.get("/runs/{run_id}/events")
def stream_run_events(run_id: str, request: Request) -> StreamingResponse:
    events_path = _layout(request).run_events_path(run_id)
    if not events_path.is_file():
        raise HTTPException(status_code=404, detail=f"run {run_id!r} has no event stream")

    def _events() -> Iterator[str]:
        for line in events_path.read_text(encoding="utf-8").splitlines():
            yield f"data: {line}\n\n"

    return StreamingResponse(_events(), media_type="text/event-stream")


@api_router.get("/proofs/{proof_id}")
def get_proof(proof_id: str) -> None:
    del proof_id
    raise HTTPException(status_code=501, detail="proof bundles are not yet implemented (BE-30)")


@api_router.put("/context")
def put_context(document: dict[str, Any], request: Request) -> dict[str, Any]:
    try:
        envelope = parse_artifact(document)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if envelope.artifact_type is not ArtifactType.CONTEXT:
        raise HTTPException(status_code=422, detail="expected a context artifact")
    write_artifact(_layout(request).context_path, envelope)
    return envelope.canonical_dict()


@api_router.put("/decisions/{decision_id}")
def put_decision(decision_id: str, document: dict[str, Any]) -> None:
    del decision_id, document
    raise HTTPException(status_code=501, detail="decisions.json is not yet implemented (BE-33)")


def create_app(*, layout: ProjectLayout, session_token: str, allowed_origin: str) -> FastAPI:
    """One request-serving app for one `pgproof ui` invocation.

    Docs are disabled: this API has no public consumer other than the bundled
    UI, and an interactive schema explorer is needless surface on a loopback
    service that already states its full contract in this module.
    """
    app = FastAPI(title="pgproof", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.layout = layout
    app.state.session_token = session_token
    app.add_middleware(OriginCheckMiddleware, allowed_origin=allowed_origin)
    app.add_middleware(SecurityHeadersMiddleware)
    app.include_router(api_router, prefix="/api/v1")
    app.mount("/", StaticFiles(directory=_STATIC_DIR, html=True), name="static")
    return app
