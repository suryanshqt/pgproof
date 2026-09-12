"""Root CLI group. Product commands are added by later roadmap items."""

import click

from pgproof import __version__


@click.group(
    name="pgproof",
    epilog="No analysis commands are implemented yet. See docs/PR_ROADMAP.md.",
)
@click.version_option(version=__version__, prog_name="pgproof", message="%(prog)s %(version)s")
def main() -> None:
    """Review the PostgreSQL design expressed by a Python codebase.

    pgproof reads a project from the local filesystem only. It sends no telemetry,
    makes no outbound network request, and never connects to a production database.
    Commands that execute project code state what they will run and require explicit
    approval before an isolated runner starts.
    """
