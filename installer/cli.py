import typer
from rich.console import Console

from installer import __version__


app = typer.Typer(
    name="vulcan",
    help="An intelligent media stack forge - inspects your system and builds a tailored Jellyfin + *arr homelab."
)

console = Console()


@app.command()
def version():
    """
    Display the Vulcan version.
    """

    console.print(
        f"[bold red]Vulcan[/bold red] version {__version__}"
    )


if __name__ == "__main__":
    app()
