# Legacy session-job Batsim prototype

This folder contains the first simulation prototype.

Old model:

BenchBase client/session = Batsim job.
Job duration = session lifetime.
Batsim scheduler = routing policy.

This model was useful for learning Batsim and testing session-level routing state, but it is not the current research direction because it does not model SQL query latency.

The current direction is the query-level simulator in query_sim/.

Do not extend this folder for the N-class scheduler campaign unless there is a specific reason to revisit Batsim.
