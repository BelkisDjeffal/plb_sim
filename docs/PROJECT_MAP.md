# PLB simulation project map

## Current goal

Find and evaluate N-class differentiated routing algorithms for replicated databases under fixed capacity.

Current target classes:

Enterprise > Premium > Freemium

## Current simulator

The current simulator is query-level.

1. A session arrives with a priority class.
2. A scheduler selects a replica.
3. The session runs one Q1 query on that replica.
4. Q1 latency is sampled from BenchBase calibration using local Q1 concurrency at query start.

## Important distinction

### Legacy client-job Batsim prototype

Old model:

BenchBase client/session = Batsim job.
Job duration = session lifetime.

This was useful for learning Batsim and testing routing state, but it does not model SQL query latency.

### Current query-level simulator

Current model:

Session admission = scheduler decision.
Query execution = sampled Q1 latency from calibration.

This is the current direction for algorithm selection.

## Rules

Scripts are the source of truth.

Notebooks are only for exploration and interpretation.

Plots are never the source of truth. Every paper plot must come from a CSV in results/ or outputs_query/.

## Naming convention

run_*.py:
  runs simulations.

analyze_*.py:
  converts raw outputs into clean CSV metrics.

plot_*.py:
  reads clean CSV metrics and generates figures.

select_*.py:
  copies only useful figures into figures/selected.

## Main campaign objective

Run the same scenario for many schedulers and compare them using decision metrics.

Schedulers to test:

- round_robin
- least_loaded
- static_partition_nclass
- pool_borrowing_nclass
- cost_function_nclass
- weighted_least_loaded

## Main metrics

Per class:

- p50 latency
- p95 latency
- p99 latency
- mean local Q1 concurrency at start
- p95 local Q1 concurrency at start
- max local Q1 concurrency

Derived metrics:

- Enterprise gain vs RR
- Premium gain vs RR
- Freemium cost vs RR
- priority ordering violations
- bounded Freemium degradation
- load concentration
- calibration support coverage
