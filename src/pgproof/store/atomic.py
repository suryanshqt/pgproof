"""Crash-safe file writes.

`docs/ARCHITECTURE.md` section 7: "Writes use temp file + fsync where
appropriate + atomic rename." A reader never observes a partially written file
at its final path: either the previous complete content is still there, or the
new complete content is, never a torn mix of the two.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from pgproof.store.paths import FILE_MODE, make_directory


def write_bytes_atomic(path: Path, data: bytes) -> None:
    """Write `data` to `path` so a crash mid-write never leaves a half-written file.

    A temporary file in the same directory is written, fsynced, and renamed onto
    `path` (`os.replace` is atomic on the same filesystem). The temporary file is
    removed if any step raises, including cancellation.
    """
    make_directory(path.parent)
    descriptor, temp_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        temp_path.chmod(FILE_MODE)
        temp_path.replace(path)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise
    _fsync_directory(path.parent)


def append_line_durable(path: Path, line: str) -> None:
    """Append one newline-terminated, fsynced line. Never truncates or rewrites."""
    make_directory(path.parent)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    path.chmod(FILE_MODE)


def _fsync_directory(directory: Path) -> None:
    """Durability for the rename itself, not only atomicity. POSIX only; CI is POSIX-only."""
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
