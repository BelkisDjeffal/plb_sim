from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

base = Path("outputs_query/no_fault_3_classes")
plot_dir = base / "plots"
plot_dir.mkdir(parents=True, exist_ok=True)

policies = ["round_robin", "least_loaded", "plb_nclass"]

all_queries = []
for policy in policies:
    q = pd.read_csv(base / policy / "query_events.csv")
    q["policy"] = policy
    all_queries.append(q)

queries = pd.concat(all_queries, ignore_index=True)

summary = (
    queries.groupby(["policy", "class"])["in_flight_at_start"]
    .agg(mean="mean", median="median", p95=lambda x: x.quantile(0.95), max="max")
    .reset_index()
)

summary.to_csv(base / "diagnostic_concurrency_by_class.csv", index=False)

for metric in ["mean", "median", "p95", "max"]:
    pivot = summary.pivot(index="class", columns="policy", values=metric)

    ax = pivot.plot(kind="bar", figsize=(8, 5))
    ax.set_xlabel("Class")
    ax.set_ylabel("Already-running Q1 queries at start")
    ax.set_title(f"Q1 concurrency at start by class and policy, {metric}")
    ax.grid(True, axis="y", alpha=0.3)
    plt.tight_layout()
    plt.savefig(plot_dir / f"diagnostic_q1_concurrency_{metric}_by_class_policy.png", dpi=200)
    plt.close()

for policy in policies:
    q = queries[queries["policy"] == policy]
    placement = pd.crosstab(q["replica"], q["class"])

    ax = placement.plot(kind="bar", stacked=True, figsize=(8, 5))
    ax.set_xlabel("Replica")
    ax.set_ylabel("Q1 queries")
    ax.set_title(f"Q1 placements per replica, {policy}")
    ax.grid(True, axis="y", alpha=0.3)
    plt.tight_layout()
    plt.savefig(plot_dir / f"diagnostic_q1_placements_per_replica_{policy}.png", dpi=200)
    plt.close()

    ts = pd.read_csv(base / policy / "active_queries_timeseries.csv")
    max_by_replica = ts.groupby("replica")["active_queries_after"].max().reset_index()

    plt.figure(figsize=(8, 5))
    plt.bar(max_by_replica["replica"].astype(str), max_by_replica["active_queries_after"])
    plt.xlabel("Replica")
    plt.ylabel("Maximum active Q1 queries")
    plt.title(f"Maximum active Q1 queries per replica, {policy}")
    plt.grid(True, axis="y", alpha=0.3)
    plt.tight_layout()
    plt.savefig(plot_dir / f"diagnostic_max_active_q1_per_replica_{policy}.png", dpi=200)
    plt.close()

print(f"Wrote diagnostics to {plot_dir}")
print(summary.to_string(index=False))
