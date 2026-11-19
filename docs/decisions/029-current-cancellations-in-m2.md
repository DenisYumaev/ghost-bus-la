# ADR-029: Current cancellations come from the 10-minute build in M2, from the detector in M3

- **Status:** Accepted
- **Date:** 2026-11-19
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
2. **"Now" is the newest fetch in the data, not the build clock.** The table says what the feed showed as of `as_of`, and a rebuild of the same data gives the same rows. The API returns `as_of`, so the page can say "as of 4:52 PM".
3. **The list is never filtered by Metro-operated status.** Unlike the reliability numbers, it just reports what the feed announced.
4. **The withdrawal question stays open.** Here a cancellation counts as current until the feed shows the trip scheduled again (`reinstated_at`). Whether a late withdrawal should retract an alert is the open SPEC section 10 question for M3, and doesn't change this list.
5. **M3:** the endpoint switches its repository to the detector's `app.cancellation_event`, which updates within a minute. The response shape stays the same, and this table is retired by the ADR that makes that switch.

## Why

It ships the endpoint with the pieces already built and tested, rather than pulling the detector forward or leaving the web page with nothing to show. Freshness is bounded by the 10-minute build, and `as_of` makes it visible. Anchoring on the data keeps rebuilds deterministic, the same as every other gold table.

## Alternatives considered

- **Pull the detector forward into M2:** the right long-term path, but it means the `app` schema, the outbox and their tests, all of which is M3 scope (hard rule 14).
- **Leave the endpoint out of M2:** the line page would lose a section the web spec puts at the top.
- **Use the build clock as "now":** fresher-looking, but a delayed build would show cancellations of trips that already ended. Rebuilds would also differ, and the table couldn't say how current it is.

## Consequences

- The list is up to about 10 minutes behind the feed, plus publish time. The page shows `as_of`.
- Trips whose cancellation the feed stops repeating, without reinstating them, stay listed until their scheduled end. That matches "announced and not withdrawn".

## Would change if

- M3's detector lands: switch to `app.cancellation_event` and retire `serving.cancellation_current`.
- Riders find a 10-minute lag misleading before M3: publish more often for this one table.
