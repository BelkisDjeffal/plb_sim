#!/usr/bin/env python3
"""
Analyze one Batsim output directory.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean

from scenario import SCENARIO


def parse_class(job_id: str) -> str:
    if "__" in job_id:
        return job_id.split("__", 1)[1]
    return "unknown"


def to_float(row: dict, names: list[str]) -> float:
    for name in names:
        if name in row and row[name] not in (None, ""):
            try:
                return float(row[name])
            except ValueError:
                pass
    return math.nan


def percentile(values: list[float], p: float) -> float:
    values = sorted(v for v in values if not math.isnan(v))
    if not values:
        return math.nan
    if len(values) == 1:
        return values[0]
    k = (len(values) - 1) * p
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return values[int(k)]
    return values[f] * (c - k) + values[c] * (k - f)


def find_jobs_csv(outdir: Path) -> Path:
    candidates = list(outdir.glob("*jobs.csv")) + list(outdir.glob("out_jobs.csv"))
    if not candidates:
        raise SystemExit(f"No jobs.csv found in {outdir}")
    return candidates[0]


def analyze_jobs(outdir: Path) -> None:
    jobs_csv = find_jobs_csv(outdir)
    rows = []
    with jobs_csv.open(newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            job_id = row.get("job_id") or row.get("id") or row.get("job")
            if not job_id:
                continue
            cls = parse_class(job_id)
            rows.append(
                {
                    "job_id": job_id,
                    "class": cls,
                    "submission_time": to_float(row, ["submission_time", "subtime"]),
                    "starting_time": to_float(row, ["starting_time", "start_time"]),
                    "finish_time": to_float(row, ["finish_time"]),
                    "execution_time": to_float(row, ["execution_time"]),
                    "waiting_time": to_float(row, ["waiting_time"]),
                    "turnaround_time": to_float(row, ["turnaround_time"]),
                    "allocated_resources": row.get("allocated_resources", ""),
                }
            )

    by_class = defaultdict(list)
    for r in rows:
        by_class[r["class"]].append(r)

    metrics_path = outdir / "metrics_by_class.csv"
    with metrics_path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "class",
                "jobs",
                "avg_waiting_time_s",
                "p95_waiting_time_s",
                "avg_turnaround_time_s",
                "p95_turnaround_time_s",
                "avg_execution_time_s",
                "p95_execution_time_s",
            ]
        )
        for cls in sorted(by_class):
            group = by_class[cls]
            waiting = [r["waiting_time"] for r in group]
            turnaround = [r["turnaround_time"] for r in group]
            execution = [r["execution_time"] for r in group]
            writer.writerow(
                [
                    cls,
                    len(group),
                    round(mean([x for x in waiting if not math.isnan(x)]), 6) if waiting else "",
                    round(percentile(waiting, 0.95), 6),
                    round(mean([x for x in turnaround if not math.isnan(x)]), 6) if turnaround else "",
                    round(percentile(turnaround, 0.95), 6),
                    round(mean([x for x in execution if not math.isnan(x)]), 6) if execution else "",
                    round(percentile(execution, 0.95), 6),
                ]
            )

    print(f"Read jobs: {jobs_csv}")
    print(f"Wrote    : {metrics_path}")

    decisions = outdir / "scheduler_decisions.csv"
    if decisions.exists():
        placement_counts = Counter()
        with decisions.open(newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("event") == "start":
                    placement_counts[(row.get("class"), row.get("replica"))] += 1

        placement_path = outdir / "placements_by_class_replica.csv"
        with placement_path.open("w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["class", "replica", "started_jobs"])
            for (cls, replica), count in sorted(placement_counts.items()):
                writer.writerow([cls, replica, count])
        print(f"Wrote    : {placement_path}")


def main() -> None:
    parser = argparse.ArgumentParser()
    default_outdir = Path("outputs") / SCENARIO["name"] / "rep_01" / "round_robin"
    parser.add_argument("--outdir", default=str(default_outdir))
    args = parser.parse_args()
    analyze_jobs(Path(args.outdir))


if __name__ == "__main__":
    main()
