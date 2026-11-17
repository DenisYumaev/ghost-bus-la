# Duplicate trip reports and late SCHEDULED reports

**Query:** `uv run python scripts/research_duplicate_trip_reports.py` over the local dbt build for service date 2026-11-15 (UTC days Nov 14–16 synced), run 2026-11-17. Read-only. It shaped the rules in `stg_trip_reports` and `stg_cancellations` (pipeline spec, section 6.1).

## Results

| Measure | Value |
| --- | --- |
| Trip-fetches (distinct trip, service date, fetch) | 14,625,827 |
| …with more than one report of the trip in one snapshot | 18,323 (0.13%) |
| …whose reports disagree, CANCELED vs SCHEDULED | 266 |
| …of those, the newest report (by entity timestamp) is CANCELED / SCHEDULED | 227 / 39 |
| …of those, the newest report has a vehicle / has none | 39 / 227 |
| Trips canceled on service date Nov 15 with a SCHEDULED report after the last CANCELED (by fetch time) | 121 |
| …of which that SCHEDULED report came before the trip's scheduled start | 117 |

## VERIFY: do reports carry Metro's timestamp, and are canceled entries re-stamped?

Run on the same build after decode v3 (entity ids), 2026-11-17:

| Measure | Value |
| --- | --- |
| Trip reports without `tripUpdate.timestamp` | 0 of 14,644,190 (CANCELED 0 of 142,572; SCHEDULED 0 of 14,501,618) |
| Canceled entities whose timestamp changes between fetches | 1,107 of 1,111 (average 128 distinct timestamps each, up to 838) |
| Canceled report timestamp behind our fetch time | median 15 s, 90th percentile 29 s, max 77 s |
| Nov 15 cancellations reinstated, by report time / by fetch time | 121 / 121 |
| Nov 15 cancellations with a later final episode: ordering raw reports / one chosen state per fetch | 11 / 6 |

So Metro re-stamps a lingering canceled entry on every fetch. It isn't a stale row; each fetch restates the cancellation, which is why report-time and fetch-time ordering agree. The remaining hazard is two live entities for one trip both refreshing their timestamps: ordering raw reports interleaved them into fake episodes (5 of the 11). `stg_cancellations` therefore uses one state per fetch, the report `stg_trip_reports` chose (newest by Metro's timestamp), ordered by fetch time.

## What it means

- Metro sometimes publishes the same trip twice in one snapshot under different entity IDs. When the two disagree, it's usually a fresh cancellation (no vehicle) next to an older report that still carries the vehicle assignment. So "the report with a vehicle wins" would be wrong in 227 of 266 cases, and "the newest report wins" is right in all of them by construction.
- Within a fetch, the newest report by Metro's timestamp decides the trip's state. Across fetches, the state sequence is ordered by fetch time: canceled entries linger for hours (day-1 probe), but Metro re-stamps them each time (see VERIFY above), so a lingering cancellation is Metro still saying so.
- A few reinstatements (4 of 121 on Nov 15) arrive only after the trip's scheduled start. The alerts spec withdraws a cancellation only while the start is still ahead, so `int_trip_observations` applies that cutoff. Silver exposes `reinstated_at`.

These are one service date's numbers. Rerun the script on more days before quoting any of them as typical.
