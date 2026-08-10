from typer.testing import CliRunner

from installer.cli import app

runner = CliRunner()


def test_version():

    result = runner.invoke(app, ["version"])

    assert result.exit_code == 0
    assert "0.1.0-alpha" in result.output
