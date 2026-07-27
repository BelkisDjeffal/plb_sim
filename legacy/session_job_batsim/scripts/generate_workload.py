#!/usr/bin/env python3

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
from pathlib import Path
from typing import Any

from scenario import SCENARIO


def stable_derived_seed(base_seed: int, name: str) -> int:
    raw = f"{base_seed}:{name}".encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()
    return int(digest[:16], 16) % (2**32)


def total_batsim_resources(platform: dict[str, Any]) -> int:
    return int(platform["replicas"]) * int(platform.get("slots_per_replica", 1))


def build_class_sequence(classes: list[str], counts: list[int], rng: random.Random) -> list[str]:
    if len(classes) != len(counts):
        raise ValueError("workload.classes and workload.class_counts must have the same length")
    if any(count <= 0 for count in counts):
        raise ValueError("all class_counts must be positive")

    labels = []
    for cls, count in zip(classes, counts):
        labels.extend([cls] * count)
    rng.shuffle(labels)
    return labels


def exponential_delay_s(rate_per_s: float, rng: random.Random) -> float:
    if rate_per_s <= 0:
        raise ValueError("Poisson arrival rate must be > 0")
    return rng.expovariate(rate_per_s)


def generate_workload(scenario: dict[str, Any]) -> dict[str, Any]:
    seed = int(scenario["seed"])
    workload = scenario["workload"]
    platform = scenario["platform"]

    total_workers = int(workload["total_workers"])
    duration_s = float(workload["duration_s"])
    classes = list(workload["classes"])
    counts = list(map(int, workload["class_counts"]))

    if sum(counts) != total_workers:
        raise ValueError(f"sum(class_counts)={sum(counts)} must equal total_workers={total_workers}")

    arrival_rng = random.Random(stable_derived_seed(seed, "arrivals.poisson"))
    class_rng = random.Random(stable_derived_seed(seed, "classes"))
    lifetime_rng = random.Random(stable_derived_seed(seed, "worker.lifetime"))

    class_sequence = build_class_sequence(classes, counts, class_rng)

    arrival_model = workload["arrival_model"].lower()
    if arrival_model != "poisson":
        raise ValueError("first prototype supports only arrival_model='poisson'")

    lifetime_cfg = workload["lifetime"]
    if lifetime_cfg["type"].lower() != "uniform":
        raise ValueError("first prototype supports only lifetime.type='uniform'")

    min_life = float(lifetime_cfg["min_s"])
    max_life = float(lifetime_cfg["max_s"])
    if min_life <= 0 or max_life <= min_life:
        raise ValueError("lifetime must satisfy 0 < min_s < max_s")

    rate = total_workers / duration_s
    jobs = []
    profiles: dict[str, dict[str, Any]] = {}
    subtime = 0.0

    for worker_id, cls in enumerate(class_sequence):
        subtime += exponential_delay_s(rate, arrival_rng)
        lifetime = lifetime_rng.uniform(min_life, max_life)

        raw_job_id = f"w{worker_id:06d}__{cls}"
        job_id = f"w0!{raw_job_id}"
        profile_id = f"p_w{worker_id:06d}"

        profiles[profile_id] = {
            "type": "delay",
            "delay": round(lifetime, 6),
        }

        extra = {
            "class": cls,
            "worker_id": worker_id,
            "lifetime_s": round(lifetime, 6),
            "scenario": scenario["name"],
        }

        jobs.append(
            {
                "id": job_id,
                "subtime": round(subtime, 6),
                "res": 1,
                "profile": profile_id,
                "walltime": round(lifetime + 60.0, 6),
                "extra_data": json.dumps(extra, separators=(",", ":")),
            }
        )

    return {
        "nb_res": total_batsim_resources(platform),
        "jobs": jobs,
        "profiles": profiles,
    }


def write_summary(workload_json: dict[str, Any], out_csv: Path) -> None:
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["job_id", "worker_id", "class", "subtime_s", "lifetime_s"])
        for job in workload_json["jobs"]:
            extra = json.loads(job["extra_data"])
            writer.writerow(
                [
                    job["id"],
                    extra["worker_id"],
                    extra["class"],
                    job["subtime"],
                    extra["lifetime_s"],
                ]
            )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    out = Path(args.out) if args.out else Path("workloads") / f"{SCENARIO['name']}.json"
    summary = out.with_name(out.stem + "_summary.csv")

    workload_json = generate_workload(SCENARIO)

    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w") as f:
        json.dump(workload_json, f, indent=2)
        f.write("\n")

    write_summary(workload_json, summary)

    print(f"Wrote workload: {out}")
    print(f"Wrote summary : {summary}")
    print(f"Jobs          : {len(workload_json['jobs'])}")
    print(f"Batsim resources nb_res: {workload_json['nb_res']}")
    print(f"Logical replicas       : {SCENARIO['platform']['replicas']}")
    print(f"Slots per replica      : {SCENARIO['platform'].get('slots_per_replica', 1)}")


if __name__ == "__main__":
    main()