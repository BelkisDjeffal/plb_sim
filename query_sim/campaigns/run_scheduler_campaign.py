#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scenario import SCENARIO  # noqa: E402
from query_sim.metrics import analyze_campaign  # noqa: E402
from query_sim.run_query_simulation import run_simulation  # noqa: E402


DEFAULT_TERMINAL_LEVELS = [240, 300, 360, 480, 600, 800, 1000]
DEFAULT_CLUSTER_SIZES = [8]
DEFAULT_SEEDS = [42]
DEDICATED_STATIC_SPLITS_BY_K = {
    8: [(6, 1, 1), (5, 2, 1), (4, 3, 1), (4, 2, 2)],
}
DEFAULT_SCHEDULERS = [
    "round_robin",
    "least_loaded",
    "dedicated_static",
    "plb_nclass",
    "global_target_repair_neutral",
    "global_target_repair_target_only",
    "global_target_repair_nomixed",
    "global_target_repair_nomixed_balance",
    "global_target_repair_v2_nomixed_init_4_2_2",
    "global_target_repair_v4",
    "global_target_repair_neutral_init_4_2_2",
    "global_target_repair_target_only_init_4_2_2",
]
DEFAULT_RATIOS = {
    "balanced": [1, 1, 1],
    "enterprise_heavy": [3, 1, 1],
    "premium_heavy": [1, 3, 1],
    "freemium_heavy": [1, 1, 3],
}


def split_counts(total: int, weights: list[int]) -> list[int]:
    if total <= 0:
        raise ValueError("total must be positive")
    if not weights or any(weight < 0 for weight in weights):
        raise ValueError("ratio weights must be non-negative")
    weight_sum = sum(weights)
    if weight_sum <= 0:
        raise ValueError("ratio weights must sum to a positive value")

    raw = [total * weight / weight_sum for weight in weights]
    counts = [int(value) for value in raw]
    remaining = total - sum(counts)
    order = sorted(range(len(weights)), key=lambda i: (raw[i] - counts[i], -i), reverse=True)
    for i in order[:remaining]:
        counts[i] += 1
    return counts


def scenario_variant(base: dict[str, Any], K: int, T: int, ratio_name: str, ratio_weights: list[int], seed: int) -> dict[str, Any]:
    scenario = deepcopy(base)
    classes = list(scenario["workload"]["classes"])
    if len(classes) != len(ratio_weights):
        raise ValueError("ratio length must match workload classes")

    scenario["seed"] = int(seed)
    scenario["platform"]["replicas"] = int(K)
    scenario["workload"]["total_workers"] = int(T)
    scenario["workload"]["class_counts"] = split_counts(int(T), ratio_weights)
    scenario["campaign"] = {
        "K": int(K),
        "T": int(T),
        "ratio": ratio_name,
        "ratio_weights": ratio_weights,
        "seed": int(seed),
    }
    return scenario


