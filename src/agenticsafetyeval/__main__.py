"""Allow ``python -m agenticsafetyeval`` as an alternative to the console script."""

from agenticsafetyeval.cli import app

if __name__ == "__main__":
    app()
