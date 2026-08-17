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


class GlobalTargetRepairNeutralPolicy(BasePolicy):
    name = "global_target_repair_neutral"
    config_key = "global_target_repair_neutral"
    classes = ["enterprise", "premium", "freemium"]
    mixed_role = "mixed"
    roles = ["enterprise", "premium", "freemium", "mixed"]
    role_labels = {
        "enterprise": "E",
        "premium": "P",
        "freemium": "F",
        "mixed": "M",
    }
    target_repair_columns = [
        "time",
        "scheduler",
        "reason",
        "move_from",
        "move_to",
        "moved_replica",
        "current_E",
        "current_P",
        "current_F",
        "current_M",
        "target_E",
        "target_P",
        "target_F",
        "target_M",
        "after_E",
        "after_P",
        "after_F",
        "after_M",
        "current_inv",
        "target_inv",
        "after_inv",
        "target_balance",
        "demand_E",
        "demand_P",
        "demand_F",
    ]

    def __init__(self, scenario: dict[str, Any]):
        super().__init__(scenario)
        cfg = scenario.get("scheduler_config", {})
        repair_cfg = cfg.get(self.config_key, {})
        self.classes = list(repair_cfg.get("class_order", cfg.get("class_order", self.classes)))
        if self.classes != ["enterprise", "premium", "freemium"]:
            raise ValueError(f"{self.name} currently expects enterprise,premium,freemium")
        self.roles = [*self.classes, self.mixed_role]
        self.control_period = float(repair_cfg.get("control_period", 1.0))
        self.last_control_time: float | None = None
        self.reference_alloc = self._load_reference_alloc(repair_cfg)
        self.floors = {
            cls: int(repair_cfg.get("floors", {}).get(cls, 1))
            for cls in self.classes
        }
        self.role_of_replica = self._init_roles(repair_cfg)
        self.target_repair_decisions: list[dict[str, Any]] = []

    def _default_reference_alloc(self) -> dict[str, int]:
        if self.nb_replicas == 8:
            return {"enterprise": 1, "premium": 3, "freemium": 3, "mixed": 1}
        if self.nb_replicas < len(self.classes):
            raise ValueError("number of replicas must be at least the number of classes")
        return {
            "enterprise": 1,
            "premium": 1,
            "freemium": 1,
            "mixed": self.nb_replicas - len(self.classes),
        }

    def _load_reference_alloc(self, repair_cfg: dict[str, Any]) -> dict[str, int]:
        reference = self._default_reference_alloc()
        reference.update({
            role: int(value)
            for role, value in repair_cfg.get("reference_alloc", {}).items()
            if role in self.roles
        })
        total = sum(reference.get(role, 0) for role in self.roles)
        if total != self.nb_replicas:
            raise ValueError(f"reference allocation {reference} sums to {total}, not K={self.nb_replicas}")
        return {role: int(reference.get(role, 0)) for role in self.roles}

    def _init_roles(self, repair_cfg: dict[str, Any]) -> dict[int, str]:
        explicit = repair_cfg.get("role_of_replica")
        if explicit:
            roles = {int(replica): str(role) for replica, role in explicit.items()}
            if set(roles) != set(range(self.nb_replicas)):
                raise ValueError("role_of_replica must define exactly one role for each replica")
            if any(role not in self.roles for role in roles.values()):
                raise ValueError(f"role_of_replica contains roles outside {self.roles}")
            return roles

        roles: dict[int, str] = {}
        replica = 0
        for role in self.roles:
            for _ in range(self.reference_alloc[role]):
                roles[replica] = role
                replica += 1
        return roles

    def _alloc_counts(self) -> dict[str, int]:
        counts = {role: 0 for role in self.roles}
        for role in self.role_of_replica.values():
            counts[role] += 1
        return counts

    def _demand(self) -> dict[str, int]:
        counts = Counter(self.session_to_class.values())
        return {cls: int(counts[cls]) for cls in self.classes}

    def _active_classes(self, demand: dict[str, int]) -> list[str]:
        return [cls for cls in self.classes if demand.get(cls, 0) > 0]

    def _pressure(self, alloc: dict[str, int], demand: dict[str, int], cls: str) -> float:
        return float(demand.get(cls, 0)) / float(max(1, alloc.get(cls, 0)))

    def _inversion_cost(self, alloc: dict[str, int], demand: dict[str, int]) -> float:
        active = self._active_classes(demand)
        if len(active) < 2:
            return 0.0
        pressures = {cls: self._pressure(alloc, demand, cls) for cls in active}
        cost = 0.0
        for left, right in zip(active, active[1:]):
            gap = max(0.0, pressures[left] - pressures[right])
            cost += gap * gap
        return float(cost)

    def _balance_cost(self, alloc: dict[str, int], demand: dict[str, int]) -> float:
        return float(sum(self._pressure(alloc, demand, cls) ** 2 for cls in self._active_classes(demand)))

    def _distance(self, alloc: dict[str, int], current: dict[str, int]) -> int:
        return int(sum(abs(int(alloc[role]) - int(current[role])) for role in self.roles))

    def _feasible_allocations(self) -> list[dict[str, int]]:
        allocations: list[dict[str, int]] = []
        current: dict[str, int] = {}

        def rec(index: int, remaining: int) -> None:
            if index == len(self.classes):
                alloc = dict(current)
                alloc[self.mixed_role] = remaining
                allocations.append({role: int(alloc.get(role, 0)) for role in self.roles})
                return

            cls = self.classes[index]
            min_value = int(self.floors[cls])
            remaining_floor = sum(int(self.floors[c]) for c in self.classes[index + 1:])
            max_value = remaining - remaining_floor
            for value in range(min_value, max_value + 1):
                current[cls] = value
                rec(index + 1, remaining - value)

        rec(0, self.nb_replicas)
        return allocations

    def _target_alloc(self, current: dict[str, int], demand: dict[str, int]) -> dict[str, int]:
        candidates = self._feasible_allocations()
        return min(
            candidates,
            key=lambda alloc: (
                self._inversion_cost(alloc, demand),
                self._balance_cost(alloc, demand),
                self._distance(alloc, current),
                tuple(alloc[role] for role in self.roles),
            ),
        )

    def _replicas_in_role(self, role: str) -> list[int]:
        return sorted(replica for replica, value in self.role_of_replica.items() if value == role)

    def _select_donor_replica(self, donor_role: str) -> int | None:
        replicas = self._replicas_in_role(donor_role)
        if not replicas:
            return None
        if donor_role == self.mixed_role:
            return min(replicas, key=lambda r: (self.active_total[r], r))
        return min(replicas, key=lambda r: (self.active_by_class[r][donor_role], self.active_total[r], r))

    def _after_alloc(self, current: dict[str, int], donor: str, receiver: str) -> dict[str, int]:
        alloc = dict(current)
        alloc[donor] -= 1
        alloc[receiver] += 1
        return alloc

    def _choose_priority_repair_move(
        self,
        current: dict[str, int],
        target: dict[str, int],
    ) -> tuple[str | None, str | None, str]:
        receiver = None
        for role in self.classes:
            if current[role] < target[role]:
                receiver = role
                break
        if receiver is None:
            return None, None, "no_class_receiver_deficit"

        for donor in [self.mixed_role, *reversed(self.classes)]:
            if current[donor] > target[donor]:
                return donor, receiver, "priority_repair"
        return None, None, "no_donor_surplus"

    def _choose_neutral_release_move(
        self,
        current: dict[str, int],
        target: dict[str, int],
        demand: dict[str, int],
    ) -> tuple[str | None, str | None, str]:
        if current[self.mixed_role] >= self.reference_alloc[self.mixed_role]:
            return None, None, "no_move_priority_respected"

        for donor in self.classes:
            if current[donor] <= target[donor]:
                continue
            if current[donor] <= self.floors[donor]:
                continue
            after = self._after_alloc(current, donor, self.mixed_role)
            if self._inversion_cost(after, demand) > 0.0:
                continue
            return donor, self.mixed_role, "neutral_release"

        return None, None, "no_safe_neutral_release"

    def _alloc_log_fields(self, prefix: str, alloc: dict[str, int]) -> dict[str, int]:
        return {
            f"{prefix}_{self.role_labels[role]}": int(alloc.get(role, 0))
            for role in self.roles
        }

    def _demand_log_fields(self, demand: dict[str, int]) -> dict[str, int]:
        return {
            f"demand_{self.role_labels[cls]}": int(demand.get(cls, 0))
            for cls in self.classes
        }

    def _record_control_decision(
        self,
        time_s: float,
        reason: str,
        move_from: str,
        move_to: str,
        moved_replica: int | str,
        current: dict[str, int],
        target: dict[str, int],
        after: dict[str, int],
        demand: dict[str, int],
    ) -> None:
        row: dict[str, Any] = {
            "time": float(time_s),
            "scheduler": self.name,
            "reason": reason,
            "move_from": move_from,
            "move_to": move_to,
            "moved_replica": moved_replica,
            "current_inv": self._inversion_cost(current, demand),
            "target_inv": self._inversion_cost(target, demand),
            "after_inv": self._inversion_cost(after, demand),
            "target_balance": self._balance_cost(target, demand),
        }
        row.update(self._alloc_log_fields("current", current))
        row.update(self._alloc_log_fields("target", target))
        row.update(self._alloc_log_fields("after", after))
        row.update(self._demand_log_fields(demand))
        self.target_repair_decisions.append({column: row.get(column, "") for column in self.target_repair_columns})

    def _run_controller(self, time_s: float) -> None:
        current = self._alloc_counts()
        demand = self._demand()
        target = self._target_alloc(current, demand)
        current_inv = self._inversion_cost(current, demand)

        if current_inv > 0.0:
            donor, receiver, reason = self._choose_priority_repair_move(current, target)
        else:
            donor, receiver, reason = self._choose_neutral_release_move(current, target, demand)

        moved_replica: int | str = ""
        after = dict(current)
        if donor is not None and receiver is not None:
            replica = self._select_donor_replica(donor)
            if replica is None:
                reason = "no_physical_donor"
            else:
                self.role_of_replica[replica] = receiver
                moved_replica = replica
                after = self._after_alloc(current, donor, receiver)

        self._record_control_decision(
            time_s=time_s,
            reason=reason,
            move_from=donor or "",
            move_to=receiver or "",
            moved_replica=moved_replica,
            current=current,
            target=target,
            after=after,
            demand=demand,
        )

    def _maybe_run_controller(self, time_s: float) -> None:
        if self.last_control_time is None or time_s - self.last_control_time >= self.control_period:
            self._run_controller(time_s)
            self.last_control_time = time_s

    def _assignment_metadata(self, replica: int) -> dict[str, Any]:
        alloc = self._alloc_counts()
        data: dict[str, Any] = {
            "replica_role_at_start": self.role_of_replica.get(int(replica), "unknown"),
        }
        for role in self.roles:
            data[f"alloc_{self.role_labels[role]}_at_start"] = int(alloc.get(role, 0))
        return data

    def assign_session(self, time_s: float, session_id: str, cls: str) -> dict[str, Any]:
        self._maybe_run_controller(time_s)
        if cls not in self.classes:
            cls = self.classes[-1]

        candidates = self._replicas_in_role(cls)
        if candidates:
            replica = min(candidates, key=lambda r: (self.active_total[r], self.active_by_class[r][cls], r))
            action = "target_repair_route"
            reason = "least_loaded_role_replica"
            source_pool = cls
            target_pool = cls
        else:
            replica = min(range(self.nb_replicas), key=lambda r: (self.active_total[r], r))
            action = "target_repair_fallback_global"
            reason = "no_replica_with_class_role"
            source_pool = self.role_of_replica.get(replica, "unknown")
            target_pool = cls

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
            "pool_sizes": self._alloc_counts(),
            **self._assignment_metadata(replica),
        }


