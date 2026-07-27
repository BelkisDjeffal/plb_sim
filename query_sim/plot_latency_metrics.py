from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

base = Path("outputs_query/no_fault_3_classes")
plot_dir = base / "plots"
plot_dir.mkdir(parents=True, exist_ok=True)

metrics = [
    ("mean_latency_s", "Mean Q1 latency"),
    ("p50_latency_s", "Median Q1 latency"),
    ("p95_latency_s", "p95 Q1 latency"),
    ("p99_latency_s", "p99 Q1 latency"),
]

policy_order = ["round_robin", "least_loaded", "plb_nclass"]
class_order = ["enterprise", "premium", "freemium", "overall"]

df = pd.read_csv(base / "comparison_metrics_by_class.csv")
df["policy"] = pd.Categorical(df["policy"], categories=policy_order, ordered=True)
df["class"] = pd.Categorical(df["class"], categories=class_order, ordered=True)
df = df.sort_values(["class", "policy"])

for metric, label in metrics:
    pivot = df.pivot(index="class", columns="policy", values=metric).loc[class_order]

    ax = pivot.plot(kind="bar", figsize=(9, 5))
    ax.set_xlabel("Class")
    ax.set_ylabel("Q1 latency (s)")
    ax.set_title(f"{label} by class and policy")
    ax.grid(True, axis="y", alpha=0.3)
    plt.xticks(rotation=0)
    plt.tight_layout()
    plt.savefig(plot_dir / f"simulation_{metric}_by_class_policy.png", dpi=200)
    plt.close()

for cls in class_order:
    part = df[df["class"] == cls].copy()
    values = part.set_index("policy")[[m for m, _ in metrics]].loc[policy_order]
    values.columns = ["mean", "p50", "p95", "p99"]

    ax = values.plot(kind="bar", figsize=(8, 5))
    ax.set_xlabel("Policy")
    ax.set_ylabel("Q1 latency (s)")
    ax.set_title(f"Q1 latency metrics, {cls}")
    ax.grid(True, axis="y", alpha=0.3)
    plt.xticks(rotation=20)
    plt.tight_layout()
    plt.savefig(plot_dir / f"simulation_latency_metrics_{cls}.png", dpi=200)
    plt.close()

rr = df[df["policy"] == "round_robin"].set_index("class")
rows = []

for _, row in df.iterrows():
    cls = row["class"]
    policy = row["policy"]

    if policy == "round_robin":
        continue

    for metric, label in metrics:
        baseline = rr.loc[cls, metric]
        value = row[metric]
        change_pct = 100.0 * (value - baseline) / baseline

        rows.append(
            {
                "class": cls,
                "policy": policy,
                "metric": metric,
                "latency_s": value,
                "round_robin_latency_s": baseline,
                "change_vs_round_robin_pct": change_pct,
            }
        )

improvement = pd.DataFrame(rows)
improvement.to_csv(base / "latency_change_vs_round_robin.csv", index=False)

for metric, label in metrics:
    part = improvement[improvement["metric"] == metric]
    pivot = part.pivot(index="class", columns="policy", values="change_vs_round_robin_pct").loc[class_order]

    ax = pivot.plot(kind="bar", figsize=(9, 5))
    ax.axhline(0, linewidth=1)
    ax.set_xlabel("Class")
    ax.set_ylabel("Change vs round_robin (%)")
    ax.set_title(f"{label}: change vs round_robin")
    ax.grid(True, axis="y", alpha=0.3)
    plt.xticks(rotation=0)
    plt.tight_layout()
    plt.savefig(plot_dir / f"simulation_{metric}_change_vs_round_robin.png", dpi=200)
    plt.close()

print(f"Wrote latency plots to {plot_dir}")
print()
print("Generated files:")
for path in sorted(plot_dir.glob("simulation_*.png")):
    print(path.name)

print()
print("Wrote:")
print(base / "latency_change_vs_round_robin.csv")
