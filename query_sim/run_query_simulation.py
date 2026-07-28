#!/usr/bin/env python3
from __future__ import annotations

import argparse
import heapq
import json
import sys
from copy import deepcopy
from itertools import count
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scenario import SCENARIO  # noqa: E402
from query_sim.latency_model import EmpiricalLatencyModel  # noqa: E402
from query_sim.policies import make_policy  # noqa: E402
from query_sim.workload import generate_workload  # noqa: E402


def percentile(series: pd.Series, q: float) -> float:
    if series.empty:
        return float("nan")
    return float(series.quantile(q))


def write_metrics(events: list[dict[str, Any]], out_csv: Path) -> None:
    df = pd.DataFrame(events)
    rows: list[dict[str, Any]] = []
    if df.empty:
        pd.DataFrame(rows).to_csv(out_csv, index=False)
        return

    for cls, group in df.groupby("class"):
        lat = group["latency_s"].astype(float)
        rows.append({
            "class": cls,
            "queries": len(group),
            "mean_latency_s": lat.mean(),
            "p50_latency_s": percentile(lat, 0.50),
            "p95_latency_s": percentile(lat, 0.95),
            "p99_latency_s": percentile(lat, 0.99),
        })

    lat = df["latency_s"].astype(float)
    rows.append({
        "class": "overall",
        "queries": len(df),
        "mean_latency_s": lat.mean(),
        "p50_latency_s": percentile(lat, 0.50),
        "p95_latency_s": percentile(lat, 0.95),
        "p99_latency_s": percentile(lat, 0.99),
    })
    pd.DataFrame(rows).to_csv(out_csv, index=False)


