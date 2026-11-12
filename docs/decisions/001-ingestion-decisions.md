# ADR-001: Ingestion decisions for day 1

- **Status:** Accepted. Verified by the day-1 probe on 2026-11-11 (`docs/research/day1-probe.md`). Decisions 1 and 3 are superseded by ADR-021; decision 6's key format by ADR-004. Decisions 2, 4, 5, and 7 stand
- **Date:** 2026-11-10
- **Scope:** Which sources to poll, how often, what to store, and how to link trips across sources

## Context

The pipeline must start archiving on day 2, because Metro's canceled-service feed only shows cancellations that are currently scheduled. History not captured is lost for good. That means these decisions must be made before all the facts are in. Each one below is chosen to be safe even if the day-1 probe turns up something unexpected, and each lists the evidence that would change it.

---

## Decision 1: Use the Metro API as the v1 realtime source; add Swiftly in week 4

**Decision.** Poll Metro's own API (`api.metro.net`) for vehicle positions, trip updates, and canceled service. Add Swiftly's direct feed in week 4 as the streaming source.

**Alternatives considered.**
- *Swiftly only:* fresher (5 to 10 seconds), but needs an API key request that may take days, and adds a second vendor dependency before anything works.
- *Both from day 1:* doubles ingestion work in the week you can least afford it.

**Why.** The Metro API needs no key, so archiving can start tomorrow with no waiting. One-minute freshness is plenty for the core question: a missed trip is absent for its whole 30 to 90 minute run, not for seconds. Swiftly's speed matters for streaming, which is week 4's job. Running both later also gives you a free data-quality check, since two independent paths should agree.

**Would change if.** The probe shows Metro's realtime endpoints are dead or stale (feed header timestamp more than 5 minutes old). Then request a Swiftly key immediately and archive only canceled service from the Metro API until it arrives.

---

## Decision 2: Store raw responses byte-for-byte, never parsed

**Decision.** Bronze stores the exact bytes the source returned: protobuf as `.pb`, JSON as `.json`. Parsing happens only in silver.

**Alternatives considered.**
- *Parse to JSON or Parquet at ingest:* easier to query on day 1.

**Why.** Parsing is code, and code has bugs. If the parser drops a field or misreads one, parsed-at-ingest data is wrong forever, while raw bytes can be re-parsed with fixed code over the full history. Protobuf is also the official GTFS-realtime format and roughly 5 to 10 times smaller than its JSON form. This is the decision that makes "rebuild everything from bronze" true, which is the answer to half the interview questions in the spec.

**Would change if.** Nothing realistic. If storage cost ever mattered, nightly compaction handles it without giving up raw fidelity.

---

## Decision 3: Poll realtime every 30 seconds and cancellations every 60 seconds

**Decision.**

| Feed | Source refresh | Poll every | Why this rate |
| --- | --- | --- | --- |
| Vehicle positions | ~1 minute | 30 s | Sampling twice per update period means you never miss an update, and catch each one within 30 s |
| Trip updates | ~1 minute | 30 s | Same |
| Canceled service | 5 to 15 minutes | 60 s | Pins each cancellation's first appearance to within a minute, which is what the advance-notice metric needs |
| GTFS static | Weekly or at service changes | Daily | Download, hash, and store only if the hash changed |

**Alternatives considered.**
- *Poll at the source's refresh rate (60 s):* clock drift between your poller and the source means you will sometimes fetch just before an update and miss it for a full cycle.
- *Poll faster (5 to 10 s):* no new information from a feed that changes once a minute, and it risks rate limiting.

**Why.** Duplicate snapshots cost nothing, because content-hash keys turn them into no-ops (Decision 6). Missing an update costs data. So err toward polling slightly faster than the source changes. Expected volume: about 2,880 realtime snapshots per feed per day, well within any reasonable limit.

**Would change if.** The API rate-limits you (HTTP 429). Back off to 60 s and record it.

---

## Decision 4: Never assume IDs match across sources; build a crosswalk and measure it

**Decision.** Link every source to the schedule through an explicit `int_trip_crosswalk` table keyed on `(trip_id, service_date, schedule_version)`. Match in this order:

1. Exact `trip_id` against the schedule version in force that day
2. Route, direction, and start time within ±10 minutes
3. Unmatched: kept, counted, and reported in feed health

The daily match rate for each source is a tracked metric with an alert below 95%.

**Alternatives considered.**
- *Join directly on `trip_id`:* simplest, and works only if every source uses identical IDs forever.

