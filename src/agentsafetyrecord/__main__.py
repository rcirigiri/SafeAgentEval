"""Allow ``python -m agentsafetyrecord`` as an alternative to the console script."""

from agentsafetyrecord.cli import app

if __name__ == "__main__":
    app()
