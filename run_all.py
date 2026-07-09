#!/usr/bin/env python3
"""Run all repetitions for the schedulers listed in scenario.py."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from scenario import SCENARIO

ROOT = Path(__file__).resolve().parent


def main() -> None:
    subprocess.run([sys.executable, str(ROOT / "generate_workload.py")], cwd=ROOT, check=True)
    subprocess.run([sys.executable, str(ROOT / "validate_workload.py")], cwd=ROOT, check=True)
    subprocess.run([sys.executable, str(ROOT / "generate_platform.py")], cwd=ROOT, check=True)

    for rep in range(1, int(SCENARIO["repetitions"]) + 1):
        for scheduler in SCENARIO["schedulers"]:
            outdir = ROOT / "outputs" / SCENARIO["name"] / f"rep_{rep:02d}" / scheduler
            subprocess.run(
                [sys.executable, str(ROOT / "run_one.py"), "--scheduler", scheduler, "--rep", str(rep)],
                cwd=ROOT,
                check=True,
            )
            subprocess.run(
                [sys.executable, str(ROOT / "analyze.py"), "--outdir", str(outdir)],
                cwd=ROOT,
                check=True,
            )
            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "analyze_state.py"),
                    "--outdir",
                    str(outdir),
                    "--theta",
                    str(SCENARIO.get("scheduler_config", {}).get("theta", 10)),
                ],
                cwd=ROOT,
                check=True,
            )


if __name__ == "__main__":
    main()
