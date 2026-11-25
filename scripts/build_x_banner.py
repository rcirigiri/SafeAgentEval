"""Render the X (Twitter) profile banner PNGs from the SVG source.

The banner design lives in ``docs/assets/brand/agenticsafetyeval-x-banner.svg``
(1500x500 logical canvas; headline and chips sit right of the profile-photo
overlap at the bottom left, the lockup sits above it). This script renders
the 3000x1000 (2x, upload this one) and 1500x500 PNGs with a headless
Chromium/Edge when available:

    python scripts/build_x_banner.py

Why not reuse the LinkedIn banner? X banners are 3:1, LinkedIn's is 4:1,
so X centre-crops it and cuts text at the right edge.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRAND = ROOT / "docs" / "assets" / "brand"
SVG = BRAND / "agenticsafetyeval-x-banner.svg"
RENDERS = [
    (BRAND / "agenticsafetyeval-x-banner.png", 3000, 1000),
    (BRAND / "agenticsafetyeval-x-banner-1500.png", 1500, 500),
]

_BROWSERS = [
    shutil.which("msedge"),
    shutil.which("chrome"),
    shutil.which("chromium"),
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
]


def main() -> None:
    browser = next((b for b in _BROWSERS if b and Path(b).exists()), None)
    if browser is None:
        raise SystemExit("no headless Chromium/Edge found; render the SVG manually")
    url = SVG.resolve().as_uri()
    with tempfile.TemporaryDirectory() as tmp:
        for out, width, height in RENDERS:
            shot = Path(tmp) / out.name
            subprocess.run(
                [
                    browser,
                    "--headless",
                    "--disable-gpu",
                    "--hide-scrollbars",
                    f"--window-size={width},{height}",
                    f"--screenshot={shot}",
                    url,
                ],
                check=True,
                capture_output=True,
            )
            shutil.copyfile(shot, out)
            print(f"wrote {out} ({width}x{height})")


if __name__ == "__main__":
    main()
