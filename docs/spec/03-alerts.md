# 03 · Alert engine

The hot path: from a new cancellation in Metro's feed to an email in a rider's inbox. This is the strongest software-engineering story in the project, so it is specified tightly.

## 1. Goals

| Goal | Target |
| --- | --- |
| **Never duplicate:** one alert per commute per canceled trip, under any crash, retry, or replay | Zero duplicates; proven by tests |
| **Never silently drop:** every match becomes `sent`, `suppressed` (with a reason), or `dead` (and pages the owner) | No row stays `pending` or `failed` past 15 minutes |
| **Fast:** p95 of `sent_at − first_seen_at` | ≤ 120 s |
| **Honest:** say what Metro announced, when, and where the data comes from | Every email |

Latency is measured from when this system first saw the cancellation in a snapshot. Trip-update snapshots are cut every 60 seconds, so a cancellation can be up to a minute old when first seen, plus whatever delay Metro's own systems add. Say so on the method page.

## 2. Services

- **`detector`**: turns cancellation snapshots into events and outbox rows. One instance.
- **`alert-worker`**: delivers outbox rows. Written so that several instances could run safely, even though one is enough.

Both use Postgres only. No message broker (ADR-008).

## 3. Detection

### 3.1 Input

`detector` watches the spool directory for new `trip_updates` snapshot files (written atomically by `ingest`). Announced cancellations are the trips in a snapshot whose `scheduleRelationship` is `CANCELED`; Metro's separate canceled-service API is dead (`docs/research/day1-probe.md`). It processes them in filename order and stores its position in `ops.consumer_cursor`. On restart it resumes after the last committed file. If the spool has been cleaned past the cursor, it catches up from S3.

It never calls Metro itself. This keeps one source of truth for what was fetched and makes every run replayable.

### 3.2 Stable key

`source_key` is the stream's `tripId`, and `service_date` is its `startDate`. Together they identify one run of one trip and stay the same across snapshots. `source` is `trip_update`. Write a test that proves two snapshots of the same cancellation produce one event.

### 3.3 Diff, per snapshot

For each trip in the snapshot marked `CANCELED`:

1. Compute `source_key` and `service_date`.
2. Upsert into `app.cancellation_event` on `(source, source_key, service_date)`: insert with `first_seen_at = fetched_at`, or update `last_seen_at`.
3. If the row was inserted (a new event), run matching (section 4) **in the same transaction**.

Then, for open events:

4. If the trip is back to `SCHEDULED` in this snapshot, or has left the stream, and its scheduled start is still ahead, set `withdrawn_at` (the cancellation was pulled; P1 sends a "may be running again" follow-up).
5. If the trip's scheduled end has passed, close the event. Canceled entries stay in the stream for hours after the trip's time, so events close by time, never by absence.

On its first run the detector sees cancellations that were announced before it started. It records them as events with `first_seen_at` set to that snapshot, and the `too_late` rule keeps stale ones from being sent.

Commit the event upserts, the outbox inserts, and the cursor advance in **one transaction per snapshot**. A crash anywhere means the whole snapshot is redone, and the unique keys make the redo harmless.

### 3.4 Fail closed

If a snapshot fails to parse, or its schema fingerprint isn't approved, the detector does not guess. It leaves the cursor where it is, raises a `detector_blocked` alert, and retries the same file every minute. Raw data keeps landing through `ingest` regardless. A snapshot logged as partial is never used to withdraw events, so a dropped connection isn't read as "everything was reinstated".

## 4. Matching events to commutes

A commute matches an event when the canceled trip is scheduled to depart the commute's stop, on one of the commute's days, inside the commute's time window.

- Resolve the trip's departure time at the rider's stop from `serving.trip_stop_time` for the schedule version in force. Convert with the service-date rule (pipeline spec, section 5) to a UTC timestamp, then to local calendar date and time in `America/Los_Angeles`.
- Compare **local calendar day and time at the rider's stop**, not the service date. A trip at 25:10 on Friday's service date departs at 01:10 on Saturday, and matches a Saturday commute.
- Trip IDs in the stream matched the schedule exactly in the probe, so matching is by `trip_id`. If a canceled trip's ID isn't in the schedule version in force, don't guess: record the event, send no alert, and count it in `cancellation_events_unmatched`. A rising count usually means a new schedule version hasn't been loaded.

Sketch (the owner writes the real query; see learning spec):

