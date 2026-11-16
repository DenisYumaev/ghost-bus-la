# Ideas

New ideas that aren't in the plan (CLAUDE.md hard rule 14). Each one needs a measured problem and a slot in a milestone before it's built.

| Idea | Why | Source | Status |
| --- | --- | --- | --- |
| Alert on sustained S3 upload errors (for example, every upload round failing for 15 minutes) | Without it, an S3 outage stays silent until the spool disk fills and snapshots start being lost | Drill 2, `docs/drills/002-block-s3.md` | Candidate; consider with M5's observability work |
