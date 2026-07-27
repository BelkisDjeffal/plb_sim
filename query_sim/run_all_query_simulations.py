#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scenario import SCENARIO


def main() -> None:
    for policy in SCENARIO.get("schedulers", ["round_robin", "least_loaded", "plb_nclass"]):
        subprocess.run(
            [
                sys.executable,
                str(ROOT / "query_sim" / "run_query_simulation.py"),
                "--policy",
                policy,
            ],
            cwd=ROOT,
            check=True,
        )


if __name__ == "__main__":
    main()
