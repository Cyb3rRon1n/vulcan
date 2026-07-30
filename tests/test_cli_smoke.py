from typer.testing import CliRunner

from installer.cli import app


runner = CliRunner()


def test_version():
    """
    Typer collapses to single-command mode when only one command is
    registered - no subcommand name needed (or accepted). This will
    change naturally once more commands land in Phase 1.
    """

    result = runner.invoke(app, [])

    assert result.exit_code == 0
    assert "0.1.0-alpha" in result.output
