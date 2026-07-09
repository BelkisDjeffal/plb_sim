# PLB/Batsim starter prototype

This folder is the first simulation brick.

Frozen model for now:

```text
BenchBase Worker / JDBC session = Batsim job
worker arrival time             = job.subtime
worker lifetime                 = job delay profile
worker priority                 = job class
PostgreSQL replica              = Batsim machine/resource
scheduler                       = routing policy
```

Do not implement PLB first. First make round-robin run end-to-end.

## Files

```text
scenario.py                 one source of truth for parameters
generate_workload.py         creates Batsim workload JSON
generate_platform.py         creates SimGrid/Batsim platform XML
validate_workload.py         checks generated workload before Batsim
run_one.py                   runs one scheduler/repetition
run_all.py                   runs all repetitions from scenario.py
analyze.py                   reads Batsim jobs.csv and scheduler logs
schedulers/round_robin.py    first baseline scheduler
schedulers/least_loaded.py   optional second baseline, later
```

## Important meanings

`repetitions` does not change the seed.

```text
seed        = controls generated workload
repetition  = rerun same config and same workload
```


## Workload parameters in scenario.py

```python
"duration_s": 360
```
The time window over which BenchBase-like workers are spawned.

```python
"total_workers": 600
```
Total number of workers/sessions to generate.

```python
"classes": ["enterprise", "premium", "freemium"]
"class_counts": [150, 150, 300]
```
Exact number of workers per priority class.

```python
"arrival_model": "poisson"
```
Workers arrive with exponential inter-arrival times.
The rate is:

```text
lambda = total_workers / duration_s
```

For the current scenario:

```text
lambda = 600 / 360 = 1.666 workers/second
```

```python
"lifetime": {"type": "uniform", "min_s": 10, "max_s": 30}
```
Each worker lives between 10 and 30 seconds, like the current Java Worker model.

```python
"profile_type": "delay"
```
First prototype uses Batsim delay profiles. This tests arrivals, lifetimes, class labels, scheduling, and logs. It does not model SQL query latency or CPU contention yet.

## Quick start

From this folder:

```bash
python3 generate_workload.py
python3 validate_workload.py
python3 generate_platform.py
```

Expected validation:

```text
jobs: 600
class counts: {'enterprise': 150, 'premium': 150, 'freemium': 300}
nb_res: 5
OK: workload is valid.
```

Then run round-robin:

```bash
python3 run_one.py --scheduler round_robin --rep 1
```

Analyze:

```bash
python3 analyze.py --outdir outputs/no_fault_3_classes/rep_01/round_robin
```

Run all repetitions listed in `scenario.py`:

```bash
python3 run_all.py
```

## If run_one.py fails

First check the logs:

```bash
cat outputs/no_fault_3_classes/rep_01/round_robin/batsim.log
cat outputs/no_fault_3_classes/rep_01/round_robin/scheduler.log
```

If the endpoint is the issue, run manually in two terminals.

Terminal 1:

```bash
batsim \
  -p platforms/platform_5.xml \
  -w workloads/no_fault_3_classes.json \
  -e outputs/no_fault_3_classes/manual_rr/out_ \
  -s tcp://*:28000
```

Terminal 2:

```bash
PLB_SCHED_LOG=outputs/no_fault_3_classes/manual_rr/scheduler_decisions.csv \
pybatsim schedulers/round_robin.py
```

Then analyze:

```bash
python3 analyze.py --outdir outputs/no_fault_3_classes/manual_rr
```

## What to do today

1. Generate workload.
2. Validate workload.
3. Generate platform.
4. Run round-robin once.
5. If it fails, send `batsim.log` and `scheduler.log`.
6. When round-robin works, run repetition 1 and repetition 2.
7. Only after that, add least-loaded.

Do not add PLB until this pipeline works.
