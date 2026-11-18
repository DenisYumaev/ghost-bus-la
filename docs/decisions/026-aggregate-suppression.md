# ADR-026: Suppression and intervals for the line summary, system summary and weekly trend

- **Status:** Accepted
- **Date:** 2026-11-17
- **Supersedes:** nothing. Supplements ADR-025, which covers reliability cells, with the rules for the three tables built from the same trips: `fct_line_summary`, `fct_system_summary` and `fct_line_trend`. Pipeline spec section 9 names only cells.
- **Evidence:** ADR-025's reasoning (trips on one day share causes); calendar arithmetic (a week has at most 7 service days); outcomes start on a Sunday (2026-11-15), so the first week of data has one service day.

## Context

The home page, the line list, the line page and the trend chart show rates that aren't hour-by-day-type cells: one rate per line, one for the whole system, and one per week. Section 9's suppression rule speaks only of cells, and the bootstrap writes intervals only into `fct_reliability`. Without a rule, each table, or worse each API endpoint, would choose its own.

## Decision

1. **Line summary and system summary:** suppress below 30 trips (scheduled − unknown) or below 10 service days. That is ADR-025's weekday minimum, used because these rates pool every day type and are the headlines people quote. A service day counts only if it has a trip in the denominator.
2. **Weekly trend:** suppress below 30 trips or below 4 service days (`min_week_service_days`). A week can never reach 10 days. But one or two days of data (the newest, still-filling week, a gap, or the first week here, which is one Sunday) would turn one bad day into a spike on the point riders read first. `n_service_days` is published, so the chart can mark weeks with 4 to 6 days as partial.
3. **The trend endpoint takes a direction.** `fct_line_trend` is per line × direction, and `direction_id` is required on `GET /v1/lines/{line}/trend`. "The last N weeks" is anchored on the newest `week_start` across all lines, and weeks with no row are returned as empty points, not skipped.
4. **Both-direction rows:** `fct_line_summary` has a row per line × window with `direction_id` NULL, pooling both directions' trips. The API never averages two direction rates.
5. **Intervals:** the bootstrap (section 9) writes `missed_rate` intervals into `fct_reliability`, and both `missed_rate` and `unplanned_share` intervals into `fct_line_summary` and `fct_system_summary` (SPEC section 1.3 asks for both). Trend points carry no intervals: the chart shows the shape over time, and the line page's summary carries the uncertainty.
6. **Every threshold is a dbt var.**

## Why

- **One rule per kind of number:** if the API had to suppress a line's headline itself, its rule would drift from dbt's, and the line list could show a rate that the line page calls "not enough data". Putting the rules in the tables, built from the same trips as the grid, makes the numbers agree by construction. A dbt test checks that they sum.
- **Why the weekday minimum for summaries:** a headline pooled over all days is quoted more than any cell, so it gets the stricter floor.
- **Why 4 days for a week:** it is the smallest count that is a majority of a full week's service days, so a published week is mostly complete.

## Alternatives considered

- **Publish only complete weeks:** simplest to read, but the newest point would lag up to 6 days behind the data.
- **No day floor for weeks (the first draft):** a single Monday's 55 trips could become a full-looking weekly point.
- **Let the API pool cells for line headlines:** puts section 8 and 9 logic outside dbt, untested against the grid.

## Consequences

- With data from 2026-11-15, the first trend week (Nov 9, one Sunday) is suppressed. Weeks from Nov 16 on publish once a line-direction has 30 trips in them.
- Line and system headlines appear after 10 service days with data, around 2026-11-24 to 25 for busy lines, subject to the 30-trip floor.

## Would change if

- Riders read partial-week points as real dips: then raise `min_week_service_days` to 7.
- The bootstrap shows summary intervals so wide that the headline misleads at 10 days: then raise the summary minimum.
