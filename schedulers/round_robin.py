#!/usr/bin/env python3
"""
Round-robin scheduler for the first Batsim prototype.

It does not protect priorities yet.
It routes to logical replicas round-robin, then allocates a free slot inside that replica.
"""

from __future__ import annotations

from collections import Counter, defaultdict

from batsim.batsim import BatsimScheduler

from common import DecisionLogger, SlotMapper, get_job_class, make_allocation


class RoundRobinScheduler(BatsimScheduler):
    def onAfterBatsimInit(self):
        self.policy = "round_robin"
        self.next_replica = 0
        self.slots = SlotMapper()
        self.nb_replicas = self.slots.replicas
        self.active_total = defaultdict(int)
        self.active_by_class = defaultdict(Counter)
        self.job_to_replica = {}
        self.job_to_slot = {}
        self.job_to_class = {}
        self.log = DecisionLogger()

    def _now(self) -> float:
        # pybatsim versions differ slightly, keep this defensive.
        t = getattr(self.bs, "time", 0.0)
        return t() if callable(t) else float(t)

    def onJobSubmission(self, job):
        cls = get_job_class(job)
        replica = self.next_replica % self.nb_replicas
        self.next_replica += 1

        if not self.slots.has_free_slot(replica):
            replica = self.slots.first_replica_with_free_slot(replica + 1)

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

Round_robin = RoundRobinScheduler
