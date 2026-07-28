from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
from math import floor
from typing import Any



class BasePolicy:
    def __init__(self, scenario: dict[str, Any]):
        self.scenario = scenario
        self.nb_replicas = int(scenario["platform"]["replicas"])
        self.active_total = defaultdict(int)
        self.active_by_class = defaultdict(Counter)
        self.session_to_replica: dict[str, int] = {}
        self.session_to_class: dict[str, str] = {}

    def assign_session(self, time_s: float, session_id: str, cls: str) -> dict[str, Any]:
        raise NotImplementedError

    def release_session(self, time_s: float, session_id: str) -> dict[str, Any] | None:
        replica = self.session_to_replica.pop(session_id, None)
        cls = self.session_to_class.pop(session_id, None)
        if replica is None or cls is None:
            return None
        self.active_total[replica] = max(0, self.active_total[replica] - 1)
        self.active_by_class[replica][cls] = max(0, self.active_by_class[replica][cls] - 1)
        return {
            "event": "release",
            "time_s": time_s,
            "session_id": session_id,
            "class": cls,
            "replica": replica,
            "action": "release",
            "source_pool": "",
            "target_pool": "",
            "reason": "query_finished",
            "pool_sizes": "",
        }

    def _register(self, session_id: str, cls: str, replica: int) -> None:
        replica = int(replica)
        self.session_to_replica[session_id] = replica
        self.session_to_class[session_id] = cls
        self.active_total[replica] += 1
        self.active_by_class[replica][cls] += 1


class RoundRobinPolicy(BasePolicy):
    name = "round_robin"

    def __init__(self, scenario: dict[str, Any]):
        super().__init__(scenario)
        self.next_replica = 0

    def assign_session(self, time_s: float, session_id: str, cls: str) -> dict[str, Any]:
        replica = self.next_replica % self.nb_replicas
        self.next_replica += 1
        self._register(session_id, cls, replica)
        return {
            "event": "assign",
            "time_s": time_s,
            "session_id": session_id,
            "class": cls,
            "replica": replica,
            "action": "round_robin",
            "source_pool": "",
            "target_pool": "",
            "reason": "next_replica",
            "pool_sizes": "",
        }


class LeastLoadedPolicy(BasePolicy):
    name = "least_loaded"

    def assign_session(self, time_s: float, session_id: str, cls: str) -> dict[str, Any]:
        replica = min(range(self.nb_replicas), key=lambda r: (self.active_total[r], r))
        self._register(session_id, cls, replica)
        return {
            "event": "assign",
            "time_s": time_s,
            "session_id": session_id,
            "class": cls,
            "replica": replica,
            "action": "least_loaded",
            "source_pool": "",
            "target_pool": "",
            "reason": "min_active_sessions",
            "pool_sizes": "",
        }


