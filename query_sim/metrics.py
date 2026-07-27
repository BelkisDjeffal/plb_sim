#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import pandas as pd


DEFAULT_CLASS_ORDER = ["enterprise", "premium", "freemium"]
BASELINES = ["round_robin", "least_loaded"]
DEGRADATION_BOUND = 2.0


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
        for suffix in ["p50", "p95"]:
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
        pivot = group.pivot_table(index="scheduler", columns="class", values="latency_p95_s", aggfunc="first")
        for scheduler in sorted(pivot.index):
            row = {**key, "scheduler": scheduler}
            for baseline in BASELINES:
                if baseline not in pivot.index:
                    continue
                if "enterprise" in pivot.columns:
                    baseline_value = float(pivot.loc[baseline, "enterprise"])
                    scheduler_value = float(pivot.loc[scheduler, "enterprise"])
                    row[f"enterprise_gain_vs_{baseline}_p95"] = baseline_value / scheduler_value if scheduler_value > 0 else float("nan")
                if "premium" in pivot.columns:
                    baseline_value = float(pivot.loc[baseline, "premium"])
                    scheduler_value = float(pivot.loc[scheduler, "premium"])
                    row[f"premium_gain_vs_{baseline}_p95"] = baseline_value / scheduler_value if scheduler_value > 0 else float("nan")
                if "freemium" in pivot.columns:
                    baseline_value = float(pivot.loc[baseline, "freemium"])
                    scheduler_value = float(pivot.loc[scheduler, "freemium"])
                    cost = scheduler_value / baseline_value if baseline_value > 0 else float("nan")
                    row[f"freemium_cost_vs_{baseline}_p95"] = cost
                    if baseline == "round_robin":
                        row["bounded_degradation_ok_p95"] = bool(cost <= DEGRADATION_BOUND) if not math.isnan(cost) else False

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


def capacity_equivalence_metrics(latency_df: pd.DataFrame, class_name: str = "enterprise", quantile_name: str = "p95") -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    value_col = f"latency_{quantile_name}_s"
    df = latency_df[latency_df["class"] == class_name].copy()
    if df.empty or value_col not in df.columns:
        return pd.DataFrame(rows)

    group_cols = ["scenario", "T", "ratio", "seed"]
    for values, group in df.groupby(group_cols):
        base_key = dict(zip(group_cols, values))
        for scheduler in sorted(set(group["scheduler"]) - set(BASELINES)):
            for _, sched_row in group[group["scheduler"] == scheduler].iterrows():
                target_latency = float(sched_row[value_col])
                K = int(sched_row["K"])
                out = {**base_key, "scheduler": scheduler, "K": K, "class": class_name, "quantile": quantile_name, "target_latency_s": target_latency}
                for baseline in BASELINES:
                    candidates = group[(group["scheduler"] == baseline) & (group["K"].astype(int) >= K)].copy()
                    candidates = candidates.sort_values("K")
                    match = candidates[candidates[value_col].astype(float) <= target_latency]
                    if match.empty:
                        out[f"capacity_equiv_vs_{baseline}"] = float("nan")
                        out[f"replica_equiv_gain_vs_{baseline}"] = float("nan")
                    else:
                        equiv_k = int(match.iloc[0]["K"])
                        out[f"capacity_equiv_vs_{baseline}"] = equiv_k
                        out[f"replica_equiv_gain_vs_{baseline}"] = equiv_k - K
                rows.append(out)
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
    capacity_df = capacity_equivalence_metrics(latency_df, class_name=class_order[0], quantile_name="p95")

    outputs = {
        "class_latency_metrics": outdir / "class_latency_metrics.csv",
        "class_concurrency_metrics": outdir / "class_concurrency_metrics.csv",
        "calibration_support_metrics": outdir / "calibration_support_metrics.csv",
        "replica_composition_metrics": outdir / "replica_composition_metrics.csv",
        "class_concentration_metrics": outdir / "class_concentration_metrics.csv",
        "decision_metrics": outdir / "decision_metrics.csv",
        "capacity_equivalence_metrics": outdir / "capacity_equivalence_metrics.csv",
    }

    latency_df.to_csv(outputs["class_latency_metrics"], index=False)
    concurrency_df.to_csv(outputs["class_concurrency_metrics"], index=False)
    support_df.to_csv(outputs["calibration_support_metrics"], index=False)
    replica_df.to_csv(outputs["replica_composition_metrics"], index=False)
    concentration_df.to_csv(outputs["class_concentration_metrics"], index=False)
    decision_df.to_csv(outputs["decision_metrics"], index=False)
    capacity_df.to_csv(outputs["capacity_equivalence_metrics"], index=False)

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
