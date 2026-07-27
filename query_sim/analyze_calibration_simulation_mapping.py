from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd


BASE = Path("outputs_query/terminal_sweep/no_fault_3_classes")
OUT = BASE / "meeting_notes"
OUT.mkdir(parents=True, exist_ok=True)

LAT = BASE / "terminal_sweep_latency_metrics.csv"
CONC = BASE / "terminal_sweep_concurrency_metrics.csv"

# Calibration paths. The first one is expected in the normal project layout.
CALIB_CANDIDATES = [
    Path("/home/spirals/phd/experiments/janvier/benchbase_data/mcplb/calibration_models/q1/q1_latency_model_exact_load.csv"),
    Path("data/calibration/q1_latency_model_exact_load.csv"),
    Path("q1_latency_model_exact_load.csv"),
]

lat = pd.read_csv(LAT)
conc = pd.read_csv(CONC)

policies = ["round_robin", "least_loaded", "plb_nclass"]
classes = ["enterprise", "premium", "freemium"]

policy_labels = {
    "round_robin": "RR",
    "least_loaded": "LL",
    "plb_nclass": "PLB",
}

class_labels = {
    "enterprise": "Enterprise",
    "premium": "Premium",
    "freemium": "Freemium",
}

# ---------------------------------------------------------------------
# 1. Load calibration if available.
# ---------------------------------------------------------------------

calib_path = None
for p in CALIB_CANDIDATES:
    if p.exists():
        calib_path = p
        break

if calib_path is None:
    print("No calibration model CSV found. Plots using only simulation data will still be produced.")
    cal = None
else:
    cal = pd.read_csv(calib_path)
    print(f"Loaded calibration: {calib_path}")

    if "in_flight_queries" in cal.columns:
        xcol = "in_flight_queries"
    elif "q1_concurrency_at_start" in cal.columns:
        xcol = "q1_concurrency_at_start"
    elif "inflight" in cal.columns:
        xcol = "inflight"
    else:
        xcol = cal.columns[0]

    metric_cols = {}
    for c in cal.columns:
        low = c.lower()
        if "p50" in low or "median" in low:
            metric_cols["p50"] = c
        elif "p95" in low:
            metric_cols["p95"] = c
        elif "p99" in low:
            metric_cols["p99"] = c

    needed = {"p50", "p95", "p99"}
    missing = needed - set(metric_cols)
    if missing:
        raise ValueError(f"Missing calibration metric columns: {missing}. Columns: {list(cal.columns)}")

    cal = cal.sort_values(xcol).copy()

    for c in metric_cols.values():
        if cal[c].max() > 100000:
            cal[c] = cal[c] / 1_000_000.0

# ---------------------------------------------------------------------
# 2. Operating region plot:
#    how terminal pressure maps to local per-replica Q1 concurrency.
# ---------------------------------------------------------------------

sim = conc[conc["class"] != "overall"].copy()

fig, axes = plt.subplots(1, 3, figsize=(16, 4.8), sharey=True)

for ax, cls in zip(axes, classes):
    part = sim[sim["class"] == cls]

    for policy in policies:
        p = part[part["policy"] == policy].sort_values("terminal_equivalent")
        ax.plot(
            p["terminal_equivalent"],
            p["mean"],
            marker="o",
            label=policy_labels[policy],
        )

    ax.set_title(class_labels[cls])
    ax.set_xlabel("Terminal-equivalent pressure")
    ax.set_ylabel("Mean already-running Q1 queries at start")
    ax.grid(True, alpha=0.3)

axes[-1].legend(title="Policy")
fig.suptitle("Mapping global terminal pressure to local Q1 concurrency", y=1.03)
fig.tight_layout()
fig.savefig(OUT / "01_terminal_pressure_to_local_q1_concurrency_mean.png", dpi=220, bbox_inches="tight")
plt.close(fig)


fig, axes = plt.subplots(1, 3, figsize=(16, 4.8), sharey=True)

for ax, cls in zip(axes, classes):
    part = sim[sim["class"] == cls]

    for policy in policies:
        p = part[part["policy"] == policy].sort_values("terminal_equivalent")
        ax.plot(
            p["terminal_equivalent"],
            p["p95"],
            marker="o",
            label=policy_labels[policy],
        )

    ax.set_title(class_labels[cls])
    ax.set_xlabel("Terminal-equivalent pressure")
    ax.set_ylabel("p95 already-running Q1 queries at start")
    ax.grid(True, alpha=0.3)

axes[-1].legend(title="Policy")
fig.suptitle("Tail exposure to local Q1 concurrency by priority", y=1.03)
fig.tight_layout()
fig.savefig(OUT / "02_terminal_pressure_to_local_q1_concurrency_p95.png", dpi=220, bbox_inches="tight")
plt.close(fig)

