from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

SWEEP = Path("outputs_query/terminal_sweep/no_fault_3_classes")
MEETING = SWEEP / "meeting_plots"
MEETING.mkdir(parents=True, exist_ok=True)

lat = pd.read_csv(SWEEP / "terminal_sweep_latency_metrics.csv")
conc = pd.read_csv(SWEEP / "terminal_sweep_concurrency_metrics.csv")

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

def plot_latency_metric(metric, title_label, output_name):
    fig, axes = plt.subplots(1, 3, figsize=(16, 4.8), sharey=True)

    for ax, cls in zip(axes, classes):
        part = lat[lat["class"] == cls]

        for policy in policies:
            p = part[part["policy"] == policy].sort_values("terminal_equivalent")
            ax.plot(
                p["terminal_equivalent"],
                p[metric],
                marker="o",
                label=policy_labels[policy],
            )

        ax.set_title(class_labels[cls])
        ax.set_xlabel("Terminal-equivalent pressure")
        ax.grid(True, alpha=0.3)

    axes[0].set_ylabel("Q1 latency (s)")
    axes[-1].legend(title="Policy")
    fig.suptitle(f"Simulation: {title_label} vs terminal-equivalent pressure by priority", y=1.03)
    fig.tight_layout()
    fig.savefig(MEETING / output_name, dpi=220, bbox_inches="tight")
    plt.close(fig)

def plot_concurrency_metric(metric, title_label, output_name):
    fig, axes = plt.subplots(1, 3, figsize=(16, 4.8), sharey=True)

    for ax, cls in zip(axes, classes):
        part = conc[conc["class"] == cls]

        for policy in policies:
            p = part[part["policy"] == policy].sort_values("terminal_equivalent")
            ax.plot(
                p["terminal_equivalent"],
                p[metric],
                marker="o",
                label=policy_labels[policy],
            )

        ax.set_title(class_labels[cls])
        ax.set_xlabel("Terminal-equivalent pressure")
        ax.grid(True, alpha=0.3)

    axes[0].set_ylabel("Already-running Q1 queries at start")
    axes[-1].legend(title="Policy")
    fig.suptitle(f"Simulation: {title_label} vs terminal-equivalent pressure by priority", y=1.03)
    fig.tight_layout()
    fig.savefig(MEETING / output_name, dpi=220, bbox_inches="tight")
    plt.close(fig)

def plot_latency_and_concurrency(lat_metric, conc_metric, lat_label, conc_label, output_name):
    fig, axes = plt.subplots(2, 3, figsize=(16, 8.5))

    for col, cls in enumerate(classes):
        lat_part = lat[lat["class"] == cls]
        conc_part = conc[conc["class"] == cls]

        ax = axes[0, col]
        for policy in policies:
            p = lat_part[lat_part["policy"] == policy].sort_values("terminal_equivalent")
            ax.plot(
                p["terminal_equivalent"],
                p[lat_metric],
                marker="o",
                label=policy_labels[policy],
            )

        ax.set_title(class_labels[cls])
        ax.set_xlabel("Terminal-equivalent pressure")
        ax.set_ylabel("Q1 latency (s)")
        ax.grid(True, alpha=0.3)

        ax = axes[1, col]
        for policy in policies:
            p = conc_part[conc_part["policy"] == policy].sort_values("terminal_equivalent")
            ax.plot(
                p["terminal_equivalent"],
                p[conc_metric],
                marker="o",
                label=policy_labels[policy],
            )

        ax.set_xlabel("Terminal-equivalent pressure")
        ax.set_ylabel("Already-running Q1 queries at start")
        ax.grid(True, alpha=0.3)

    axes[0, 2].legend(title="Policy")
    axes[1, 2].legend(title="Policy")

    fig.suptitle(
        f"Simulation by priority: {lat_label} latency and {conc_label} Q1 concurrency",
        y=1.02,
    )
    fig.tight_layout()
    fig.savefig(MEETING / output_name, dpi=220, bbox_inches="tight")
    plt.close(fig)

plot_latency_metric(
    "p50_latency_s",
    "median Q1 latency",
    "ONEPNG_latency_p50_by_priority.png",
)

plot_latency_metric(
    "p95_latency_s",
    "p95 Q1 latency",
    "ONEPNG_latency_p95_by_priority.png",
)

plot_concurrency_metric(
    "mean",
    "mean Q1 concurrency at start",
    "ONEPNG_concurrency_mean_by_priority.png",
)

plot_concurrency_metric(
    "p95",
    "p95 Q1 concurrency at start",
    "ONEPNG_concurrency_p95_by_priority.png",
)

plot_latency_and_concurrency(
    "p50_latency_s",
    "mean",
    "median",
    "mean",
    "ONEPNG_p50_latency_and_mean_concurrency_by_priority.png",
)

plot_latency_and_concurrency(
    "p95_latency_s",
    "p95",
    "p95",
    "p95",
    "ONEPNG_p95_latency_and_p95_concurrency_by_priority.png",
)

print("Wrote combined plots:")
for path in sorted(MEETING.glob("ONEPNG_*.png")):
    print(path)