**Why.** This is the most important open question, and the decision is built to be right whatever the answer is. If IDs match, step 1 catches nearly everything and the crosswalk costs one extra table. If they don't, the fallback still works and the gap is visible as a number instead of silently becoming fake missed trips. Metro's trip IDs also embed a service-change tag such as `SEPT21`, so they change at every service change. A direct join would break overnight at the next one, which is exactly the failure the December service change will test.

**Would change if.** The probe shows canceled-service entries carry no trip ID at all, only line, direction, and time. Then the fallback becomes the primary matcher for that source, and its precision gets hand-validated first.

---

## Decision 5: Store all times in UTC; derive service date from the schedule's own rule

**Decision.** Every timestamp is stored in UTC. Service date is computed per the GTFS convention: a trip's times are measured from noon minus 12 hours on its service date in `America/Los_Angeles`, so 25:10 belongs to the previous service date.

**Alternatives considered.**
- *Store local time:* reads naturally, but is ambiguous during the daylight-saving change, when 1:30 a.m. happens twice.
- *Service date = calendar date of the observation:* puts every after-midnight trip on the wrong day.

**Why.** UTC is unambiguous; local time is a display concern. The GTFS rule is the one Metro's schedule is written against, so using anything else guarantees mismatches for late-night service. Both edge cases get their own unit tests, including the March 2027 daylight-saving change.

**Would change if.** Never. This is standard practice, not a judgment call.

---

## Decision 6: Bronze layout and idempotency key

**Decision.**

```text
s3://<bucket>/bronze/<feed>/dt=YYYY-MM-DD/<fetched_at_utc>_<sha256[:16]>.<pb|json>
```

- `dt` is the UTC fetch date (a storage partition, not the service date)
- The SHA-256 of the response body is the idempotency key: if a file with that hash already exists for the feed, the write is skipped
- Every attempt, success or failure, also writes a row to `raw_fetch_log`

**Alternatives considered.**
- *Partition by service date in bronze:* requires parsing to know the service date, which breaks Decision 2.
- *Key on fetch time:* two polls of the same unchanged snapshot would create two files, and dedup moves downstream where it is harder.

**Why.** Bronze must be dumb and reliable: it knows only when it fetched and what bytes it got. The content hash makes re-runs, restarts, and overlapping pollers safe by construction. The fetch log is what lets the pipeline tell a feed outage from a quiet feed, which is what the "unknown" outcome rests on.

**Would change if.** Only for performance at much larger scale, and nightly compaction already covers that.

---

## Decision 7: Ingest every line; scope headline metrics to Metro-operated lines

**Decision.** Archive all lines the feeds return. Filter to Metro-operated lines only when computing headline metrics. The 15 contracted lines (96, 125, 128, 130, 167, 177, 205, 218, 232, 256, 266, 501, 577, 603, 605, per Metro's cancellation report page) are kept as a separate dimension.

**Alternatives considered.**
- *Ingest only Metro-operated lines:* smaller, but throws away data you can never recover.

**Why.** Filtering is cheap and reversible; not archiving is neither. Headline metrics must be scoped because Metro's cancellation feed and monthly report both exclude contracted lines, so including them would compare unlike things. Keeping the contracted lines' realtime data also enables a later analysis that Metro's own reports can't do.

**Would change if.** Metro's list of contracted lines changes. It is a seeded table, versioned like the schedule.

---

## Verification checklist (results from `docs/research/day1-probe.md`)

| Question | Decision it tests | Result |
| --- | --- | --- |
| Do Metro API realtime endpoints respond with fresh data? | 1 | Over REST, no: they return empty lists. Over WebSocket, yes: median vehicle lag 22 s |
| Are realtime responses protobuf, JSON, or both? | 2 | JSON only, one message per vehicle or trip |
| How often does the feed header timestamp actually change? | 3 | There is no feed header. The server re-sends the whole fleet every 3 to 4 s |
| Do canceled-service entries carry trip IDs, and what share match GTFS? | 4 | The canceled-service API is dead (last updated 2022-10-04). Cancellations appear in trip updates as `CANCELED`, and 64 of 64 sampled trip IDs matched GTFS |
| Any rate limiting or auth required? | 1, 3 | No key needed. WebSocket limits are undocumented and untested over long connections |

Results 1 and 3 contradict decisions 1 and 3. ADR-021 supersedes them; the decisions above are left as written. Decision records are a history, not a current-state document.
