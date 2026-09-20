"""The Docker-backed `Runner`. `docs/ARCHITECTURE.md` section 11.

Isolation choices this module makes, none dictated by name in the docs but
each required by `docs/ARCHITECTURE.md:72-74`'s "no host write mount, no
external network, explicit resource/time limits, non-root":

- The repository is copied, on the host, into a throwaway staging directory
  pgproof itself creates and makes world-writable; that disposable copy — not
  the caller's real repository — is bind-mounted read-write at `/workspace`.
  The real repository is never mounted or otherwise reachable from inside the
  container, so a host write is structurally impossible. Staging on the host
  also sidesteps a real portability trap: a plain read-only bind mount of the
  original directory, read back as a fixed non-root UID, fails outright
  whenever that directory isn't world-readable (the common case for anything
  `tempfile`/`pytest.tmp_path` creates, mode `0700`).
- The container always runs as a fixed non-root uid:gid.
- `--network none` unless `RunnerConfig.network` opts in.
- `--cpus`/`--memory`/`--pids-limit` map directly from `RunnerConfig`.
- Every container/network this adapter creates carries a `pgproof.owner`
  label, so `find_orphaned_containers` can find what a crashed run left
  behind without tracking anything itself.
"""

from __future__ import annotations

import dataclasses
import hashlib
import re
import shutil
import subprocess
import tempfile
import time
import uuid
from collections.abc import Sequence
from pathlib import Path

from pgproof.domain.execution import RunnerConfig, RunOutcome
from pgproof.ports.runner import RunSpec

_DOCKER_INFO_TIMEOUT_SECONDS = 3
_POLL_INTERVAL_SECONDS = 0.2
_STOP_GRACE_SECONDS = "5"
_WORKSPACE = "/workspace"
_DEFAULT_USER = "1000:1000"

_LABEL_OWNER = "pgproof.owner"
_OWNER_VALUE = "pgproof"
_PS_FORMAT = "{{.ID}}\t{{.Names}}"

_MEMORY_RE = re.compile(r"^(\d+(?:\.\d+)?)\s*([kKmMgG]?)[bB]?$")


class RunnerUnavailableError(RuntimeError):
    """The Docker daemon is not reachable."""


class RunnerBuildError(RuntimeError):
    """`docker build` for a `RunnerConfig.build` Dockerfile failed."""


@dataclasses.dataclass(frozen=True)
class DockerCapability:
    cli_found: bool
    daemon_reachable: bool


@dataclasses.dataclass(frozen=True)
class OrphanedContainer:
    id: str
    name: str


def probe_docker() -> DockerCapability:
    if shutil.which("docker") is None:
        return DockerCapability(cli_found=False, daemon_reachable=False)
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=_DOCKER_INFO_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return DockerCapability(cli_found=True, daemon_reachable=False)
    return DockerCapability(cli_found=True, daemon_reachable=result.returncode == 0)


def _docker(
    args: Sequence[str], *, timeout: float | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *args], capture_output=True, text=True, timeout=timeout, check=False
    )


def _normalize_memory(memory: str) -> str:
    match = _MEMORY_RE.match(memory.strip())
    if not match:
        raise ValueError(f"unrecognised memory limit: {memory!r}")
    value, unit = match.groups()
    return f"{value}{unit.lower()}" if unit else f"{value}b"


def resolve_image(config: RunnerConfig, root: Path) -> str:
    if config.image:
        return config.image
    assert config.build is not None  # RunnerConfig.__post_init__ requires one or the other
    dockerfile = (root / config.build).resolve()
    tag = f"pgproof-runner:{hashlib.sha256(str(dockerfile).encode()).hexdigest()[:12]}"
    built = _docker(["build", "-f", str(dockerfile), "-t", tag, str(dockerfile.parent)])
    if built.returncode != 0:
        raise RunnerBuildError(built.stderr)
    return tag


