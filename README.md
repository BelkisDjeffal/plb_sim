# PLB Query-Level Simulation

This repository contains a query-level simulation framework for evaluating differentiated routing and resource-allocation strategies in replicated database services with fixed capacity.

The current model supports three service classes:

**Enterprise > Premium > Freemium**

## Simulation Model

For each arriving session:

1. A service class is assigned.
2. A scheduler selects a database replica.
3. The session executes a Q1 query on the selected replica.
4. Query latency is sampled from BenchBase calibration data according to the local query concurrency observed at execution time.

The simulator is used to compare routing and replica-allocation strategies under controlled workload scenarios.

## Repository Structure

`query_sim/`
Query-level simulator, scheduling logic and experiment scripts.

`scenario.py`
Scenario and workload configuration.

`data/calibration/`
Calibration inputs derived from PostgreSQL experiments.

`figures/selected/`
Selected simulation results and visualizations.

`legacy/`
Previous simulation prototypes retained for traceability.

## Running the Current Experiments

```bash
PYTHONPATH=. python3 query_sim/run_terminal_sweep.py
python3 query_sim/plot_terminal_sweep.py
python3 query_sim/plot_terminal_sweep_combined.py
python3 query_sim/analyze_calibration_simulation_mapping.py
```

## Current Development

Current work focuses on a scheduler campaign framework for evaluating multiple N-user-class routing algorithms under common scenarios and comparing them using consistent performance and allocation metrics.
