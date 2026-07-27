from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

sim_base = Path("outputs_query/no_fault_3_classes")
sim_plot_dir = sim_base / "plots"
sim_plot_dir.mkdir(parents=True, exist_ok=True)

calib_base = Path("/home/spirals/phd/experiments/janvier/benchbase_data/mcplb")
calib_model_dir = calib_base / "calibration_models" / "q1"
calib_plot_dir = calib_model_dir.parent / "q1_plots"
calib_plot_dir.mkdir(parents=True, exist_ok=True)

policies = ["round_robin", "least_loaded", "plb_nclass"]
classes = ["enterprise", "premium", "freemium"]

# ---------------------------------------------------------------------
# 1. Calibration plots: terminals -> latency
# ---------------------------------------------------------------------

by_t_path = calib_model_dir / "q1_latency_by_terminals.csv"
if by_t_path.exists():
    by_t = pd.read_csv(by_t_path)

    plt.figure(figsize=(9, 5))
    plt.plot(by_t["terminals"], by_t["p50_ms"] / 1000.0, marker="o", label="p50")
    plt.plot(by_t["terminals"], by_t["p95_ms"] / 1000.0, marker="o", label="p95")
    plt.plot(by_t["terminals"], by_t["p99_ms"] / 1000.0, marker="o", label="p99")
    plt.xlabel("BenchBase terminals")
    plt.ylabel("Q1 latency (s)")
    plt.title("Calibration: Q1 latency by terminal pressure")
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(calib_plot_dir / "calibration_latency_vs_terminals.png", dpi=200)
    plt.close()

# ---------------------------------------------------------------------
# 2. Calibration plots: Q1 concurrency at start -> latency
# ---------------------------------------------------------------------

exact_path = calib_model_dir / "q1_latency_model_exact_load.csv"
if exact_path.exists():
    exact = pd.read_csv(exact_path)

    x_col = "in_flight_queries"
    if "q1_concurrency_at_start" in exact.columns:
        x_col = "q1_concurrency_at_start"

    plt.figure(figsize=(9, 5))
    plt.plot(exact[x_col], exact["p50_ms"] / 1000.0, marker=".", label="p50")
    plt.plot(exact[x_col], exact["p95_ms"] / 1000.0, marker=".", label="p95")
    plt.plot(exact[x_col], exact["p99_ms"] / 1000.0, marker=".", label="p99")
    plt.xlabel("Already-running Q1 queries at start")
    plt.ylabel("Q1 latency (s)")
    plt.title("Calibration: Q1 latency by Q1 concurrency at start")
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(calib_plot_dir / "calibration_latency_vs_q1_concurrency_at_start.png", dpi=200)
    plt.close()

# ---------------------------------------------------------------------
# 3. Simulation data
# ---------------------------------------------------------------------

frames = []
for policy in policies:
    path = sim_base / policy / "query_events.csv"
    df = pd.read_csv(path)
    df["policy"] = policy
    frames.append(df)

sim = pd.concat(frames, ignore_index=True)

sim["q1_concurrency_at_start"] = sim["in_flight_at_start"]
sim["latency_s"] = sim["latency_s"]

# ---------------------------------------------------------------------
# 4. Simulation: latency vs Q1 concurrency, one plot per class
# ---------------------------------------------------------------------

