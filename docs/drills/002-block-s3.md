# Drill 2: block S3 for 10 minutes; confirm the spool drains

- **Date:** 2026-11-16, 06:40:35–06:50:46 UTC (block in place about 10 min 11 s)
- **Milestone:** M0 (`docs/SPEC.md` M0 chaos drill; infra spec section 15, drill 2)
- **Image:** `7da9646`

## What was done

On the VM, through SSM Run Command:

1. Scheduled the undo first: `systemd-run --on-active=600` removing the rules, so the block would lift even if this session dropped. (It fired 11 s late, at 06:50:46.58 per its journal: systemd timers default to one-minute accuracy.)
2. Added 10 rules to Docker's `DOCKER-USER` chain (the command output counted 10): `REJECT` TCP 443 to each CIDR in the AWS-managed prefix list `com.amazonaws.us-west-2.s3` (`pl-68a54001`). The rules were confirmed in place at 06:40:35. `DOCKER-USER` sees only forwarded (container) traffic, so the host's SSM agent was unaffected. The container's own calls to the instance metadata service for credentials do pass through it, but 169.254.169.254 isn't in the S3 prefix list, so they weren't blocked either.
3. Watched the fetch log and the spool from inside the container.

## What was expected

- Uploads fail; snapshots keep landing in the spool; the streams and the health check are unaffected.
- After the block lifts, the uploader's backoff retries, every queued snapshot uploads, and the spool's pending count returns to zero. Nothing is lost.

## What happened

From the container's fetch log, events at or after 06:40 UTC (checked 06:52:12):

| | Result |
| --- | --- |
| First upload error | 06:41:02.544, `EndpointConnectionError` |
| Upload errors during the block | 17, one per uploader round (a round stops at its first error); 16 gaps over 533 s, the last one 60 s, as the backoff climbs 1, 2, 4, … to its 60 s cap |
| Last upload error | 06:49:55.506 |
| Rules removed | 06:50:46.58 (undo unit's journal) |
| First successful upload after the block | 06:50:55.524: the uploader's next retry, 9 s after removal. That gap reflects where the backoff sleep happened to be, not a recovery time |
| Snapshots pending at 06:43 | 8 (5 vehicle positions, 3 trip updates) |
| Snapshots pending at 06:52:12 | **0** (first check after the block; the fetch log can't show the exact moment the last file landed, because a round logs its start time on every line) |
| Stream cuts since 06:40 | 38, all written to the spool (0 failed) |
| Container health / restarts | `healthy` throughout / 0 |
| Reject rules after the timer | 0 |

The container logged no `heartbeat_failed` lines from 06:39 to 06:53, so the heartbeat kept pinging. That's correct by design: it reports stream health (spool writes), and the streams were healthy. Healthchecks.io isn't in the S3 prefix list. An S3 outage shows up as `upload` errors in the fetch log, not as a missed heartbeat.

## What was fixed

Nothing; the spool-then-upload design behaved as specified (pipeline spec section 2.4; ADR-004).

**Gap, noted, not fixed:** a long S3 outage raises no alert of its own today. It would surface only when the spool disk fills: cuts become `spool_error`, `/healthz` turns unhealthy after three intervals, the heartbeat stops, and `ingest_heartbeat_missed` fires, by which time new snapshots are being lost. The planned `spool_disk_high` alert at 70% (infra spec section 9; pipeline spec section 2.6) isn't built yet; it's M5 work. An alert on sustained upload errors would catch it sooner; that's recorded as a candidate in `docs/ideas.md`, not planned (hard rule 14).
