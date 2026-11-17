# Ideas

New ideas that aren't in the plan (CLAUDE.md hard rule 14). Each one needs a measured problem and a slot in a milestone before it's built.

| Idea | Why | Source | Status |
| --- | --- | --- | --- |
| Alert on sustained S3 upload errors (for example, every upload round failing for 15 minutes) | Without it, an S3 outage stays silent until the spool disk fills and snapshots start being lost | Drill 2, `docs/drills/002-block-s3.md` | Candidate; consider with M5's observability work |
| Give the detector the same duplicate-report rule as `stg_trip_reports` (newest report per trip by report time) | Otherwise alerts and site counts can disagree on whether a trip is canceled | Review of PR #33 | Required when the detector is built (M3) |
| Make `dim_stop_times` and `dim_trips` incremental (insert only new `schedule_version`s) | Weekly `calendar_dates` versions repeat ~2.1M stop times each; a full rebuild grows to ~110M rows a year | SQL review of PR #32 | Candidate; when dbt runs nightly (M4) |
