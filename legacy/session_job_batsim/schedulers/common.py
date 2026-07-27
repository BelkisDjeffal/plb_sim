"""Small helpers shared by schedulers."""

from __future__ import annotations

import csv
import json
import os
import sys
from collections import Counter, defaultdict, deque
from pathlib import Path
from typing import Any, Dict

# Make scenario.py importable when pybatsim runs a scheduler from schedulers/.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scenario import SCENARIO  # noqa: E402

try:
    from procset import ProcSet
except Exception as exc:  # pragma: no cover, only raised when pybatsim is missing
    raise RuntimeError("This scheduler must be run with pybatsim installed.") from exc


def get_job_class(job: Any) -> str:
    """Extract class from job.extra_data when available, else from job id suffix."""
    raw = None
    for attr in ("extra_data", "metadata"):
        raw = getattr(job, attr, None)
        if raw:
            break

    if raw:
        try:
            if isinstance(raw, str):
                return json.loads(raw).get("class", "unknown")
            if isinstance(raw, dict):
                return raw.get("class", "unknown")
        except Exception:
            pass

    jid = str(getattr(job, "id", ""))
    if "__" in jid:
        return jid.split("__", 1)[1]
    return "unknown"


def make_allocation(resource_id: int) -> ProcSet:
    """Allocate one Batsim resource.

    In the slot model, resource_id is a slot, not a logical replica.
    """
    return ProcSet(int(resource_id))


class SlotMapper:
    """Map logical replicas to Batsim resource slots."""

    def __init__(self):
        p = SCENARIO["platform"]
        self.replicas = int(p["replicas"])
        self.slots_per_replica = int(p.get("slots_per_replica", 1))
        self.total_slots = self.replicas * self.slots_per_replica
        self.free_by_replica = {
            r: deque(range(r * self.slots_per_replica, (r + 1) * self.slots_per_replica))
            for r in range(self.replicas)
        }
        self.slot_to_replica = {
            slot: slot // self.slots_per_replica for slot in range(self.total_slots)
        }

    def has_free_slot(self, replica: int) -> bool:
        return bool(self.free_by_replica[int(replica)])

    def pop_slot(self, replica: int) -> int:
        replica = int(replica)
        if not self.free_by_replica[replica]:
            raise RuntimeError(f"No free slot on replica {replica}")
        return self.free_by_replica[replica].popleft()

    def release_slot(self, slot: int) -> None:
        slot = int(slot)
        replica = self.slot_to_replica[slot]
        self.free_by_replica[replica].append(slot)

    def first_replica_with_free_slot(self, start: int = 0) -> int:
        for offset in range(self.replicas):
            r = (int(start) + offset) % self.replicas
            if self.has_free_slot(r):
                return r
        raise RuntimeError("No free slots left in the platform")


class DecisionLogger:
    def __init__(self, path: str | None = None):
        self.path = Path(path or os.environ.get("PLB_SCHED_LOG", "scheduler_decisions.csv"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.f = self.path.open("w", newline="")
        self.writer = csv.writer(self.f)
        self.writer.writerow(
            [
                "time_s",
                "event",
                "job_id",
                "class",
                "replica",
                "slot",
                "policy",
                "action",
                "source_pool",
                "target_pool",
                "reason",
                "pool_sizes",
                "active_total_after",
                "active_by_class_after",
            ]
        )
        self.f.flush()

    def log(
        self,
        time_s: float,
        event: str,
        job_id: str,
        cls: str,
        replica: int | str,
        slot: int | str,
        policy: str,
        active_total: Dict[int, int],
        active_by_class: Dict[int, Counter],
        action: str = "",
        source_pool: str = "",
        target_pool: str = "",
        reason: str = "",
        pool_sizes: Dict[str, int] | None = None,
    ) -> None:
        self.writer.writerow(
            [
                round(float(time_s), 6),
                event,
                job_id,
                cls,
                replica,
                slot,
                policy,
                action,
                source_pool,
                target_pool,
                reason,
                json.dumps(dict(sorted(pool_sizes.items()))) if pool_sizes else "",
                json.dumps(dict(sorted(active_total.items()))),
                json.dumps({str(k): dict(v) for k, v in sorted(active_by_class.items())}),
            ]
        )
        self.f.flush()

    def close(self) -> None:
        try:
            self.f.close()
        except Exception:
            pass
