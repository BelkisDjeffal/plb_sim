# Repository structure

## Active code

query_sim/

This is the active query-level simulator.

The model is:

1. A session arrives with a priority class.
2. A scheduler selects a replica.
3. The session runs one Q1 query on the selected replica.
4. Q1 latency is sampled from BenchBase calibration using local Q1 concurrency at query start.

Important files:

query_sim/latency_model.py
  Loads and samples the Q1 calibration model.

query_sim/policies.py
  Current routing policies used by the query-level simulator.

query_sim/run_query_simulation.py
  Runs one query-level simulation.

query_sim/run_all_query_simulations.py
  Runs the current set of policies.

query_sim/run_terminal_sweep.py
  Runs the current terminal-pressure sweep.

query_sim/schedulers/
  Target location for the cleaned scheduler interface.

query_sim/campaigns/
  Target location for automatic scheduler campaigns.

query_sim/analysis/
  Target location for decision-metric scripts.

query_sim/plots/
  Target location for final plotting scripts.

## Legacy code

legacy/session_job_batsim/

This contains the old Batsim prototype where one session/client was modeled as one Batsim job.

This code is kept for traceability but is not the current direction.

## Generated outputs

outputs_query/

Generated simulation results. Not committed by default.

figures/diagnostics/

Archived or diagnostic figures. Not committed by default.

figures/selected/

Small set of selected figures useful for meetings or papers.

## Documentation

docs/

Project map, commands, inventory, and cleanup notes.

## Main rule

For the new N-class algorithm campaign, modify query_sim/ only.

Do not modify legacy/session_job_batsim/ unless intentionally revisiting the old Batsim model.
