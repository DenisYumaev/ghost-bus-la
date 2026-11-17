# Drill 1: stop `ingest` for an hour

- **Date:** 2026-11-17 01:31:40–02:31:39 UTC (2026-11-16 17:31–18:31 in Los Angeles, during evening service; the owner chose to run it watched rather than overnight)
- **Milestone:** M0 acceptance criterion 2 (`docs/SPEC.md` M0: "killing the container for an hour shows up as a gap in the fetch log and the heartbeat alert fires"); infra spec section 15, drill 1
- **Image:** `7da9646`
- **Cost:** one hour of archive, 120 vehicle-position and 60 trip-update cuts, permanently missing. That was expected and accepted before the drill.

## What was done

On the VM, through SSM Run Command:

1. Scheduled the restart first: `systemd-run --unit=drill1-undo --on-active=3600 --timer-property=AccuracySec=1s`, running `docker compose … start ingest`, so ingest would come back even if this session dropped. (Drill 2's timer fired 11 s late at the default one-minute accuracy; `AccuracySec=1s` fixed that.)
2. `docker compose … stop ingest` at 01:31:38.5. The container finished at 01:31:40.3 (exit code 0, last log line `service_stop`). The restart policy `always` doesn't restart a container stopped by hand.
3. Watched for the Healthchecks.io email, then checked the restart, the fetch log and objects in S3, and the spool.

**This was a graceful stop (SIGTERM), not a hard kill.** The service made its final cuts and uploaded them before exiting. The criterion's observable result (a gap and the alert) doesn't depend on how the process dies, but the crash path, a SIGKILL that leaves spool files and an open fetch-log hour behind for the next start, was **not** exercised here. Recovery of leftover spool files at startup is covered by unit tests, not by a drill.

## What was expected

- The heartbeat stops, and `ingest_heartbeat_missed` emails the owner.
- The fetch log shows no attempts for the hour: a visible gap. Downstream, that gap makes those windows feed-unhealthy, so trips that overlap it are classified `unknown`, not `missed` (pipeline spec, sections 2.5 and 8). The M1 models that do this don't exist yet, so that part is still to be shown.
- On restart the streams resume on the next cut boundary, the heartbeat recovers, and nothing captured before the stop is lost.

## What happened

| | Result |
| --- | --- |
| Final cuts on shutdown | 01:31:38.7, both feeds, `written`, not partial. Both objects confirmed in bronze (76.5 KB vehicle positions, 427 KB trip updates), uploaded by the shutdown pass at 01:31:39.3 (the fetch log's `upload` events) |
| **DOWN email** | Received **01:35:41 UTC**, about 4 minutes after the stop (01:31:40.3): "success signal did not arrive on time, grace time passed … Last Ping 4 minutes". The receive time includes Healthchecks' alert cycle and mail delivery |
| Fetch-log events from 01:31:40 to 02:31:38 | **0** of any kind: the gap is visible |
| Restart timer fired | 02:31:38.96 (journal); container started 02:31:39.1 |
| `service_start` | 02:31:41; the startup GTFS download found no change (`duplicate`) |
| First cuts after the restart | 02:32:00, both feeds, `written` |
| **UP email** | Received **02:32:02 UTC**, 2 s after the first cut; Healthchecks counted 56 min 21 s of downtime (measured from the DOWN alert) |
| Cuts 02:32:00–02:59:30 | 56 vehicle positions and 28 trip updates, all `written`; their timestamps match the 30 s and 60 s grid exactly, one per interval, none missing or duplicated |
| Container after restart | `healthy`, 0 restarts; spool pending 0 at about 03:21 (a rough shell count of files without `.uploaded` markers) |

## What was fixed

- **The documented alert delay was wrong.** The runbook and the infra spec said "no ping for 3 minutes". Healthchecks.io waits one period (1 minute) and then the grace time (3 minutes), so the email arrives about 4 minutes after the last ping. Both documents now say so.

Nothing in the code needed changing. Both M0 acceptance criteria are now met (criterion 1: `docs/research/measured-day-2026-11-14.md`).

**Not tested:** a hard kill (see above). **Noted, not changed:** a container stopped by hand stays stopped; `restart: always` covers crashes and reboots, not a manual stop. That's intended (a stop is a decision); the heartbeat email is the safeguard against a mistaken one.
