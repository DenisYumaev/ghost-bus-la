# Chaos drills

One record per drill (infra spec, section 15): what was done, what was expected, what happened, what was fixed. Counted by the `drills` metric in `docs/SPEC.md` section 1.3.

| # | Drill | Date | Result |
| --- | --- | --- | --- |
| [1](001-kill-ingest.md) | Kill `ingest` for an hour | 2026-11-17 | Passed: DOWN email about 4 min after a graceful stop, zero fetch-log events for the hour, cuts resumed at the next boundary, UP email 2 s after the first cut. Hard kill not exercised |
| [2](002-block-s3.md) | Block S3 for 10 minutes; confirm the spool drains | 2026-11-16 | Passed: 38 snapshots kept spooling, uploads resumed on the first retry after the block, pending 0 by the next check; nothing lost |
| [3](003-rerun-day.md) | Run the same day twice; outputs must be identical | 2026-11-17 | Passed: re-compacting and re-decoding UTC days 2026-11-14 to 16 from bronze (the full input of service date Nov 15) and rebuilding gave identical fingerprints for all 31 warehouse tables and views (290,086,638 rows); a plain dbt rebuild was identical too |
