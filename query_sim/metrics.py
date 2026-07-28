#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
from typing import Any

import pandas as pd


DEFAULT_CLASS_ORDER = ["enterprise", "premium", "freemium"]
PRIORITY_AGNOSTIC_BASELINES = ["round_robin", "least_loaded"]
DEGRADATION_BOUND = 2.0
LATENCY_QUANTILES = ["p50", "p95"]
STATIC_NAME_RE = re.compile(r"^static_(\d+(?:_\d+)*)$")


def quantile(series: pd.Series, q: float) -> float:
    if series.empty:
        return float("nan")
    return float(series.astype(float).quantile(q))


def load_run_metadata(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "run_metadata.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def run_key_from_metadata(metadata: dict[str, Any], run_dir: Path) -> dict[str, Any]:
    return {
        "scenario": metadata.get("scenario_name", "unknown"),
        "scheduler": metadata.get("scheduler", run_dir.name),
        "K": int(metadata.get("K", 0)),
        "T": int(metadata.get("T", 0)),
        "ratio": metadata.get("ratio", "unknown"),
        "seed": int(metadata.get("seed", 0)),
    }


def query_events_path(run_dir: Path) -> Path:
    return run_dir / "query_events.csv"


def load_query_events(run_dir: Path) -> pd.DataFrame:
    path = query_events_path(run_dir)
    if not path.exists():
        raise FileNotFoundError(path)
    df = pd.read_csv(path)
    if "q1_start_concurrency" not in df.columns and "in_flight_at_start" in df.columns:
        df["q1_start_concurrency"] = df["in_flight_at_start"]
    if "q1_end_concurrency" not in df.columns and "in_flight_at_end" in df.columns:
        df["q1_end_concurrency"] = df["in_flight_at_end"]
    return df


def discover_run_dirs(root: Path) -> list[Path]:
    return sorted({p.parent for p in root.rglob("query_events.csv")})


def is_static_partition_scheduler(name: str) -> bool:
    return bool(STATIC_NAME_RE.match(str(name)))


def parse_static_split(name: str) -> tuple[int, ...] | None:
    match = STATIC_NAME_RE.match(str(name))
    if not match:
        return None
    return tuple(int(part) for part in match.group(1).split("_"))


def scheduler_kind(name: str) -> str:
    if name in PRIORITY_AGNOSTIC_BASELINES:
        return "priority_agnostic"
    if is_static_partition_scheduler(name):
        return "dedicated_partition"
    return "candidate"


def dedicated_replicas_for_class(scheduler: str, class_name: str, class_order: list[str], K: int) -> float:
    split = parse_static_split(scheduler)
    if split is None:
        return float(K) if scheduler in PRIORITY_AGNOSTIC_BASELINES else float("nan")
    if class_name not in class_order:
        return float("nan")
    idx = class_order.index(class_name)
    return float(split[idx]) if idx < len(split) else float("nan")


def latency_rows(df: pd.DataFrame, key: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    groups = [(cls, group) for cls, group in df.groupby("class")]
    groups.append(("overall", df))

    for cls, group in groups:
        lat = group["latency_s"].astype(float)
        rows.append({
            **key,
            "class": cls,
            "n_queries": int(len(group)),
            "latency_mean_s": float(lat.mean()) if len(lat) else float("nan"),
            "latency_p50_s": quantile(lat, 0.50),
            "latency_p95_s": quantile(lat, 0.95),
            "latency_p99_s": quantile(lat, 0.99),
            "latency_max_s": float(lat.max()) if len(lat) else float("nan"),
        })
    return rows


def concurrency_rows(df: pd.DataFrame, key: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    groups = [(cls, group) for cls, group in df.groupby("class")]
    groups.append(("overall", df))

    for cls, group in groups:
        c = group["q1_start_concurrency"].astype(float)
        rows.append({
            **key,
            "class": cls,
            "n_queries": int(len(group)),
            "q1_start_concurrency_mean": float(c.mean()) if len(c) else float("nan"),
            "q1_start_concurrency_p50": quantile(c, 0.50),
            "q1_start_concurrency_p95": quantile(c, 0.95),
            "q1_start_concurrency_max": float(c.max()) if len(c) else float("nan"),
        })
    return rows


def support_rows(df: pd.DataFrame, key: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    groups = [(cls, group) for cls, group in df.groupby("class")]
    groups.append(("overall", df))

    for cls, group in groups:
        n = len(group)
        sources = group.get("sample_source", pd.Series([], dtype=str)).astype(str)
        exact = int((sources == "exact").sum()) if n else 0
        out_support = int(sources.str.startswith("out_of_support").sum()) if n else 0
        rows.append({
            **key,
            "class": cls,
            "n_queries": int(n),
            "exact_sample_fraction": exact / n if n else float("nan"),
            "out_of_support_fraction": out_support / n if n else float("nan"),
        })
    return rows


def integrate_replica_intervals(df: pd.DataFrame, key: dict[str, Any], metadata: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    classes = list(metadata.get("classes", DEFAULT_CLASS_ORDER))
    K = int(metadata.get("K", key.get("K", int(df["replica"].max()) + 1 if not df.empty else 0)))
    if df.empty or K <= 0:
        return [], []

    min_t = float(df["query_start_s"].min())
    max_t = float(df["query_finish_s"].max())
    makespan = max(max_t - min_t, 1e-9)

    replica_rows: list[dict[str, Any]] = []
    class_time_by_replica = {cls: {r: 0.0 for r in range(K)} for cls in classes}

    for replica in range(K):
        r_df = df[df["replica"].astype(int) == replica]
        events: list[tuple[float, int, str]] = []
        for record in r_df.to_dict("records"):
            cls = str(record["class"])
            events.append((float(record["query_start_s"]), 1, cls))
            events.append((float(record["query_finish_s"]), -1, cls))
        events.sort(key=lambda x: (x[0], -x[1]))

        active_by_class = {cls: 0 for cls in classes}
        active_total = 0
        last_t = min_t
        area_total = 0.0
        busy_time = 0.0
        mixed_time = 0.0
        peak_active = 0
        area_by_class = {cls: 0.0 for cls in classes}

        for time_s, delta, cls in events:
            time_s = max(min_t, min(max_t, time_s))
            dt = max(0.0, time_s - last_t)
            if dt > 0:
                area_total += active_total * dt
                if active_total > 0:
                    busy_time += dt
                if sum(1 for value in active_by_class.values() if value > 0) >= 2:
                    mixed_time += dt
                for class_name, active in active_by_class.items():
                    area_by_class[class_name] += active * dt
                last_t = time_s

            if cls not in active_by_class:
                active_by_class[cls] = 0
                area_by_class[cls] = 0.0
            active_by_class[cls] = max(0, active_by_class[cls] + delta)
            active_total = max(0, active_total + delta)
            peak_active = max(peak_active, active_total)

        dt = max(0.0, max_t - last_t)
        if dt > 0:
            area_total += active_total * dt
            if active_total > 0:
                busy_time += dt
            if sum(1 for value in active_by_class.values() if value > 0) >= 2:
                mixed_time += dt
            for class_name, active in active_by_class.items():
                area_by_class[class_name] += active * dt

        for cls in classes:
            class_time_by_replica.setdefault(cls, {})[replica] = area_by_class.get(cls, 0.0)

        dominant_class = "none"
        if area_total > 0:
            dominant_class = max(classes, key=lambda cls: area_by_class.get(cls, 0.0))

        row = {
            **key,
            "replica": replica,
            "mean_active_q1": area_total / makespan,
            "peak_active_q1": int(peak_active),
            "busy_time_fraction": busy_time / makespan,
            "idle_time_fraction": 1.0 - busy_time / makespan,
            "mixed_time_fraction": mixed_time / makespan,
            "dominant_class": dominant_class,
        }
        for cls in classes:
            fraction = area_by_class.get(cls, 0.0) / area_total if area_total > 0 else 0.0
            row[f"{cls}_query_time_fraction"] = fraction
        replica_rows.append(row)

    concentration_rows: list[dict[str, Any]] = []
    for cls in classes:
        replica_times = class_time_by_replica.get(cls, {})
        total_time = sum(replica_times.values())
        if total_time <= 0:
            hhi = float("nan")
            effective_replicas = float("nan")
            top_replica_fraction = float("nan")
        else:
            shares = [value / total_time for value in replica_times.values()]
            hhi = sum(share * share for share in shares)
            effective_replicas = 1.0 / hhi if hhi > 0 else float("nan")
            top_replica_fraction = max(shares) if shares else float("nan")
        concentration_rows.append({
            **key,
            "class": cls,
            "class_query_time_total_s": total_time,
            "replica_concentration_hhi": hhi,
            "effective_replicas": effective_replicas,
            "top_replica_fraction": top_replica_fraction,
        })

    return replica_rows, concentration_rows


def priority_violation_metrics(latency_df: pd.DataFrame, class_order: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    base_cols = ["scenario", "K", "T", "ratio", "seed", "scheduler"]
    class_df = latency_df[latency_df["class"].isin(class_order)].copy()
    if class_df.empty:
        return rows

    for values, group in class_df.groupby(base_cols):
        key = dict(zip(base_cols, values))
        by_class = group.set_index("class")
        row = {**key}
        for suffix in LATENCY_QUANTILES:
            vals = [float(by_class.loc[cls, f"latency_{suffix}_s"]) for cls in class_order if cls in by_class.index]
            violation = False
            gap = 0.0
            for left, right in zip(vals, vals[1:]):
                diff = left - right
                if diff > 0:
                    violation = True
                    gap += diff
            row[f"priority_violation_{suffix}"] = bool(violation)
            row[f"priority_violation_gap_{suffix}_s"] = gap
        rows.append(row)
    return rows


def decision_metrics(latency_df: pd.DataFrame, class_order: list[str]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    base_cols = ["scenario", "K", "T", "ratio", "seed"]
    class_df = latency_df[latency_df["class"].isin(class_order)].copy()
    if class_df.empty:
        return pd.DataFrame(rows)

    priority_df = pd.DataFrame(priority_violation_metrics(latency_df, class_order))

    for values, group in class_df.groupby(base_cols):
        key = dict(zip(base_cols, values))
        schedulers = sorted(group["scheduler"].unique())
        for scheduler in schedulers:
            row = {**key, "scheduler": scheduler, "scheduler_kind": scheduler_kind(scheduler)}
            for suffix in LATENCY_QUANTILES:
                pivot = group.pivot_table(index="scheduler", columns="class", values=f"latency_{suffix}_s", aggfunc="first")
                if scheduler not in pivot.index:
                    continue
                for baseline in PRIORITY_AGNOSTIC_BASELINES:
                    if baseline not in pivot.index:
                        continue
                    for class_name in class_order:
                        if class_name not in pivot.columns:
                            continue
                        baseline_value = float(pivot.loc[baseline, class_name])
                        scheduler_value = float(pivot.loc[scheduler, class_name])
                        if class_name == class_order[-1]:
                            value = scheduler_value / baseline_value if baseline_value > 0 else float("nan")
                            metric_name = f"{class_name}_cost_vs_{baseline}_{suffix}"
                            row[metric_name] = value
                            if baseline == "round_robin":
                                ok_name = f"bounded_degradation_ok_{suffix}"
                                row[ok_name] = bool(value <= DEGRADATION_BOUND) if not math.isnan(value) else False
                        else:
                            value = baseline_value / scheduler_value if scheduler_value > 0 else float("nan")
                            metric_name = f"{class_name}_gain_vs_{baseline}_{suffix}"
                            row[metric_name] = value

            if not priority_df.empty:
                match = priority_df[
                    (priority_df["scenario"] == key["scenario"])
                    & (priority_df["K"] == key["K"])
                    & (priority_df["T"] == key["T"])
                    & (priority_df["ratio"] == key["ratio"])
                    & (priority_df["seed"] == key["seed"])
                    & (priority_df["scheduler"] == scheduler)
                ]
                if not match.empty:
                    row.update(match.iloc[0].to_dict())
            rows.append(row)
    return pd.DataFrame(rows)


def baseline_comparison_metrics(latency_df: pd.DataFrame, class_order: list[str]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    base_cols = ["scenario", "K", "T", "ratio", "seed"]
    classes = [*class_order, "overall"]
    df = latency_df[latency_df["class"].isin(classes)].copy()
    if df.empty:
        return pd.DataFrame(rows)

    for values, group in df.groupby(base_cols):
        key = dict(zip(base_cols, values))
        K = int(key["K"])
        schedulers = sorted(group["scheduler"].unique())
        baseline_schedulers = [
            scheduler for scheduler in schedulers
            if scheduler in PRIORITY_AGNOSTIC_BASELINES or is_static_partition_scheduler(scheduler)
        ]
        candidate_schedulers = [scheduler for scheduler in schedulers if scheduler not in baseline_schedulers]

        indexed = group.set_index(["scheduler", "class"])
        for scheduler in candidate_schedulers:
            for baseline in baseline_schedulers:
                for class_name in classes:
                    if (scheduler, class_name) not in indexed.index or (baseline, class_name) not in indexed.index:
                        continue
                    scheduler_row = indexed.loc[(scheduler, class_name)]
                    baseline_row = indexed.loc[(baseline, class_name)]
                    for suffix in LATENCY_QUANTILES:
                        value_col = f"latency_{suffix}_s"
                        scheduler_latency = float(scheduler_row[value_col])
                        baseline_latency = float(baseline_row[value_col])
                        rows.append({
                            **key,
                            "scheduler": scheduler,
                            "scheduler_kind": scheduler_kind(scheduler),
                            "baseline_scheduler": baseline,
                            "baseline_kind": scheduler_kind(baseline),
                            "class": class_name,
                            "quantile": suffix,
                            "scheduler_latency_s": scheduler_latency,
                            "baseline_latency_s": baseline_latency,
                            "latency_ratio_to_baseline": scheduler_latency / baseline_latency if baseline_latency > 0 else float("nan"),
                            "latency_delta_to_baseline_s": scheduler_latency - baseline_latency,
                            "baseline_replicas_for_class": dedicated_replicas_for_class(baseline, class_name, class_order, K),
                        })
    return pd.DataFrame(rows)


def analyze_campaign(root: Path, outdir: Path | None = None) -> dict[str, Path]:
    outdir = outdir or root
    outdir.mkdir(parents=True, exist_ok=True)
    run_dirs = discover_run_dirs(root)
    if not run_dirs:
        raise FileNotFoundError(f"no query_events.csv found under {root}")

    latency: list[dict[str, Any]] = []
    concurrency: list[dict[str, Any]] = []
    support: list[dict[str, Any]] = []
    replica_composition: list[dict[str, Any]] = []
    concentration: list[dict[str, Any]] = []
    class_order = DEFAULT_CLASS_ORDER

    for run_dir in run_dirs:
        metadata = load_run_metadata(run_dir)
        key = run_key_from_metadata(metadata, run_dir)
        if metadata.get("class_order"):
            class_order = list(metadata["class_order"])
        df = load_query_events(run_dir)
        latency.extend(latency_rows(df, key))
        concurrency.extend(concurrency_rows(df, key))
        support.extend(support_rows(df, key))
        replica_rows, concentration_rows = integrate_replica_intervals(df, key, metadata)
        replica_composition.extend(replica_rows)
        concentration.extend(concentration_rows)

    latency_df = pd.DataFrame(latency)
    concurrency_df = pd.DataFrame(concurrency)
    support_df = pd.DataFrame(support)
    replica_df = pd.DataFrame(replica_composition)
    concentration_df = pd.DataFrame(concentration)
    decision_df = decision_metrics(latency_df, class_order)
    comparison_df = baseline_comparison_metrics(latency_df, class_order)

    outputs = {
        "class_latency_metrics": outdir / "class_latency_metrics.csv",
        "class_concurrency_metrics": outdir / "class_concurrency_metrics.csv",
        "calibration_support_metrics": outdir / "calibration_support_metrics.csv",
        "replica_composition_metrics": outdir / "replica_composition_metrics.csv",
        "class_concentration_metrics": outdir / "class_concentration_metrics.csv",
        "decision_metrics": outdir / "decision_metrics.csv",
        "baseline_comparison_metrics": outdir / "baseline_comparison_metrics.csv",
    }

    latency_df.to_csv(outputs["class_latency_metrics"], index=False)
    concurrency_df.to_csv(outputs["class_concurrency_metrics"], index=False)
    support_df.to_csv(outputs["calibration_support_metrics"], index=False)
    replica_df.to_csv(outputs["replica_composition_metrics"], index=False)
    concentration_df.to_csv(outputs["class_concentration_metrics"], index=False)
    decision_df.to_csv(outputs["decision_metrics"], index=False)
    comparison_df.to_csv(outputs["baseline_comparison_metrics"], index=False)

    return outputs


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="outputs_query/scheduler_campaign")
    parser.add_argument("--outdir", default=None)
    args = parser.parse_args()

    root = Path(args.root)
    outdir = Path(args.outdir) if args.outdir else root
    outputs = analyze_campaign(root, outdir)
    for label, path in outputs.items():
        print(f"wrote {label}: {path}")


if __name__ == "__main__":
    main()
