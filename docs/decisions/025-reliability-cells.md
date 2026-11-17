# ADR-025: Reliability cells: schedule day types, service-day hours, data-anchored windows, a weekend day minimum

- **Status:** Accepted (the weekend minimum was the owner's choice, 2026-11-17)
- **Date:** 2026-11-17
- **Supersedes:** pipeline spec section 9's single suppression rule ("fewer than 30 trips or fewer than 10 service days"). The 10-day minimum now applies to weekday cells only; Saturday and Sunday cells need 4. Also settles three points the specs leave open: how a service date gets its day type, which hour a trip counts in, and what the windows are anchored to
- **Evidence:**
  - `docs/research/holiday-service.md`: on Thanksgiving and Labor Day 2026 the schedule removes all 12 weekday service IDs and adds the 12 Sunday ones; July 4 (a Saturday) also gets Sunday service. The current schedule has no mixed weekly patterns.
  - Calendar arithmetic: any 28-day window contains exactly 4 Saturdays and 4 Sundays.
  - Outcomes start at service date 2026-11-15 (the first stored schedule ZIP).

## Context

`fct_reliability` reports rates per line × direction × day type × hour × window (`28d`, `90d`, `all`). The API returns these cells (API spec section 4.1), and `28d` is the default window. Section 9 suppresses any cell with fewer than 30 trips or fewer than 10 service days. Under that rule, every Saturday and Sunday cell in the `28d` window would be suppressed forever, whatever the data. The specs also don't say which day type a holiday is, which hour a 25:30 trip belongs to, or when a window ends.

## Decision

1. **Day type comes from the schedule.** A service date takes the weekly pattern most of its scheduled trips come from: Monday–Friday days only = `weekday`, Saturday only = `saturday`, Sunday only = `sunday`. Mixed patterns and services missing from `calendar.txt` don't vote. A date with no voting trips falls back to its calendar day. Ties go to the alphabetically first pattern. A warning test flags a schedule that introduces mixed patterns.
2. **Hour is the local clock hour of the scheduled start; day type follows the service date.** A 25:30 trip of Friday's service is in the `weekday` cells at hour 1. Hours use America/Los_Angeles, with daylight saving time applied.
3. **Windows end at the last service date with outcomes**, never at the build clock. `28d` is that date and the 27 before it, and `90d` likewise. `all` starts at the first date with outcomes. Each cell also reports `first_data_date`, the first date it has data for, which can be later than `window_start`.
4. **Suppression:** a cell publishes counts but no rates if it has fewer than 30 trips in the denominator (scheduled − unknown). It is also suppressed if it has fewer service days than its day type's minimum: 10 for weekday cells, 4 for Saturday and Sunday cells. A service day counts only if it has at least one trip in the denominator. The minimums are dbt vars (`min_cell_trips`, `min_cell_service_days_weekday`, `min_cell_service_days_weekend`).
5. **Trips are kept unless `is_metro_operated` is false.** It is NULL until the contracted-lines seed (ADR-024 decision 6). Contracted lines then drop out of the cells (SPEC section 2).

## Why

- **Day type:** Metro runs Sunday service on holidays, and the schedule says so. Using the calendar day would put Thanksgiving's Sunday-service trips into weekday cells, mixing two operating plans in one rate. Letting the schedule decide needs no holiday list to maintain.
- **Hour:** service-day hours match how riders read a printed timetable: the 1:30 AM bus after Friday night is in Friday's column.
- **Windows:** anchoring on the data makes a rebuild reproducible (drill 3). A stalled pipeline then can't silently shrink a window while still labelling it 28 days.
- **Weekend minimum:** the day minimum exists because trips on the same day share causes, such as an operator shortage. Ten days protects weekday cells from one bad day dominating. Requiring ten weekend days in a window that can only ever hold four would hide every weekend number in the default view. Instead, four (every weekend day in the window) plus the 30-trip floor lets weekend rates appear. The cluster bootstrap's intervals (section 9) then show how much less certain they are, rather than hiding them.

## Alternatives considered

- **Keep 10 days everywhere:** weekend cells would show only in the `90d` and `all` windows, after about 10 weekends (late January 2027). Honest, but the default view would show no weekend numbers at launch.
- **Coarser weekend cells (3-hour bands):** reaches 30 trips sooner, but still needs the day minimum, so it doesn't fix the `28d` window. More scope.
- **Calendar day type plus a holiday list:** a second source of truth that goes stale when Metro changes its holidays.
- **Clock hour with the calendar day:** the 25:30 trip would land in Saturday cells, though it belongs to Friday's service and Friday's operations.

## Consequences

- With data from 2026-11-15, weekday cells can first publish a rate after 10 weekdays: Thanksgiving is a Sunday-service day, so around 2026-11-30. Weekend cells can publish after 4 Saturdays (2026-12-12) and 4 Sunday-service days (2026-11-29: Nov 15, 22, 26 and 29, since Thanksgiving runs Sunday service). The busiest hours come first; thin lines need longer to reach 30 trips. Until then the site shows counts and "not enough data yet".
- Weekend rates rest on fewer independent days, so their intervals are wider. The API returns `ci_low` and `ci_high` with every rate (API spec section 1), and the page must show them.
- Changing a minimum is a one-line var change, and a sensitivity run is one command.

## Would change if

- The bootstrap shows weekend intervals too wide to tell anything apart at 4 days. Then raise the weekend minimum, or default weekend views to `90d`.
- Metro starts encoding holidays differently, for example with mixed patterns or a special service not in `calendar.txt`. The warning test fires, and the day-type rule is revisited.
- Riders find service-day hours confusing in testing. The convention is then explained on the method page, or switched to clock days.
