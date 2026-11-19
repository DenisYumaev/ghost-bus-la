# ADR-029: Current cancellations come from the 10-minute build in M2, from the detector in M3

- **Status:** Accepted
- **Date:** 2026-11-18
- **Supersedes:** nothing. Settles API spec section 7's open note on `GET /v1/cancellations/current`, which the spec lists under M2 without a data source. The realtime path in `docs/SPEC.md` section 4 (the detector writing `app.cancellation_event`) is M3.
- **Evidence:**
  - The pipeline already links realtime cancellations to scheduled trips through the crosswalk, with first-seen and reinstated times (`int_trip_observations`, PRs #33 and #35; hard rule 6).
  - The open-date dbt build is planned every 10 minutes (pipeline spec section 11).
  - Metro restates a cancellation in nearly every snapshot (`docs/research/duplicate-trip-reports.md`: 1,107 of 1,111 canceled entities re-stamped between fetches), so the newest fetch reflects the current state.

## Context

The line page and the home page show "currently announced cancellations" (web spec). M2 has no detector and no `app` schema: those come with alerts in M3. A nightly batch can't say what is canceled now.

## Decision

1. **M2: a gold model, `fct_current_cancellations`, built by every open-date build** and published as `serving.cancellation_current`. It holds the trips that are still canceled at the newest successful trip-update fetch in the data:
   - announced at some point (`canceled_first_seen_at` set);
   - not reinstated since (`reinstated_at` NULL);
   - whose scheduled end is not yet past that fetch.
2. **"Now" is the newest fetch the decoded state covers, not the build clock.**
   - It is the newest trip-update fetch in the decoded reports, not in the fetch log, which can list fetches not yet decoded.
   - A rebuild of the same data gives the same rows.
   - `as_of` is published on its own one-row table, so even an empty list says "nothing canceled as of 4:52 PM".
   - A dbt test fails the build if there is no decoded fetch, so a broken sync can't publish an empty list that looks like a quiet day.
   - The API adds `stale` when `as_of` is more than 90 minutes old, and caches this list for 60 s instead of 5 minutes.
   - Names and headsigns come from each trip's own schedule version.
3. **Only the open-date build publishes it.** Both tables are left out of a plain `make publish`, and the open-date build publishes them with `--only`. Otherwise a closed-date build, a nightly close or a backfill, whose newest fetch is after every trip has ended, would replace the live list with an empty one.
4. **The list is never filtered by Metro-operated status.** Unlike the reliability numbers, it just reports what the feed announced.
5. **The withdrawal question stays open.** Here a cancellation counts as current until the feed shows the trip scheduled again (`reinstated_at`). Whether a late withdrawal should retract an alert is the open SPEC section 10 question for M3, and doesn't change this list.
6. **Prerequisite: an open-day sync mode.** Today `make dbt-sync` needs the UTC day after the range decoded, so it can't include the open day. The open-day pipeline (M2 deploy work) must sync today, and yesterday until it closes, from partial data. Until then the endpoint is correct but empty.
7. **M3:** the endpoint switches its repository to the detector's `app.cancellation_event`, which updates within a minute. The response shape stays the same, and this table is retired by the ADR that makes that switch.

## Why

It ships the endpoint with the pieces already built and tested, rather than pulling the detector forward or leaving the web page with nothing to show. Freshness is bounded by how far the decoded data reaches: up to about an hour until the fetch log uploads more often (see Consequences), and the 10-minute build after that. `as_of` and `stale` make it visible either way. Anchoring on the data keeps rebuilds deterministic, the same as every other gold table.

## Alternatives considered

- **Pull the detector forward into M2:** the right long-term path, but it means the `app` schema, the outbox and their tests, all of which is M3 scope (hard rule 14).
- **Leave the endpoint out of M2:** the line page would lose a section the web spec puts at the top.
- **Use the build clock as "now":** fresher-looking, but a delayed build would show cancellations of trips that already ended. Rebuilds would also differ, and the table couldn't say how current it is.

## Consequences

- **The lag is up to about an hour, not 10 minutes, until the fetch-log cadence changes.** Ingest uploads the fetch log only when each hour closes (`fetch_log.py`), and compaction takes `fetched_at` from it. So an open-day build sees data up to about 60 minutes plus the upload delay behind real time. The page shows `as_of`. The open-day pipeline should upload the open hour's fetch log every few minutes (content-hash keys make re-uploads safe); this claim gets updated with that change.
- A cancellation announced in the evening for an early trip on the next service date isn't listed until that service date enters the build (at local midnight), because the open-date build covers today and yesterday (pipeline spec section 11).
- Advance notice can be negative (canceled after the scheduled start). The web shows "announced after departure", not a negative number.
- Trips whose cancellation the feed stops repeating, without reinstating them, stay listed until their scheduled end. That matches "announced and not withdrawn".

## Would change if

- M3's detector lands: switch to `app.cancellation_event` and retire `serving.cancellation_current`.
- The open-day pipeline uploads the fetch log every few minutes: update the lag stated here to the measured value.
- Riders find even that lag misleading before M3: pull the detector forward for this endpoint.
