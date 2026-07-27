# Cleanup status

## Current state

The repository now separates documentation, selected figures, diagnostic figures, query-level simulation code, and legacy Batsim/session-job code.

## Current selected figures

- figures/selected/current_query_level/ONEPNG_p50_latency_and_mean_concurrency_by_priority.png
- figures/selected/current_query_level/ONEPNG_p95_latency_and_p95_concurrency_by_priority.png
- figures/selected/current_query_level/ONEPNG_latency_p50_by_priority.png
- figures/selected/current_query_level/ONEPNG_latency_p95_by_priority.png
- figures/selected/current_query_level/ONEPNG_concurrency_mean_by_priority.png
- figures/selected/current_query_level/ONEPNG_concurrency_p95_by_priority.png
- figures/selected/current_query_level/01_terminal_pressure_to_local_q1_concurrency_mean.png
- figures/selected/current_query_level/02_terminal_pressure_to_local_q1_concurrency_p95.png
- figures/selected/current_query_level/03_calibration_curve_with_simulation_points_T240.png
- figures/selected/current_query_level/03_calibration_curve_with_simulation_points_T300.png
- figures/selected/current_query_level/03_calibration_curve_with_simulation_points_T360.png
- figures/selected/current_query_level/03_calibration_curve_with_simulation_points_T400.png
- figures/selected/current_query_level/03_calibration_curve_with_simulation_points_T480.png
- figures/selected/current_query_level/03_calibration_curve_with_simulation_points_T600.png

## Missing expected figures

- none

## Interpretation

The current source of truth is the query-level simulator under query_sim/.
The old Batsim/session-job prototype should be treated as legacy and should not be extended for the next campaign.
The next technical goal is to create an automatic scheduler campaign framework.

## Do not move yet

Do not move root scripts or the old schedulers directory yet. Some imports may still depend on the current layout.
Move code only after the scheduler campaign runs successfully.