def find_orphaned_containers() -> tuple[OrphanedContainer, ...]:
    result = _docker(
        ["ps", "-a", "--filter", f"label={_LABEL_OWNER}={_OWNER_VALUE}", "--format", _PS_FORMAT]
    )
    if result.returncode != 0:
        return ()
    orphans = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        container_id, _, name = line.partition("\t")
        orphans.append(OrphanedContainer(id=container_id, name=name))
    return tuple(orphans)


def remove_containers(ids: Sequence[str]) -> None:
    for container_id in ids:
        _docker(["rm", "-f", container_id])


def _stage_source(source: Path, run_id: str) -> Path:
    staging = Path(tempfile.mkdtemp(prefix=f"pgproof-runner-{run_id}-"))
    shutil.copytree(source, staging, dirs_exist_ok=True)
    for path in (staging, *staging.rglob("*")):
        path.chmod(0o777)
    return staging


class DockerRunner:
    def run(self, spec: RunSpec) -> RunOutcome:
        if not probe_docker().daemon_reachable:
            raise RunnerUnavailableError("Docker daemon is not reachable")
        image = resolve_image(spec.config, spec.source)
        run_id = uuid.uuid4().hex[:12]
        memory = _normalize_memory(spec.config.memory)
        staging = _stage_source(spec.source, run_id)
        try:
            create_args = [
                "create",
                "--name",
                f"pgproof-runner-{run_id}",
                "--label",
                f"{_LABEL_OWNER}={_OWNER_VALUE}",
                "--user",
                _DEFAULT_USER,
                "--network",
                "bridge" if spec.config.network else "none",
                "--cpus",
                str(spec.config.cpu),
                "--memory",
                memory,
                "--memory-swap",
                memory,
                "--pids-limit",
                str(spec.config.pids),
                "-v",
                f"{staging}:{_WORKSPACE}:rw",
                "--workdir",
                _WORKSPACE,
            ]
            for key, value in spec.environment.items():
                create_args += ["-e", f"{key}={value}"]
            create_args += [image, *spec.command]

            created = _docker(create_args)
            if created.returncode != 0:
                return RunOutcome(
                    exit_code=None,
                    timed_out=False,
                    cancelled=False,
                    stdout="",
                    stderr=created.stderr,
                    duration_seconds=0.0,
                )
            container_id = created.stdout.strip()
            try:
                return self._run_created_container(container_id, spec)
            finally:
                _docker(["rm", "-f", container_id])
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    def _run_created_container(self, container_id: str, spec: RunSpec) -> RunOutcome:
        started_at = time.monotonic()
        start = _docker(["start", container_id])
        if start.returncode != 0:
            return RunOutcome(
                exit_code=None,
                timed_out=False,
                cancelled=False,
                stdout="",
                stderr=start.stderr,
                duration_seconds=time.monotonic() - started_at,
            )

        deadline = started_at + spec.config.timeout_seconds
        timed_out = False
        cancelled = False
        while True:
            if spec.cancel_event is not None and spec.cancel_event.is_set():
                cancelled = True
                break
            if time.monotonic() >= deadline:
                timed_out = True
                break
            inspect = _docker(["inspect", "-f", "{{.State.Running}}", container_id])
            if inspect.returncode != 0 or inspect.stdout.strip() != "true":
                break
            time.sleep(_POLL_INTERVAL_SECONDS)

        if timed_out or cancelled:
            _docker(["stop", "-t", _STOP_GRACE_SECONDS, container_id])

        logs = _docker(["logs", container_id])
        exit_code: int | None = None
        if not timed_out and not cancelled:
            inspected_code = _docker(["inspect", "-f", "{{.State.ExitCode}}", container_id])
            if inspected_code.returncode == 0:
                try:
                    exit_code = int(inspected_code.stdout.strip())
                except ValueError:
                    exit_code = None

        return RunOutcome(
            exit_code=exit_code,
            timed_out=timed_out,
            cancelled=cancelled,
            stdout=logs.stdout,
            stderr=logs.stderr,
            duration_seconds=time.monotonic() - started_at,
        )
