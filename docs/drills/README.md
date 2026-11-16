# Chaos drills

One record per drill (infra spec, section 15): what was done, what was expected, what happened, what was fixed. Counted by the `drills` metric in `docs/SPEC.md` section 1.3.

| # | Drill | Date | Result |
| --- | --- | --- | --- |
| 1 | Kill `ingest` for an hour | not yet run | |
| [2](002-block-s3.md) | Block S3 for 10 minutes; confirm the spool drains | 2026-11-16 | Passed: spool drained 20 s after the block lifted; nothing lost |
