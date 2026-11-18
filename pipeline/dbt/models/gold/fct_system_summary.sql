-- One row per window: (time_window). Headline numbers for the home page and
-- GET /v1/system/summary (pipeline spec section 6.3, API spec section 4.1): counts and the
-- section 8 rates over every trip in scope, plus how much data stands behind them. It sums the
-- same trips as fct_reliability, so the home page and the line pages always agree.
-- Suppressed below min_cell_trips trips or min_cell_service_days_weekday service days (ADR-026):
-- a system-wide rate from a few days would be a headline built on noise. Nothing here is
-- quotable until M5 validates against Metro's report (hard rule 11). Intervals for missed_rate
-- and unplanned_share (SPEC section 1.3) come with the bootstrap; NULL until then.
with totals as (
    select
        w.time_window,
        w.window_start,
        w.window_end,
        min(o.service_date) as first_data_date,
        count(distinct o.service_date) filter (where o.outcome <> 'unknown') as n_service_days,
        count(distinct o.line) as n_lines,
        count(*) as n_scheduled,
        count(*) filter (where o.outcome = 'unknown') as n_unknown,
        count(*) filter (where o.outcome = 'ran') as n_ran,
        count(*) filter (where o.outcome = 'partial') as n_partial,
        count(*) filter (where o.outcome = 'missed') as n_missed,
        count(*) filter (where o.outcome = 'missed' and o.announced) as n_missed_announced,
        count(*) filter (where o.outcome = 'missed' and not o.announced) as n_missed_unplanned,
        count(*) filter (where o.outcome = 'ran' and o.announced) as n_ran_announced
    from {{ ref('int_trip_cells') }} as o
    inner join {{ ref('int_windows') }} as w
        on o.service_date between w.window_start and w.window_end
    group by w.time_window, w.window_start, w.window_end
),

judged as (
    select
        *,
        n_scheduled - n_unknown as n_trips,
        n_scheduled - n_unknown < {{ var('min_cell_trips') }}
            or n_service_days < {{ var('min_cell_service_days_weekday') }} as suppressed
    from totals
)

select
    time_window,
    window_start,
    window_end,
    first_data_date,
    n_service_days,
    n_lines,
    n_scheduled,
    n_unknown,
    n_trips,
    n_ran,
    n_partial,
    n_missed,
    n_missed_announced,
    n_missed_unplanned,
    n_ran_announced,
    case when not suppressed then n_missed / nullif(n_trips, 0) end as missed_rate,
    case when not suppressed then n_missed_announced / nullif(n_trips, 0) end as announced_rate,
    case when not suppressed then n_missed_unplanned / nullif(n_trips, 0) end as unplanned_rate,
    case when not suppressed and n_missed > 0 then n_missed_unplanned / n_missed end
        as unplanned_share,
    suppressed,
    cast(null as double) as missed_rate_ci_low,
    cast(null as double) as missed_rate_ci_high,
    cast(null as double) as unplanned_share_ci_low,
    cast(null as double) as unplanned_share_ci_high
from judged
