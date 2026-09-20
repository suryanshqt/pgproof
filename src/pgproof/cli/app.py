"""Root CLI group. Product commands are added by later roadmap items."""

import click

from pgproof import __version__
from pgproof.cli.commands.doctor import doctor
from pgproof.cli.commands.inspect import inspect_
from pgproof.cli.commands.ui import ui


@click.group(
    name="pgproof",
    epilog="Not every command is implemented yet. See docs/PR_ROADMAP.md.",
)
@click.version_option(version=__version__, prog_name="pgproof", message="%(prog)s %(version)s")
@click.option(
    "--ascii",
    "force_ascii",
    is_flag=True,
    help="Force ASCII output; no Unicode glyphs. docs/INTERFACE_DESIGN.md section 4.",
)
@click.option(
    "--verbose",
    is_flag=True,
    help="Reveal rejected candidates and detailed evidence. docs/INTERFACE_DESIGN.md section 4.",
)
@click.pass_context
def main(ctx: click.Context, force_ascii: bool, verbose: bool) -> None:
    """Review the PostgreSQL design expressed by a Python codebase.

    pgproof reads a project from the local filesystem only. It sends no telemetry,
    makes no outbound network request, and never connects to a production database.
    Commands that execute project code state what they will run and require explicit
    approval before an isolated runner starts.
    """
    ctx.ensure_object(dict)
    ctx.obj["force_ascii"] = force_ascii
    ctx.obj["verbose"] = verbose


main.add_command(doctor)
main.add_command(inspect_)
main.add_command(ui)
