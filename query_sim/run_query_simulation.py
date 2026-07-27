#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import heapq
import json
import sys
from itertools import count
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from generate_workload import generate_workload  # noqa: E402
from scenario import SCENARIO  # noqa: E402
from query_sim.latency_model import EmpiricalLatencyModel  # noqa: E402
from query_sim.policies import make_policy  # noqa: E402


def percentile(series: pd.Series, q: float) -> float:
    if series.empty:
        return float("nan")
    return float(series.quantile(q))


def write_metrics(events: list[dict], out_csv: Path) -> None:
    df = pd.DataFrame(events)
    rows = []
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", choices=["round_robin", "least_loaded", "plb_nclass"], required=True)
    parser.add_argument("--calibration", default="data/calibration/q1_query_observations.csv")
    parser.add_argument("--outdir", default=None)
    parser.add_argument("--min-samples", type=int, default=20)
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args()

    seed = int(args.seed if args.seed is not None else SCENARIO["seed"])
    outdir = Path(args.outdir) if args.outdir else ROOT / "outputs_query" / SCENARIO["name"] / args.policy
    outdir.mkdir(parents=True, exist_ok=True)

    workload = generate_workload(SCENARIO)
    latency_model = EmpiricalLatencyModel(ROOT / args.calibration, min_samples=args.min_samples, seed=seed)
    policy = make_policy(args.policy, SCENARIO)

    active_queries = [0 for _ in range(int(SCENARIO["platform"]["replicas"]))]
    event_queue: list[tuple[float, int, str, dict]] = []
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

    query_events: list[dict] = []
    placement_events: list[dict] = []
    active_query_events: list[dict] = []

    while event_queue:
        now, _, event_type, payload = heapq.heappop(event_queue)

        if event_type == "arrival":
            session_id = payload["session_id"]
            cls = payload["class"]
            decision = policy.assign_session(now, session_id, cls)
            replica = int(decision["replica"])
            placement_events.append({**decision, "policy": args.policy})

            in_flight_start = active_queries[replica]
            latency_ms, sample_source, sample_load = latency_model.sample_ms(in_flight_start)
            latency_s = latency_ms / 1000.0
            active_queries[replica] += 1
            active_query_events.append({
                "time_s": now,
                "event": "query_start",
                "policy": args.policy,
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
                    "in_flight_at_start": in_flight_start,
                    "sample_source": sample_source,
                    "sample_load": sample_load,
                    "placement_action": decision.get("action", ""),
                    "placement_reason": decision.get("reason", ""),
                },
            ))

        elif event_type == "query_end":
            replica = int(payload["replica"])
            in_flight_at_end = max(0, active_queries[replica] - 1)
            active_queries[replica] = max(0, active_queries[replica] - 1)
            active_query_events.append({
                "time_s": now,
                "event": "query_end",
                "policy": args.policy,
                "replica": replica,
                "active_queries_after": active_queries[replica],
            })
            release = policy.release_session(now, payload["session_id"])
            if release:
                placement_events.append({**release, "policy": args.policy})

            query_events.append({
                "policy": args.policy,
                "query_id": payload["query_id"],
                "session_id": payload["session_id"],
                "class": payload["class"],
                "replica": replica,
                "query_start_s": payload["query_start_s"],
                "query_finish_s": now,
                "latency_s": payload["latency_s"],
                "in_flight_at_start": payload["in_flight_at_start"],
                "in_flight_at_end": in_flight_at_end,
                "sample_source": payload["sample_source"],
                "sample_load": payload["sample_load"],
                "placement_action": payload["placement_action"],
                "placement_reason": payload["placement_reason"],
            })

    query_csv = outdir / "query_events.csv"
    metrics_csv = outdir / "metrics_by_class.csv"
    placements_csv = outdir / "session_placements.csv"
    active_csv = outdir / "active_queries_timeseries.csv"

    pd.DataFrame(query_events).to_csv(query_csv, index=False)
    write_metrics(query_events, metrics_csv)
    pd.DataFrame(placement_events).to_csv(placements_csv, index=False)
    pd.DataFrame(active_query_events).to_csv(active_csv, index=False)

    print(f"policy: {args.policy}")
    print(f"queries: {len(query_events)}")
    print(f"wrote: {query_csv}")
    print(f"wrote: {metrics_csv}")
    print(f"wrote: {placements_csv}")
    print(f"wrote: {active_csv}")


if __name__ == "__main__":
    main()