```sql
insert into app.alert_outbox
  (user_id, commute_id, cancellation_event_id, alert_type, dedupe_key, stop_departure_at, payload)
select c.user_id, c.id, :event_id, 'announced_cancellation',
       c.id || ':' || :event_id || ':announced_cancellation',
       st.departure_utc,
       jsonb_build_object(...)
from app.commute c
join serving.trip_stop_time st
  on st.schedule_version = :version and st.trip_id = :trip_id and st.stop_id = c.stop_id
where c.active
  and c.line = :line and c.direction_id = :direction_id
  and (extract(isodow from st.departure_utc at time zone 'America/Los_Angeles')::int - 1) = any (c.days_of_week)
  and (st.departure_utc at time zone 'America/Los_Angeles')::time between c.window_start and c.window_end
on conflict (dedupe_key) do nothing;
```

**The reverse direction:** when a rider creates or edits a commute, match it against all open events in the same transaction, so a cancellation announced an hour ago still produces an alert.

## 5. Delivery

### 5.1 State machine

```text
pending ──claim──► sending ──ok──► sent
   ▲                  │
   │                  ├─ transient error ─► failed ──(backoff)──► claimed again
   │                  └─ permanent error or 6th attempt ─► dead   (pages the owner)
   └─ suppressed (decided at claim time, with a reason)
```

### 5.2 Claiming work

```sql
select id from app.alert_outbox
where status in ('pending', 'failed') and next_attempt_at <= now()
order by stop_departure_at
limit 20
for update skip locked;
```

`SKIP LOCKED` lets several workers pull different rows without blocking each other. Order by departure time so the most urgent alerts go first. Mark claimed rows `sending` and commit before calling the email provider, so no database transaction is held open across a network call.

A sweeper returns rows stuck in `sending` for more than 2 minutes to `failed`. That covers a worker that died mid-send.

### 5.3 Suppression, checked at claim time

| Reason | Rule |
| --- | --- |
| `too_late` | Now is more than 2 minutes past `stop_departure_at` |
| `commute_inactive` | The commute was paused or deleted |
| `withdrawn` | The event was withdrawn before sending |
| `user_rate_limit` | More than 20 alerts to this user today (protects against a feed glitch) |

Suppressed rows are kept. The share suppressed as `too_late` is a product metric: how often Metro's announcement arrives too late to act on.

### 5.4 Sending

- One provider behind an interface: `EmailProvider.send(message, idempotency_key) -> message_id`. Ship one real adapter and a file-writing adapter for local development and tests.
- Pass `dedupe_key` as the provider's idempotency key if it supports one (`VERIFY`). If a worker crashes after the provider accepts the email but before the row is marked `sent`, the retry is then absorbed by the provider. If the provider has no such feature, the residual risk is one duplicate email in that narrow crash window; state it in the ADR.
- Retry schedule for transient failures (timeouts, 429, 5xx): 15 s, 60 s, 4 min, 15 min, 1 h. Then `dead`.
- Permanent failures (invalid address, hard bounce): `dead` at once, and pause the user's commutes after two hard bounces.

**Delivery semantics, stated plainly:** at-least-once from detector to provider, made effectively-once by the outbox unique key and the provider idempotency key.

### 5.5 Digesting (P1)

If more than two outbox rows for the same commute become due within 60 seconds, send one email listing all affected trips.

## 6. Email content

Plain, short, readable on a phone lock screen. Text and simple HTML versions.

```text
Subject: Line 720 · 7:40 AM trip canceled (Wilshire / Western)

Metro's realtime feed marks this trip as canceled:

  Line 720 to Santa Monica
  Scheduled at Wilshire / Western: 7:40 AM, Thu Dec 3
  Next scheduled trips at your stop: 7:52 AM, 8:04 AM

First seen in LA Metro's realtime feed at 6:58 AM.
Your commute "Morning to work" has run 94% of its trips over the past 28 days.

Manage alerts: https://<domain>/account
Unsubscribe from this commute: <one-click link>

Ghost Bus LA is an independent project and is not affiliated with LA Metro.
```

The example values are illustrative. Rules: the subject carries line, time, and stop; "next scheduled trips" excludes other trips already announced as canceled; the reliability line appears only when the cell isn't suppressed; times are local; no tracking pixels.

Sender domain is authenticated with SPF, DKIM, and DMARC before the first real send.

## 7. Failure modes