class PLBNClassPolicy(BasePolicy):
    name = "plb_nclass"

    def __init__(self, scenario: dict[str, Any]):
        super().__init__(scenario)
        cfg = scenario.get("scheduler_config", {})
        self.classes = list(cfg.get("class_order", scenario["workload"]["classes"]))
        self.priority_index = {cls: i for i, cls in enumerate(self.classes)}
        self.theta = int(cfg.get("theta", 10))
        self.alpha = float(cfg.get("alpha", 0.7))
        self.tau = int(floor(self.alpha * self.theta))
        self.kappa = {c: int(cfg.get("kappa", {}).get(c, 1)) for c in self.classes}
        self.targets = {c: int(cfg.get("targets", {}).get(c, 1)) for c in self.classes}
        self.donor_policy = str(cfg.get("donor_policy", "load_first"))
        self.higher_borrow_mode = str(cfg.get("higher_borrow_mode", "safe_surplus"))
        self.return_policy = str(cfg.get("return_policy", "simple"))
        self.pools = self._init_pools(cfg.get("initial_pools", {}))
        self.owner = {}
        self.return_to = {}
        self._rebuild_owner()

    def _init_pools(self, initial: dict[str, Any]) -> dict[str, set[int]]:
        pools = {c: set(map(int, initial.get(c, []))) for c in self.classes}
        pools["mixed"] = set(map(int, initial.get("mixed", [])))
        assigned = set().union(*pools.values()) if pools else set()
        pools["mixed"].update(set(range(self.nb_replicas)) - assigned)
        return pools

    def _rebuild_owner(self) -> None:
        self.owner.clear()
        for pool, replicas in self.pools.items():
            for r in replicas:
                self.owner[int(r)] = pool

    def _pool_sizes(self) -> dict[str, int]:
        return {pool: len(replicas) for pool, replicas in self.pools.items()}

    def _load(self, replica: int) -> int:
        return int(self.active_total[int(replica)])

    def _class_load(self, cls: str, replica: int) -> int:
        return int(self.active_by_class[int(replica)][cls])

    def _pool_replicas(self, pool: str) -> list[int]:
        return sorted(self.pools.get(pool, set()))

    def _least_loaded(self, replicas: list[int]) -> int | None:
        if not replicas:
            return None
        return min(replicas, key=lambda r: (self._load(r), r))

    def _min_load(self, pool: str) -> int:
        replicas = self._pool_replicas(pool)
        if not replicas:
            return 10**12
        return min(self._load(r) for r in replicas)

    def _move_replica(self, replica: int, source: str, target: str) -> None:
        replica = int(replica)
        self.pools[source].remove(replica)
        self.pools[target].add(replica)
        self.owner[replica] = target
        self.return_to[replica] = source

    def _lower_classes(self, cls: str) -> list[str]:
        return self.classes[self.priority_index[cls] + 1 :]

    def _higher_classes(self, cls: str) -> list[str]:
        return list(reversed(self.classes[: self.priority_index[cls]]))

    def _eligible_lower_candidates(self, cls: str) -> list[tuple[str, int]]:
        candidates = []
        for donor_cls in self._lower_classes(cls):
            if len(self.pools[donor_cls]) - 1 < self.kappa[donor_cls]:
                continue
            for replica in self._pool_replicas(donor_cls):
                candidates.append((donor_cls, replica))
        return candidates

    def _select_lower_donor(self, cls: str) -> tuple[str | None, int | None]:
        candidates = self._eligible_lower_candidates(cls)
        if not candidates:
            return None, None
        min_self = self._min_load(cls)
        source, replica = min(candidates, key=lambda x: (self._load(x[1]), x[1]))
        return (source, replica) if self._load(replica) < min_self else (None, None)

    def _eligible_higher_candidates(self, cls: str) -> list[tuple[str, int]]:
        if self.higher_borrow_mode == "disabled":
            return []
        candidates = []
        min_self = self._min_load(cls)
        for donor_cls in self._higher_classes(cls):
            if len(self.pools[donor_cls]) - 1 < self.targets[donor_cls]:
                continue
            for replica in self._pool_replicas(donor_cls):
                if self._load(replica) >= min_self:
                    continue
                if self.higher_borrow_mode == "empty_owner_only" and self._class_load(donor_cls, replica) > 0:
                    continue
                if self.higher_borrow_mode == "safe_surplus" and self._load(replica) >= self.theta:
                    continue
                candidates.append((donor_cls, replica))
        return candidates

    def _select_higher_donor(self, cls: str) -> tuple[str | None, int | None]:
        candidates = self._eligible_higher_candidates(cls)
        if not candidates:
            return None, None
        i = self.priority_index[cls]
        return min(candidates, key=lambda x: (abs(self.priority_index[x[0]] - i), self._load(x[1]), x[1]))

    def _select_replica(self, cls: str) -> tuple[int, str, str, str, str]:
        if cls not in self.pools:
            cls = self.classes[-1]

        own = self._pool_replicas(cls)
        under = [r for r in own if self._load(r) < self.theta]
        if under:
            return self._least_loaded(under), "own_pool", cls, cls, "under_theta"

        mixed = self._pool_replicas("mixed")
        if mixed:
            replica = self._least_loaded(mixed)
            self._move_replica(replica, "mixed", cls)
            return replica, "borrow_mixed", "mixed", cls, "own_pool_saturated"

        source, replica = self._select_lower_donor(cls)
        if source is not None and replica is not None:
            self._move_replica(replica, source, cls)
            return replica, "borrow_lower", source, cls, self.donor_policy

        source, replica = self._select_higher_donor(cls)
        if source is not None and replica is not None:
            self._move_replica(replica, source, cls)
            return replica, "borrow_higher_surplus", source, cls, self.higher_borrow_mode

        if own:
            return self._least_loaded(own), "fallback", cls, cls, "least_loaded_own_pool"

        all_replicas = list(range(self.nb_replicas))
        replica = self._least_loaded(all_replicas)
        return replica, "fallback_global", self.owner.get(replica, "unknown"), cls, "empty_pool"

    def _maybe_return_replicas(self, time_s: float) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        if self.return_policy != "simple":
            return events
        changed = True
        while changed:
            changed = False
            for cls in self.classes:
                if len(self.pools[cls]) <= self.targets[cls]:
                    continue
                for replica in sorted(self.pools[cls]):
                    target = self.return_to.get(replica)
                    if not target:
                        continue
                    if self._class_load(cls, replica) > 0:
                        continue
                    other = [r for r in self.pools[cls] if r != replica]
                    if other and min(self._load(r) for r in other) >= self.tau:
                        continue
                    self.pools[cls].remove(replica)
                    self.pools[target].add(replica)
                    self.owner[replica] = target
                    self.return_to.pop(replica, None)
                    events.append({
                        "event": "return",
                        "time_s": time_s,
                        "session_id": "",
                        "class": cls,
                        "replica": replica,
                        "action": "return_to_origin",
                        "source_pool": cls,
                        "target_pool": target,
                        "reason": "simple_return",
                        "pool_sizes": self._pool_sizes(),
                    })
                    changed = True
                    break
                if changed:
                    break
        return events

    def assign_session(self, time_s: float, session_id: str, cls: str) -> dict[str, Any]:
        self._maybe_return_replicas(time_s)
        replica, action, source_pool, target_pool, reason = self._select_replica(cls)
        self._register(session_id, cls, replica)
        return {
            "event": "assign",
            "time_s": time_s,
            "session_id": session_id,
            "class": cls,
            "replica": replica,
            "action": action,
            "source_pool": source_pool,
            "target_pool": target_pool,
            "reason": reason,
            "pool_sizes": self._pool_sizes(),
        }

    def release_session(self, time_s: float, session_id: str) -> dict[str, Any] | None:
        event = super().release_session(time_s, session_id)
        self._maybe_return_replicas(time_s)
        return event


