# PLB simulation experiment plan

Each campaign changes one main dimension. Results from different questions are kept in separate output, figure, and notebook folders.

## 01 Algorithm variants

Question: Which algorithm design gives the best QoS tradeoff?

Fixed:
- K=8
- seed=42
- common T range
- four workload ratios

Main algorithms:
- N-class PLB
- target-repair v2
- target-repair v2 init 4-2-2
- target-repair v3
- target-repair v4

Status: existing results available.

Output:
`outputs_query/01_algorithm_variants/`

Figures:
`figures/selected/01_algorithm_variants/`

Notebook:
`notebooks/01_algorithm_variants.ipynb`

## 02 N-class calibration

Question: Is the original N-class PLB fairly calibrated?

Change:
- theta first

Keep fixed:
- alpha
- kappa
- initial pools
- K=8
- seed=42
- common workload settings

Start with:
- theta=5
- theta=10
- theta=20
- theta=40

After theta is understood, study alpha or kappa separately only if needed.

Output:
`outputs_query/02_nclass_calibration/`

Figures:
`figures/selected/02_nclass_calibration/`

Notebook:
`notebooks/02_nclass_calibration.ipynb`

## 03 Initial allocation

Question: How sensitive are serious candidates to the initial replica allocation?

Change:
- initial allocation only

Use a small set of meaningful allocations.

Output:
`outputs_query/03_initial_allocation/`

Figures:
`figures/selected/03_initial_allocation/`

Notebook:
`notebooks/03_initial_allocation.ipynb`

## 04 Cluster scaling

Question: Does behavior remain valid for smaller and larger clusters?

Change:
- K

Start with:
- K=4
- K=8
- K=16

Scale workload pressure and initial allocations with K.

Output:
`outputs_query/04_cluster_scaling/`

Figures:
`figures/selected/04_cluster_scaling/`

Notebook:
`notebooks/04_cluster_scaling.ipynb`

## 05 Workload ratios

Question: How robust are algorithms to different static class compositions?

Ratios:
- 1:1:1
- 3:1:1
- 1:3:1
- 1:1:3

Status: existing results available.

Output:
`outputs_query/05_workload_ratios/`

Figures:
`figures/selected/05_workload_ratios/`

Notebook:
`notebooks/05_workload_ratios.ipynb`

## 06 Adaptation and stability

Question: Is PLB adaptive without excessive role changes?

Use dynamic workloads with ratio changes during one run.

Metrics:
- number of replica role changes
- role changes per minute
- number of allocations visited
- fraction of time in dominant allocation
- back-and-forth role changes
- adaptation time after a workload change
- latency during adaptation

Compare:
- static partition
- Round Robin
- calibrated N-class PLB
- final target-repair candidates

This experiment is also the main place to study whether Mixed provides useful shared capacity.

Output:
`outputs_query/06_adaptation_stability/`

Figures:
`figures/selected/06_adaptation_stability/`

Notebook:
`notebooks/06_adaptation_stability.ipynb`

## 07 Final validation

Question: Are the final conclusions robust?

Only final candidates and important baselines.

Use:
- multiple seeds
- selected ratios
- selected K values
- selected load levels

Output:
`outputs_query/07_final_validation/`

Figures:
`figures/selected/07_final_validation/`

Notebook:
`notebooks/07_final_validation.ipynb`

## Plotting rule

All notebooks import `notebooks/plot_style.py`.

Detailed plots remain separated by experiment condition. Avoid combining algorithm, K, ratio, initialization, and parameter sweeps in one figure.

Use vector PDF for paper figures.
