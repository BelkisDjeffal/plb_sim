from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import matplotlib.pyplot as plt
import pandas as pd

from scenario import SCENARIO
OUT = ROOT / "outputs_query" / SCENARIO["name"]
PLOTS = ROOT / "outputs_query" / SCENARIO["name"] / "plots"
PLOTS.mkdir(parents=True, exist_ok=True)

frames = []
for policy_dir in OUT.iterdir():
    if not policy_dir.is_dir() or policy_dir.name == "plots":
        continue
    path = policy_dir / "metrics_by_class.csv"
    if path.exists():
        df = pd.read_csv(path)
        df["policy"] = policy_dir.name
        frames.append(df)

if not frames:
    raise SystemExit("No metrics_by_class.csv files found")

metrics = pd.concat(frames, ignore_index=True)
metrics.to_csv(OUT / "comparison_metrics_by_class.csv", index=False)

for cls in [c for c in metrics["class"].unique() if c != "overall"] + ["overall"]:
    sub = metrics[metrics["class"] == cls].copy()
    x = range(len(sub))
    plt.figure(figsize=(8, 5))
    plt.plot(list(x), sub["p50_latency_s"], marker="o", label="p50")
    plt.plot(list(x), sub["p95_latency_s"], marker="o", label="p95")
    plt.plot(list(x), sub["p99_latency_s"], marker="o", label="p99")
    plt.xticks(list(x), sub["policy"], rotation=20)
    plt.xlabel("Policy")
    plt.ylabel("Q1 latency (s)")
    plt.title(f"Query-level Q1 latency, {cls}")
    plt.grid(True, alpha=0.3)
    plt.legend()
    plt.tight_layout()
    plt.savefig(PLOTS / f"query_latency_{cls}.png", dpi=200)
    plt.close()

print(f"Wrote {OUT / 'comparison_metrics_by_class.csv'}")
print(f"Wrote plots to {PLOTS}")