class StaticPartitionPolicy(BasePolicy):
    name = "static_partition"

    def __init__(self, scenario: dict[str, Any]):
        super().__init__(scenario)
        cfg = scenario.get("scheduler_config", {})
        classes = list(cfg.get("class_order", scenario["workload"]["classes"]))
        static_cfg = cfg.get("static_partition", {})
        partitions = static_cfg.get("partitions")
        if partitions:
            self.partitions = {
                cls: sorted({int(r) for r in partitions.get(cls, [])})
                for cls in classes
            }
        else:
            self.partitions = self._build_balanced_partitions(classes)
        self.fallback = str(static_cfg.get("fallback", "least_loaded_all"))
        self.routing = str(static_cfg.get("routing", "round_robin"))
        self.next_by_class = defaultdict(int)

    def _build_balanced_partitions(self, classes: list[str]) -> dict[str, list[int]]:
        partitions = {cls: [] for cls in classes}
        if not classes:
            return partitions
        for replica in range(self.nb_replicas):
            cls = classes[replica % len(classes)]
            partitions[cls].append(replica)
        return partitions

    def _candidate_replicas(self, cls: str) -> list[int]:
        candidates = self.partitions.get(cls, [])
        if candidates:
            return list(candidates)
        if self.fallback == "least_loaded_all":
            return list(range(self.nb_replicas))
        raise ValueError(f"static partition has no replicas for class {cls}")

    def _select_static_replica(self, cls: str, candidates: list[int]) -> tuple[int, str]:
        if self.routing == "round_robin":
            index = self.next_by_class[cls] % len(candidates)
            self.next_by_class[cls] += 1
            return int(candidates[index]), "round_robin_within_dedicated_partition"
        if self.routing == "least_loaded":
            replica = min(candidates, key=lambda r: (self.active_total[r], r))
            return int(replica), "least_loaded_within_dedicated_partition"
        raise ValueError(f"unknown static partition routing: {self.routing}")

    def assign_session(self, time_s: float, session_id: str, cls: str) -> dict[str, Any]:
        candidates = self._candidate_replicas(cls)
        replica, reason = self._select_static_replica(cls, candidates)
        self._register(session_id, cls, replica)
        return {
            "event": "assign",
            "time_s": time_s,
            "session_id": session_id,
            "class": cls,
            "replica": replica,
            "action": "static_partition",
            "source_pool": cls,
            "target_pool": cls,
            "reason": reason,
            "pool_sizes": {k: len(v) for k, v in self.partitions.items()},
        }


