#!/usr/bin/env python3

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from pprint import pformat

ROOT = Path(__file__).resolve().parent
SCENARIO_FILE = ROOT / "scenario.py"


def load_base_scenario() -> dict:
    spec = importlib.util.spec_from_file_location("scenario", SCENARIO_FILE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module.SCENARIO


def write_scenario(scenario: dict) -> None:
    SCENARIO_FILE.write_text("SCENARIO = " + pformat(scenario, width=100, sort_dicts=False) + "\n")


def run(cmd: list[str]) -> None:
    print("$", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=ROOT, check=True)


def merge_csv(inputs: list[tuple[str, str, int, Path]], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    fieldnames = []

    for scenario_name, scheduler, rep, path in inputs:
        if not path.exists() or path.stat().st_size == 0:
            continue
        with path.open(newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                row = dict(row)
                row["scenario"] = scenario_name
                row["scheduler"] = scheduler
                row["rep"] = rep
                rows.append(row)
                for key in row:
                    if key not in fieldnames:
                        fieldnames.append(key)

    if not rows:
        output.write_text("")
        return

    ordered = ["scenario", "scheduler", "rep"] + [k for k in fieldnames if k not in {"scenario", "scheduler", "rep"}]
    with output.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=ordered)
        writer.writeheader()
        writer.writerows(rows)


def scenario_from_variant(base: dict, variant: dict, schedulers: list[str], repetitions: int) -> dict:
    scenario = json.loads(json.dumps(base))
    scenario["name"] = variant["name"]
    scenario["repetitions"] = repetitions
    scenario["schedulers"] = schedulers

    workload = scenario["workload"]
    for key in ["duration_s", "total_workers", "class_counts", "classes"]:
        if key in variant:
            workload[key] = variant[key]

    if "theta" in variant:
        scenario.setdefault("scheduler_config", {})["theta"] = int(variant["theta"])

    if "initial_pools" in variant:
        scenario.setdefault("scheduler_config", {})["initial_pools"] = variant["initial_pools"]

    if "donor_policy" in variant:
        scenario.setdefault("scheduler_config", {})["donor_policy"] = variant["donor_policy"]

    if "higher_borrow_mode" in variant:
        scenario.setdefault("scheduler_config", {})["higher_borrow_mode"] = variant["higher_borrow_mode"]

    return scenario


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="experiments/nclass_small.json")
    parser.add_argument("--skip-existing", action="store_true")
    args = parser.parse_args()

    config_path = ROOT / args.config
    exp = json.loads(config_path.read_text())
    base = load_base_scenario()
    backup = SCENARIO_FILE.read_text()

    schedulers = list(exp.get("schedulers", base.get("schedulers", [])))
    repetitions = int(exp.get("repetitions", 1))
    result_root = ROOT / "results" / exp["name"]
    result_root.mkdir(parents=True, exist_ok=True)

    metric_inputs = []
    exposure_inputs = []
    replica_inputs = []
    imbalance_inputs = []
    borrow_inputs = []

    try:
        for variant in exp["scenarios"]:
            scenario = scenario_from_variant(base, variant, schedulers, repetitions)
            write_scenario(scenario)

            run([sys.executable, "generate_workload.py"])
            run([sys.executable, "validate_workload.py"])
            run([sys.executable, "generate_platform.py"])

            for rep in range(1, repetitions + 1):
                for scheduler in schedulers:
                    outdir = ROOT / "outputs" / scenario["name"] / f"rep_{rep:02d}" / scheduler
                    if args.skip_existing and (outdir / "scheduler_decisions.csv").exists():
                        print(f"Skipping existing run: {outdir}")
                    else:
                        run([sys.executable, "run_one.py", "--scheduler", scheduler, "--rep", str(rep)])
                    run([sys.executable, "analyze.py", "--outdir", str(outdir)])
                    run([sys.executable, "analyze_state.py", "--outdir", str(outdir), "--theta", str(scenario["scheduler_config"]["theta"])])

                    metric_inputs.append((scenario["name"], scheduler, rep, outdir / "metrics_by_class.csv"))
                    exposure_inputs.append((scenario["name"], scheduler, rep, outdir / "saturation_exposure_by_class.csv"))
                    replica_inputs.append((scenario["name"], scheduler, rep, outdir / "replica_load_summary.csv"))
                    imbalance_inputs.append((scenario["name"], scheduler, rep, outdir / "imbalance_summary.csv"))
                    borrow_inputs.append((scenario["name"], scheduler, rep, outdir / "borrow_events.csv"))

        merge_csv(metric_inputs, result_root / "all_metrics_by_class.csv")
        merge_csv(exposure_inputs, result_root / "all_saturation_exposure.csv")
        merge_csv(replica_inputs, result_root / "all_replica_load_summary.csv")
        merge_csv(imbalance_inputs, result_root / "all_imbalance_summary.csv")
        merge_csv(borrow_inputs, result_root / "all_borrow_events.csv")

        print(f"Results written to: {result_root}")
    finally:
        SCENARIO_FILE.write_text(backup)


if __name__ == "__main__":
    main()
