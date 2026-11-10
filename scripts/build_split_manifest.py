"""Build the public split manifest: SHA-256 of every public scenario file.

Run from the repository root:

    python scripts/build_split_manifest.py

Writes ``safeorderbench/splits/public_banking_v1.json``. The manifest is a
timestamped, hash-linked inventory of the released public scenarios; the
private held-out set is committed to separately and never written here.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PUBLIC = ROOT / "safeorderbench" / "public" / "banking"
OUT = ROOT / "safeorderbench" / "splits" / "public_banking_v1.json"
_ID = re.compile(r"^scenario_id:\s*(\S+)", re.M)


def main() -> None:
    entries = []
    for path in sorted(PUBLIC.rglob("*.yaml")):
        text = path.read_text(encoding="utf-8")
        match = _ID.search(text)
        entries.append(
            {
                "scenario_id": match.group(1) if match else path.stem,
                "path": path.relative_to(ROOT / "safeorderbench").as_posix(),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    manifest = {
        "split": "public_banking_v1",
        "generated": date.today().isoformat(),
        "domain": "banking",
        "scenario_count": len(entries),
        "scenarios": entries,
    }
    OUT.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT} with {len(entries)} scenarios")


if __name__ == "__main__":
    main()