| Failure | What happens | Why it is safe |
| --- | --- | --- |
| Detector crashes mid-snapshot | Transaction rolls back; snapshot is reprocessed | Upserts and `on conflict do nothing` are idempotent |
| Snapshot replayed 10 times | No new outbox rows | Unique `dedupe_key` |
| Worker crashes after claim, before send | Sweeper returns the row to `failed`; it is retried | No send happened |
| Worker crashes after send, before marking `sent` | Row retried | Provider idempotency key |
| Email provider down for an hour | Rows back off; many become `too_late` and are suppressed | Riders don't get stale alerts |
| Postgres down | Detector and worker stop and retry; `ingest` keeps archiving | Spool and S3 hold the snapshots for catch-up |
| Feed returns garbage or changes shape | Detector fails closed and pages | No false "all clear" |
| Feed outage, then recovery | Catch-up processes snapshots in order; late ones are suppressed | `too_late` rule |
| Two detectors started by mistake | Second one can't take the advisory lock and exits | `pg_try_advisory_lock` at startup |
| Clock skew | All comparisons use database time (`now()`) | One clock |

## 8. Likely-missing flags (P1) and alerts from them (P2, gated)

Unplanned misses are the rider's worst case, and Metro's feed can't warn about them. The design below is recorded as ADR-005 when this work starts.

**Signal.** A trip is flagged **likely missing** when its scheduled start plus a grace period (10 minutes to begin with) passes with no vehicle observed on it. If a vehicle appears later, the flag is **retracted**. Trips already announced as canceled aren't flagged.

**Baseline detector (P1, M5).** A second loop in `detector` runs once a minute over the realtime snapshots in the spool, matched through the crosswalk against today's scheduled trips in `serving`. It writes flag and retract events to `app.ghost_flag`, keyed on `(trip_id, service_date, detector_version, event_type)`, so a replay is a no-op. The site shows the live list, "Likely missing right now", labeled as an estimate with its measured precision. A nightly job copies the events to gold as `fct_ghost_alerts`.

**Scoring, nightly (M6).** Once a service date is final in `fct_trip_outcomes`, score every flag, per detector version:

- **Precision:** flags whose trip ended `missed`, over flags whose trip ended `missed`, `ran`, or `partial`. Flags on `unknown` and `likely_untracked` trips are left out and reported separately.
- **Recall:** share of missed trips flagged within 15 minutes of scheduled start.
- **Detection latency:** from the deadline (start plus grace) to the flag.
- **Retraction rate.**

**Alerts from flags (P2).** Riders opt in per commute. Ship only if precision is at least 0.85 over 14 or more service days, with the lower bound of a cluster-bootstrap interval at least 0.75. Be honest about lead time: the flag fires 10 minutes after the trip should have left its first stop, so riders boarding near the start of a line get little or no warning, and the `too_late` rule suppresses those alerts. Report the share suppressed and the median lead time for the rest.

Shipping this needs a migration: the outbox gains a nullable `ghost_flag_id`, and `cancellation_event_id` becomes nullable with a check that exactly one of the two is set.

Write the result up in `docs/research/likely-missing-scoring.md` with a go/no-go. A well-argued "no-go" is as good a portfolio piece as a shipped feature.

**If it ships:** the email says "Likely not running (our estimate)", states the measured precision in plain words ("about 9 in 10 of these warnings have been right"), and a follow-up is sent if the flag is retracted.

**Streaming is not built in this plan.** A streaming version (a faster feed into Redpanda, with event-time timers and replay) is adopted only if the baseline misses its bars: p95 detection latency over 2 minutes, or precision under 0.8 at the chosen grace period, over at least 7 service days. Record the measured numbers and the decision in ADR-005 either way. "I measured the simple version and it was enough" is a stronger answer to "why not Kafka?" than adopting it by default.

## 9. Metrics

| Metric | Type |
| --- | --- |
| `alerts_detect_to_send_seconds` | Histogram |
| `alerts_outbox_rows{status}` | Gauge |
| `alerts_suppressed_total{reason}` | Counter |
| `alerts_send_attempts_total{result}` | Counter |
| `detector_lag_seconds` (now minus newest processed snapshot) | Gauge |
| `detector_blocked` | Gauge (0 or 1) |
| `cancellation_events_open` | Gauge |

Alert rules and their runbook entries are in the infra spec.

## 10. Tests

- **Unit:** stable key; diff logic (new, seen again, withdrawn, expired); local day and time matching across midnight and on DST change dates; suppression rules; retry schedule.
- **Integration (real Postgres):** snapshot to outbox in one transaction; commute created after an event still matches; account deletion removes pending alerts.
- **Property-based (Hypothesis):** generate random sequences of snapshots, replays, detector crashes (abort at a random statement), and worker crashes. Invariants: at most one `sent` row per `dedupe_key`; every matched (commute, event) pair has exactly one outbox row; no row is `sent` after its `too_late` cutoff.
- **Replay test:** a recorded day of real cancellation snapshots runs through detector and worker with the file adapter; the set of emails is identical across three runs.
- **Concurrency:** two workers against 500 pending rows; every row sent exactly once.
