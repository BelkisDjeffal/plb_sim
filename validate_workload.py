#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from scenario import SCENARIO


def expected_nb_res() -> int:
    p = SCENARIO["platform"]
    return int(p["replicas"]) * int(p.get("slots_per_replica", 1))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("workload", nargs="?", default=f"workloads/{SCENARIO['name']}.json")
    args = parser.parse_args()

    path = Path(args.workload)
    with path.open() as f:
        data = json.load(f)

    jobs = data["jobs"]
    profiles = data["profiles"]
    classes = []
    lifetimes = []
    subtimes = []

    for job in jobs:
        extra = json.loads(job["extra_data"])
        classes.append(extra["class"])
        lifetimes.append(float(extra["lifetime_s"]))
        subtimes.append(float(job["subtime"]))
        if job["profile"] not in profiles:
            raise AssertionError(f"missing profile for job {job['id']}")
        if int(job["res"]) != 1:
            raise AssertionError(f"job {job['id']} has res != 1")

    counts = Counter(classes)
    expected = dict(zip(SCENARIO["workload"]["classes"], SCENARIO["workload"]["class_counts"]))

    print("Workload:", path)
    print("nb_res:", data["nb_res"])
    print("logical replicas:", SCENARIO["platform"]["replicas"])
    print("slots per replica:", SCENARIO["platform"].get("slots_per_replica", 1))
    print("jobs:", len(jobs))
    print("class counts:", dict(counts))
    print("expected:", expected)
    print("first subtime:", round(min(subtimes), 3))
    print("last subtime:", round(max(subtimes), 3))
    print("min lifetime:", round(min(lifetimes), 3))
    print("max lifetime:", round(max(lifetimes), 3))

    assert data["nb_res"] == expected_nb_res()
    assert len(jobs) == SCENARIO["workload"]["total_workers"]
    assert dict(counts) == expected
    assert all(earlier <= later for earlier, later in zip(subtimes, subtimes[1:]))
    assert min(lifetimes) >= SCENARIO["workload"]["lifetime"]["min_s"]
    assert max(lifetimes) <= SCENARIO["workload"]["lifetime"]["max_s"]

    print("OK: workload is valid.")


if __name__ == "__main__":
    main()