# ---------------------------------------------------------------------
# 3. Calibration curve with simulation operating points.
# ---------------------------------------------------------------------

if cal is not None:
    for terminal in sorted(sim["terminal_equivalent"].unique()):
        if terminal not in [240, 300, 360, 400, 480, 600]:
            continue

        terminal_sim = sim[sim["terminal_equivalent"] == terminal]

        fig, ax = plt.subplots(figsize=(11, 6))

        ax.plot(cal[xcol], cal[metric_cols["p50"]], linewidth=1.8, label="Calibration p50")
        ax.plot(cal[xcol], cal[metric_cols["p95"]], linewidth=1.8, label="Calibration p95")
        ax.plot(cal[xcol], cal[metric_cols["p99"]], linewidth=1.8, label="Calibration p99")

        # Show simulation mean local concurrency as vertical markers.
        markers = [
            ("round_robin", "enterprise"),
            ("least_loaded", "enterprise"),
            ("plb_nclass", "enterprise"),
            ("plb_nclass", "premium"),
            ("plb_nclass", "freemium"),
        ]

        ymax = ax.get_ylim()[1]

        for policy, cls in markers:
            row = terminal_sim[
                (terminal_sim["policy"] == policy)
                & (terminal_sim["class"] == cls)
            ]
            if row.empty:
                continue

            mean_value = float(row["mean"].iloc[0])
            label = f"{policy_labels[policy]} {class_labels[cls]}"
            ax.axvline(mean_value, linestyle=":", linewidth=1.5)
            ax.text(
                mean_value,
                ymax * 0.95,
                label,
                rotation=90,
                va="top",
                ha="right",
                fontsize=8,
            )

        ax.set_title(f"Simulation operating points on Q1 calibration curve, T={terminal}")
        ax.set_xlabel("Already-running Q1 queries on selected replica")
        ax.set_ylabel("Q1 latency (s)")
        ax.grid(True, alpha=0.3)
        ax.legend(loc="lower right")
        fig.tight_layout()
        fig.savefig(OUT / f"03_calibration_curve_with_simulation_points_T{terminal}.png", dpi=220, bbox_inches="tight")
        plt.close(fig)

# ---------------------------------------------------------------------
# 4. Compact decision table for the current sweep.
# ---------------------------------------------------------------------

summary_rows = []

for terminal in sorted(sim["terminal_equivalent"].unique()):
    for policy in policies:
        for cls in classes:
            lrow = lat[
                (lat["terminal_equivalent"] == terminal)
                & (lat["policy"] == policy)
                & (lat["class"] == cls)
            ]
            crow = conc[
                (conc["terminal_equivalent"] == terminal)
                & (conc["policy"] == policy)
                & (conc["class"] == cls)
            ]

            if lrow.empty or crow.empty:
                continue

            summary_rows.append({
                "terminal_equivalent": terminal,
                "policy": policy,
                "class": cls,
                "p50_latency_s": float(lrow["p50_latency_s"].iloc[0]),
                "p95_latency_s": float(lrow["p95_latency_s"].iloc[0]),
                "mean_local_q1_concurrency": float(crow["mean"].iloc[0]),
                "p95_local_q1_concurrency": float(crow["p95"].iloc[0]),
                "max_local_q1_concurrency": float(crow["max"].iloc[0]),
            })

summary = pd.DataFrame(summary_rows)

# Add relative latency effects vs RR within each terminal/class.
rr = summary[summary["policy"] == "round_robin"][
    ["terminal_equivalent", "class", "p50_latency_s", "p95_latency_s"]
].rename(columns={
    "p50_latency_s": "rr_p50_latency_s",
    "p95_latency_s": "rr_p95_latency_s",
})

summary = summary.merge(rr, on=["terminal_equivalent", "class"], how="left")
summary["p50_change_vs_rr_pct"] = 100.0 * (
    summary["p50_latency_s"] - summary["rr_p50_latency_s"]
) / summary["rr_p50_latency_s"]
summary["p95_change_vs_rr_pct"] = 100.0 * (
    summary["p95_latency_s"] - summary["rr_p95_latency_s"]
) / summary["rr_p95_latency_s"]

summary.to_csv(OUT / "current_sweep_decision_metrics.csv", index=False)

# One readable table for the highest available terminal level.
max_t = int(summary["terminal_equivalent"].max())
max_table = summary[summary["terminal_equivalent"] == max_t].copy()
max_table = max_table.sort_values(["class", "policy"])
max_table.to_csv(OUT / f"current_sweep_decision_metrics_T{max_t}.csv", index=False)

print("Wrote meeting analysis to:")
print(OUT)
for p in sorted(OUT.glob("*.png")):
    print(p.name)
print()
print("Decision tables:")
print(OUT / "current_sweep_decision_metrics.csv")
print(OUT / f"current_sweep_decision_metrics_T{max_t}.csv")
