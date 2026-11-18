-- One row per window: (time_window). Headline numbers for the home page and
-- GET /v1/system/summary (pipeline spec section 6.3, API spec section 4.1): counts and the
-- section 8 rates over every trip in scope, plus how much data stands behind them. It sums the
-- same trips as fct_reliability, so the home page and the line pages always agree.
-- Suppressed below min_cell_trips trips or min_cell_service_days_weekday service days (ADR-026):
-- a system-wide rate from a few days would be a headline built on noise. Nothing here is
-- quotable until M5 validates against Metro's report (hard rule 11). Intervals for missed_rate
-- and unplanned_share (SPEC section 1.3) come from the cluster bootstrap (ADR-027), published
-- only where the rates are.
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
    j.time_window,
    j.window_start,
    j.window_end,
    j.first_data_date,
    j.n_service_days,
    j.n_lines,
    j.n_scheduled,
    j.n_unknown,
    j.n_trips,
    j.n_ran,
    j.n_partial,
    j.n_missed,
    j.n_missed_announced,
    j.n_missed_unplanned,
    j.n_ran_announced,
    case when not j.suppressed then j.n_missed / nullif(j.n_trips, 0) end as missed_rate,
    case when not j.suppressed then j.n_missed_announced / nullif(j.n_trips, 0) end as announced_rate,
    case when not j.suppressed then j.n_missed_unplanned / nullif(j.n_trips, 0) end as unplanned_rate,
    case when not j.suppressed and j.n_missed > 0 then j.n_missed_unplanned / j.n_missed end
        as unplanned_share,
    j.suppressed,
    case when not j.suppressed then b.missed_rate_ci_low end as missed_rate_ci_low,
    case when not j.suppressed then b.missed_rate_ci_high end as missed_rate_ci_high,
    case when not j.suppressed then b.unplanned_share_ci_low end as unplanned_share_ci_low,
    case when not j.suppressed then b.unplanned_share_ci_high end as unplanned_share_ci_high
from judged as j
left join {{ ref('int_bootstrap_intervals') }} as b
    on b.grain = 'system' and j.time_window = b.time_window
