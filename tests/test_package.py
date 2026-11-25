from typer.testing import CliRunner

from agenticsafetyeval import __version__
from agenticsafetyeval.cli import app


def test_version_command_reports_package_version() -> None:
    result = CliRunner().invoke(app, ["version"])

    assert result.exit_code == 0
    assert result.stdout.strip() == __version__
