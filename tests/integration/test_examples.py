from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[2]


def test_black_box_example_expectations_hold() -> None:
    completed = subprocess.run(
        [sys.executable, str(ROOT / "examples/black_box/banking_demo.py")],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    summary = json.loads(completed.stdout)
    assert summary["expectations_hold"] is True
    assert len(summary["results"]) == 32  # 16 scenarios x safe/unsafe
    assert all(r["trace_verified"] for r in summary["results"])