for cls in classes:
    part = sim[sim["class"] == cls].copy()

    plt.figure(figsize=(9, 5))

    for policy in policies:
        p = part[part["policy"] == policy]

        summary = (
            p.groupby("q1_concurrency_at_start")["latency_s"]
            .agg(
                samples="count",
                p50="median",
                p95=lambda x: x.quantile(0.95),
            )
            .reset_index()
            .sort_values("q1_concurrency_at_start")
        )

        plt.plot(
            summary["q1_concurrency_at_start"],
            summary["p50"],
            marker=".",
            label=f"{policy} p50",
        )

    plt.xlabel("Already-running Q1 queries on selected replica at start")
    plt.ylabel("Simulated Q1 latency (s)")
    plt.title(f"Simulation: median Q1 latency vs Q1 concurrency, {cls}")
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(sim_plot_dir / f"simulation_p50_latency_vs_q1_concurrency_{cls}.png", dpi=200)
    plt.close()

    plt.figure(figsize=(9, 5))

    for policy in policies:
        p = part[part["policy"] == policy]

        summary = (
            p.groupby("q1_concurrency_at_start")["latency_s"]
            .agg(
                samples="count",
                p50="median",
                p95=lambda x: x.quantile(0.95),
            )
            .reset_index()
            .sort_values("q1_concurrency_at_start")
        )

        plt.plot(
            summary["q1_concurrency_at_start"],
            summary["p95"],
            marker=".",
            label=f"{policy} p95",
        )

    plt.xlabel("Already-running Q1 queries on selected replica at start")
    plt.ylabel("Simulated Q1 latency (s)")
    plt.title(f"Simulation: p95 Q1 latency vs Q1 concurrency, {cls}")
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(sim_plot_dir / f"simulation_p95_latency_vs_q1_concurrency_{cls}.png", dpi=200)
    plt.close()

# ---------------------------------------------------------------------
# 5. Simulation: scatter latency vs Q1 concurrency, by class and policy
# ---------------------------------------------------------------------

for policy in policies:
    part = sim[sim["policy"] == policy].copy()

    plt.figure(figsize=(9, 5))

    for cls in classes:
        p = part[part["class"] == cls]
        plt.scatter(
            p["q1_concurrency_at_start"],
            p["latency_s"],
            s=12,
            alpha=0.45,
            label=cls,
        )

    plt.xlabel("Already-running Q1 queries on selected replica at start")
    plt.ylabel("Simulated Q1 latency (s)")
    plt.title(f"Simulation: Q1 latency vs Q1 concurrency, {policy}")
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(sim_plot_dir / f"simulation_scatter_latency_vs_q1_concurrency_{policy}.png", dpi=200)
    plt.close()

# ---------------------------------------------------------------------
# 6. Simulation: concurrency distribution by class and policy
# ---------------------------------------------------------------------

summary = (
    sim.groupby(["policy", "class"])["q1_concurrency_at_start"]
    .agg(
        samples="count",
        mean="mean",
        p50="median",
        p95=lambda x: x.quantile(0.95),
        max="max",
    )
    .reset_index()
)

summary.to_csv(sim_base / "simulation_q1_concurrency_by_class_policy.csv", index=False)

for metric in ["mean", "p50", "p95", "max"]:
    pivot = summary.pivot(index="class", columns="policy", values=metric).loc[classes]

    ax = pivot.plot(kind="bar", figsize=(9, 5))
    ax.set_xlabel("Priority class")
    ax.set_ylabel("Already-running Q1 queries at start")
    ax.set_title(f"Simulation: Q1 concurrency at start by class and policy, {metric}")
    ax.grid(True, axis="y", alpha=0.3)
    plt.xticks(rotation=0)
    plt.tight_layout()
    plt.savefig(sim_plot_dir / f"simulation_q1_concurrency_{metric}_by_class_policy.png", dpi=200)
    plt.close()

# ---------------------------------------------------------------------
# 7. Write a latency-load summary table for reading
# ---------------------------------------------------------------------

latency_load_summary = (
    sim.groupby(["policy", "class", "q1_concurrency_at_start"])["latency_s"]
    .agg(
        samples="count",
        p50="median",
        p95=lambda x: x.quantile(0.95),
        p99=lambda x: x.quantile(0.99),
    )
    .reset_index()
    .sort_values(["policy", "class", "q1_concurrency_at_start"])
)

latency_load_summary.to_csv(sim_base / "simulation_latency_by_q1_concurrency_class_policy.csv", index=False)

print("Wrote simulation load-latency plots to:")
print(sim_plot_dir)
print()
print("Wrote tables:")
print(sim_base / "simulation_q1_concurrency_by_class_policy.csv")
print(sim_base / "simulation_latency_by_q1_concurrency_class_policy.csv")