class GlobalTargetRepairTargetOnlyPolicy(GlobalTargetRepairNeutralPolicy):
    name = "global_target_repair_target_only"
    config_key = "global_target_repair_target_only"

    def _choose_neutral_release_move(
        self,
        current: dict[str, int],
        target: dict[str, int],
        demand: dict[str, int],
    ) -> tuple[str | None, str | None, str]:
        current_distance = self._distance(current, target)

        def safe_move(donor: str, receiver: str) -> bool:
            after = self._after_alloc(current, donor, receiver)
            return (
                self._inversion_cost(after, demand) == 0.0
                and self._distance(after, target) < current_distance
            )

        if current[self.mixed_role] > target[self.mixed_role]:
            for receiver in self.classes:
                if current[receiver] >= target[receiver]:
                    continue
                if safe_move(self.mixed_role, receiver):
                    return self.mixed_role, receiver, "neutral_fill_from_mixed"

        if current[self.mixed_role] < target[self.mixed_role]:
            for donor in reversed(self.classes):
                if current[donor] <= target[donor]:
                    continue
                if current[donor] <= self.floors[donor]:
                    continue
                if safe_move(donor, self.mixed_role):
                    return donor, self.mixed_role, "neutral_release_to_target"

        if current == target:
            return None, None, "no_move_at_target"
        return None, None, "no_safe_target_move"


