# Query-level Q1 simulation

This keeps routing at session level and changes execution to query level.

One simulated session is assigned to one replica by the selected policy. In this first version, the session runs one Q1 query. The query duration is sampled from the empirical Q1 latency observations according to the number of active queries already running on the chosen replica.

Main files:

- `query_sim/latency_model.py`: empirical exact-load sampler with local fallback.
- `query_sim/policies.py`: session-level RR, LL, and PLB policies without Batsim.
- `query_sim/run_query_simulation.py`: runs one policy.
- `query_sim/run_all_query_simulations.py`: runs all policies from `scenario.py`.
- `query_sim/plot_query_results.py`: creates first comparison plots.

Required calibration input:

```text
data/calibration/q1_query_observations.csv
```

Run:

```bash
python3 query_sim/run_all_query_simulations.py
python3 query_sim/plot_query_results.py
```

Outputs:

```text
outputs_query/<scenario>/<policy>/query_events.csv
outputs_query/<scenario>/<policy>/metrics_by_class.csv
outputs_query/<scenario>/<policy>/session_placements.csv
outputs_query/<scenario>/<policy>/active_queries_timeseries.csv
outputs_query/<scenario>/comparison_metrics_by_class.csv
outputs_query/<scenario>/plots/*.png
```

Definitions:

`in_flight_at_start` is the number of other queries already running on the selected replica when the new query starts.

`in_flight_at_end` is the number of other queries still running on the selected replica when this query finishes.
