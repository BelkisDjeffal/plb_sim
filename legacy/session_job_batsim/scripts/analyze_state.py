#!/usr/bin/env python3

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

from scenario import SCENARIO


def parse_json_dict(value: str) -> dict:
    if not value:
        return {}
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return {}


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


def read_decisions(path: Path) -> list[dict]:
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def build_intervals(rows: list[dict]) -> tuple[list[dict], list[tuple[float, float, dict[tuple[int, str], int]]]]:
    events = sorted(rows, key=lambda r: (float(r.get("time_s") or 0), r.get("event") != "finish"))
    active_jobs = {}
    active = defaultdict(int)
    snapshots = []
    intervals = []
    prev_t = 0.0

    def snapshot(t: float) -> dict:
        replica_ids = sorted({r for r, _ in active.keys()})
        classes = sorted({c for _, c in active.keys()})
        row = {"time_s": round(t, 6)}
        for r in replica_ids:
            row[f"replica_{r}"] = sum(active[(r, c)] for c in classes)
            for cls in classes:
                row[f"replica_{r}__{cls}"] = active[(r, cls)]
        for cls in classes:
            row[f"class__{cls}"] = sum(active[(r, cls)] for r in replica_ids)
        row["total"] = sum(active.values())
        return row

    snapshots.append(snapshot(0.0))

    for row in events:
        event = row.get("event", "")
        if event not in {"start", "finish"}:
            continue

        t = float(row.get("time_s") or 0)
        if t > prev_t:
            intervals.append((prev_t, t, dict(active)))
            prev_t = t

        job_id = row.get("job_id", "")
        if event == "start":
            cls = row.get("class", "unknown")
            replica = int(row.get("replica"))
            active_jobs[job_id] = (cls, replica)
            active[(replica, cls)] += 1
        elif job_id in active_jobs:
            cls, replica = active_jobs.pop(job_id)
            active[(replica, cls)] -= 1
            if active[(replica, cls)] <= 0:
                active.pop((replica, cls), None)

        snapshots.append(snapshot(t))

    return snapshots, intervals


def write_table(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    keys = sorted({k for row in rows for k in row.keys()})
    if not keys:
        path.write_text("")
        return
    preferred = [k for k in ["policy", "time_s", "class", "replica", "action"] if k in keys]
    keys = preferred + [k for k in keys if k not in preferred]
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)


def saturation_exposure(intervals, theta: int) -> list[dict]:
    total = defaultdict(float)
    saturated = defaultdict(float)

    for t0, t1, active in intervals:
        dt = t1 - t0
        if dt <= 0:
            continue
        replicas = sorted({r for r, _ in active.keys()})
        classes = sorted({c for _, c in active.keys()})
        for r in replicas:
            replica_total = sum(active.get((r, c), 0) for c in classes)
            sat = replica_total >= theta
            for cls in classes:
                value = active.get((r, cls), 0) * dt
                total[cls] += value
                if sat:
                    saturated[cls] += value

    rows = []
    for cls in sorted(total):
        exposure = 100 * saturated[cls] / total[cls] if total[cls] else 0.0
        rows.append(
            {
                "class": cls,
                "session_seconds": round(total[cls], 6),
                "saturated_session_seconds": round(saturated[cls], 6),
                "saturation_exposure_pct": round(exposure, 6),
            }
        )
    return rows


def replica_summary(snapshots: list[dict], theta: int) -> list[dict]:
    replica_cols = sorted(
        [k for row in snapshots for k in row if k.startswith("replica_") and "__" not in k],
        key=lambda x: int(x.split("_", 1)[1]),
    )
    rows = []
    for col in replica_cols:
        values = [float(row.get(col, 0)) for row in snapshots]
        if not values:
            continue
        rows.append(
            {
                "replica": col.replace("replica_", "r"),
                "max_active": max(values),
                "mean_active": round(sum(values) / len(values), 6),
                "p95_active": round(percentile(values, 0.95), 6),
                "time_points_above_theta_pct": round(100 * sum(v >= theta for v in values) / len(values), 6),
            }
        )
    return rows


def imbalance_summary(snapshots: list[dict]) -> list[dict]:
    replica_cols = sorted(
        [k for row in snapshots for k in row if k.startswith("replica_") and "__" not in k],
        key=lambda x: int(x.split("_", 1)[1]),
    )
    values = []
    for row in snapshots:
        loads = [float(row.get(col, 0)) for col in replica_cols]
        if loads:
            values.append(max(loads) - min(loads))
    if not values:
        return []
    return [
        {
            "mean_imbalance": round(sum(values) / len(values), 6),
            "p95_imbalance": round(percentile(values, 0.95), 6),
            "max_imbalance": max(values),
        }
    ]


def pool_size_rows(rows: list[dict]) -> list[dict]:
    out = []
    for row in rows:
        pool_sizes = parse_json_dict(row.get("pool_sizes", ""))
        if not pool_sizes:
            continue
        item = {"time_s": float(row.get("time_s") or 0), "event": row.get("event", "")}
        item.update({str(k): v for k, v in pool_sizes.items()})
        out.append(item)
    return out


def borrow_event_rows(rows: list[dict]) -> list[dict]:
    actions = {"borrow_mixed", "borrow_lower", "borrow_higher_surplus", "return_to_origin"}
    out = []
    for row in rows:
        action = row.get("action", "")
        if action not in actions:
            continue
        out.append(
            {
                "time_s": float(row.get("time_s") or 0),
                "event": row.get("event", ""),
                "class": row.get("class", ""),
                "replica": row.get("replica", ""),
                "action": action,
                "source_pool": row.get("source_pool", ""),
                "target_pool": row.get("target_pool", ""),
                "reason": row.get("reason", ""),
            }
        )
    return out


def main() -> None:
    default_theta = int(SCENARIO.get("scheduler_config", {}).get("theta", 10))
    parser = argparse.ArgumentParser()
    parser.add_argument("--outdir", required=True)
    parser.add_argument("--theta", type=int, default=default_theta)
    args = parser.parse_args()

    outdir = Path(args.outdir)
    decisions_path = outdir / "scheduler_decisions.csv"
    if not decisions_path.exists():
        raise SystemExit(f"Missing scheduler decisions file: {decisions_path}")

    decisions = read_decisions(decisions_path)
    snapshots, intervals = build_intervals(decisions)

    write_table(outdir / "active_state_timeseries.csv", snapshots)
    write_table(outdir / "saturation_exposure_by_class.csv", saturation_exposure(intervals, args.theta))
    write_table(outdir / "replica_load_summary.csv", replica_summary(snapshots, args.theta))
    write_table(outdir / "imbalance_summary.csv", imbalance_summary(snapshots))
    write_table(outdir / "pool_size_timeseries.csv", pool_size_rows(decisions))
    write_table(outdir / "borrow_events.csv", borrow_event_rows(decisions))

    print(f"Read     : {decisions_path}")
    print(f"Wrote    : {outdir / 'active_state_timeseries.csv'}")
    print(f"Wrote    : {outdir / 'saturation_exposure_by_class.csv'}")
    print(f"Wrote    : {outdir / 'replica_load_summary.csv'}")
    print(f"Wrote    : {outdir / 'imbalance_summary.csv'}")
    print(f"Wrote    : {outdir / 'pool_size_timeseries.csv'}")
    print(f"Wrote    : {outdir / 'borrow_events.csv'}")


if __name__ == "__main__":
    main()
