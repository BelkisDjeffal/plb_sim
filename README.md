# PLB query-level simulation

This repository contains simulation code for studying N-class differentiated routing algorithms for replicated databases under fixed capacity.

The current target priority order is:

Enterprise > Premium > Freemium

## Current research goal

The goal is to design and evaluate N-class differentiated routing algorithms.

This is not the old session-as-job Batsim model. The active simulator is query-level:

1. A session arrives with a priority class.
2. A scheduler selects a replica.
3. The session runs one Q1 query on the selected replica.
4. Q1 latency is sampled from BenchBase calibration using local Q1 concurrency at query start.

The next technical goal is to build an automatic scheduler campaign framework so that multiple N-class routing algorithms can be tested on the same scenarios and compared with decision metrics.

## Active code

query_sim/

Active query-level simulator.

scenario.py

Current scenario configuration used by the query-level simulator.

docs/

Project notes, commands, inventories, and cleanup status.

figures/selected/

Small set of selected figures worth inspecting.

data/calibration/

Local calibration inputs. Large calibration CSV files are not committed.

## Legacy code

legacy/session_job_batsim/

Old prototype where a BenchBase client/session was modeled as a Batsim job.

This model is kept for traceability, but it is not the current direction because it does not model SQL query latency.

The old Batsim platform, workload, and experiment configs are stored under:

legacy/session_job_batsim/config/

## Generated outputs

Generated outputs are not committed by default.

Ignored folders include:

outputs/
outputs_query/
results/
figures/diagnostics/
_cleanup_backup/



## Scheduler campaign

The campaign runner executes the same scenario family for several schedulers and writes standard metric tables.

```bash
PYTHONPATH=. python3 query_sim/campaigns/run_scheduler_campaign.py
```

The first baseline set is:

```text
round_robin
least_loaded
dedicated static partitions
```

The existing `plb_nclass` policy is kept as a current candidate, not as a baseline.

Main campaign outputs:

```text
outputs_query/scheduler_campaign/class_latency_metrics.csv
outputs_query/scheduler_campaign/class_concurrency_metrics.csv
outputs_query/scheduler_campaign/replica_composition_metrics.csv
outputs_query/scheduler_campaign/class_concentration_metrics.csv
outputs_query/scheduler_campaign/decision_metrics.csv
outputs_query/scheduler_campaign/baseline_comparison_metrics.csv
```

## Current workflow

Regenerate the current query-level terminal sweep:

    PYTHONPATH=. python3 query_sim/run_terminal_sweep.py
    python3 query_sim/plot_terminal_sweep.py
    python3 query_sim/plot_terminal_sweep_combined.py
    python3 query_sim/analyze_calibration_simulation_mapping.py

## Next planned structure

query_sim/schedulers/

Clean scheduler interface and scheduler implementations.

query_sim/campaigns/

Automatic campaign runners.

query_sim/analysis/

Decision-metric scripts.

query_sim/plots/

Final plotting scripts.

## Rule

For new N-class algorithm work, modify query_sim/ only.

Do not extend legacy/session_job_batsim/ unless intentionally revisiting the old Batsim prototype.
