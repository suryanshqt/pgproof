"""`pgproof ui`: start the local, loopback-only review UI.

Server lifecycle and routing are `pgproof.local_api`; this module owns the
CLI surface: argument parsing, the printed URL, and whether a browser opens.

`--keep-open` is accepted per `docs/TECHNICAL_DESIGN.md` section 2 but has no
effect yet: the standalone command already blocks in the foreground until
interrupted, and section 9's "terminates with the CLI process" distinction
only matters once another command can start a UI session as a side effect
(no such caller exists yet).
"""

from __future__ import annotations

import webbrowser
from pathlib import Path

import click

from pgproof.local_api.app import create_app
from pgproof.local_api.server import LOOPBACK_HOST, bind_loopback_socket, bound_port, serve
from pgproof.local_api.session import new_session_token
from pgproof.store.paths import ProjectLayout


@click.command("ui")
@click.argument(
    "path",
    type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path),
    default=".",
)
@click.option("--no-open", "no_open", is_flag=True, help="Do not open a browser automatically.")
@click.option(
    "--keep-open", "_keep_open", is_flag=True, help="Reserved; see this module's docstring."
)
def ui(path: Path, no_open: bool, _keep_open: bool) -> None:
    """Start the local, loopback-only review UI for PATH."""
    layout = ProjectLayout(path.resolve())
    layout.ensure_base_layout()
    sock = bind_loopback_socket()
    port = bound_port(sock)
    token = new_session_token()
    origin = f"http://{LOOPBACK_HOST}:{port}"
    url = f"{origin}/?token={token}"
    app = create_app(layout=layout, session_token=token, allowed_origin=origin)
    click.echo(f"pgproof ui listening on {url}")
    if not no_open:
        webbrowser.open(url)
    serve(app, sock)
