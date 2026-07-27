#!/usr/bin/env python3

from __future__ import annotations

from collections import Counter, defaultdict
from math import floor
from typing import Any

from batsim.batsim import BatsimScheduler

from common import DecisionLogger, SlotMapper, get_job_class, make_allocation
from scenario import SCENARIO


class NClassPLBScheduler(BatsimScheduler):
    def onAfterBatsimInit(self):
        cfg = SCENARIO.get("scheduler_config", {})
        self.policy = "plb_nclass"
        self.classes = list(cfg.get("class_order", SCENARIO["workload"]["classes"]))
        self.priority_index = {cls: i for i, cls in enumerate(self.classes)}
        self.theta = int(cfg.get("theta", 10))
        self.alpha = float(cfg.get("alpha", 0.7))
        self.tau = int(floor(self.alpha * self.theta))
        self.kappa = {c: int(cfg.get("kappa", {}).get(c, 1)) for c in self.classes}
        self.targets = {c: int(cfg.get("targets", {}).get(c, 1)) for c in self.classes}
        self.donor_policy = str(cfg.get("donor_policy", "load_first"))
        self.higher_borrow_mode = str(cfg.get("higher_borrow_mode", "safe_surplus"))
        self.return_policy = str(cfg.get("return_policy", "simple"))

        self.slots = SlotMapper()
        self.nb_replicas = self.slots.replicas
        self.pools = self._init_pools(cfg.get("initial_pools", {}))
        self.owner = {}
        self.return_to = {}
        self._rebuild_owner()

        self.active_total = defaultdict(int)
        self.active_by_class = defaultdict(Counter)
        self.job_to_replica = {}
        self.job_to_slot = {}
        self.job_to_class = {}
        self.log = DecisionLogger()

    def _init_pools(self, initial: dict[str, Any]) -> dict[str, set[int]]:
        pools = {c: set(map(int, initial.get(c, []))) for c in self.classes}
        pools["mixed"] = set(map(int, initial.get("mixed", [])))
        assigned = set().union(*pools.values()) if pools else set()
        missing = set(range(self.nb_replicas)) - assigned
        pools["mixed"].update(missing)
        return pools

    def _rebuild_owner(self) -> None:
        self.owner.clear()
        for pool, replicas in self.pools.items():
            for r in replicas:
                self.owner[int(r)] = pool

    def _now(self) -> float:
        t = getattr(self.bs, "time", 0.0)
        return t() if callable(t) else float(t)

    def _pool_sizes(self) -> dict[str, int]:
        return {pool: len(replicas) for pool, replicas in self.pools.items()}

    def _load(self, replica: int) -> int:
        return int(self.active_total[int(replica)])

    def _class_load(self, cls: str, replica: int) -> int:
        return int(self.active_by_class[int(replica)][cls])

    def _free_pool_replicas(self, pool: str) -> list[int]:
        return sorted(r for r in self.pools.get(pool, set()) if self.slots.has_free_slot(r))

    def _least_loaded(self, replicas: list[int]) -> int | None:
        if not replicas:
            return None
        return min(replicas, key=lambda r: (self._load(r), r))

    def _min_load(self, pool: str) -> int:
        replicas = self._free_pool_replicas(pool)
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
        i = self.priority_index[cls]
        return self.classes[i + 1 :]

    def _higher_classes(self, cls: str) -> list[str]:
        i = self.priority_index[cls]
        return list(reversed(self.classes[:i]))

    def _eligible_lower_candidates(self, cls: str) -> list[tuple[str, int]]:
        candidates = []
        for donor_cls in self._lower_classes(cls):
            if len(self.pools[donor_cls]) - 1 < self.kappa[donor_cls]:
                continue
            for replica in self._free_pool_replicas(donor_cls):
                candidates.append((donor_cls, replica))
        return candidates

    def _select_lower_donor(self, cls: str) -> tuple[str | None, int | None]:
        candidates = self._eligible_lower_candidates(cls)
        if not candidates:
            return None, None

        min_self = self._min_load(cls)

        if self.donor_policy == "priority_first_lowest":
            for donor_cls in reversed(self._lower_classes(cls)):
                local = [(p, r) for p, r in candidates if p == donor_cls]
                if not local:
                    continue
                source, replica = min(local, key=lambda x: (self._load(x[1]), x[1]))
                if self._load(replica) < min_self:
                    return source, replica
            return None, None

        if self.donor_policy == "adjacent":
            lower = self._lower_classes(cls)
            if not lower:
                return None, None
            local = [(p, r) for p, r in candidates if p == lower[0]]
            if not local:
                return None, None
            source, replica = min(local, key=lambda x: (self._load(x[1]), x[1]))
            return (source, replica) if self._load(replica) < min_self else (None, None)

        if self.donor_policy == "surplus_first":
            best_source = max(
                {p for p, _ in candidates},
                key=lambda p: (len(self.pools[p]) - self.kappa[p], -self.priority_index[p]),
            )
            local = [(p, r) for p, r in candidates if p == best_source]
            source, replica = min(local, key=lambda x: (self._load(x[1]), x[1]))
            return (source, replica) if self._load(replica) < min_self else (None, None)

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
            for replica in self._free_pool_replicas(donor_cls):
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

        own = self._free_pool_replicas(cls)
        under = [r for r in own if self._load(r) < self.theta]
        if under:
            replica = self._least_loaded(under)
            return replica, "own_pool", cls, cls, "under_theta"

        mixed = self._free_pool_replicas("mixed")
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
            replica = self._least_loaded(own)
            return replica, "fallback", cls, cls, "least_loaded_own_pool"

        all_free = [r for r in range(self.nb_replicas) if self.slots.has_free_slot(r)]
        replica = self._least_loaded(all_free)
        source = self.owner.get(replica, "unknown")
        return replica, "fallback_global", source, cls, "empty_or_full_pool"

    def _maybe_return_replicas(self) -> None:
        if self.return_policy != "simple":
            return

        changed = True
        while changed:
            changed = False
            for cls in self.classes:
                if len(self.pools[cls]) <= self.targets[cls]:
                    continue
                replicas = sorted(self.pools[cls])
                for replica in replicas:
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
                    self.log.log(
                        self._now(),
                        "return",
                        "",
                        cls,
                        replica,
                        "",
                        self.policy,
                        self.active_total,
                        self.active_by_class,
                        action="return_to_origin",
                        source_pool=cls,
                        target_pool=target,
                        reason="simple_return",
                        pool_sizes=self._pool_sizes(),
                    )
                    changed = True
                    break
                if changed:
                    break

    def onJobSubmission(self, job):
        self._maybe_return_replicas()

        cls = get_job_class(job)
        replica, action, source_pool, target_pool, reason = self._select_replica(cls)
        slot = self.slots.pop_slot(replica)
        job.allocation = make_allocation(slot)

        self.active_total[replica] += 1
        self.active_by_class[replica][cls] += 1
        self.job_to_replica[job.id] = replica
        self.job_to_slot[job.id] = slot
        self.job_to_class[job.id] = cls

        self.log.log(
            self._now(),
            "start",
            job.id,
            cls,
            replica,
            slot,
            self.policy,
            self.active_total,
            self.active_by_class,
            action=action,
            source_pool=source_pool,
            target_pool=target_pool,
            reason=reason,
            pool_sizes=self._pool_sizes(),
        )

        self.bs.execute_jobs([job])

    def onJobCompletion(self, job):
        replica = self.job_to_replica.pop(job.id, "unknown")
        slot = self.job_to_slot.pop(job.id, "unknown")
        cls = self.job_to_class.pop(job.id, get_job_class(job))

        if slot != "unknown":
            self.slots.release_slot(int(slot))

        if replica != "unknown":
            replica = int(replica)
            self.active_total[replica] = max(0, self.active_total[replica] - 1)
            self.active_by_class[replica][cls] = max(0, self.active_by_class[replica][cls] - 1)

        self.log.log(
            self._now(),
            "finish",
            job.id,
            cls,
            replica,
            slot,
            self.policy,
            self.active_total,
            self.active_by_class,
            action="finish",
            pool_sizes=self._pool_sizes(),
        )

        self._maybe_return_replicas()

    def onSimulationEnds(self):
        self.log.close()


Plb_nclass = NClassPLBScheduler
