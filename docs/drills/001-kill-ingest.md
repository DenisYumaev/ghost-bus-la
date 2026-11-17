# Drill 1: kill `ingest` for an hour

- **Date:** 2026-11-17 01:31:40–02:31:39 UTC (2026-11-16 17:31–18:31 in Los Angeles, during evening service; the owner chose to run it watched rather than overnight)
- **Milestone:** M0 acceptance criterion 2 (`docs/SPEC.md` M0: "killing the container for an hour shows up as a gap in the fetch log and the heartbeat alert fires"); infra spec section 15, drill 1
- **Image:** `7da9646`
- **Cost:** one hour of archive, about 120 vehicle-position and 60 trip-update cuts, permanently missing. That was expected and accepted before the drill.

## What was done

On the VM, through SSM Run Command:

1. Scheduled the restart first: `systemd-run --unit=drill1-undo --on-active=3600 --timer-property=AccuracySec=1s`, running `docker compose … start ingest`, so ingest would come back even if this session dropped. (Drill 2's timer fired 11 s late at the default one-minute accuracy; `AccuracySec=1s` fixed that.)
2. `docker compose … stop ingest` at 01:31:38.5; the container reported stopped at 01:31:40.6 (exit code 0, last log line `service_stop`). The restart policy `always` doesn't restart a container stopped by hand.
3. Watched for the Healthchecks.io email, then checked the restart, the fetch log in S3, and the spool.

## What was expected

- The heartbeat stops, and `ingest_heartbeat_missed` emails the owner.
- The fetch log shows no attempts for the hour: a visible gap, so those minutes become `unknown`, never `missed` (pipeline spec, section 2.5).
- On restart the streams resume on the next cut boundary, the heartbeat recovers, and nothing captured before the stop is lost.

## What happened

| | Result |
| --- | --- |
| Last cuts before the stop | 01:31:38.7, both feeds: the final cut on SIGTERM (clean shutdown makes a final cut) |
| Fetch-log hour 01 uploaded | 01:31:41, by the uploader's final pass on shutdown |
| **DOWN email** | **01:35:41 UTC**, 4 min 1 s after the stop: "success signal did not arrive on time, grace time passed … Last Ping 4 minutes" |
| Fetch-log events from 01:31:40 to 02:31:38 | **0** of any kind: the gap is visible |
| Restart timer fired | 02:31:38.96 (journal); container started 02:31:39.1 |
| `service_start` | 02:31:41; the startup GTFS download found no change (`duplicate`) |
| First cuts after the restart | 02:32:00, both feeds, `written` |
| **UP email** | **02:32:02 UTC**, 2 s after the first cut; Healthchecks counted 56 min 21 s of downtime (from the DOWN alert) |
| Cuts 02:32:00–02:59:30 | 56 vehicle positions and 28 trip updates, all `written`: exactly one per scheduled interval |
| Container after restart | `healthy`, 0 restarts; spool pending 0 at 03:21 |

## What was fixed

- **The documented alert delay was wrong.** The runbook and the infra spec said "no ping for 3 minutes". Healthchecks.io waits one period (1 minute) and then the grace time (3 minutes), so the email came about 4 minutes after the last ping. Both documents now say so.

Nothing in the code needed changing. Both M0 acceptance criteria are now met (criterion 1: `docs/research/measured-day-2026-11-14.md`).

**Gap, noted, not fixed:** a container that's stopped stays stopped until someone starts it. `restart: always` covers crashes and reboots, not a manual stop. That's intended (a stop is a decision), but it means a mistaken `docker compose stop` would cost data until the heartbeat email is acted on. The email is the safeguard; no change.
