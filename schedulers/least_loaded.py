#!/usr/bin/env python3
"""Least-loaded scheduler baseline.

It chooses the logical replica with the fewest active workers, then allocates one free slot on it.
It does not protect priorities yet.
"""

from __future__ import annotations

from collections import Counter, defaultdict

from batsim.batsim import BatsimScheduler

from common import DecisionLogger, SlotMapper, get_job_class, make_allocation


class LeastLoadedScheduler(BatsimScheduler):
    def onAfterBatsimInit(self):
        self.policy = "least_loaded"
        self.slots = SlotMapper()
        self.nb_replicas = self.slots.replicas
        self.active_total = defaultdict(int)
        self.active_by_class = defaultdict(Counter)
        self.job_to_replica = {}
        self.job_to_slot = {}
        self.job_to_class = {}
        self.log = DecisionLogger()

    def _now(self) -> float:
        t = getattr(self.bs, "time", 0.0)
        return t() if callable(t) else float(t)

    def choose_replica(self) -> int:
        candidates = [r for r in range(self.nb_replicas) if self.slots.has_free_slot(r)]
        if not candidates:
            raise RuntimeError("No free slots left in the platform")
        return min(candidates, key=lambda r: (self.active_total[r], r))

    def onJobSubmission(self, job):
        cls = get_job_class(job)
        replica = self.choose_replica()
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
        )
        self.bs.execute_jobs([job])

    def onJobCompletion(self, job):
        replica = self.job_to_replica.pop(job.id, "unknown")
        slot = self.job_to_slot.pop(job.id, "unknown")
        cls = self.job_to_class.pop(job.id, get_job_class(job))

        if slot != "unknown":
            self.slots.release_slot(int(slot))

        if replica != "unknown":
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
        )

    def onSimulationEnds(self):
        self.log.close()

Least_loaded = LeastLoadedScheduler
