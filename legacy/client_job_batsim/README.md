# Legacy client-job Batsim prototype

This folder documents the first simulation model.

Old model:

BenchBase Worker / JDBC session = Batsim job.
Worker lifetime = job duration.
Scheduler = routing policy.

This model was useful to test session-level routing and PLB state transitions, but it does not model SQL query latency.

The current paper direction uses the query-level simulator in query_sim/.