def run_simulation(
    policy_name: str,
    scenario: dict[str, Any] | None = None,
    calibration: str | Path = "data/calibration/q1_query_observations.csv",
    outdir: str | Path | None = None,
    min_samples: int = 20,
    seed: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Path]:
    scenario_obj = deepcopy(scenario if scenario is not None else SCENARIO)
    seed_value = int(seed if seed is not None else scenario_obj["seed"])
    scenario_obj["seed"] = seed_value

    output_dir = Path(outdir) if outdir else ROOT / "outputs_query" / scenario_obj["name"] / policy_name
    output_dir.mkdir(parents=True, exist_ok=True)

    workload = generate_workload(scenario_obj)
    latency_model = EmpiricalLatencyModel(ROOT / calibration, min_samples=min_samples, seed=seed_value)
    policy = make_policy(policy_name, scenario_obj)

    active_queries = [0 for _ in range(int(scenario_obj["platform"]["replicas"]))]
    event_queue: list[tuple[float, int, str, dict[str, Any]]] = []
    next_event_id = count()

    for job in workload["jobs"]:
        extra = json.loads(job["extra_data"])
        payload = {
            "session_id": str(job["id"]),
            "class": extra["class"],
            "worker_id": extra["worker_id"],
            "session_lifetime_s": extra.get("lifetime_s", ""),
        }
        heapq.heappush(event_queue, (float(job["subtime"]), next(next_event_id), "arrival", payload))

    query_events: list[dict[str, Any]] = []
    placement_events: list[dict[str, Any]] = []
    active_query_events: list[dict[str, Any]] = []

    while event_queue:
        now, _, event_type, payload = heapq.heappop(event_queue)

        if event_type == "arrival":
            session_id = payload["session_id"]
            cls = payload["class"]
            decision = policy.assign_session(now, session_id, cls)
            replica = int(decision["replica"])
            placement_events.append({**decision, "policy": policy_name})

            q1_start_concurrency = active_queries[replica]
            latency_ms, sample_source, sample_load = latency_model.sample_ms(q1_start_concurrency)
            latency_s = latency_ms / 1000.0
            active_queries[replica] += 1
            active_query_events.append({
                "time_s": now,
                "event": "query_start",
                "policy": policy_name,
                "class": cls,
                "replica": replica,
                "active_queries_after": active_queries[replica],
            })

            query_id = f"q_{session_id}"
            heapq.heappush(event_queue, (
                now + latency_s,
                next(next_event_id),
                "query_end",
                {
                    "query_id": query_id,
                    "session_id": session_id,
                    "class": cls,
                    "replica": replica,
                    "query_start_s": now,
                    "latency_s": latency_s,
                    "q1_start_concurrency": q1_start_concurrency,
                    "sample_source": sample_source,
                    "sample_load": sample_load,
                    "placement_action": decision.get("action", ""),
                    "placement_reason": decision.get("reason", ""),
                },
            ))

        elif event_type == "query_end":
            replica = int(payload["replica"])
            q1_end_concurrency = max(0, active_queries[replica] - 1)
            active_queries[replica] = max(0, active_queries[replica] - 1)
            active_query_events.append({
                "time_s": now,
                "event": "query_end",
                "policy": policy_name,
                "class": payload["class"],
                "replica": replica,
                "active_queries_after": active_queries[replica],
            })
            release = policy.release_session(now, payload["session_id"])
            if release:
                placement_events.append({**release, "policy": policy_name})

            query_events.append({
                "policy": policy_name,
                "query_id": payload["query_id"],
                "session_id": payload["session_id"],
                "class": payload["class"],
                "replica": replica,
                "query_start_s": payload["query_start_s"],
                "query_finish_s": now,
                "latency_s": payload["latency_s"],
                "q1_start_concurrency": payload["q1_start_concurrency"],
                "q1_end_concurrency": q1_end_concurrency,
                "in_flight_at_start": payload["q1_start_concurrency"],
                "in_flight_at_end": q1_end_concurrency,
                "sample_source": payload["sample_source"],
                "sample_load": payload["sample_load"],
                "placement_action": payload["placement_action"],
                "placement_reason": payload["placement_reason"],
            })

    query_csv = output_dir / "query_events.csv"
    metrics_csv = output_dir / "metrics_by_class.csv"
    placements_csv = output_dir / "session_placements.csv"
    active_csv = output_dir / "active_queries_timeseries.csv"
    metadata_json = output_dir / "run_metadata.json"

    pd.DataFrame(query_events).to_csv(query_csv, index=False)
    write_metrics(query_events, metrics_csv)
    pd.DataFrame(placement_events).to_csv(placements_csv, index=False)
    pd.DataFrame(active_query_events).to_csv(active_csv, index=False)

    run_metadata = {
        "scenario_name": scenario_obj["name"],
        "scheduler": policy_name,
        "seed": seed_value,
        "K": int(scenario_obj["platform"]["replicas"]),
        "T": int(scenario_obj["workload"]["total_workers"]),
        "class_counts": list(map(int, scenario_obj["workload"]["class_counts"])),
        "classes": list(scenario_obj["workload"]["classes"]),
        "class_order": list(scenario_obj.get("scheduler_config", {}).get("class_order", scenario_obj["workload"]["classes"])),
        "duration_s": float(scenario_obj["workload"]["duration_s"]),
        "calibration": str(calibration),
        "min_samples": int(min_samples),
    }
    if metadata:
        run_metadata.update(metadata)
    metadata_json.write_text(json.dumps(run_metadata, indent=2) + "\n")

    return {
        "query_events": query_csv,
        "metrics_by_class": metrics_csv,
        "session_placements": placements_csv,
        "active_queries_timeseries": active_csv,
        "run_metadata": metadata_json,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", required=True)
    parser.add_argument("--calibration", default="data/calibration/q1_query_observations.csv")
    parser.add_argument("--outdir", default=None)
    parser.add_argument("--min-samples", type=int, default=20)
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args()

    outputs = run_simulation(
        policy_name=args.policy,
        calibration=args.calibration,
        outdir=args.outdir,
        min_samples=args.min_samples,
        seed=args.seed,
    )

    print(f"policy: {args.policy}")
    for label, path in outputs.items():
        print(f"wrote {label}: {path}")


if __name__ == "__main__":
    main()
