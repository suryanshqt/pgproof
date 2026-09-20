"""The `.pgproof` directory layout, `docs/ARCHITECTURE.md` section 7.

```text
.pgproof/
  context.json
  analysis/{schema,code,workload,evidence,recommendations,scenarios}.json
  diagrams/{current,target}.graph.json
  runs/<run-id>/{manifest.json, events.ndjson, result.json}
```

`project.json`, `decisions.json`, `analysis/migration-plan.json` and `proofs/`
have no domain model yet (BE-04, BE-33 and BE-14 respectively per
`docs/PR_ROADMAP.md`) and are deliberately absent here.

Directories and files are created owner-only: `docs/ARCHITECTURE.md` section 7
requires private values to be stored with restrictive permissions, and nothing
under `.pgproof` is meant to be group- or world-readable by default.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final, Literal

from pgproof.domain.envelope import ArtifactType

DIR_MODE: Final = 0o700
FILE_MODE: Final = 0o600

_ANALYSIS_FILENAMES: Final[dict[ArtifactType, str]] = {
    ArtifactType.SCHEMA: "schema.json",
    ArtifactType.CODE: "code.json",
    ArtifactType.WORKLOAD: "workload.json",
    ArtifactType.EVIDENCE: "evidence.json",
    ArtifactType.RECOMMENDATIONS: "recommendations.json",
    ArtifactType.SCENARIOS: "scenarios.json",
}

DiagramView = Literal["current", "target"]


class ProjectLayout:
    """Paths under one project's `.pgproof` directory. Creates nothing by itself."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root

    @property
    def pgproof_dir(self) -> Path:
        return self.project_root / ".pgproof"

    @property
    def analysis_dir(self) -> Path:
        return self.pgproof_dir / "analysis"

    @property
    def diagrams_dir(self) -> Path:
        return self.pgproof_dir / "diagrams"

    @property
    def runs_dir(self) -> Path:
        return self.pgproof_dir / "runs"

    @property
    def context_path(self) -> Path:
        return self.pgproof_dir / "context.json"

    def analysis_path(self, artifact_type: ArtifactType) -> Path:
        try:
            filename = _ANALYSIS_FILENAMES[artifact_type]
        except KeyError as error:
            known = ", ".join(sorted(item.value for item in _ANALYSIS_FILENAMES))
            raise ValueError(
                f"{artifact_type.value!r} has no analysis-directory location; "
                f"expected one of: {known}"
            ) from error
        return self.analysis_dir / filename

    def diagram_path(self, view: DiagramView) -> Path:
        return self.diagrams_dir / f"{view}.graph.json"

    def run_dir(self, run_id: str) -> Path:
        return self.runs_dir / run_id

    def run_manifest_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "manifest.json"

    def run_events_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "events.ndjson"

    def run_result_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "result.json"

    def ensure_base_layout(self) -> None:
        """Create the fixed top-level directories. Per-run directories are made on demand."""
        for directory in (self.pgproof_dir, self.analysis_dir, self.diagrams_dir, self.runs_dir):
            make_directory(directory)


def make_directory(path: Path) -> None:
    """`mkdir` that ignores the process umask, so the mode is exactly `DIR_MODE`."""
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(DIR_MODE)
