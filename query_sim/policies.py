from __future__ import annotations

from collections import Counter, defaultdict
from math import floor
from typing import Any

from scenario import SCENARIO


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


def make_policy(name: str, scenario: dict[str, Any]):
    if name == "round_robin":
        return RoundRobinPolicy(scenario)
    if name == "least_loaded":
        return LeastLoadedPolicy(scenario)
    if name == "plb_nclass":
        return PLBNClassPolicy(scenario)
    raise ValueError(f"unknown policy: {name}")
