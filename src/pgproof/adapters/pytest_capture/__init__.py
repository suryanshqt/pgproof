"""Loads and names the standalone capture plugin (`plugin.py`) for injection
into the isolated runner's staged workspace, `docs/TECHNICAL_DESIGN.md`
section 10. `plugin.py` itself has no `pgproof` import and is never imported
by pgproof's own process for execution — only read as text here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

PLUGIN_MODULE_NAME: Final = "_pgproof_capture_plugin"
PLUGIN_WORKSPACE_PATH: Final = f"{PLUGIN_MODULE_NAME}.py"
CAPTURE_FILE_PATH: Final = ".pgproof-capture/events.ndjson"
CAPTURE_FILE_ENV: Final = "PGPROOF_CAPTURE_FILE"
# BE-21: written once, at `pytest_sessionfinish`, alongside `CAPTURE_FILE_PATH`
# rather than through `CAPTURE_FILE_ENV` — its own path is derived from that
# same env var inside the plugin (`plugin._summary_path`), so no second env
# var is needed to locate it.
CAPTURE_SUMMARY_PATH: Final = ".pgproof-capture/summary.json"
UNSAFE_VALUES_ENV: Final = "PGPROOF_CAPTURE_UNSAFE_VALUES"
PLUGINS_ENV: Final = "PYTEST_PLUGINS"
PYTHONPATH_ENV: Final = "PYTHONPATH"


def load_plugin_source() -> str:
    return Path(__file__).with_name("plugin.py").read_text(encoding="utf-8")
