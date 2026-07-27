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

def plot_change_vs_rr():
    metrics = [
        ("p50_latency_s", "Median latency"),
        ("p95_latency_s", "p95 latency"),
    ]

    fig, axes = plt.subplots(2, 3, figsize=(16, 8.5), sharex=True)

    for row, (metric, label) in enumerate(metrics):
        for col, cls in enumerate(classes):
            ax = axes[row, col]
            part = lat[lat["class"] == cls]

            rr = (
                part[part["policy"] == "round_robin"]
                .sort_values("terminal_equivalent")
                .set_index("terminal_equivalent")[metric]
            )

            for policy in ["least_loaded", "plb_nclass"]:
                p = (
                    part[part["policy"] == policy]
                    .sort_values("terminal_equivalent")
                    .set_index("terminal_equivalent")[metric]
                )

                common = rr.index.intersection(p.index)
                change = 100.0 * (p.loc[common] - rr.loc[common]) / rr.loc[common]

                ax.plot(common, change, marker="o", label=policy_labels[policy])

            ax.axhline(0, linewidth=1)
            ax.set_title(class_labels[cls])
            ax.set_xlabel("Terminal-equivalent pressure")
            ax.set_ylabel(f"{label} change vs RR (%)")
            ax.grid(True, alpha=0.3)

    axes[0, 2].legend(title="Policy")
    axes[1, 2].legend(title="Policy")
    fig.suptitle("Simulation: latency change vs Round Robin by priority", y=1.02)
    fig.tight_layout()
    fig.savefig(MEETING / "ONEPNG_latency_change_vs_rr_by_priority.png", dpi=220, bbox_inches="tight")
    plt.close(fig)

def plot_priority_gap():
    fig, axes = plt.subplots(2, 1, figsize=(10, 8), sharex=True)

    for policy in policies:
        p = lat[lat["policy"] == policy]
        ent = (
            p[p["class"] == "enterprise"]
            .sort_values("terminal_equivalent")
            .set_index("terminal_equivalent")["p50_latency_s"]
        )
        free = (
            p[p["class"] == "freemium"]
            .sort_values("terminal_equivalent")
            .set_index("terminal_equivalent")["p50_latency_s"]
        )
        common = ent.index.intersection(free.index)
        gap = free.loc[common] - ent.loc[common]

        axes[0].plot(common, gap, marker="o", label=policy_labels[policy])

    axes[0].axhline(0, linewidth=1)
    axes[0].set_ylabel("Freemium - Enterprise p50 latency (s)")
    axes[0].set_title("Latency priority gap")
    axes[0].grid(True, alpha=0.3)
    axes[0].legend(title="Policy")

    for policy in policies:
        p = conc[conc["policy"] == policy]
        ent = (
            p[p["class"] == "enterprise"]
            .sort_values("terminal_equivalent")
            .set_index("terminal_equivalent")["mean"]
        )
        free = (
            p[p["class"] == "freemium"]
            .sort_values("terminal_equivalent")
            .set_index("terminal_equivalent")["mean"]
        )
        common = ent.index.intersection(free.index)
        gap = free.loc[common] - ent.loc[common]

        axes[1].plot(common, gap, marker="o", label=policy_labels[policy])

    axes[1].axhline(0, linewidth=1)
    axes[1].set_xlabel("Terminal-equivalent pressure")
    axes[1].set_ylabel("Freemium - Enterprise mean Q1 concurrency")
    axes[1].set_title("Concurrency priority gap")
    axes[1].grid(True, alpha=0.3)
    axes[1].legend(title="Policy")

    fig.suptitle("Simulation: priority gap between Freemium and Enterprise", y=1.02)
    fig.tight_layout()
    fig.savefig(MEETING / "ONEPNG_priority_gap_freemium_minus_enterprise.png", dpi=220, bbox_inches="tight")
    plt.close(fig)

def plot_plb_placement_heatmaps():
    levels = sorted(int(p.name[1:]) for p in SWEEP.glob("T*"))
    fig, axes = plt.subplots(2, 3, figsize=(16, 8.5))
    axes = axes.flatten()

    for ax, terminal in zip(axes, levels):
        qpath = SWEEP / f"T{terminal}" / "plb_nclass" / "query_events.csv"
        q = pd.read_csv(qpath)

        table = pd.crosstab(q["class"], q["replica"])
        table = table.reindex(index=classes, fill_value=0)
        table = table.reindex(columns=list(range(8)), fill_value=0)

        im = ax.imshow(table.values, aspect="auto")
        ax.set_title(f"T={terminal}")
        ax.set_xlabel("Replica")
        ax.set_ylabel("Class")
        ax.set_xticks(range(8))
        ax.set_xticklabels(range(8))
        ax.set_yticks(range(len(classes)))
        ax.set_yticklabels([class_labels[c] for c in classes])

        for i in range(table.shape[0]):
            for j in range(table.shape[1]):
                value = int(table.values[i, j])
                if value > 0:
                    ax.text(j, i, str(value), ha="center", va="center", fontsize=8)

    for ax in axes[len(levels):]:
        ax.axis("off")

    fig.colorbar(im, ax=axes.tolist(), shrink=0.75, label="Number of Q1 queries")
    fig.suptitle("PLB query placement by class and replica", y=1.02)
    fig.tight_layout()
    fig.savefig(MEETING / "ONEPNG_plb_query_placement_heatmaps.png", dpi=220, bbox_inches="tight")
    plt.close(fig)

def plot_plb_action_counts():
    rows = []

    for tdir in sorted(SWEEP.glob("T*"), key=lambda p: int(p.name[1:])):
        terminal = int(tdir.name[1:])
        qpath = tdir / "plb_nclass" / "query_events.csv"
        q = pd.read_csv(qpath)

        if "placement_action" not in q.columns:
            continue

        counts = q["placement_action"].value_counts().reset_index()
        counts.columns = ["placement_action", "count"]
        counts["terminal_equivalent"] = terminal
        rows.append(counts)

    if not rows:
        return

    data = pd.concat(rows, ignore_index=True)
    pivot = (
        data.pivot_table(
            index="terminal_equivalent",
            columns="placement_action",
            values="count",
            fill_value=0,
            aggfunc="sum",
        )
        .sort_index()
    )

    ax = pivot.plot(kind="bar", stacked=True, figsize=(11, 5.5))
    ax.set_xlabel("Terminal-equivalent pressure")
    ax.set_ylabel("Number of PLB placements")
    ax.set_title("PLB placement actions by terminal-equivalent pressure")
    ax.grid(True, axis="y", alpha=0.3)
    plt.tight_layout()
    plt.savefig(MEETING / "ONEPNG_plb_action_counts_by_terminal.png", dpi=220, bbox_inches="tight")
    plt.close()

plot_change_vs_rr()
plot_priority_gap()
plot_plb_placement_heatmaps()
plot_plb_action_counts()

print("Wrote extra plots:")
for path in sorted(MEETING.glob("ONEPNG_*")):
    print(path.name)
