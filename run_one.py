#!/usr/bin/env python3


from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from scenario import SCENARIO


ROOT = Path(__file__).resolve().parent


def require_command(name: str) -> None:
    if shutil.which(name) is None:
        raise SystemExit(
            f"Missing command '{name}'. Activate your Nix/Batsim environment first."
        )


def ensure_inputs() -> tuple[Path, Path]:
    workload = ROOT / "workloads" / f"{SCENARIO['name']}.json"
    platform = ROOT / "platforms" / f"platform_{SCENARIO['platform']['replicas']}replicas_{SCENARIO['platform'].get('slots_per_replica', 1)}slots.xml"

    if not workload.exists():
        subprocess.run([sys.executable, str(ROOT / "generate_workload.py")], cwd=ROOT, check=True)
    if not platform.exists():
        subprocess.run([sys.executable, str(ROOT / "generate_platform.py")], cwd=ROOT, check=True)

    return workload, platform


def scheduler_file(policy: str) -> Path:
    path = ROOT / "schedulers" / f"{policy}.py"
    if not path.exists():
        raise SystemExit(f"Unknown scheduler policy '{policy}': {path} does not exist")
    return path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scheduler", default="round_robin", help="round_robin or least_loaded")
    parser.add_argument("--rep", type=int, default=1, help="repetition number, does not change seed")
    parser.add_argument("--port", type=int, default=28000)
    parser.add_argument("--endpoint", default=None, help="Batsim scheduler endpoint")
    parser.add_argument("--dry-run", action="store_true", help="print commands without executing")
    args = parser.parse_args()

    require_command("batsim")
    require_command("pybatsim")

    workload, platform = ensure_inputs()
    sched = scheduler_file(args.scheduler)

    outdir = ROOT / "outputs" / SCENARIO["name"] / f"rep_{args.rep:02d}" / args.scheduler
    outdir.mkdir(parents=True, exist_ok=True)

    endpoint = args.endpoint or f"tcp://127.0.0.1:{args.port}"

    batsim_prefix = outdir / "out_"
    decision_log = outdir / "scheduler_decisions.csv"

    batsim_cmd = [
        "batsim",
        "-p",
        str(platform),
        "-w",
        str(workload),
        "-e",
        str(batsim_prefix),
        "-s",
        endpoint,
    ]

    pybatsim_cmd = ["pybatsim", str(sched)]

    print("Output dir:", outdir)
    print("Batsim command:", " ".join(batsim_cmd))
    print("PyBatsim command:", " ".join(pybatsim_cmd))

    if args.dry_run:
        return

    env = os.environ.copy()
    env["PLB_SCHED_LOG"] = str(decision_log)

    batsim_log = (outdir / "batsim.log").open("w")
    sched_log = (outdir / "scheduler.log").open("w")

    batsim_proc = subprocess.Popen(
        batsim_cmd,
        cwd=ROOT,
        stdout=batsim_log,
        stderr=subprocess.STDOUT,
        env=env,
    )

    time.sleep(1.0)

    sched_proc = subprocess.Popen(
        pybatsim_cmd,
        cwd=ROOT,
        stdout=sched_log,
        stderr=subprocess.STDOUT,
        env=env,
    )

    sched_rc = sched_proc.wait()
    batsim_rc = batsim_proc.wait()

    batsim_log.close()
    sched_log.close()

    print("pybatsim exit:", sched_rc)
    print("batsim exit  :", batsim_rc)

    if sched_rc != 0 or batsim_rc != 0:
        print("Run failed. Check:")
        print(" ", outdir / "batsim.log")
        print(" ", outdir / "scheduler.log")
        raise SystemExit(1)

    print("Run completed.")
    print("Now analyze:")
    print(f"  python3 analyze.py --outdir {outdir}")


if __name__ == "__main__":
    main()