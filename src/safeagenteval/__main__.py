"""Allow ``python -m safeagenteval`` as an alternative to the console script."""

from safeagenteval.cli import app

if __name__ == "__main__":
    app()
