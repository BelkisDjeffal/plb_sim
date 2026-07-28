# Current commands

## Active simulator

The active simulator is:

query_sim/

The old session-job Batsim prototype is archived in:

legacy/session_job_batsim/

## Regenerate current query-level terminal sweep

cd /home/spirals/phd/experiments/plb_batsim

PYTHONPATH=. python3 query_sim/run_terminal_sweep.py
python3 query_sim/plot_terminal_sweep.py
python3 query_sim/plot_terminal_sweep_combined.py
python3 query_sim/analyze_calibration_simulation_mapping.py

## Current important outputs

outputs_query/terminal_sweep/no_fault_3_classes/terminal_sweep_latency_metrics.csv
outputs_query/terminal_sweep/no_fault_3_classes/terminal_sweep_concurrency_metrics.csv

## Current selected figures

ls -lh figures/selected/current_query_level

## Next technical objective

Build an automatic scheduler campaign framework:

query_sim/schedulers/
query_sim/campaigns/run_scheduler_campaign.py
query_sim/analysis/analyze_scheduler_campaign.py
query_sim/plots/plot_scheduler_campaign.py

Goal:

Test many N-class differentiated routing algorithms automatically, repeat the same scenarios for each scheduler, compute decision metrics, and rank algorithms.

## Scheduler campaign pipeline

Run the current automatic scheduler campaign:

```bash
cd /home/spirals/phd/experiments/plb_batsim
PYTHONPATH=. python3 query_sim/campaigns/run_scheduler_campaign.py
```

Main generated tables:

```text
outputs_query/scheduler_campaign/class_latency_metrics.csv
outputs_query/scheduler_campaign/class_concurrency_metrics.csv
outputs_query/scheduler_campaign/replica_composition_metrics.csv
outputs_query/scheduler_campaign/class_concentration_metrics.csv
outputs_query/scheduler_campaign/decision_metrics.csv
outputs_query/scheduler_campaign/baseline_comparison_metrics.csv
```

Current baseline schedulers:

```text
round_robin
least_loaded
dedicated static partitions
```
