from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

SWEEP = Path("outputs_query/terminal_sweep/no_fault_3_classes")
PLOT_DIR = SWEEP / "plots"
MEETING = SWEEP / "meeting_plots"

PLOT_DIR.mkdir(parents=True, exist_ok=True)
MEETING.mkdir(parents=True, exist_ok=True)

policies = ["round_robin", "least_loaded", "plb_nclass"]
classes = ["enterprise", "premium", "freemium", "overall"]

rows_latency = []
rows_concurrency = []

for tdir in sorted(SWEEP.glob("T*"), key=lambda p: int(p.name[1:])):
    terminal = int(tdir.name[1:])

    for policy in policies:
        qpath = tdir / policy / "query_events.csv"
        if not qpath.exists():
            print(f"missing {qpath}")
            continue

        q = pd.read_csv(qpath)
        q["terminal_equivalent"] = terminal
        q["policy"] = policy
        q["q1_concurrency_at_start"] = q["in_flight_at_start"]

        latency_by_class = (
            q.groupby(["terminal_equivalent", "policy", "class"])["latency_s"]
            .agg(
                queries="count",
                mean_latency_s="mean",
                p50_latency_s="median",
                p95_latency_s=lambda x: x.quantile(0.95),
                p99_latency_s=lambda x: x.quantile(0.99),
            )
            .reset_index()
        )

        latency_overall = (
            q.groupby(["terminal_equivalent", "policy"])["latency_s"]
            .agg(
                queries="count",
                mean_latency_s="mean",
                p50_latency_s="median",
                p95_latency_s=lambda x: x.quantile(0.95),
                p99_latency_s=lambda x: x.quantile(0.99),
            )
            .reset_index()
        )
        latency_overall["class"] = "overall"

        rows_latency.append(pd.concat([latency_by_class, latency_overall], ignore_index=True))

        concurrency_by_class = (
            q.groupby(["terminal_equivalent", "policy", "class"])["q1_concurrency_at_start"]
            .agg(
                queries="count",
                mean="mean",
                p50="median",
                p95=lambda x: x.quantile(0.95),
                max="max",
            )
            .reset_index()
        )

        concurrency_overall = (
            q.groupby(["terminal_equivalent", "policy"])["q1_concurrency_at_start"]
            .agg(
                queries="count",
                mean="mean",
                p50="median",
                p95=lambda x: x.quantile(0.95),
                max="max",
            )
            .reset_index()
        )
        concurrency_overall["class"] = "overall"

        rows_concurrency.append(pd.concat([concurrency_by_class, concurrency_overall], ignore_index=True))

if not rows_latency:
    raise SystemExit("No query_events.csv files found under the sweep folder.")

lat = pd.concat(rows_latency, ignore_index=True)
conc = pd.concat(rows_concurrency, ignore_index=True)

lat.to_csv(SWEEP / "terminal_sweep_latency_metrics.csv", index=False)
conc.to_csv(SWEEP / "terminal_sweep_concurrency_metrics.csv", index=False)

latency_metrics = [
    ("mean_latency_s", "Mean Q1 latency"),
    ("p50_latency_s", "Median Q1 latency"),
    ("p95_latency_s", "p95 Q1 latency"),
    ("p99_latency_s", "p99 Q1 latency"),
]

concurrency_metrics = [
    ("mean", "Mean Q1 concurrency at start"),
    ("p50", "Median Q1 concurrency at start"),
    ("p95", "p95 Q1 concurrency at start"),
    ("max", "Maximum Q1 concurrency at start"),
]

for cls in classes:
    part = lat[lat["class"] == cls].copy()

    for metric, label in latency_metrics:
        plt.figure(figsize=(9, 5))

        for policy in policies:
            p = part[part["policy"] == policy].sort_values("terminal_equivalent")
            plt.plot(p["terminal_equivalent"], p[metric], marker="o", label=policy)

        plt.xlabel("Terminal-equivalent pressure")
        plt.ylabel("Q1 latency (s)")
        plt.title(f"Simulation: {label} vs terminal-equivalent pressure, {cls}")
        plt.legend()
        plt.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(PLOT_DIR / f"sweep_{metric}_vs_terminals_{cls}.png", dpi=200)
        plt.close()

for cls in classes:
    part = conc[conc["class"] == cls].copy()

    for metric, label in concurrency_metrics:
        plt.figure(figsize=(9, 5))

        for policy in policies:
            p = part[part["policy"] == policy].sort_values("terminal_equivalent")
            plt.plot(p["terminal_equivalent"], p[metric], marker="o", label=policy)

        plt.xlabel("Terminal-equivalent pressure")
        plt.ylabel("Already-running Q1 queries at start")
        plt.title(f"Simulation: {label} vs terminal-equivalent pressure, {cls}")
        plt.legend()
        plt.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(PLOT_DIR / f"sweep_q1_concurrency_{metric}_vs_terminals_{cls}.png", dpi=200)
        plt.close()

for p in MEETING.glob("*.png"):
    p.unlink()

important = [
    "sweep_p50_latency_s_vs_terminals_enterprise.png",
    "sweep_p50_latency_s_vs_terminals_premium.png",
    "sweep_p50_latency_s_vs_terminals_freemium.png",
    "sweep_p95_latency_s_vs_terminals_enterprise.png",
    "sweep_p95_latency_s_vs_terminals_premium.png",
    "sweep_p95_latency_s_vs_terminals_freemium.png",
    "sweep_q1_concurrency_mean_vs_terminals_enterprise.png",
    "sweep_q1_concurrency_mean_vs_terminals_premium.png",
    "sweep_q1_concurrency_mean_vs_terminals_freemium.png",
    "sweep_q1_concurrency_p95_vs_terminals_enterprise.png",
    "sweep_q1_concurrency_p95_vs_terminals_premium.png",
    "sweep_q1_concurrency_p95_vs_terminals_freemium.png",
]

for name in important:
    src = PLOT_DIR / name
    if src.exists():
        (MEETING / name).write_bytes(src.read_bytes())

print(f"Wrote plots to {PLOT_DIR}")
print(f"Wrote meeting subset to {MEETING}")
print(f"Wrote {SWEEP / 'terminal_sweep_latency_metrics.csv'}")
print(f"Wrote {SWEEP / 'terminal_sweep_concurrency_metrics.csv'}")
