# Drill 2: block S3 for 10 minutes; confirm the spool drains

- **Date:** 2026-11-16, 06:40:35–06:50:35 UTC
- **Milestone:** M0 (`docs/SPEC.md` M0 chaos drill; infra spec section 15, drill 2)
- **Image:** `7da9646`

## What was done

On the VM, through SSM Run Command:

1. Scheduled the undo first: `systemd-run --on-active=600` removing the rules, so the block could not outlive 10 minutes even if this session dropped.
2. Added 10 rules to Docker's `DOCKER-USER` chain: `REJECT` TCP 443 to each CIDR in the AWS-managed prefix list `com.amazonaws.us-west-2.s3` (`pl-68a54001`). `DOCKER-USER` filters container traffic only, so the SSM agent and the instance metadata service were unaffected.
3. Watched the fetch log and the spool from inside the container; the timer removed the rules at 06:50:35.

## What was expected

- Uploads fail; snapshots keep landing in the spool; the streams and the health check are unaffected.
- After the block lifts, the uploader's backoff retries, every queued snapshot uploads, and the spool's pending count returns to zero. Nothing is lost.

## What happened

From the container's fetch log, events at or after 06:40 UTC (checked 06:52:12):

| | Result |
| --- | --- |
| First upload error | 06:41:02.544, `EndpointConnectionError` |
| Upload errors during the block | 17 (one per backoff round, spaced up to 60 s) |
| Last upload error | 06:49:55.506 |
| First successful upload after the block | 06:50:55.524, 20 s after the rules were removed |
| Snapshots pending at 06:43 | 8 (5 vehicle positions, 3 trip updates) |
| Snapshots pending at 06:52 | **0** |
| Stream cuts since 06:40 | 38, all written to the spool (0 failed) |
| Container health / restarts | `healthy` throughout / 0 |
| Reject rules after the timer | 0 |

The heartbeat kept pinging during the block, which is correct: it reports stream health, and the streams were healthy. An S3 outage shows up as `upload` errors in the fetch log, not as a missed heartbeat.

## What was fixed

Nothing; the spool-then-upload design behaved as specified (pipeline spec section 2.4; ADR-004). One gap noted for M5's observability work: a long S3 outage would raise no alert by itself until the spool fills. The infra spec already plans an alert at 70% spool disk usage (pipeline spec section 2.6); an alert on sustained upload errors would catch it sooner.