def run_campaign(
    outdir: Path,
    terminal_levels: list[int],
    cluster_sizes: list[int],
    seeds: list[int],
    schedulers: list[str],
    ratios: dict[str, list[int]],
    calibration: str,
    min_samples: int,
    clean: bool,
) -> dict[str, Path]:
    if clean and outdir.exists():
        shutil.rmtree(outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    for K in cluster_sizes:
        for T in terminal_levels:
            for ratio_name, ratio_weights in ratios.items():
                for seed in seeds:
                    scenario = scenario_variant(SCENARIO, K, T, ratio_name, ratio_weights, seed)
                    counts = scenario["workload"]["class_counts"]
                    for scheduler in expand_schedulers_for_k(schedulers, K):
                        run_dir = outdir / f"K{K}" / f"T{T}" / f"ratio_{ratio_name}" / f"seed{seed}" / scheduler
                        print("=" * 80)
                        print(f"scheduler={scheduler} K={K} T={T} ratio={ratio_name} seed={seed} class_counts={counts}")
                        print("=" * 80)
                        run_simulation(
                            policy_name=scheduler,
                            scenario=scenario,
                            calibration=calibration,
                            outdir=run_dir,
                            min_samples=min_samples,
                            seed=seed,
                            metadata={
                                "ratio": ratio_name,
                                "ratio_weights": ratio_weights,
                            },
                        )

    return analyze_campaign(outdir, outdir)


def parse_int_list(value: str) -> list[int]:
    return [int(part.strip()) for part in value.split(",") if part.strip()]


def parse_scheduler_list(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def parse_ratio_weights(value: str) -> list[int]:
    parts = value.replace(":", ",").split(",")
    weights = [int(part.strip()) for part in parts if part.strip()]
    if not weights:
        raise ValueError("ratio weights must not be empty")
    return weights


def parse_ratio_list(value: str) -> dict[str, list[int]]:
    selected: dict[str, list[int]] = {}

    for item in [part.strip() for part in value.split(",") if part.strip()]:
        if "=" in item:
            name, weights_text = item.split("=", 1)
            name = name.strip()
            if not name:
                raise ValueError("custom ratio name must not be empty")
            selected[name] = parse_ratio_weights(weights_text)
        elif item in DEFAULT_RATIOS:
            selected[item] = DEFAULT_RATIOS[item]
        else:
            known = ", ".join(DEFAULT_RATIOS)
            raise ValueError(
                f"unknown ratio '{item}'. Use one of: {known}; "
                "or define a custom ratio as name=w1:w2:w3."
            )

    if not selected:
        raise ValueError("at least one ratio must be selected")
    return selected


def static_scheduler_name(split: tuple[int, ...]) -> str:
    return "static_" + "_".join(str(value) for value in split)


def expand_schedulers_for_k(schedulers: list[str], K: int) -> list[str]:
    expanded: list[str] = []
    for scheduler in schedulers:
        if scheduler in {"dedicated_static", "static_dedicated"}:
            splits = DEDICATED_STATIC_SPLITS_BY_K.get(int(K))
            if not splits:
                raise ValueError(
                    f"no dedicated static split configured for K={K}. "
                    "Add it to DEDICATED_STATIC_SPLITS_BY_K."
                )
            expanded.extend(static_scheduler_name(tuple(split)) for split in splits)
        else:
            expanded.append(scheduler)

    deduplicated: list[str] = []
    seen: set[str] = set()
    for scheduler in expanded:
        if scheduler not in seen:
            deduplicated.append(scheduler)
            seen.add(scheduler)
    return deduplicated


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--outdir", default="outputs_query/scheduler_campaign")
    parser.add_argument("--terminal-levels", default=",".join(map(str, DEFAULT_TERMINAL_LEVELS)))
    parser.add_argument("--cluster-sizes", default=",".join(map(str, DEFAULT_CLUSTER_SIZES)))
    parser.add_argument("--seeds", default=",".join(map(str, DEFAULT_SEEDS)))
    parser.add_argument("--schedulers", default=",".join(DEFAULT_SCHEDULERS))
    parser.add_argument("--ratios", default="balanced")
    parser.add_argument("--calibration", default="data/calibration/q1_query_observations.csv")
    parser.add_argument("--min-samples", type=int, default=20)
    parser.add_argument("--keep-existing", action="store_true")
    args = parser.parse_args()

    outputs = run_campaign(
        outdir=ROOT / args.outdir,
        terminal_levels=parse_int_list(args.terminal_levels),
        cluster_sizes=parse_int_list(args.cluster_sizes),
        seeds=parse_int_list(args.seeds),
        schedulers=parse_scheduler_list(args.schedulers),
        ratios=parse_ratio_list(args.ratios),
        calibration=args.calibration,
        min_samples=args.min_samples,
        clean=not args.keep_existing,
    )

    print()
    for label, path in outputs.items():
        print(f"wrote {label}: {path}")


if __name__ == "__main__":
    main()
