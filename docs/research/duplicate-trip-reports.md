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

## What it means

- Metro sometimes publishes the same trip twice in one snapshot under different entity IDs. When the two disagree, it's usually a fresh cancellation (no vehicle) next to an older report that still carries the vehicle assignment. So "the report with a vehicle wins" would be wrong in 227 of 266 cases, and "the newest report wins" is right in all of them by construction.
- Ordering cancellation state by Metro's report time, not fetch time, matters because canceled entries linger for hours (day-1 probe). A stale CANCELED fetched late must not outrank a newer SCHEDULED.
- A few reinstatements (4 of 121 on Nov 15) arrive only after the trip's scheduled start. The alerts spec withdraws a cancellation only while the start is still ahead, so `int_trip_observations` applies that cutoff. Silver exposes `reinstated_at`.

These are one service date's numbers. Rerun the script on more days before quoting any of them as typical.