AVAILABLE_POLICIES = {
    "round_robin": RoundRobinPolicy,
    "least_loaded": LeastLoadedPolicy,
    "static_partition": StaticPartitionPolicy,
    "plb_nclass": PLBNClassPolicy,
}


def parse_static_split_name(name: str) -> tuple[int, ...] | None:
    if not name.startswith("static_"):
        return None
    parts = name.removeprefix("static_").split("_")
    if not parts or any(not part.isdigit() for part in parts):
        return None
    return tuple(int(part) for part in parts)


def build_dedicated_partitions(nb_replicas: int, classes: list[str], split: tuple[int, ...]) -> dict[str, list[int]]:
    if len(split) != len(classes):
        raise ValueError(f"static split {split} does not match classes {classes}")
    if any(value <= 0 for value in split):
        raise ValueError(f"static split must allocate at least one replica per class: {split}")
    if sum(split) != nb_replicas:
        raise ValueError(f"static split {split} does not sum to K={nb_replicas}")

    partitions: dict[str, list[int]] = {}
    cursor = 0
    for cls, count in zip(classes, split):
        partitions[cls] = list(range(cursor, cursor + count))
        cursor += count
    return partitions


def make_static_scenario(name: str, scenario: dict[str, Any], split: tuple[int, ...]) -> dict[str, Any]:
    static_scenario = deepcopy(scenario)
    cfg = static_scenario.setdefault("scheduler_config", {})
    classes = list(cfg.get("class_order", static_scenario["workload"]["classes"]))
    nb_replicas = int(static_scenario["platform"]["replicas"])
    cfg["static_partition"] = {
        "name": name,
        "split": list(split),
        "partitions": build_dedicated_partitions(nb_replicas, classes, split),
        "routing": "round_robin",
        "fallback": "error",
    }
    return static_scenario


def make_policy(name: str, scenario: dict[str, Any]):
    static_split = parse_static_split_name(name)
    if static_split is not None:
        return StaticPartitionPolicy(make_static_scenario(name, scenario, static_split))

    try:
        return AVAILABLE_POLICIES[name](scenario)
    except KeyError as exc:
        choices = ", ".join(sorted([*AVAILABLE_POLICIES, "static_<split>"]))
        raise ValueError(f"unknown policy: {name}. Available policies: {choices}") from exc