class GlobalTargetRepairNeutralInit422Policy(GlobalTargetRepairNeutralPolicy):
    name = "global_target_repair_neutral_init_4_2_2"
    config_key = "global_target_repair_neutral_init_4_2_2"

    def _default_reference_alloc(self) -> dict[str, int]:
        if self.nb_replicas == 8:
            return {"enterprise": 4, "premium": 2, "freemium": 2, "mixed": 0}
        return super()._default_reference_alloc()


class GlobalTargetRepairTargetOnlyInit422Policy(GlobalTargetRepairTargetOnlyPolicy):
    name = "global_target_repair_target_only_init_4_2_2"
    config_key = "global_target_repair_target_only_init_4_2_2"

    def _default_reference_alloc(self) -> dict[str, int]:
        if self.nb_replicas == 8:
            return {"enterprise": 4, "premium": 2, "freemium": 2, "mixed": 0}
        return super()._default_reference_alloc()


AVAILABLE_POLICIES = {
    "round_robin": RoundRobinPolicy,
    "least_loaded": LeastLoadedPolicy,
    "static_partition": StaticPartitionPolicy,
    "plb_nclass": PLBNClassPolicy,
    "global_target_repair_neutral": GlobalTargetRepairNeutralPolicy,
    "global_target_repair_target_only": GlobalTargetRepairTargetOnlyPolicy,
    "global_target_repair_neutral_init_4_2_2": GlobalTargetRepairNeutralInit422Policy,
    "global_target_repair_target_only_init_4_2_2": GlobalTargetRepairTargetOnlyInit422Policy,
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
