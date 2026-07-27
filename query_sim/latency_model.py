from __future__ import annotations

import random
from collections import defaultdict
from pathlib import Path

import pandas as pd


class EmpiricalLatencyModel:
    def __init__(self, csv_path: str | Path, min_samples: int = 20, seed: int = 42):
        self.csv_path = Path(csv_path)
        self.min_samples = int(min_samples)
        self.rng = random.Random(seed)

        df = pd.read_csv(self.csv_path)
        if "in_flight_queries" not in df.columns:
            raise ValueError("q1_query_observations.csv must contain in_flight_queries")
        if "latency_ms" not in df.columns:
            raise ValueError("q1_query_observations.csv must contain latency_ms")

        df = df.dropna(subset=["in_flight_queries", "latency_ms"]).copy()
        df["in_flight_queries"] = df["in_flight_queries"].astype(int)
        df["latency_ms"] = df["latency_ms"].astype(float)
        df = df[df["latency_ms"] > 0]

        if df.empty:
            raise ValueError(f"no valid latency samples in {self.csv_path}")

        self.samples_by_load: dict[int, list[float]] = defaultdict(list)
        for load, group in df.groupby("in_flight_queries"):
            self.samples_by_load[int(load)] = group["latency_ms"].tolist()

        self.available_loads = sorted(self.samples_by_load)
        self.min_load = self.available_loads[0]
        self.max_load = self.available_loads[-1]

    def _collect_window(self, load: int, radius: int) -> list[float]:
        samples: list[float] = []
        low = load - radius
        high = load + radius
        for key in self.available_loads:
            if low <= key <= high:
                samples.extend(self.samples_by_load[key])
        return samples

    def sample_ms(self, load: int) -> tuple[float, str, int]:
        load = max(0, int(load))

        exact = self.samples_by_load.get(load, [])
        if len(exact) >= self.min_samples:
            return self.rng.choice(exact), "exact", load

        for radius in (1, 2, 3, 5):
            window = self._collect_window(load, radius)
            if len(window) >= self.min_samples:
                return self.rng.choice(window), f"window_{radius}", load

        nearest = min(self.available_loads, key=lambda x: (abs(x - load), x))
        source = "nearest"
        if load > self.max_load:
            source = "out_of_support_highest"
            nearest = self.max_load
        elif load < self.min_load:
            source = "out_of_support_lowest"
            nearest = self.min_load
        return self.rng.choice(self.samples_by_load[nearest]), source, nearest
