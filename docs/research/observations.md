# Trip matching and observations: service date 2026-11-15

**Query:** `uv run python scripts/research_observations.py 2026-11-15` over the local dbt build (UTC days Nov 14–16 synced), run 2026-11-17. Read-only.

## Results

| Measure | Value |
| --- | --- |
| Realtime trip keys in scope, matched exactly | 9,532 of 9,532 |
| Scheduled trips | 9,534 |
| …observed running (a matched SCHEDULED position, or a chosen SCHEDULED update with a vehicle, in the window) | 9,405 |
| …by vehicle positions / by trip updates only | 9,300 / 105 |
| …`rt_canceled` (canceled and not reinstated before the start) | 247 |
| …both `rt_canceled` and observed running | 121 |
| Of those 121: positions after the scheduled start / positions only before it / trip updates only | 76 / 12 / 33 |
| Of those 121: reinstated only after the start / never reinstated | 4 / 117 |
| Of the 76 with positions after the start: progress after the start (max stop sequence / stops), p25 / p50 / p75 | 0.03 / 0.21 / 0.47 |
| Of the 88 with positions: cancellation first seen after the last position was fetched | 84 |
| All observed trips with positions only before the start | 23 of 9,405 |
| All trips observed by positions: coverage p10 / p25 / p50 | 0.97 / 0.99 / 1.00 |

## What it means

- Exact matching works on this date: every in-scope realtime key matched the version in force.
- Most observed trips covered their route (median coverage 1.0, 90% above 0.97).
- The 121 trips that were both observed and canceled are mostly **mid-trip cancellations**: the bus ran part of the route (median 0.21 of it after the start), stopped reporting, and the trip was then marked canceled (84 of the 88 with positions were canceled after the last position). Twelve only waited before departure. Either way they didn't run. Spec section 8 already labels this `partial` (observed, coverage under 0.80), so outcomes need the coverage rule in M1, not only M4. That decision, and what to do with the 33 seen only through trip updates (no position, so no coverage), go to the outcomes PR with an ADR.
- An earlier draft of this note described the 121 as "117 canceled after the last position, median coverage 0.15". That mixed in the reinstatement count from `duplicate-trip-reports.md`. The figures above come from the committed script.

One service date. Rerun on more days before quoting any of this as typical.
